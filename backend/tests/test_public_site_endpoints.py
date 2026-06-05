from datetime import datetime, timedelta, timezone

import httpx
import pytest

from kyrgame import constants, fixtures, models
from kyrgame.webapp import create_app


def _spell_bits(spells: list[models.SpellModel], sbkref: int, count: int) -> int:
    mask = 0
    for spell in [spell for spell in spells if spell.sbkref == sbkref][:count]:
        mask |= spell.bitdef
    return mask


def _player_payload(
    player_id: str,
    *,
    level: int,
    spells: list[models.SpellModel],
    owned: int = 0,
    female: bool = False,
):
    template = fixtures.build_player().model_copy(deep=True)
    return template.model_copy(
        update={
            "uidnam": player_id[: constants.UIDSIZ],
            "plyrid": player_id,
            "altnam": f"{player_id.title()} Alt",
            "attnam": f"{player_id.title()} Att",
            "level": level,
            "nmpdes": constants.level_to_nmpdes(level),
            "hitpts": level * 4,
            "spts": level * 2,
            "offspls": _spell_bits(spells, constants.OFFENS, owned),
            "defspls": _spell_bits(spells, constants.DEFENS, owned),
            "othspls": _spell_bits(spells, constants.OTHERS, owned),
            "spells": [],
            "nspells": 0,
            "gpobjs": [],
            "obvals": [],
            "npobjs": 0,
            "flags": int(template.flags | (constants.PlayerFlag.FEMALE if female else 0)),
        }
    )


def _add_player(
    db,
    player_id: str,
    *,
    level: int,
    spells: list[models.SpellModel],
    owned: int = 0,
    female: bool = False,
):
    player_model = _player_payload(
        player_id, level=level, spells=spells, owned=owned, female=female
    )
    record = models.Player(**player_model.model_dump())
    db.add(record)
    db.flush([record])
    return record, player_model


def _add_session(
    db,
    player: models.Player,
    *,
    token: str,
    last_seen: datetime,
    created_at: datetime | None = None,
    active: bool = False,
):
    session = models.PlayerSession(
        player_id=player.id,
        session_token=token,
        room_id=player.gamloc,
        is_active=active,
        created_at=created_at or last_seen,
        last_seen=last_seen,
        expires_at=last_seen + timedelta(days=2),
    )
    db.add(session)
    return session


@pytest.mark.anyio
async def test_public_player_activity_groups_sessions_active_players_and_recent_window(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "1000")
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        spells = app.state.fixture_cache["spells"]
        now = datetime.now(timezone.utc).replace(microsecond=0)
        with app.state.session_factory() as db:
            live_record, live_model = _add_player(db, "live", level=25, spells=spells, owned=2)
            _add_session(db, live_record, token="live-old", last_seen=now - timedelta(hours=1))
            app.state.active_player_sessions["live-token"] = live_model
            app.state.active_player_connected_at["live-token"] = now - timedelta(minutes=3)

            fresh_record, fresh_model = _add_player(
                db, "fresh", level=11, spells=spells, owned=1, female=True
            )
            _add_session(db, fresh_record, token="fresh-old", last_seen=now - timedelta(hours=1))
            app.state.active_player_sessions["fresh-token"] = fresh_model
            app.state.active_player_connected_at["fresh-token"] = now - timedelta(seconds=5)

            db_active_record, _ = _add_player(db, "tokened", level=10, spells=spells, owned=1)
            _add_session(
                db,
                db_active_record,
                token="tokened-session",
                last_seen=now - timedelta(seconds=30),
                created_at=now - timedelta(seconds=30),
                active=True,
            )

            stale_active_record, _ = _add_player(db, "quiet", level=9, spells=spells, owned=3)
            _add_session(
                db,
                stale_active_record,
                token="quiet-session",
                last_seen=now - timedelta(minutes=10),
                active=True,
            )

            for index in range(6):
                record, _ = _add_player(
                    db,
                    f"recent{index + 1}",
                    level=8 - index,
                    spells=spells,
                    owned=index % 3,
                )
                _add_session(
                    db,
                    record,
                    token=f"recent-{index + 1}",
                    last_seen=now - timedelta(days=index + 1),
                )

            stale_record, _ = _add_player(db, "stale", level=9, spells=spells, owned=3)
            _add_session(
                db,
                stale_record,
                token="stale-session",
                last_seen=now - timedelta(days=8),
            )
            db.commit()

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/public/player-activity")

        assert response.status_code == 200
        payload = response.json()
        active_ids = [player["player_id"] for player in payload["active"]]
        recent_ids = [player["player_id"] for player in payload["recent"]]

        assert active_ids == ["fresh", "tokened", "live"]
        assert recent_ids == ["quiet", "recent1", "recent2", "recent3", "recent4"]
        assert "recent6" not in recent_ids
        assert "stale" not in recent_ids
        assert "live" not in recent_ids
        assert "quiet" not in active_ids
        assert payload["active"][0]["rank_title"] == "Blue Wizard"
        assert payload["active"][0]["wizard_symbol"] == "🧙‍♀️"
        assert payload["active"][0]["spellbook_count"] == 3
        assert payload["active"][0]["active"] is True
        assert payload["active"][0]["connected_at"] is not None
        assert payload["active"][0]["connection_duration_seconds"] < payload["active"][1]["connection_duration_seconds"]
        assert payload["active"][1]["connection_duration_seconds"] < payload["active"][2]["connection_duration_seconds"]
        assert payload["recent"][0]["active"] is False
        assert payload["recent"][0]["connected_at"] is None
        assert payload["recent"][0]["connection_duration_seconds"] is None
        assert set(payload["active"][0]) == {
            "player_id",
            "display_name",
            "level",
            "rank_title",
            "wizard_symbol",
            "spellbook_count",
            "active",
            "last_seen",
            "connected_at",
            "connection_duration_seconds",
        }


@pytest.mark.anyio
async def test_public_leaderboard_sorts_by_level_spellbook_count_and_player_id(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "1000")
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        spells = app.state.fixture_cache["spells"]
        now = datetime.now(timezone.utc).replace(microsecond=0)
        with app.state.session_factory() as db:
            for player_id, level, owned in [
                ("archer", 24, 1),
                ("beacon", 24, 3),
                ("cipher", 24, 3),
                ("delver", 23, 8),
            ]:
                record, _ = _add_player(db, player_id, level=level, spells=spells, owned=owned)
                _add_session(
                    db,
                    record,
                    token=f"{player_id}-session",
                    last_seen=now - timedelta(minutes=1),
                )
            db.commit()

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/public/leaderboard")

        assert response.status_code == 200
        players = response.json()["players"]
        ordered_ids = [player["player_id"] for player in players[:4]]

        assert ordered_ids == ["beacon", "cipher", "archer", "delver"]
        assert players[0]["level"] == 24
        assert players[0]["rank_title"] == "Arch-Mage of Jewels"
        assert players[0]["spellbook_count"] == 9
        assert "gold" not in players[0]
        assert "session_token" not in players[0]
        assert "offspls" not in players[0]
