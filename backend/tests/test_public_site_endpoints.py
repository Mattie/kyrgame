import string
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.dialects import sqlite

from kyrgame import constants, fixtures, models, webapp
from kyrgame.webapp import (
    PUBLIC_LEADERBOARD_LIMIT,
    PUBLIC_RECENT_PLAYER_SCAN_LIMIT,
    create_app,
)


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
async def test_public_activity_and_leaderboard_hide_allowlisted_admin_accounts(
    monkeypatch, tmp_path
):
    allowlist_path = tmp_path / "admin-allowlist.yaml"
    allowlist_path.write_text(
        """
admins:
  adminacct:
    roles: [player_admin]
  modacct:
    roles: [content_admin]
""".lstrip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "1000")
    monkeypatch.setenv("KYRGAME_ADMIN_ALLOWLIST_PATH", str(allowlist_path))
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        spells = app.state.fixture_cache["spells"]
        now = datetime.now(timezone.utc).replace(microsecond=0)
        with app.state.session_factory() as db:
            admin_record, admin_model = _add_player(
                db, "adminplyr", level=25, spells=spells, owned=6
            )
            db.add(
                models.Account(
                    userid="AdminAcct",
                    userid_norm="adminacct",
                    password_hash="test-password-hash",
                    player_id=admin_record.id,
                )
            )
            _add_session(
                db,
                admin_record,
                token="admin-token",
                last_seen=now - timedelta(minutes=1),
                active=True,
            )
            stale_admin_model = admin_model.model_copy(update={"plyrid": "oldadmin"})
            app.state.active_player_sessions["admin-token"] = stale_admin_model
            app.state.active_player_connected_at["admin-token"] = now - timedelta(seconds=10)

            mod_record, _ = _add_player(db, "modplyr", level=25, spells=spells, owned=5)
            db.add(
                models.Account(
                    userid="ModAcct",
                    userid_norm="modacct",
                    password_hash="test-password-hash",
                    player_id=mod_record.id,
                )
            )
            _add_session(
                db,
                mod_record,
                token="mod-recent-session",
                last_seen=now - timedelta(minutes=1, seconds=30),
            )

            hero_record, hero_model = _add_player(
                db, "hero", level=24, spells=spells, owned=2
            )
            _add_session(
                db,
                hero_record,
                token="hero-recent-session",
                last_seen=now - timedelta(minutes=2),
            )
            app.state.active_player_sessions["hero-token"] = hero_model
            app.state.active_player_connected_at["hero-token"] = now - timedelta(seconds=20)

            recent_record, _ = _add_player(db, "recent", level=23, spells=spells, owned=1)
            _add_session(
                db,
                recent_record,
                token="recent-session",
                last_seen=now - timedelta(minutes=3),
            )
            collision_record, _ = _add_player(
                db, "oldadmin", level=22, spells=spells, owned=1
            )
            _add_session(
                db,
                collision_record,
                token="collision-session",
                last_seen=now - timedelta(minutes=4),
            )
            db.commit()

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            activity_response = await client.get("/public/player-activity")
            leaderboard_response = await client.get("/public/leaderboard")

        assert activity_response.status_code == 200
        activity = activity_response.json()
        assert [player["player_id"] for player in activity["active"]] == ["hero"]
        recent_ids = [player["player_id"] for player in activity["recent"]]
        assert "adminplyr" not in recent_ids
        assert "modplyr" not in recent_ids
        assert "oldadmin" in recent_ids
        assert "recent" in recent_ids

        assert leaderboard_response.status_code == 200
        leaderboard_ids = [
            player["player_id"] for player in leaderboard_response.json()["players"]
        ]
        assert "adminplyr" not in leaderboard_ids
        assert "modplyr" not in leaderboard_ids
        assert "hero" in leaderboard_ids
        oldadmin_summary = next(
            player
            for player in leaderboard_response.json()["players"]
            if player["player_id"] == "oldadmin"
        )
        assert oldadmin_summary["active"] is False


