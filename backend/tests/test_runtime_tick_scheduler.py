import pytest
from fastapi import FastAPI

from kyrgame.runtime import bootstrap_app, shutdown_app


@pytest.mark.anyio
async def test_bootstrap_initializes_tick_scheduler_and_shutdown_cancels_timers(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "0.25")

    app = FastAPI()
    await bootstrap_app(app)

    assert hasattr(app.state, "tick_scheduler")
    assert hasattr(app.state, "tick_runtime")
    assert app.state.tick_scheduler.tick_seconds == 0.25

    spell_handle = app.state.tick_runtime.handles["spell_tick"]
    animation_handle = app.state.tick_runtime.handles["animation_tick"]
    assert not spell_handle.cancelled
    assert not animation_handle.cancelled

    handle = app.state.tick_scheduler.register_recurring_timer(
        "test_tick", 1, lambda: None
    )
    assert not handle.cancelled

    await shutdown_app(app)

    assert spell_handle.cancelled
    assert animation_handle.cancelled
    assert handle.cancelled
    assert app.state.scheduler._task is None


@pytest.mark.anyio
async def test_bootstrap_uses_default_tick_seconds_when_env_missing(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.delenv("KYRGAME_TICK_SECONDS", raising=False)

    app = FastAPI()
    await bootstrap_app(app)

    assert app.state.tick_scheduler.tick_seconds == 1.0

    await shutdown_app(app)
