import string
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from kyrgame import constants, fixtures, models
from kyrgame.webapp import PUBLIC_RECENT_PLAYER_SCAN_LIMIT, create_app


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
async def test_public_player_id_lookup_reports_existing_available_and_reserved(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "1000")
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            existing = await client.get("/public/player-id/hero")
            available = await client.get("/public/player-id/Willow")
            lower_available = await client.get("/public/player-id/avalon")
            reserved = await client.get("/public/player-id/Zar")
            lower_reserved = await client.get("/public/player-id/zar")
            invalid = await client.get("/public/player-id/ab12")

        assert existing.status_code == 200
        assert existing.json() == {
            "player_id": "hero",
            "canonical_player_id": "hero",
            "valid": True,
            "exists": True,
            "available": False,
            "reserved": False,
            "account_bound": False,
            "status": "existing",
        }
        assert available.status_code == 200
        assert available.json() == {
            "player_id": "Willow",
            "canonical_player_id": "Willow",
            "valid": True,
            "exists": False,
            "available": True,
            "reserved": False,
            "account_bound": None,
            "status": "available",
        }
        assert lower_available.json()["player_id"] == "Avalon"
        assert lower_available.json()["canonical_player_id"] == "Avalon"
        assert reserved.json()["status"] == "reserved"
        assert reserved.json()["available"] is False
        assert lower_reserved.json()["player_id"] == "Zar"
        assert lower_reserved.json()["canonical_player_id"] == "Zar"
        assert invalid.json()["status"] == "invalid"
        assert invalid.json()["valid"] is False


@pytest.mark.anyio
async def test_public_player_id_lookup_reports_existing_account_binding(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "1000")
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        with app.state.session_factory() as db:
            player = db.scalar(select(models.Player).where(models.Player.plyrid == "hero"))
            assert player is not None
            db.add(
                models.Account(
                    userid="hero",
                    userid_norm="hero",
                    password_hash="test-password-hash",
                    player_id=player.id,
                )
            )
            db.commit()

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            existing = await client.get("/public/player-id/hero")

        assert existing.status_code == 200
        assert existing.json()["status"] == "existing"
        assert existing.json()["account_bound"] is True


@pytest.mark.anyio
async def test_public_player_id_lookup_rate_limits_repeated_checks(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "1000")
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for index in range(30):
                response = await client.get(
                    "/public/player-id/Willow",
                    headers={
                        "cf-connecting-ip": f"198.51.100.{index}",
                        "x-forwarded-for": f"203.0.113.{index}",
                    },
                )
                assert response.status_code == 200

            limited = await client.get(
                "/public/player-id/Willow",
                headers={"cf-connecting-ip": "198.51.100.200", "x-forwarded-for": "203.0.113.200"},
            )

        assert limited.status_code == 429
        assert limited.json()["detail"] == "Too many Player-ID checks. Please slow down."


@pytest.mark.anyio
async def test_public_player_id_lookup_bounds_rate_limit_client_cache(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "1000")
    monkeypatch.setenv("KYRGAME_TRUST_PROXY_HEADERS", "1")
    monkeypatch.setenv("KYRGAME_HTTP_RATE_LIMIT_MAX_CLIENT_KEYS", "3")
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for index in range(5):
                response = await client.get(
                    "/public/player-id/Willow",
                    headers={"x-forwarded-for": f"203.0.113.{index}"},
                )
                assert response.status_code == 200

        limiters = app.state.public_player_id_lookup_rate_limiters
        assert len(limiters) == 3


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

        assert active_ids == ["fresh", "live"]
        assert recent_ids == ["tokened", "quiet", "recent1", "recent2", "recent3"]
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
async def test_public_player_activity_excludes_runtime_active_players_before_recent_cap(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "1000")
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        spells = app.state.fixture_cache["spells"]
        now = datetime.now(timezone.utc).replace(microsecond=0)
        active_names = [
            f"aa{first}{second}"
            for first in string.ascii_lowercase
            for second in string.ascii_lowercase
        ][: PUBLIC_RECENT_PLAYER_SCAN_LIMIT + 1]
        offline_names = ["offaa", "offab", "offac", "offad", "offae"]
        with app.state.session_factory() as db:
            for index, player_id in enumerate(active_names):
                record, player_model = _add_player(
                    db, player_id, level=25, spells=spells, owned=2
                )
                _add_session(
                    db,
                    record,
                    token=f"{player_id}-old-session",
                    last_seen=now - timedelta(seconds=index + 1),
                )
                app.state.active_player_sessions[f"{player_id}-token"] = player_model
                app.state.active_player_connected_at[f"{player_id}-token"] = (
                    now - timedelta(minutes=index + 1)
                )

            for index, player_id in enumerate(offline_names):
                record, _ = _add_player(db, player_id, level=10, spells=spells, owned=1)
                _add_session(
                    db,
                    record,
                    token=f"{player_id}-session",
                    last_seen=now - timedelta(minutes=2, seconds=index),
                )
            db.commit()

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/public/player-activity")

        assert response.status_code == 200
        payload = response.json()
        assert [player["player_id"] for player in payload["recent"]] == offline_names


@pytest.mark.anyio
async def test_public_player_activity_orders_recent_timestamp_ties_by_player_id(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "1000")
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        spells = app.state.fixture_cache["spells"]
        now = datetime.now(timezone.utc).replace(microsecond=0)
        tied_seen_at = now - timedelta(days=1)
        with app.state.session_factory() as db:
            for player_id, last_seen in [
                ("zulu", tied_seen_at),
                ("alpha", tied_seen_at),
                ("bravo", now - timedelta(hours=12)),
            ]:
                record, _ = _add_player(db, player_id, level=10, spells=spells, owned=1)
                _add_session(
                    db,
                    record,
                    token=f"{player_id}-session",
                    last_seen=last_seen,
                )
            db.commit()

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/public/player-activity")

        assert response.status_code == 200
        payload = response.json()
        assert [player["player_id"] for player in payload["recent"]] == [
            "bravo",
            "alpha",
            "zulu",
        ]


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


@pytest.mark.anyio
async def test_public_leaderboard_caps_release_payload_size(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "1000")
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        spells = app.state.fixture_cache["spells"]
        with app.state.session_factory() as db:
            names = [
                f"p{first}{second}"
                for first in string.ascii_lowercase
                for second in string.ascii_lowercase
            ][:60]
            for player_id in names:
                _add_player(db, player_id, level=25, spells=spells, owned=3)
            db.commit()

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/public/leaderboard")

        assert response.status_code == 200
        assert len(response.json()["players"]) == 50


@pytest.mark.anyio
async def test_public_leaderboard_ranks_spellbooks_before_payload_slice(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "1000")
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        spells = app.state.fixture_cache["spells"]
        with app.state.session_factory() as db:
            low_spell_names = [
                f"a{first}{second}{third}"
                for first in string.ascii_lowercase
                for second in string.ascii_lowercase
                for third in string.ascii_lowercase
            ][:505]
            for player_id in low_spell_names:
                _add_player(db, player_id, level=25, spells=spells, owned=0)
            _add_player(db, "zzzz", level=25, spells=spells, owned=6)
            db.commit()

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/public/leaderboard")

        assert response.status_code == 200
        players = response.json()["players"]
        assert players[0]["player_id"] == "zzzz"
