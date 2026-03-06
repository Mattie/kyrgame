from fastapi import FastAPI

from kyrgame import database, models
from kyrgame.runtime import RuntimeConfig, _database_has_locations, bootstrap_app, shutdown_app


def test_runtime_config_parses_seed_boot_flags(monkeypatch):
    monkeypatch.setenv("KYRGAME_RESET_ON_BOOT", "1")
    monkeypatch.setenv("KYRGAME_SEED_IF_EMPTY", "0")

    config = RuntimeConfig.from_env()

    assert config.reset_on_boot is True
    assert config.seed_if_empty is False


def test_runtime_config_uses_safe_default_seed_boot_flags(monkeypatch):
    monkeypatch.delenv("KYRGAME_RESET_ON_BOOT", raising=False)
    monkeypatch.delenv("KYRGAME_SEED_IF_EMPTY", raising=False)

    config = RuntimeConfig.from_env()

    assert config.reset_on_boot is False
    assert config.seed_if_empty is True


def test_database_has_locations_detects_empty_and_populated(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'runtime-empty-check.db'}"
    engine = database.get_engine(database_url)
    database.init_db_schema(engine)
    session_factory = database.create_session_factory(engine)

    with session_factory() as session:
        assert _database_has_locations(session) is False

        session.add(
            models.Location(
                id=1,
                brfdes="Room",
                objlds="",
                nlobjs=0,
                objects=[],
                gi_north=0,
                gi_south=0,
                gi_east=0,
                gi_west=0,
            )
        )
        session.commit()

        assert _database_has_locations(session) is True


def test_should_seed_database_prefers_explicit_reset(monkeypatch, tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'runtime-should-seed.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_RESET_ON_BOOT", "1")
    monkeypatch.setenv("KYRGAME_SEED_IF_EMPTY", "0")
    config = RuntimeConfig.from_env()

    engine = database.get_engine(database_url)
    database.init_db_schema(engine)
    session_factory = database.create_session_factory(engine)

    with session_factory() as session:
        assert config.should_seed_database(session) is True


async def _bootstrap_with_seed_flags(monkeypatch, tmp_path, *, seed_if_empty: str):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'runtime-seeding.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_RESET_ON_BOOT", "0")
    monkeypatch.setenv("KYRGAME_SEED_IF_EMPTY", seed_if_empty)

    app = FastAPI()
    await bootstrap_app(app)
    await shutdown_app(app)


import pytest


@pytest.mark.anyio
async def test_bootstrap_skips_fixture_reload_when_seed_if_empty_disabled(
    monkeypatch, tmp_path
):
    calls: list[object] = []

    monkeypatch.setattr(
        "kyrgame.runtime.loader.load_all_from_fixtures",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    await _bootstrap_with_seed_flags(monkeypatch, tmp_path, seed_if_empty="0")

    assert calls == []


@pytest.mark.anyio
async def test_bootstrap_seeds_empty_database_when_enabled(monkeypatch, tmp_path):
    calls: list[object] = []

    monkeypatch.setattr(
        "kyrgame.runtime.loader.load_all_from_fixtures",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    await _bootstrap_with_seed_flags(monkeypatch, tmp_path, seed_if_empty="1")

    assert len(calls) == 1
