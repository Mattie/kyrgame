import asyncio
import contextlib
import os
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from fastapi import FastAPI
from starlette.websockets import WebSocketState

from . import commands, constants, database, fixtures, loader, models, repositories, rooms
from .env import load_env_file
from .gateway import RoomGateway
from .presence import PresenceService
from .scheduler import SchedulerService
from .spells.tick_system import (
    NoopSpellTickMessaging,
    SQLAlchemySpellTickPlayerRepository,
    SpellTickConstants,
    SpellTickSystem,
)
from .timing.runtime import RuntimeTickCoordinator
from .timing.scheduler import TickScheduler
from .world.animation_tick_system import (
    AnimationTickRuntimeBridge,
    AnimationTickSystem,
    BrownieRoutine,
    DryadWanderRoutine,
    ElfEncounterRoutine,
    GemSpawnRoutine,
    InMemoryAnimationTickPersistence,
    ZarDragonRoutine,
)


@dataclass
class RuntimeConfig:
    database_url: str
    migration_runner: str
    seed_paths: List[Path] = field(default_factory=list)
    run_migrations: bool = True
    migration_revision: str = "head"
    reset_on_boot: bool = False
    # Default to seed only when the database is empty so first boot is usable without forcing reloads.
    seed_if_empty: bool = True

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
        env_path = os.getenv("KYRGAME_ENV_FILE")
        load_env_file(Path(env_path) if env_path else None)

        seed_paths_env = os.getenv("KYRGAME_SEED_PATHS")
        default_seed = Path(__file__).resolve().parents[1] / "fixtures"
        seed_paths = (
            [Path(part) for part in seed_paths_env.split(os.pathsep)]
            if seed_paths_env
            else [default_seed]
        )

        return cls(
            database_url=os.getenv("DATABASE_URL", "sqlite+pysqlite:///:memory:"),
            migration_runner=os.getenv("KYRGAME_MIGRATION_RUNNER", "alembic"),
            seed_paths=seed_paths,
            run_migrations=_env_flag("KYRGAME_RUN_MIGRATIONS", default=True),
            migration_revision=os.getenv("KYRGAME_MIGRATION_REVISION", "head"),
            reset_on_boot=_env_flag("KYRGAME_RESET_ON_BOOT", default=False),
            seed_if_empty=_env_flag("KYRGAME_SEED_IF_EMPTY", default=True),
        )

    def should_seed_database(self, session: Session) -> bool:
        if self.reset_on_boot:
            return True
        if self.seed_if_empty:
            return not _database_has_locations(session)
        return False

    def primary_seed_path(self) -> Optional[Path]:
        for seed in self.seed_paths:
            if seed.exists():
                return seed
        return None


