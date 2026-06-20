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
from .honor_mode import HonorModePolicy
from .presence import PresenceService
from .scheduler import SchedulerService
from .session_state import sync_active_player_state_from_db
from .spells.tick_system import (
    NoopSpellTickMessaging,
    SQLAlchemySpellTickPlayerRepository,
    SpellTickConstants,
    SpellTickSystem,
)
from .telemetry import TelemetryEventSink
from .timing.runtime import RuntimeTickCoordinator
from .timing.scheduler import TickScheduler
from .world.animation_tick_system import (
    AnimationTickRuntimeBridge,
    AnimationTickSystem,
    BrownieRoutine,
    DryadWanderRoutine,
    ElfEncounterRoutine,
    GemSpawnRoutine,
    SQLAlchemyAnimationTickPersistence,
    ZarDragonRoutine,
)


async def _publish_runtime_scry_output(app: FastAPI, player_id: str | None, message: dict) -> None:
    publisher = getattr(app.state, "scry_publish_output", None)
    if publisher is None or not player_id:
        return
    await publisher(app, player_id, message)


async def _publish_runtime_scry_for_recipients(
    app: FastAPI, recipients: list | None, message: dict
) -> None:
    if not recipients:
        return
    socket_players = getattr(app.state, "game_socket_players", {})
    for recipient in recipients:
        await _publish_runtime_scry_output(app, socket_players.get(recipient), message)


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
    db_connect_attempts: int = 1
    db_connect_retry_seconds: float = 1.0
    force_honor_mode: bool = False

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
            db_connect_attempts=_env_int("KYRGAME_DB_CONNECT_ATTEMPTS", default=1),
            db_connect_retry_seconds=_env_float("KYRGAME_DB_CONNECT_RETRY_SECONDS", default=1.0),
            force_honor_mode=_env_flag("KYRGAME_FORCE_HONOR_MODE", default=False),
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
    normalized = value.strip().lower()
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    if normalized in {"1", "true", "yes", "on"}:
        return True
    return True