@pytest.mark.anyio
async def test_public_leaderboard_filters_admin_accounts_before_limit(
    monkeypatch, tmp_path
):
    allowlist_path = tmp_path / "admin-allowlist.yaml"
    allowlist_path.write_text(
        "admins:\n"
        + "\n".join(
            f"  adm{index:02d}:\n    roles: [player_admin]"
            for index in range(PUBLIC_LEADERBOARD_LIMIT + 2)
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "1000")
    monkeypatch.setenv("KYRGAME_ADMIN_ALLOWLIST_PATH", str(allowlist_path))
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        spells = app.state.fixture_cache["spells"]
        with app.state.session_factory() as db:
            for index in range(PUBLIC_LEADERBOARD_LIMIT + 2):
                player_id = f"a{index:02d}plyr"
                admin_record, _ = _add_player(
                    db, player_id, level=25, spells=spells, owned=6
                )
                db.add(
                    models.Account(
                        userid=f"Adm{index:02d}",
                        userid_norm=f"adm{index:02d}",
                        password_hash="test-password-hash",
                        player_id=admin_record.id,
                    )
                )

            _add_player(db, "visible", level=24, spells=spells, owned=1)
            db.commit()

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/public/leaderboard")

        assert response.status_code == 200
        leaderboard_ids = [player["player_id"] for player in response.json()["players"]]
        assert "visible" in leaderboard_ids
        assert all(not player_id.startswith("a") for player_id in leaderboard_ids)


@pytest.mark.anyio
async def test_public_summaries_use_player_id_for_out_of_game_display_names(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "1000")
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        spells = app.state.fixture_cache["spells"]
        now = datetime.now(timezone.utc).replace(microsecond=0)
        with app.state.session_factory() as db:
            active_record, active_model = _add_player(
                db, "willow", level=13, spells=spells, owned=2
            )
            active_record.altnam = "Some willowisp"
            active_model.altnam = "Some willowisp"
            _add_session(
                db,
                active_record,
                token="willow-old-session",
                last_seen=now - timedelta(minutes=3),
            )
            app.state.active_player_sessions["willow-token"] = active_model
            app.state.active_player_connected_at["willow-token"] = now - timedelta(minutes=1)

            recent_record, _ = _add_player(db, "cedar", level=12, spells=spells, owned=1)
            recent_record.altnam = "Some willowisp"
            _add_session(
                db,
                recent_record,
                token="cedar-session",
                last_seen=now - timedelta(minutes=2),
            )
            db.commit()

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            activity_response = await client.get("/public/player-activity")
            leaderboard_response = await client.get("/public/leaderboard")

        assert activity_response.status_code == 200
        activity = activity_response.json()
        assert activity["active"][0]["player_id"] == "willow"
        assert activity["active"][0]["display_name"] == "willow"
        assert activity["recent"][0]["player_id"] == "cedar"
        assert activity["recent"][0]["display_name"] == "cedar"

        assert leaderboard_response.status_code == 200
        leaderboard_by_id = {
            player["player_id"]: player
            for player in leaderboard_response.json()["players"]
            if player["player_id"] in {"willow", "cedar"}
        }
        assert leaderboard_by_id["willow"]["display_name"] == "willow"
        assert leaderboard_by_id["cedar"]["display_name"] == "cedar"


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


def test_public_leaderboard_statement_orders_and_limits_in_sql():
    statement = webapp._public_leaderboard_player_statement(fixtures.load_spells())
    compiled = str(
        statement.compile(
            dialect=sqlite.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    normalized_sql = " ".join(compiled.split())

    assert "FROM players" in normalized_sql
    assert "ORDER BY players.level DESC" in normalized_sql
    assert "public_spellbook_count DESC" in normalized_sql
    assert "lower(players.plyrid) ASC, players.plyrid ASC" in normalized_sql
    assert f"LIMIT {PUBLIC_LEADERBOARD_LIMIT}" in normalized_sql


@pytest.mark.anyio
async def test_public_leaderboard_builds_summaries_after_payload_slice(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "1000")
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    converted_player_ids: list[str] = []
    original_player_model_from_record = webapp._player_model_from_record

    def count_player_model_from_record(record: models.Player):
        converted_player_ids.append(record.plyrid)
        return original_player_model_from_record(record)

    monkeypatch.setattr(webapp, "_player_model_from_record", count_player_model_from_record)

    async with app.router.lifespan_context(app):
        spells = app.state.fixture_cache["spells"]
        with app.state.session_factory() as db:
            low_spell_names = [
                f"b{first}{second}{third}"
                for first in string.ascii_lowercase
                for second in string.ascii_lowercase
                for third in string.ascii_lowercase
            ][: PUBLIC_LEADERBOARD_LIMIT + 20]
            for player_id in low_spell_names:
                _add_player(db, player_id, level=25, spells=spells, owned=0)
            _add_player(db, "zzzz", level=25, spells=spells, owned=6)
            db.commit()

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/public/leaderboard")

        assert response.status_code == 200
        assert len(response.json()["players"]) == PUBLIC_LEADERBOARD_LIMIT
        assert len(converted_player_ids) == PUBLIC_LEADERBOARD_LIMIT
        assert converted_player_ids[0] == "zzzz"
