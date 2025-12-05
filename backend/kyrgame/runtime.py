import asyncio
import contextlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI

from . import commands, database, fixtures, loader, rooms
from .gateway import RoomGateway
from .presence import PresenceService
from .scheduler import SchedulerService


@dataclass
class RuntimeConfig:
    database_url: str
    migration_runner: str
    seed_paths: List[Path] = field(default_factory=list)
    run_migrations: bool = True
    migration_revision: str = "head"

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
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
            run_migrations=os.getenv("KYRGAME_RUN_MIGRATIONS", "1").lower()
            not in {"0", "false", "no"},
            migration_revision=os.getenv("KYRGAME_MIGRATION_REVISION", "head"),
        )

    def primary_seed_path(self) -> Optional[Path]:
        for seed in self.seed_paths:
            if seed.exists():
                return seed
        return None


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
        loader.load_all_from_fixtures(session, fixture_root=seed_root)

    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.gateway = RoomGateway()
    app.state.presence = PresenceService()
    app.state.scheduler = SchedulerService()
    await app.state.scheduler.start()

    message_bundles = fixtures.load_message_bundles(seed_root)
    default_messages = message_bundles[fixtures.DEFAULT_LOCALE]

    app.state.fixture_cache = {
        "locations": fixtures.load_locations(seed_root),
        "objects": fixtures.load_objects(seed_root),
        "spells": fixtures.load_spells(seed_root),
        "commands": fixtures.load_commands(seed_root),
        "players": fixtures.load_players(seed_root),
        "player_template": fixtures.build_player(seed_root),
        "messages": default_messages,
        "message_bundles": message_bundles,
        "summary": fixtures.fixture_summary(seed_root),
    }
    app.state.location_index = {loc.id: loc for loc in app.state.fixture_cache["locations"]}

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
    )

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