def _env_int(name: str, *, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return int(value)


def _env_float(name: str, *, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    return float(value)


def _database_has_locations(session: Session) -> bool:
    return session.query(models.Location.id).first() is not None


async def bootstrap_app(app: FastAPI):
    """Initialize database, fixture cache, and background tasks."""

    runtime_config = RuntimeConfig.from_env()
    engine = database.get_engine(runtime_config.database_url)
    database.wait_for_database(
        engine,
        attempts=runtime_config.db_connect_attempts,
        delay_seconds=runtime_config.db_connect_retry_seconds,
    )

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
    app.state.runtime_config = runtime_config
    app.state.honor_mode_policy = HonorModePolicy(
        force_honor_mode=runtime_config.force_honor_mode
    )
    app.state.session_factory = session_factory
    app.state.gateway = RoomGateway()
    app.state.presence = PresenceService()
    app.state.scheduler = SchedulerService()
    await app.state.scheduler.start()
    app.state.tick_scheduler = TickScheduler(
        app.state.scheduler,
        tick_seconds=_tick_seconds_from_env(),
    )
    if not hasattr(app.state, "telemetry_sink"):
        app.state.telemetry_sink = TelemetryEventSink.from_env()
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

    objects_by_id = {obj.id: obj for obj in app.state.fixture_cache["objects"]}
    object_names_by_id = {obj.id: obj.name for obj in app.state.fixture_cache["objects"]}
    app.state.animation_rng = random.Random()

    def _animation_room_picker(low: int, high: int) -> int:
        # Legacy genrdn(low, high) excludes the upper bound.
        # Source: legacy/KYRANIM.C:326-459.
        return app.state.animation_rng.randrange(low, high)

    def _animation_chance_picker(low: int, high: int) -> int:
        return app.state.animation_rng.randrange(low, high)

    def _animation_pick_gem(low: int, high: int) -> int:
        return app.state.animation_rng.randrange(low, high)

    def _animation_pick_gold(low: int, high: int) -> int:
        return app.state.animation_rng.randrange(low, high)

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

    def _animation_player_ids_getter(room_id: int) -> list[str]:
        return [player.plyrid for player in _animation_players_getter(room_id)]

    def _animation_player_persister(player: models.PlayerModel) -> None:
        with session_factory() as db:
            record = db.scalar(select(models.Player).where(models.Player.plyrid == player.plyrid))
            if not record:
                return
            record.gamloc = player.gamloc
            record.pgploc = player.pgploc
            record.altnam = player.altnam
            record.attnam = player.attnam
            record.nmpdes = player.nmpdes
            record.flags = int(player.flags)
            record.level = player.level
            record.hitpts = player.hitpts
            record.spts = player.spts
            record.gold = player.gold
            record.gpobjs = list(player.gpobjs)
            record.obvals = list(player.obvals)
            record.npobjs = player.npobjs
            record.spells = list(player.spells)
            record.nspells = player.nspells
            record.offspls = player.offspls
            record.defspls = player.defspls
            record.othspls = player.othspls
            record.charms = list(player.charms)
            record.gemidx = player.gemidx
            record.stones = list(player.stones)
            record.macros = player.macros
            record.stumpi = player.stumpi
            record.spouse = player.spouse
            record.honor_mode = player.honor_mode
            db.commit()

    def _animation_death_recovery_persister(player: models.PlayerModel, plan) -> None:
        # modern_death_recovery: Zar death commits the recovered player and all
        # changed room-object rows together. See docs/MODERN_FEATURES.md.
        updated_locations: list[tuple[int, list[int]]] = []
        with session_factory() as db:
            try:
                record = db.scalar(
                    select(models.Player).where(models.Player.plyrid == player.plyrid)
                )
                if not record:
                    db.rollback()
                    raise RuntimeError(
                        "Cannot persist modern_death_recovery for missing player "
                        f"{player.plyrid}"
                    )
                def value(field_name: str):
                    return plan.player_updates.get(field_name, getattr(player, field_name))

                record.gamloc = value("gamloc")
                record.pgploc = value("pgploc")
                record.altnam = value("altnam")
                record.attnam = value("attnam")
                record.nmpdes = value("nmpdes")
                record.flags = int(value("flags"))
                record.level = value("level")
                record.hitpts = value("hitpts")
                record.spts = value("spts")
                record.gold = value("gold")
                record.gpobjs = list(value("gpobjs"))
                record.obvals = list(value("obvals"))
                record.npobjs = value("npobjs")
                record.spells = list(value("spells"))
                record.nspells = value("nspells")
                record.offspls = value("offspls")
                record.defspls = value("defspls")
                record.othspls = value("othspls")
                record.charms = list(value("charms"))
                record.gemidx = value("gemidx")
                record.stones = list(value("stones"))
                record.macros = value("macros")
                record.stumpi = value("stumpi")
                record.spouse = value("spouse")
                record.honor_mode = value("honor_mode")
                location_repo = repositories.LocationRepository(db)
                for room_update in plan.room_object_updates:
                    location_repo.update_objects(
                        room_update.room_id, list(room_update.object_ids)
                    )
                    updated_locations.append(
                        (room_update.room_id, list(room_update.object_ids))
                    )
                db.commit()
            except Exception:
                db.rollback()
                raise
        for room_id, object_ids in updated_locations:
            location = app.state.location_index.get(room_id)
            if location:
                app.state.location_index[room_id] = location.model_copy(
                    update={"objects": object_ids, "nlobjs": len(object_ids)}
                )

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
        object_name_lookup=_animation_object_name_lookup,
        zar_location_setter=_set_zar_location,
        locations_getter=lambda: app.state.location_index,
        death_recovery_persister=_animation_death_recovery_persister,
        honor_mode_policy=app.state.honor_mode_policy,
    )
    app.state.animation_zar_routine = zar_routine
    app.state.animation_tick_persistence = SQLAlchemyAnimationTickPersistence(session_factory)
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
                player_ids_getter=_animation_player_ids_getter,
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
        locations=app.state.location_index.values(),
        messages=default_messages,
        players=app.state.fixture_cache["players"],
        room_scripts=fixtures.load_room_scripts(seed_root),
        objects=app.state.fixture_cache["objects"],
        spells=app.state.fixture_cache["spells"],
        room_picker=_animation_chance_picker,
        room_objects_getter=_animation_get_room_objects,
        room_objects_setter=_animation_set_room_objects,
        room_players_getter=_animation_players_getter,
        honor_mode_policy=app.state.honor_mode_policy,
        defer_modern_death_recovery=True,
    )
    zar_routine.initialize(app.state.animation_tick_system.state)
    app.state.animation_tick_system.persist_state()

    hardcoded_room_flags = {(7, "chantd")}

    def _get_room_flag(room_id: int, key: str) -> int:
        # Legacy `chantd` is owned by the hardcoded temple handler.
        # Source: legacy/KYRROUS.C:319-330 and legacy/KYRANIM.C:140-143.
        if (room_id, key) in hardcoded_room_flags:
            return int(app.state.room_scripts.get_room_state(room_id).flags.get(key, 0))
        if not app.state.room_scripts.yaml_engine:
            return 0
        return int(app.state.room_scripts.yaml_engine.get_room_state(room_id).get(key, 0))

    def _set_room_flag(room_id: int, key: str, value: int) -> None:
        if (room_id, key) in hardcoded_room_flags:
            app.state.room_scripts.get_room_state(room_id).flags[key] = value
            return
        if not app.state.room_scripts.yaml_engine:
            return
        app.state.room_scripts.yaml_engine.get_room_state(room_id)[key] = value

    def _runtime_active_player_flags() -> dict[str, int]:
        flags: dict[str, int] = {}
        for player in getattr(app.state, "active_players", {}).values():
            flags[player.plyrid] = int(player.flags)
        for player in getattr(app.state, "active_player_sessions", {}).values():
            flags[player.plyrid] = int(player.flags)
        return flags

    def _runtime_active_player_index() -> dict[str, models.PlayerModel]:
        indexed_players: dict[str, models.PlayerModel] = {}
        for player in getattr(app.state, "active_players", {}).values():
            player_key = player.plyrid.strip().casefold()
            if player_key:
                indexed_players[player_key] = player
        for player in getattr(app.state, "active_player_sessions", {}).values():
            player_key = player.plyrid.strip().casefold()
            if player_key:
                indexed_players[player_key] = player
        return indexed_players

    async def _room_occupants_refresh_payload(
        player_id: str,
        room_id: int,
        *,
        occupants: list[str] | None = None,
        player_flags_by_id: dict[str, int] | None = None,
    ) -> dict | None:
        if occupants is None:
            occupants = await app.state.presence.players_in_room(room_id)
        active_player_index = _runtime_active_player_index()

        def payload_active_player_lookup(lookup_player_id: str):
            return active_player_index.get(lookup_player_id.strip().casefold())

        viewer = payload_active_player_lookup(player_id)
        entries = commands._room_occupant_display_entries(
            sorted(occupants),
            viewer_id=player_id,
            viewer=viewer,
            player_lookup=payload_active_player_lookup,
            player_flags_by_id=player_flags_by_id,
        )
        others = [entry.display_name for entry in entries]
        text, message_id = commands._format_room_occupant_entries(
            entries, default_messages
        )
        if not text:
            return None
        if player_flags_by_id is None:
            player_flags_by_id = _runtime_active_player_flags()
        return {
            "scope": "player",
            "event": "room_occupants",
            "type": "room_occupants",
            "location": room_id,
            "occupants": others,
            "occupant_details": commands._room_occupant_detail_payload(entries),
            "text": text,
            "message_id": message_id,
        }

    async def _target_room_refresh_payloads(player_id: str, room_id: int) -> list[dict]:
        location = app.state.location_index.get(room_id)
        player_state = app.state.active_players.get(player_id)
        if location is None or player_state is None:
            return []

        state = commands.GameState(
            player=player_state,
            locations=app.state.location_index,
            objects=objects_by_id,
            messages=default_messages,
            content_mappings=content_mappings,
            presence=app.state.presence,
        )
        description_id, long_description = commands._location_description(state, location)
        payloads = [
            {
                "scope": "player",
                "event": "location_description",
                "type": "location_description",
                "location": location.id,
                "message_id": description_id,
                "text": long_description or location.brfdes,
            },
            commands._room_objects_event(location, objects_by_id, None, description_id),
        ]
        occupants = await app.state.presence.players_in_room(room_id)
        player_flags_by_id = _runtime_active_player_flags()
        occupant_payload = await _room_occupants_refresh_payload(
            player_id,
            room_id,
            occupants=occupants,
            player_flags_by_id=player_flags_by_id,
        )
        if occupant_payload:
            payloads.append(occupant_payload)
        return payloads

    async def _send_runtime_player_payload(
        player_id: str, room_id: int, payload: dict
    ) -> None:
        envelope = {"type": "command_response", "room": room_id, "payload": payload}
        session_connections = getattr(app.state, "session_connections", {})
        for token in await app.state.presence.sessions_for_player(player_id):
            target_socket = session_connections.get(token)
            if not target_socket:
                continue
            if target_socket.application_state != WebSocketState.CONNECTED:
                continue
            await target_socket.send_json(envelope)
            await _publish_runtime_scry_output(app, player_id, envelope)

    async def _send_room_occupant_refreshes(room_ids: set[int]) -> None:
        for room_id in room_ids:
            occupants = commands._dedupe_room_occupants(
                sorted(await app.state.presence.players_in_room(room_id))
            )
            player_flags_by_id = _runtime_active_player_flags()
            for player_id in occupants:
                payload = await _room_occupants_refresh_payload(
                    player_id,
                    room_id,
                    occupants=occupants,
                    player_flags_by_id=player_flags_by_id,
                )
                if payload:
                    await _send_runtime_player_payload(player_id, room_id, payload)

    async def _spell_tick_callback():
        result = app.state.spell_tick_system.tick()

        for touched in result.touched_players:
            sync_active_player_state_from_db(app, touched.player_id)

        player_flags_by_id = _runtime_active_player_flags()
        for direct_message in result.direct_messages:
            player_flags = player_flags_by_id.get(direct_message.player_id)
            payload = {
                "scope": "player",
                "event": "room_message",
                "type": "room_message",
                "message_id": direct_message.message_id,
                "text": direct_message.text,
                "player": direct_message.player_id,
            }
            if player_flags is not None:
                payload["player_flags"] = int(player_flags)
            await _send_runtime_player_payload(
                direct_message.player_id,
                direct_message.room_id,
                payload,
            )

        session_connections = getattr(app.state, "session_connections", {})
        affected_room_ids: set[int] = set()
        for room_message in result.room_messages:
            excluded_sockets = set()
            for token in await app.state.presence.sessions_for_player(
                room_message.exclude_player_id
            ):
                if await app.state.presence.room_for_session(token) != room_message.room_id:
                    continue
                target_socket = session_connections.get(token)
                if not target_socket:
                    continue
                if target_socket.application_state != WebSocketState.CONNECTED:
                    continue
                excluded_sockets.add(target_socket)
            if not excluded_sockets:
                continue
            payload = {
                "scope": "room",
                "event": "room_message",
                "type": "room_message",
                "message_id": room_message.message_id,
                "text": room_message.text,
                "exclude_player": room_message.exclude_player_id,
            }
            envelope = {"type": "room_broadcast", "room": room_message.room_id, "payload": payload}
            recipients = await app.state.gateway.broadcast(
                room_message.room_id,
                envelope,
                exclude=excluded_sockets or None,
            )
            await _publish_runtime_scry_for_recipients(app, recipients, envelope)
            affected_room_ids.add(room_message.room_id)

        if affected_room_ids:
            await _send_room_occupant_refreshes(affected_room_ids)

    app.state.spell_tick_callback = _spell_tick_callback

    async def _dispatch_animation_event(event):
        text = app.state.animation_tick_callback.resolve_event_text(event)
        if not text and not event.payload:
            return
        event_payload = dict(event.payload)
        room_event_payload = {
            key: value
            for key, value in event_payload.items()
            if not key.startswith("target_") and key not in {"target_only"}
        }
        excluded_sockets = set()
        target_player = event_payload.get("target_player")
        target_text = event_payload.get("target_text")
        target_message_id = event_payload.get("target_message_id")
        target_event = event_payload.get("target_event")
        target_type = event_payload.get("target_type", target_event)
        move_player_to = event_payload.get("move_player_to")
        target_only = bool(event_payload.get("target_only"))
        if target_player and event_payload.get("death_reset"):
            sync_active_player_state_from_db(app, target_player)
        if target_player and (
            (target_text and target_message_id) or target_event or move_player_to is not None
        ):
            # Legacy reference: KYRANIM.C elves() prints the hint/reward to usrnum,
            # then prints EMSG02/EMSG03 to the rest of the room (lines 367-383).
            target_room = int(move_player_to if move_player_to is not None else event.room_id)
            followup_payloads: list[dict] = []
            if move_player_to is not None:
                for session_token, player_state in getattr(
                    app.state, "active_player_sessions", {}
                ).items():
                    if player_state.plyrid == target_player:
                        player_state.pgploc = target_room
                        player_state.gamloc = target_room
                        app.state.active_players[target_player] = player_state
                        await app.state.presence.set_location(
                            target_player, target_room, session_token
                        )
                        target_socket = app.state.session_connections.get(session_token)
                        if (
                            target_socket
                            and target_socket.application_state == WebSocketState.CONNECTED
                        ):
                            await app.state.gateway.register(
                                target_room, target_socket, announce=False
                            )
                with session_factory() as db:
                    session_repo = repositories.PlayerSessionRepository(db)
                    for token in await app.state.presence.sessions_for_player(target_player):
                        session_repo.set_room(token, target_room)
                    db.commit()
                # Legacy entrgp() sends the new room description, visible objects,
                # and occupants after forced placement (legacy/KYRUTIL.C:236-256).
                followup_payloads = await _target_room_refresh_payloads(
                    target_player, target_room
                )

            if target_event:
                target_payload = {
                    "event": target_event,
                    "scope": "target",
                    "type": target_type or target_event,
                    "message_id": target_message_id,
                    "text": target_text or "",
                    "animation_flag": event.flag,
                    "player": target_player,
                    "location": event_payload.get("location", target_room),
                }
                if move_player_to is not None:
                    target_payload["move_player_to"] = target_room
                if event_payload.get("death_reset"):
                    target_payload["death_reset"] = True
            else:
                target_payload = {
                    "event": "room_message",
                    "scope": "target",
                    "type": "room_message",
                    "message_id": target_message_id,
                    "text": target_text,
                    "animation_flag": event.flag,
                    "player": target_player,
                }
                if event_payload.get("death_reset"):
                    target_payload["death_reset"] = True
            for metadata_key in (
                "modern_death_recovery",
                "old_level",
                "new_level",
                "filtered_items",
                "vanished_items",
                "dropped_rooms",
                "refresh_location",
                "recipient_scope",
                "pre_death_drop",
                "object_id",
            ):
                if metadata_key in event_payload:
                    target_payload[metadata_key] = event_payload[metadata_key]
            target_envelope = {
                "type": "command_response",
                "room": target_room,
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
                await _publish_runtime_scry_output(app, target_player, target_envelope)
                for followup_payload in followup_payloads:
                    followup_envelope = {
                        "type": "command_response",
                        "room": target_room,
                        "payload": followup_payload,
                    }
                    await target_socket.send_json(followup_envelope)
                    await _publish_runtime_scry_output(app, target_player, followup_envelope)

        if target_only:
            return

        exclude_player = event_payload.get("exclude_player")
        exclude_players = set(event_payload.get("exclude_players") or [])
        if exclude_player:
            exclude_players.add(exclude_player)
        for exclude_player_id in exclude_players:
            for token in await app.state.presence.sessions_for_player(exclude_player_id):
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
        envelope = app.state.room_scripts.room_broadcast_envelope(event.room_id, payload)
        recipients = await app.state.gateway.broadcast(
            event.room_id,
            envelope,
            exclude=excluded_sockets or None,
        )
        await _publish_runtime_scry_for_recipients(app, recipients, envelope)

    app.state.dispatch_animation_event = _dispatch_animation_event

    async def _record_animation_audit(event_type: str, payload):
        telemetry_sink = getattr(app.state, "telemetry_sink", None)
        if telemetry_sink is None:
            return
        await telemetry_sink.record_system(event_type=event_type, payload=dict(payload))

    app.state.animation_tick_callback = AnimationTickRuntimeBridge(
        system=app.state.animation_tick_system,
        room_flag_getter=_get_room_flag,
        room_flag_setter=_set_room_flag,
        message_lookup=lambda key: messages_catalog.get(key, ""),
        event_dispatcher=_dispatch_animation_event,
        audit_recorder=_record_animation_audit,
        expected_interval_seconds=app.state.tick_scheduler.ticks_to_seconds(15),
    )
    app.state.tick_runtime = RuntimeTickCoordinator(
        tick_scheduler=app.state.tick_scheduler,
        spell_tick=app.state.spell_tick_callback,
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
