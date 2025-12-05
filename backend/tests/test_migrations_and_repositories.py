from pathlib import Path
from datetime import datetime, timezone

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select

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
        "player_sessions",
        "player_inventories",
        "spell_timers",
        "room_occupants",
    }.issubset(table_names)


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
