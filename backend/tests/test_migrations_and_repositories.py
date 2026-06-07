from pathlib import Path
from datetime import datetime, timezone

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import OperationalError

from kyrgame import database, loader, models, repositories


@pytest.fixture()
def database_url(tmp_path):
    return f"sqlite+pysqlite:///{tmp_path/'kyrgame.db'}"


@pytest.fixture()
def alembic_config(database_url, monkeypatch):
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture()
def migrated_engine(alembic_config, database_url):
    command.upgrade(alembic_config, "head")
    engine = database.get_engine(database_url, connect_args={"check_same_thread": False})
    yield engine
    engine.dispose()


@pytest.fixture()
def session_factory(migrated_engine):
    return database.create_session_factory(migrated_engine)


@pytest.fixture()
def session(session_factory):
    with session_factory() as db_session:
        yield db_session


@pytest.fixture()
def seeded_session(session):
    loader.load_all_from_fixtures(session)
    return session


def test_alembic_upgrade_creates_all_tables(migrated_engine):
    inspector = inspect(migrated_engine)
    table_names = set(inspector.get_table_names())

    assert {
        "spells",
        "objects",
        "locations",
        "players",
        "commands",
        "messages",
        "accounts",
        "player_sessions",
        "player_inventories",
        "spell_timers",
        "room_occupants",
    }.issubset(table_names)


def test_message_text_column_has_no_legacy_catalog_length_cap(migrated_engine):
    inspector = inspect(migrated_engine)
    message_columns = {
        column["name"]: column
        for column in inspector.get_columns("messages")
    }

    assert getattr(message_columns["text"]["type"], "length", None) is None


def test_initial_schema_revision_does_not_include_session_lifecycle_columns(
    alembic_config, database_url
):
    command.upgrade(alembic_config, "0001_initial_schema")
    engine = database.get_engine(database_url, connect_args={"check_same_thread": False})
    try:
        inspector = inspect(engine)
        session_columns = {
            column["name"] for column in inspector.get_columns("player_sessions")
        }

        assert "lifecycle_state" not in session_columns
        assert "lifecycle_step" not in session_columns
    finally:
        engine.dispose()


def test_player_and_content_column_lengths_match_existing_contracts(migrated_engine):
    inspector = inspect(migrated_engine)

    spell_name = inspector.get_columns("spells")[1]
    assert spell_name["name"] == "name"
    assert spell_name["type"].length == 32

    location_columns = {column["name"]: column for column in inspector.get_columns("locations")}
    assert location_columns["brfdes"]["type"].length == 80
    assert location_columns["objlds"]["type"].length == 160

    player_columns = {column["name"]: column for column in inspector.get_columns("players")}
    assert player_columns["uidnam"]["type"].length == 14
    assert player_columns["plyrid"]["type"].length == 14
    assert player_columns["altnam"]["type"].length == 30
    assert player_columns["attnam"]["type"].length == 30
    assert player_columns["spouse"]["type"].length == 14

    session_columns = {
        column["name"]: column for column in inspector.get_columns("player_sessions")
    }
    assert session_columns["lifecycle_state"]["type"].length == 32
    assert session_columns["lifecycle_step"]["type"].python_type is int
    assert session_columns["session_kind"]["type"].length == 16
    assert session_columns["hidden_from_activity"]["type"].python_type is bool

    account_columns = {column["name"]: column for column in inspector.get_columns("accounts")}
    assert account_columns["userid_norm"]["type"].length == 14
    assert account_columns["userid"]["type"].length == 14
    assert account_columns["password_hash"]["type"].length == 255


def test_runtime_in_memory_migration_keeps_followup_session_lifecycle_columns():
    database_url = "sqlite+pysqlite:///:memory:"
    engine = database.get_engine(database_url)
    try:
        database.run_migrations(database_url=database_url, engine=engine)
        with engine.connect() as connection:
            inspector = inspect(connection)
            session_columns = {
                column["name"]: column
                for column in inspector.get_columns("player_sessions")
            }
            version = connection.execute(
                text("select version_num from alembic_version")
            ).scalar_one()

        assert session_columns["lifecycle_state"]["type"].length == 32
        assert session_columns["lifecycle_step"]["type"].python_type is int
        assert session_columns["session_kind"]["type"].length == 16
        assert session_columns["hidden_from_activity"]["type"].python_type is bool
        assert version == "0003_accounts_session_metadata"
    finally:
        engine.dispose()


def test_wait_for_database_retries_transient_operational_errors(monkeypatch):
    sleeps: list[float] = []

    class ReadyConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement):
            self.statement = statement

    class FlakyEngine:
        def __init__(self):
            self.connect_calls = 0

        def connect(self):
            self.connect_calls += 1
            if self.connect_calls < 3:
                raise OperationalError("SELECT 1", {}, Exception("database system is starting up"))
            return ReadyConnection()

    monkeypatch.setattr(database.time, "sleep", lambda seconds: sleeps.append(seconds))

    engine = FlakyEngine()

    database.wait_for_database(engine, attempts=3, delay_seconds=0.25)

    assert engine.connect_calls == 3
    assert sleeps == [0.25, 0.25]


def test_inventory_repository_upserts_by_slot(seeded_session):
    player_id = seeded_session.scalar(select(models.Player.id))
    repo = repositories.InventoryRepository(seeded_session)

    repo.set_slot(player_id=player_id, slot_index=0, object_id=3, object_value=25)
    repo.set_slot(player_id=player_id, slot_index=0, object_id=4, object_value=30)
    seeded_session.commit()

    items = repo.list_for_player(player_id)
    assert len(items) == 1
    assert items[0].object_id == 4
    assert items[0].object_value == 30


def test_spell_timer_repository_prunes_expired(seeded_session):
    player_id = seeded_session.scalar(select(models.Player.id))
    repo = repositories.SpellTimerRepository(seeded_session)

    repo.set_timer(player_id=player_id, spell_id=1, remaining_ticks=5)
    repo.set_timer(player_id=player_id, spell_id=2, remaining_ticks=0)
    seeded_session.commit()

    repo.prune_expired(player_id)
    seeded_session.commit()

    timers = repo.list_active(player_id)
    assert [timer.spell_id for timer in timers] == [1]


def test_room_occupant_repository_limits_duplicates(seeded_session):
    player_id = seeded_session.scalar(select(models.Player.id))
    repo = repositories.RoomOccupantRepository(seeded_session)

    repo.add_or_update(room_id=10, player_id=player_id)
    repo.add_or_update(room_id=10, player_id=player_id)
    seeded_session.commit()

    occupants = repo.list_room(room_id=10)
    assert len(occupants) == 1

    repo.remove(room_id=10, player_id=player_id)
    seeded_session.commit()
    assert repo.list_room(room_id=10) == []


def test_player_session_repository_tracks_last_seen(seeded_session):
    player_id = seeded_session.scalar(select(models.Player.id))
    repo = repositories.PlayerSessionRepository(seeded_session)

    new_session = repo.create_session(player_id=player_id, session_token="abc", room_id=1)
    seeded_session.commit()
    initial_seen = new_session.last_seen

    updated_at = datetime.now(timezone.utc)
    repo.mark_seen("abc", timestamp=updated_at)
    repo.deactivate("abc")
    seeded_session.commit()
    seeded_session.refresh(new_session)

    assert repo.list_active(player_id) == []
    assert new_session.is_active is False
    assert new_session.last_seen.replace(tzinfo=None) >= initial_seen.replace(tzinfo=None)
    assert new_session.last_seen.replace(tzinfo=None) >= updated_at.replace(tzinfo=None)