def _env_flag(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() not in {"0", "false", "no"}


def _database_has_locations(session: Session) -> bool:
    return session.query(models.Location.id).first() is not None


async def bootstrap_app(app: FastAPI):
    """Initialize database, fixture cache, and background tasks."""

    runtime_config = RuntimeConfig.from_env()
    engine = database.get_engine(runtime_config.database_url)

    if runtime_config.run_migrations and runtime_config.migration_runner == "alembic":
        database.run_migrations(
            database_url=runtime_config.database_url,
            revision=runtime_config.migration_revision,
            engine=engine,
        )
    elif runtime_config.database_url.startswith("sqlite"):
        database.init_db_schema(engine)

    session_factory = database.create_session_factory(engine)
    seed_root = runtime_config.primary_seed_path()
    with session_factory() as session:
        if runtime_config.should_seed_database(session):
            # Guard destructive fixture reloads so persistent demo/prod databases are not reset on each boot.
            loader.load_all_from_fixtures(session, fixture_root=seed_root)

    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.gateway = RoomGateway()
    app.state.presence = PresenceService()
    app.state.scheduler = SchedulerService()
    await app.state.scheduler.start()
    app.state.tick_scheduler = TickScheduler(
        app.state.scheduler,
        tick_seconds=_tick_seconds_from_env(),
    )
    message_bundles = fixtures.load_message_bundles(seed_root)
    messages_catalog = message_bundles[fixtures.DEFAULT_LOCALE].messages
    app.state.spell_tick_system = SpellTickSystem(
        session_factory=session_factory,
        player_repository_factory=SQLAlchemySpellTickPlayerRepository,
        messaging=NoopSpellTickMessaging(),
        constants=SpellTickConstants(),
        message_lookup=lambda key: messages_catalog.get(key, ""),
    )
    default_messages = message_bundles[fixtures.DEFAULT_LOCALE]
    content_mappings = fixtures.load_content_mappings(seed_root)

    app.state.fixture_cache = {
        "locations": fixtures.load_locations(seed_root),
        "objects": fixtures.load_objects(seed_root),
        "spells": fixtures.load_spells(seed_root),
        "commands": fixtures.load_commands(seed_root),
        "players": fixtures.load_players(seed_root),
        "player_template": fixtures.build_player(seed_root),
        "messages": default_messages,
        "message_bundles": message_bundles,
        "content_mappings": content_mappings,
        "summary": fixtures.fixture_summary(seed_root),
    }
    
    # Load locations from database to get persisted object state, fallback to fixtures
    with session_factory() as db:
        location_records = db.query(models.Location).all()
        if location_records:
            # Convert database records to LocationModel instances
            db_locations = [
                models.LocationModel(
                    id=rec.id,
                    brfdes=rec.brfdes,
                    objlds=rec.objlds,
                    nlobjs=rec.nlobjs,
                    objects=rec.objects,
                    gi_north=rec.gi_north,
                    gi_south=rec.gi_south,
                    gi_east=rec.gi_east,
                    gi_west=rec.gi_west,
                )
                for rec in location_records
            ]
            app.state.location_index = {loc.id: loc for loc in db_locations}
        else:
            # No database records yet, use fixtures
            app.state.location_index = {loc.id: loc for loc in app.state.fixture_cache["locations"]}

    object_names_by_id = {obj.id: obj.name for obj in app.state.fixture_cache["objects"]}
    app.state.animation_rng = random.Random()

    def _animation_room_picker(low: int, high: int) -> int:
        return app.state.animation_rng.randint(low, high)

    def _animation_chance_picker(low: int, high: int) -> int:
        return app.state.animation_rng.randrange(low, high)

    def _animation_pick_gem(low: int, high: int) -> int:
        return app.state.animation_rng.randint(low, high)

    def _animation_pick_gold(low: int, high: int) -> int:
        return app.state.animation_rng.randint(low, high)

    def _animation_get_room_objects(room_id: int) -> list[int]:
        location = app.state.location_index.get(room_id)
        return list(location.objects) if location else []

    def _animation_set_room_objects(room_id: int, object_ids: list[int]) -> None:
        location = app.state.location_index.get(room_id)
        with session_factory() as db:
            location_repo = repositories.LocationRepository(db)
            try:
                location_repo.update_objects(room_id, list(object_ids))
            except ValueError:
                db.rollback()
                return
            db.commit()
        if location:
            app.state.location_index[room_id] = location.model_copy(
                update={"objects": list(object_ids), "nlobjs": len(object_ids)}
            )

    def _animation_object_name_lookup(object_id: int) -> str:
        return object_names_by_id.get(object_id, "object")

    def _animation_location_phrase_lookup(room_id: int) -> str:
        location = app.state.location_index.get(room_id)
        return location.objlds if location else "nearby"

    def _animation_message_formatter(message_id: str, *args: object) -> str:
        template = messages_catalog.get(message_id, "")
        if args:
            try:
                return template % args
            except TypeError:
                return template
        return template

    def _gemakr_message_formatter(gem_name: str) -> str:
        return _animation_message_formatter("GEMAPP", gem_name)

    def _animation_player_getter(room_id: int) -> models.PlayerModel | None:
        # Legacy rndlgp only scans active terminals for animation encounters
        # (legacy/KYRANIM.C:95-107).
        for player in getattr(app.state, "active_player_sessions", {}).values():
            if player.gamloc == room_id:
                return player
        for player in getattr(app.state, "active_players", {}).values():
            if player.gamloc == room_id:
                return player
        return None

    def _animation_players_getter(room_id: int) -> list[models.PlayerModel]:
        players_by_id: dict[str, models.PlayerModel] = {}
        for player in getattr(app.state, "active_player_sessions", {}).values():
            if player.gamloc == room_id:
                players_by_id[player.plyrid] = player
        for player in getattr(app.state, "active_players", {}).values():
            if player.gamloc == room_id:
                players_by_id.setdefault(player.plyrid, player)
        return sorted(players_by_id.values(), key=lambda player: (player.modno, player.plyrid))

    def _animation_player_persister(player: models.PlayerModel) -> None:
        with session_factory() as db:
            record = db.scalar(select(models.Player).where(models.Player.plyrid == player.plyrid))
            if not record:
                return
            record.gamloc = player.gamloc
            record.pgploc = player.pgploc
            record.hitpts = player.hitpts
            record.spts = player.spts
            record.gold = player.gold
            record.gpobjs = list(player.gpobjs)
            record.obvals = list(player.obvals)
            record.npobjs = player.npobjs
            db.commit()

    def _set_zar_location(room_id: int) -> None:
        room_scripts = getattr(app.state, "room_scripts", None)
        yaml_engine = getattr(room_scripts, "yaml_engine", None)
        if yaml_engine is None:
            return
        yaml_engine.get_room_state(302)["zar_location"] = room_id

    def _animation_pronoun(player: models.PlayerModel) -> str:
        return "her" if player.flags & constants.PlayerFlag.FEMALE else "him"

    elf_routine = ElfEncounterRoutine(
        room_picker=_animation_room_picker,
        gold_picker=_animation_pick_gold,
        player_getter=_animation_player_getter,
        player_persister=_animation_player_persister,
        message_formatter=_animation_message_formatter,
    )
    app.state.animation_elf_routine = elf_routine
    zar_routine = ZarDragonRoutine(
        room_picker=_animation_room_picker,
        chance_picker=_animation_chance_picker,
        room_objects_getter=_animation_get_room_objects,
        room_objects_setter=_animation_set_room_objects,
        players_getter=_animation_players_getter,
        player_persister=_animation_player_persister,
        message_formatter=_animation_message_formatter,
        zar_location_setter=_set_zar_location,
    )
    app.state.animation_zar_routine = zar_routine
    app.state.animation_tick_persistence = InMemoryAnimationTickPersistence()
    app.state.animation_tick_system = AnimationTickSystem(
        persistence=app.state.animation_tick_persistence,
        routine_handlers={
            "dryads": DryadWanderRoutine(
                room_picker=_animation_room_picker,
                room_objects_getter=_animation_get_room_objects,
                room_objects_setter=_animation_set_room_objects,
                object_name_lookup=_animation_object_name_lookup,
                location_phrase_lookup=_animation_location_phrase_lookup,
                message_formatter=_animation_message_formatter,
            ),
            "elves": elf_routine,
            "gemakr": GemSpawnRoutine(
                room_picker=_animation_room_picker,
                gem_picker=_animation_pick_gem,
                room_objects_getter=_animation_get_room_objects,
                room_objects_setter=_animation_set_room_objects,
                gem_name_lookup=_animation_object_name_lookup,
                message_formatter=_gemakr_message_formatter,
            ),
            "browns": BrownieRoutine(
                player_getter=_animation_player_getter,
                player_persister=_animation_player_persister,
                message_formatter=_animation_message_formatter,
                pronoun_lookup=_animation_pronoun,
            ),
            "zarapp": zar_routine.zarapp,
        },
        mob_updater=zar_routine.chkzar,
    )

    command_vocabulary = commands.CommandVocabulary(
        app.state.fixture_cache["commands"], default_messages
    )
    app.state.command_vocabulary = command_vocabulary
    app.state.command_dispatcher = commands.CommandDispatcher(
        commands.build_default_registry(command_vocabulary)
    )

    app.state.room_scripts = rooms.RoomScriptEngine(
        gateway=app.state.gateway,
        scheduler=app.state.scheduler,
        locations=app.state.fixture_cache["locations"],
        messages=default_messages,
        players=app.state.fixture_cache["players"],
        room_scripts=fixtures.load_room_scripts(seed_root),
        objects=app.state.fixture_cache["objects"],
        spells=app.state.fixture_cache["spells"],
    )
    zar_routine.initialize(app.state.animation_tick_system.state)
    app.state.animation_tick_system.persist_state()

    def _get_room_flag(room_id: int, key: str) -> int:
        if not app.state.room_scripts.yaml_engine:
            return 0
        return int(app.state.room_scripts.yaml_engine.get_room_state(room_id).get(key, 0))

    def _set_room_flag(room_id: int, key: str, value: int) -> None:
        if not app.state.room_scripts.yaml_engine:
            return
        app.state.room_scripts.yaml_engine.get_room_state(room_id)[key] = value

    async def _dispatch_animation_event(event):
        text = app.state.animation_tick_callback.resolve_event_text(event)
        if not text and not event.payload:
            return
        event_payload = dict(event.payload)
        room_event_payload = {
            key: value
            for key, value in event_payload.items()
            if not key.startswith("target_") and key not in {"target_only", "exclude_player"}
        }
        excluded_sockets = set()
        target_player = event_payload.get("target_player")
        target_text = event_payload.get("target_text")
        target_message_id = event_payload.get("target_message_id")
        target_only = bool(event_payload.get("target_only"))
        if target_player and target_text and target_message_id:
            # Legacy reference: KYRANIM.C elves() prints the hint/reward to usrnum,
            # then prints EMSG02/EMSG03 to the rest of the room (lines 367-383).
            target_payload = {
                "event": "room_message",
                "scope": "target",
                "type": "room_message",
                "message_id": target_message_id,
                "text": target_text,
                "animation_flag": event.flag,
                "player": target_player,
            }
            target_envelope = {
                "type": "command_response",
                "room": event.room_id,
                "payload": target_payload,
            }
            for token in await app.state.presence.sessions_for_player(target_player):
                target_socket = app.state.session_connections.get(token)
                if not target_socket:
                    continue
                if target_socket.application_state != WebSocketState.CONNECTED:
                    continue
                excluded_sockets.add(target_socket)
                await target_socket.send_json(target_envelope)

        if target_only:
            return

        exclude_player = event_payload.get("exclude_player")
        if exclude_player:
            for token in await app.state.presence.sessions_for_player(exclude_player):
                target_socket = app.state.session_connections.get(token)
                if not target_socket:
                    continue
                if target_socket.application_state != WebSocketState.CONNECTED:
                    continue
                excluded_sockets.add(target_socket)

        payload_event = room_event_payload.get(
            "event",
            room_event_payload.get("type", "room_message"),
        )
        payload = {
            "event": payload_event,
            "scope": "room",
            "type": room_event_payload.get("type", "room_message"),
            "message_id": event.message_id,
            "text": text,
            "animation_flag": event.flag,
        }
        payload.update(room_event_payload)
        await app.state.gateway.broadcast(
            event.room_id,
            app.state.room_scripts.room_broadcast_envelope(event.room_id, payload),
            exclude=excluded_sockets or None,
        )

    app.state.dispatch_animation_event = _dispatch_animation_event

    app.state.animation_tick_callback = AnimationTickRuntimeBridge(
        system=app.state.animation_tick_system,
        room_flag_getter=_get_room_flag,
        room_flag_setter=_set_room_flag,
        message_lookup=lambda key: messages_catalog.get(key, ""),
        event_dispatcher=_dispatch_animation_event,
    )
    app.state.tick_runtime = RuntimeTickCoordinator(
        tick_scheduler=app.state.tick_scheduler,
        spell_tick=app.state.spell_tick_system,
        animation_tick=app.state.animation_tick_callback,
    )
    app.state.tick_runtime.start()

    app.state.background_tasks = [asyncio.create_task(_heartbeat_task(app))]


async def shutdown_app(app: FastAPI):
    tasks = getattr(app.state, "background_tasks", [])
    for task in tasks:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    gateway = getattr(app.state, "gateway", None)
    if gateway:
        await gateway.close_all()

    tick_runtime = getattr(app.state, "tick_runtime", None)
    if tick_runtime:
        tick_runtime.stop()

    tick_scheduler = getattr(app.state, "tick_scheduler", None)
    if tick_scheduler:
        tick_scheduler.cancel_all()

    scheduler = getattr(app.state, "scheduler", None)
    if scheduler:
        await scheduler.stop()

    engine = getattr(app.state, "engine", None)
    if engine is not None:
        engine.dispose()


async def _heartbeat_task(app: FastAPI):
    while True:
        await asyncio.sleep(1.0)
        app.state.last_heartbeat = app.state.__dict__.get("last_heartbeat", 0) + 1


def _tick_seconds_from_env() -> float:
    raw_value = os.getenv("KYRGAME_TICK_SECONDS")
    if raw_value is None:
        return 1.0

    try:
        tick_seconds = float(raw_value)
    except ValueError:
        return 1.0

    if tick_seconds <= 0:
        return 1.0
    return tick_seconds
