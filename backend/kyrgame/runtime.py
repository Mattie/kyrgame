import asyncio
import contextlib
from fastapi import FastAPI

from . import database, fixtures, loader, rooms
from .gateway import RoomGateway
from .scheduler import SchedulerService


async def bootstrap_app(app: FastAPI):
    """Initialize database, fixture cache, and background tasks."""

    engine = database.get_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    database.init_db_schema(engine)
    session = database.create_session(engine)
    loader.load_all_from_fixtures(session)
    session.close()

    app.state.engine = engine
    app.state.gateway = RoomGateway()
    app.state.scheduler = SchedulerService()
    await app.state.scheduler.start()

    message_bundles = fixtures.load_message_bundles()
    default_messages = message_bundles[fixtures.DEFAULT_LOCALE]

    app.state.fixture_cache = {
        "locations": fixtures.load_locations(),
        "objects": fixtures.load_objects(),
        "spells": fixtures.load_spells(),
        "commands": fixtures.load_commands(),
        "messages": default_messages,
        "message_bundles": message_bundles,
        "summary": fixtures.fixture_summary(),
    }

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
