import asyncio
import json
import socket

import httpx
import pytest
import uvicorn
import websockets
from sqlalchemy import func, select

from kyrgame import accounts, constants, models
from kyrgame.webapp import create_app, _websocket_command_rate_limiter
from session_test_helpers import seed_returning_players


def _get_open_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    _, port = sock.getsockname()
    sock.close()
    return port


async def _receive_initial_room_payloads(websocket):
    welcome = json.loads(await asyncio.wait_for(websocket.recv(), timeout=1))
    assert welcome["type"] == "room_welcome"
    for _ in range(4):
        try:
            message = json.loads(await asyncio.wait_for(websocket.recv(), timeout=1))
        except asyncio.TimeoutError:
            break
        assert message["type"] == "command_response"


async def _drain_pending_messages(websocket):
    while True:
        try:
            await asyncio.wait_for(websocket.recv(), timeout=0.05)
        except asyncio.TimeoutError:
            break


async def _assert_no_matching(websocket, predicate, timeout: float = 0.35):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return
        try:
            message = json.loads(await asyncio.wait_for(websocket.recv(), timeout=remaining))
        except asyncio.TimeoutError:
            return
        if predicate(message):
            raise AssertionError(f"Unexpected message received: {message}")


async def _wait_until(predicate, timeout: float = 2.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.05)
    assert predicate()


@pytest.mark.anyio
async def test_session_creation_first_login_and_recovery():
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            logo_resp = await client.get("/auth/logo")
            assert logo_resp.status_code == 200
            assert "Kyrandia" in logo_resp.json()["message"]

            create_resp = await client.post(
                "/auth/session", json={"player_id": "rook", "room_id": 12, "create_player": True}
            )
            assert create_resp.status_code == 201
            created = create_resp.json()["session"]

            assert created["player_id"] == "Rook"
            assert created["first_login"] is True
            assert created["room_id"] == 0
            assert created["token"]
            assert created["lifecycle"] == {
                "state": "first_login_intro",
                "step": 2,
            }
            assert [
                message["message_id"] for message in created["lifecycle_messages"]
            ] == ["GOODPD"]
            assert '"Rook"' in created["lifecycle_messages"][0]["text"]
            assert "Rook" not in await app.state.presence.players_in_room(created["room_id"])

            resume_resp = await client.post(
                "/auth/session", json={"player_id": "rook", "resume_token": created["token"]}
            )
            assert resume_resp.status_code == 200
            resumed = resume_resp.json()["session"]

            assert resumed["token"] == created["token"]
            assert resumed["resumed"] is True
            assert resumed["lifecycle"] == created["lifecycle"]
            assert [
                message["message_id"] for message in resumed["lifecycle_messages"]
            ] == ["GOODPD"]
            assert '"Rook"' in resumed["lifecycle_messages"][0]["text"]


@pytest.mark.anyio
async def test_explicit_first_login_claim_returns_legacy_intro_messages_and_initgp_state():
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            create_resp = await client.post(
                "/auth/session",
                json={"player_id": "mERLin", "room_id": 12, "create_player": True},
            )
            assert create_resp.status_code == 201
            created = create_resp.json()["session"]

            assert created["player_id"] == "Merlin"
            assert created["room_id"] == 0
            assert created["first_login"] is True
            assert created["player_flags"] == int(constants.PlayerFlag.LOADED)
            assert created["honor_mode"] is True
            assert created["effective_honor_mode"] is True
            assert [
                message["message_id"] for message in created["lifecycle_messages"]
            ] == ["GOODPD"]
            assert '"Merlin"' in created["lifecycle_messages"][0]["text"]
            assert created["lifecycle"] == {
                "state": "first_login_intro",
                "step": 2,
            }

        db = app.state.session_factory()
        try:
            player = db.scalar(select(models.Player).where(models.Player.plyrid == "Merlin"))
            assert player is not None
            assert player.uidnam == "Merlin"
            assert player.altnam == "Merlin"
            assert player.attnam == "Merlin"
            assert player.gamloc == 0
            assert player.pgploc == 0
            assert player.level == 1
            assert player.hitpts == 4
            assert player.spts == 2
            assert player.gold == 0
            assert player.gpobjs == []
            assert player.spells == []
            assert player.flags == int(constants.PlayerFlag.LOADED)
            assert player.honor_mode is True
        finally:
            db.close()


@pytest.mark.anyio
async def test_first_login_claim_can_opt_out_of_honor_mode():
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            create_resp = await client.post(
                "/auth/session",
                json={
                    "player_id": "arcana",
                    "create_player": True,
                    "honor_mode": False,
                },
            )

        assert create_resp.status_code == 201
        created = create_resp.json()["session"]
        assert created["honor_mode"] is False
        assert created["effective_honor_mode"] is False

        db = app.state.session_factory()
        try:
            player = db.scalar(select(models.Player).where(models.Player.plyrid == "Arcana"))
            assert player is not None
            assert player.honor_mode is False
        finally:
            db.close()


@pytest.mark.anyio
async def test_force_honor_mode_ignores_first_login_opt_out(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path/'force-honor.db'}")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "1000")
    monkeypatch.setenv("KYRGAME_FORCE_HONOR_MODE", "1")
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            create_resp = await client.post(
                "/auth/session",
                json={
                    "player_id": "valiant",
                    "create_player": True,
                    "honor_mode": False,
                },
            )

        assert create_resp.status_code == 201
        created = create_resp.json()["session"]
        assert created["honor_mode"] is True
        assert created["effective_honor_mode"] is True

        with app.state.session_factory() as db:
            player = db.scalar(select(models.Player).where(models.Player.plyrid == "Valiant"))
            assert player is not None
            assert player.honor_mode is True


@pytest.mark.anyio
async def test_fresh_session_reenters_previous_room_after_x_exit_state():
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        with app.state.session_factory() as db:
            player = db.scalar(select(models.Player).where(models.Player.plyrid == "hero"))
            assert player is not None
            player.gamloc = -1
            player.pgploc = 12
            db.commit()

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/auth/session", json={"player_id": "hero"})

        assert response.status_code == 201
        session = response.json()["session"]
        assert session["room_id"] == 12
        assert "hero" in await app.state.presence.players_in_room(12)

        with app.state.session_factory() as db:
            player = db.scalar(select(models.Player).where(models.Player.plyrid == "hero"))
            assert player is not None
            assert player.gamloc == 12
            assert player.pgploc == 12
            session_record = db.scalar(
                select(models.PlayerSession).where(
                    models.PlayerSession.session_token == session["token"]
                )
            )
            assert session_record is not None
            assert session_record.room_id == 12


@pytest.mark.anyio
async def test_account_login_reenters_previous_room_after_x_exit_state():
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        with app.state.session_factory() as db:
            player = db.scalar(select(models.Player).where(models.Player.plyrid == "hero"))
            assert player is not None
            player.gamloc = -1
            player.pgploc = 24
            db.add(
                models.Account(
                    userid="hero",
                    userid_norm=accounts.normalize_userid("hero"),
                    password_hash=accounts.hash_password("swordfish"),
                    player_id=player.id,
                )
            )
            db.commit()

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/auth/login", json={"userid": "hero", "password": "swordfish"}
            )

        assert response.status_code == 201
        session = response.json()["session"]
        assert session["room_id"] == 24
        assert "hero" in await app.state.presence.players_in_room(24)

        with app.state.session_factory() as db:
            player = db.scalar(select(models.Player).where(models.Player.plyrid == "hero"))
            assert player is not None
            assert player.gamloc == 24
            assert player.pgploc == 24
            session_record = db.scalar(
                select(models.PlayerSession).where(
                    models.PlayerSession.session_token == session["token"]
                )
            )
            assert session_record is not None
            assert session_record.room_id == 24


@pytest.mark.anyio
async def test_first_login_claim_accepts_lady_background_flag():
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            create_resp = await client.post(
                "/auth/session",
                json={"player_id": "morgana", "create_player": True, "background": "lady"},
            )

        assert create_resp.status_code == 201
        created = create_resp.json()["session"]
        assert created["player_id"] == "Morgana"
        assert created["first_login"] is True
        assert created["player_flags"] == int(
            constants.PlayerFlag.LOADED | constants.PlayerFlag.FEMALE
        )

        db = app.state.session_factory()
        try:
            player = db.scalar(select(models.Player).where(models.Player.plyrid == "Morgana"))
            assert player is not None
            assert player.flags == int(constants.PlayerFlag.LOADED | constants.PlayerFlag.FEMALE)
        finally:
            db.close()


@pytest.mark.anyio
async def test_explicit_first_login_advances_intro_one_enter_at_a_time():
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            create_resp = await client.post(
                "/auth/session",
                json={"player_id": "mERLin", "create_player": True},
            )
            assert create_resp.status_code == 201
            session = create_resp.json()["session"]
            token = session["token"]

            expected_pages = [
                ("INTROA", {"state": "first_login_intro", "step": 3}),
                ("INTROB", {"state": "first_login_intro", "step": 4}),
                ("INTROC", {"state": "first_login_intro", "step": 5}),
                ("INTROD", {"state": "first_login_intro", "step": 6}),
            ]
            for message_id, lifecycle in expected_pages:
                advance = await client.post(
                    "/auth/session/lifecycle/advance",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"input": ""},
                )
                assert advance.status_code == 200
                advanced = advance.json()["session"]
                assert [
                    message["message_id"] for message in advanced["lifecycle_messages"]
                ] == [message_id]
                assert advanced["lifecycle"] == lifecycle

            ready = await client.post(
                "/auth/session/lifecycle/advance",
                headers={"Authorization": f"Bearer {token}"},
                json={"input": ""},
            )
            assert ready.status_code == 200
            ready_session = ready.json()["session"]
            assert ready_session["lifecycle_messages"] == []
            assert ready_session["lifecycle"] == {
                "state": "first_login_entry",
                "step": 6,
            }


@pytest.mark.anyio
async def test_explicit_first_login_relogin_preserves_pending_lifecycle():
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            create_resp = await client.post(
                "/auth/session",
                json={"player_id": "Merlin", "create_player": True},
            )
            assert create_resp.status_code == 201
            session = create_resp.json()["session"]
            token = session["token"]

            intro_relogin = await client.post(
                "/auth/session",
                json={"player_id": "Merlin", "room_id": 12},
            )
            assert intro_relogin.status_code == 201
            intro_session = intro_relogin.json()["session"]
            assert intro_session["replaced_sessions"] == 1
            assert intro_session["room_id"] == 0
            assert intro_session["lifecycle"] == {
                "state": "first_login_intro",
                "step": 2,
            }
            assert [
                message["message_id"] for message in intro_session["lifecycle_messages"]
            ] == ["GOODPD"]
            assert '"Merlin"' in intro_session["lifecycle_messages"][0]["text"]
            assert "Merlin" not in await app.state.presence.players_in_room(0)

            replaced_token = intro_session["token"]
            assert replaced_token != token
            advance = await client.post(
                "/auth/session/lifecycle/advance",
                headers={"Authorization": f"Bearer {replaced_token}"},
                json={"input": ""},
            )
            assert advance.status_code == 200
            assert [
                message["message_id"]
                for message in advance.json()["session"]["lifecycle_messages"]
            ] == ["INTROA"]

            for _ in range(4):
                ready = await client.post(
                    "/auth/session/lifecycle/advance",
                    headers={"Authorization": f"Bearer {replaced_token}"},
                    json={"input": ""},
                )
                assert ready.status_code == 200
            ready_session = ready.json()["session"]
            assert ready_session["lifecycle"] == {
                "state": "first_login_entry",
                "step": 6,
            }

            entry_relogin = await client.post(
                "/auth/session",
                json={"player_id": "Merlin", "room_id": 12},
            )
            assert entry_relogin.status_code == 201
            entry_session = entry_relogin.json()["session"]
            assert entry_session["room_id"] == 0
            assert entry_session["lifecycle"] == {
                "state": "first_login_entry",
                "step": 6,
            }
            assert entry_session["lifecycle_messages"] == []
            assert "Merlin" not in await app.state.presence.players_in_room(0)


@pytest.mark.anyio
@pytest.mark.parametrize("player_id", ["ab", "toolongname", "merlin7", "bad name"])
async def test_explicit_first_login_rejects_bad_player_ids_with_legacy_messages(player_id):
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/auth/session", json={"player_id": player_id, "create_player": True}
            )

            assert response.status_code == 422
            detail = response.json()["detail"]
            assert detail["message_ids"] == ["BADPID", "B4PLA2"]
            assert [message["message_id"] for message in detail["messages"]] == [
                "BADPID",
                "B4PLA2",
            ]


@pytest.mark.anyio
@pytest.mark.parametrize("player_id", ["ab", "toolongname", "merlin7", "bad name"])
async def test_default_login_rejects_bad_player_ids_with_legacy_messages(player_id):
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/auth/session", json={"player_id": player_id})

            assert response.status_code == 422
            detail = response.json()["detail"]
            assert detail["message_ids"] == ["BADPID", "B4PLA2"]


@pytest.mark.anyio
@pytest.mark.parametrize("player_id", ["Sysop", "Zar", "dragon", "dryad", "elf", "brownie"])
async def test_explicit_first_login_rejects_reserved_player_ids_with_legacy_messages(player_id):
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/auth/session", json={"player_id": player_id, "create_player": True}
            )

            assert response.status_code == 409
            detail = response.json()["detail"]
            assert detail["message_ids"] == ["NTGOOD", "B4PLA2"]


@pytest.mark.anyio
@pytest.mark.parametrize("player_id", ["Sysop", "Zar", "dragon", "dryad", "elf", "brownie"])
async def test_default_login_rejects_unknown_reserved_player_ids_without_claiming(player_id):
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/auth/session", json={"player_id": player_id})

            assert response.status_code == 404
            assert response.json()["detail"] == "Player-ID not found. Create Character to claim it."


@pytest.mark.anyio
async def test_default_login_does_not_create_unknown_valid_player_id():
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/auth/session", json={"player_id": "Willow"})

            assert response.status_code == 404
            assert response.json()["detail"] == "Player-ID not found. Create Character to claim it."

        db = app.state.session_factory()
        try:
            assert db.scalar(select(models.Player).where(models.Player.plyrid == "Willow")) is None
        finally:
            db.close()


@pytest.mark.anyio
async def test_explicit_first_login_rejects_duplicate_claims_but_existing_login_still_works():
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post(
                "/auth/session", json={"player_id": "Merlin", "create_player": True}
            )
            assert first.status_code == 201

            duplicate = await client.post(
                "/auth/session", json={"player_id": "Merlin", "create_player": True}
            )
            assert duplicate.status_code == 409
            assert duplicate.json()["detail"]["message_ids"] == ["NTGOOD", "B4PLA2"]

            returning = await client.post("/auth/session", json={"player_id": "Merlin"})
            assert returning.status_code == 201
            assert returning.json()["session"]["first_login"] is False


@pytest.mark.anyio
async def test_explicit_first_login_claim_lock_covers_session_commit():
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        app.state.session_replacement_lock = asyncio.Lock()
        await app.state.session_replacement_lock.acquire()
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first_task = asyncio.create_task(
                client.post(
                    "/auth/session",
                    json={"player_id": "Merlin", "create_player": True},
                )
            )
            await _wait_until(
                lambda: len(app.state.session_replacement_lock._waiters or []) == 1
            )
            second_task = asyncio.create_task(
                client.post(
                    "/auth/session",
                    json={"player_id": "Merlin", "create_player": True},
                )
            )
            await asyncio.sleep(0)
            app.state.session_replacement_lock.release()

            first, second = await asyncio.gather(first_task, second_task)

            assert sorted([first.status_code, second.status_code]) == [201, 409]
            duplicate = second if second.status_code == 409 else first
            assert duplicate.json()["detail"]["message_ids"] == ["NTGOOD", "B4PLA2"]

        db = app.state.session_factory()
        try:
            player_count = db.scalar(
                select(func.count())
                .select_from(models.Player)
                .where(func.lower(models.Player.plyrid) == "merlin")
            )
            assert player_count == 1
        finally:
            db.close()


@pytest.mark.anyio
async def test_concurrent_login_policy_and_logout():
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post("/auth/session", json={"player_id": "hero"})
            token_one = first.json()["session"]["token"]

            second = await client.post("/auth/session", json={"player_id": "hero"})
            assert second.status_code == 201
            session_two = second.json()["session"]
            token_two = session_two["token"]
            assert session_two["replaced_sessions"] == 1

            old_validation = await client.get(
                "/auth/session", headers={"Authorization": f"Bearer {token_one}"}
            )
            assert old_validation.status_code == 401

            active_validation = await client.get(
                "/auth/session", headers={"Authorization": f"Bearer {token_two}"}
            )
            assert active_validation.status_code == 200
            assert active_validation.json()["session"]["player_id"] == "hero"

            logout_resp = await client.post(
                "/auth/logout", headers={"Authorization": f"Bearer {token_two}"}
            )
            assert logout_resp.status_code == 200

            post_logout = await client.get(
                "/auth/session", headers={"Authorization": f"Bearer {token_two}"}
            )
            assert post_logout.status_code == 401


@pytest.mark.anyio
async def test_case_variant_login_reuses_existing_player_record():
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post(
                "/auth/session", json={"player_id": "Merlin", "create_player": True}
            )
            assert first.status_code == 201
            first_session = first.json()["session"]
            assert first_session["player_id"] == "Merlin"
            assert first_session["first_login"] is True

            second = await client.post("/auth/session", json={"player_id": "merlin", "room_id": 7})
            assert second.status_code == 201
            second_session = second.json()["session"]
            assert second_session["player_id"] == "Merlin"
            assert second_session["room_id"] == 0
            assert second_session["first_login"] is False
            assert second_session["replaced_sessions"] == 1
            assert second_session["lifecycle"] == {
                "state": "first_login_intro",
                "step": 2,
            }

            old_validation = await client.get(
                "/auth/session", headers={"Authorization": f"Bearer {first_session['token']}"}
            )
            assert old_validation.status_code == 401

            token = second_session["token"]
            for _ in range(5):
                advance = await client.post(
                    "/auth/session/lifecycle/advance",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"input": ""},
                )
                assert advance.status_code == 200

            third = await client.post("/auth/session", json={"player_id": "merlin", "room_id": 7})
            assert third.status_code == 201
            third_session = third.json()["session"]
            assert third_session["player_id"] == "Merlin"
            assert third_session["room_id"] == 0
            assert third_session["lifecycle"] == {
                "state": "first_login_entry",
                "step": 6,
            }

        db = app.state.session_factory()
        try:
            players = db.scalars(
                select(models.Player).where(func.lower(models.Player.plyrid) == "merlin")
            ).all()
            assert len(players) == 1
            assert players[0].uidnam == "Merlin"
        finally:
            db.close()


def test_websocket_command_rate_limit_env_uses_validated_defaults(monkeypatch):
    monkeypatch.setenv("KYRGAME_WS_COMMAND_RATE_LIMIT_MAX_EVENTS", "not-an-int")
    monkeypatch.setenv("KYRGAME_WS_COMMAND_RATE_LIMIT_WINDOW_SECONDS", "0")

    fallback = _websocket_command_rate_limiter()

    assert fallback.max_events == 2
    assert fallback.window_seconds == 0.5

    monkeypatch.setenv("KYRGAME_WS_COMMAND_RATE_LIMIT_MAX_EVENTS", "7")
    monkeypatch.setenv("KYRGAME_WS_COMMAND_RATE_LIMIT_WINDOW_SECONDS", "0.25")

    configured = _websocket_command_rate_limiter()

    assert configured.max_events == 7
    assert configured.window_seconds == 0.25


@pytest.mark.anyio
async def test_websocket_requires_valid_token_and_tracks_reconnects():
    app = create_app()
    host = "127.0.0.1"
    port = _get_open_port()

    config = uvicorn.Config(app, host=host, port=port, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    async with httpx.AsyncClient(base_url=f"http://{host}:{port}") as client:
        session_resp = await client.post("/auth/session", json={"player_id": "hero"})
        session_data = session_resp.json()["session"]
        token = session_data["token"]
        room_id = session_data["room_id"]

        bad_uri = f"ws://{host}:{port}/ws/rooms/{room_id}?token=invalid"
        with pytest.raises(websockets.InvalidStatusCode):
            async with websockets.connect(bad_uri):
                pass

        uri = f"ws://{host}:{port}/ws/rooms/{room_id}?token={token}"
        async with websockets.connect(uri) as ws:
            welcome = json.loads(await asyncio.wait_for(ws.recv(), timeout=1))
            assert welcome["type"] == "room_welcome"

            move_payload = {"type": "command", "command": "move", "args": {"direction": "north"}}
            await ws.send(json.dumps(move_payload))

            response = json.loads(await asyncio.wait_for(ws.recv(), timeout=1))
            assert response["type"] == "command_response"

        validate_after_disconnect = await client.get(
            "/auth/session", headers={"Authorization": f"Bearer {token}"}
        )
        resumed_room = validate_after_disconnect.json()["session"]["room_id"]
        reconnect_uri = f"ws://{host}:{port}/ws/rooms/{resumed_room}?token={token}"
        async with websockets.connect(reconnect_uri) as ws:
            welcome_again = json.loads(await asyncio.wait_for(ws.recv(), timeout=1))
            assert welcome_again["type"] == "room_welcome"

    server.should_exit = True
    await server_task


@pytest.mark.anyio
async def test_admin_scry_socket_streams_initial_snapshot_and_live_events(monkeypatch, tmp_path):
    allowlist_path = tmp_path / "admin-allowlist.yaml"
    allowlist_path.write_text(
        """
admins:
  opal:
    roles: [player_admin]
""".lstrip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("KYRGAME_ADMIN_ALLOWLIST_PATH", str(allowlist_path))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path/'scry.db'}")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "1000")
    monkeypatch.setenv("KYRGAME_TELEMETRY_DIR", str(tmp_path / "telemetry"))

    app = create_app()
    host = "127.0.0.1"
    port = _get_open_port()

    config = uvicorn.Config(app, host=host, port=port, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    seed_returning_players(app, ("seer",))

    try:
        async with httpx.AsyncClient(base_url=f"http://{host}:{port}") as client:
            player_resp = await client.post("/auth/session", json={"player_id": "Hero", "room_id": 7})
            assert player_resp.status_code == 201
            player_session = player_resp.json()["session"]
            canonical_player_id = player_session["player_id"]

            witness_resp = await client.post("/auth/session", json={"player_id": "seer", "room_id": 7})
            assert witness_resp.status_code == 201
            witness_session = witness_resp.json()["session"]

            admin_resp = await client.post(
                "/auth/register",
                json={
                    "userid": "Opal",
                    "password": "correct horse battery staple",
                    "session_kind": "admin",
                },
            )
            assert admin_resp.status_code == 201
            admin_session = admin_resp.json()["session"]

            player_uri = (
                f"ws://{host}:{port}/ws/rooms/{player_session['room_id']}"
                f"?token={player_session['token']}"
            )
            async with websockets.connect(player_uri) as player_ws:
                await _receive_initial_room_payloads(player_ws)

                scry_uri = f"ws://{host}:{port}/ws/admin/scry/HeRo?token={admin_session['token']}"
                async with websockets.connect(scry_uri) as scry_ws:
                    started = json.loads(await asyncio.wait_for(scry_ws.recv(), timeout=1))
                    assert started["type"] == "scry_started"
                    assert started["player_id"] == canonical_player_id
                    assert started["room"] == 7

                    initial_events = []
                    for _ in range(5):
                        message = json.loads(await asyncio.wait_for(scry_ws.recv(), timeout=1))
                        initial_events.append(message)
                        event = message.get("event", {})
                        payload = event.get("payload", {})
                        if payload.get("payload", {}).get("event") == "location_description":
                            break

                    assert any(
                        message.get("type") == "scry_event"
                        and message.get("player_id") == canonical_player_id
                        and message.get("event", {}).get("event_type") == "output"
                        and message.get("event", {}).get("payload", {}).get("type") == "room_welcome"
                        for message in initial_events
                    )
                    assert any(
                        message.get("event", {})
                        .get("payload", {})
                        .get("payload", {})
                        .get("event")
                        == "location_description"
                        for message in initial_events
                    )

                    await player_ws.send(json.dumps({"type": "command", "command": "look"}))
                    live_input = None
                    for _ in range(6):
                        candidate = json.loads(
                            await asyncio.wait_for(scry_ws.recv(), timeout=1)
                        )
                        if candidate.get("event", {}).get("event_type") == "input":
                            live_input = candidate
                            break
                    assert live_input is not None
                    assert live_input == {
                        "type": "scry_event",
                        "player_id": canonical_player_id,
                        "event": {"event_type": "input", "payload": {"command": "look"}},
                    }

                    witness_uri = (
                        f"ws://{host}:{port}/ws/rooms/{witness_session['room_id']}"
                        f"?token={witness_session['token']}"
                    )
                    async with websockets.connect(witness_uri) as witness_ws:
                        await _receive_initial_room_payloads(witness_ws)
                        player_enter = None
                        for _ in range(8):
                            candidate = json.loads(
                                await asyncio.wait_for(scry_ws.recv(), timeout=1)
                            )
                            payload = candidate.get("event", {}).get("payload", {})
                            if (
                                candidate.get("event", {}).get("event_type") == "output"
                                and payload.get("type") == "room_broadcast"
                                and payload.get("payload", {}).get("event") == "player_enter"
                            ):
                                player_enter = candidate
                                break
                        assert player_enter is not None
                        assert player_enter["player_id"] == canonical_player_id

                        await witness_ws.send(
                            json.dumps({"type": "command", "command": "whisper hero hush"})
                        )
                        target_whisper = None
                        for _ in range(8):
                            candidate = json.loads(
                                await asyncio.wait_for(scry_ws.recv(), timeout=1)
                            )
                            payload = candidate.get("event", {}).get("payload", {})
                            if (
                                candidate.get("event", {}).get("event_type") == "output"
                                and payload.get("type") == "command_response"
                                and payload.get("payload", {}).get("message_id") == "WHISPR1"
                            ):
                                target_whisper = candidate
                                break
                        assert target_whisper is not None
                        assert target_whisper["player_id"] == canonical_player_id

                    await scry_ws.send(json.dumps({"type": "command", "command": "look"}))
                    read_only = None
                    for _ in range(6):
                        candidate = json.loads(
                            await asyncio.wait_for(scry_ws.recv(), timeout=1)
                        )
                        if candidate.get("type") == "scry_read_only":
                            read_only = candidate
                            break
                    assert read_only is not None
                    assert read_only == {
                        "type": "scry_read_only",
                        "detail": "SCRY observers cannot send commands",
                    }

                game_scry_uri = (
                    f"ws://{host}:{port}/ws/admin/scry/Hero?token={player_session['token']}"
                )
                with pytest.raises(websockets.InvalidStatusCode):
                    async with websockets.connect(game_scry_uri):
                        pass
    finally:
        server.should_exit = True
        await server_task


@pytest.mark.anyio
async def test_first_login_blocks_room_socket_until_intro_finishes_and_enters_in_flash():
    app = create_app()
    host = "127.0.0.1"
    port = _get_open_port()

    config = uvicorn.Config(app, host=host, port=port, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    try:
        async with httpx.AsyncClient(base_url=f"http://{host}:{port}") as client:
            witness_resp = await client.post(
                "/auth/session", json={"player_id": "hero", "room_id": 0}
            )
            assert witness_resp.status_code == 201
            witness_session = witness_resp.json()["session"]
            witness_uri = (
                f"ws://{host}:{port}/ws/rooms/0?token={witness_session['token']}"
            )

            async with websockets.connect(witness_uri) as witness_ws:
                await _receive_initial_room_payloads(witness_ws)

                create_payload = {"player_id": "Merlin", "create_player": True}
                create_resp = await client.post("/auth/session", json=create_payload)
                assert create_resp.status_code == 201
                session_data = create_resp.json()["session"]
                assert session_data["lifecycle"] == {
                    "state": "first_login_intro",
                    "step": 2,
                }
                token = session_data["token"]
                gated_uri = f"ws://{host}:{port}/ws/rooms/0?token={token}"
                assert "Merlin" not in await app.state.presence.players_in_room(0)

                with pytest.raises(websockets.InvalidStatusCode):
                    async with websockets.connect(gated_uri):
                        pass

                for _ in range(5):
                    advance = await client.post(
                        "/auth/session/lifecycle/advance",
                        headers={"Authorization": f"Bearer {token}"},
                        json={"input": ""},
                    )
                    assert advance.status_code == 200

                async with websockets.connect(gated_uri) as player_ws:
                    welcome = json.loads(await asyncio.wait_for(player_ws.recv(), timeout=1))
                    assert welcome["type"] == "room_welcome"
                    assert "Merlin" in await app.state.presence.players_in_room(0)

                    seen_flash = False
                    for _ in range(4):
                        message = json.loads(await asyncio.wait_for(witness_ws.recv(), timeout=1))
                        payload = message.get("payload", {})
                        if (
                            message.get("type") == "room_broadcast"
                            and payload.get("event") == "room_message"
                            and "appeared in a flash" in payload.get("text", "")
                        ):
                            seen_flash = True
                            break
                    assert seen_flash

                validate = await client.get(
                    "/auth/session", headers={"Authorization": f"Bearer {token}"}
                )
                assert validate.json()["session"]["lifecycle"] is None
    finally:
        server.should_exit = True
        await server_task


@pytest.mark.anyio
async def test_invisible_first_login_flash_only_reaches_cinvis_observers():
    app = create_app()
    host = "127.0.0.1"
    port = _get_open_port()

    config = uvicorn.Config(app, host=host, port=port, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    seed_returning_players(app, ("seer",))

    try:
        async with httpx.AsyncClient(base_url=f"http://{host}:{port}") as client:
            witness_resp = await client.post(
                "/auth/session", json={"player_id": "hero", "room_id": 0}
            )
            assert witness_resp.status_code == 201
            witness_session = witness_resp.json()["session"]
            witness_uri = (
                f"ws://{host}:{port}/ws/rooms/0?token={witness_session['token']}"
            )

            seer_resp = await client.post(
                "/auth/session", json={"player_id": "seer", "room_id": 0}
            )
            assert seer_resp.status_code == 201
            seer_session = seer_resp.json()["session"]
            seer_uri = f"ws://{host}:{port}/ws/rooms/0?token={seer_session['token']}"

            with app.state.session_factory() as db:
                seer = db.scalar(select(models.Player).where(models.Player.plyrid == "seer"))
                assert seer is not None
                seer.charms = [
                    1 if index == constants.CharmSlot.INVISIBILITY else 0
                    for index in range(constants.NCHARM)
                ]
                db.commit()

            async with websockets.connect(witness_uri) as witness_ws:
                await _receive_initial_room_payloads(witness_ws)
                async with websockets.connect(seer_uri) as seer_ws:
                    await _receive_initial_room_payloads(seer_ws)
                    await _drain_pending_messages(witness_ws)

                    create_payload = {"player_id": "Merlin", "create_player": True}
                    create_resp = await client.post("/auth/session", json=create_payload)
                    assert create_resp.status_code == 201
                    token = create_resp.json()["session"]["token"]

                    for _ in range(5):
                        advance = await client.post(
                            "/auth/session/lifecycle/advance",
                            headers={"Authorization": f"Bearer {token}"},
                            json={"input": ""},
                        )
                        assert advance.status_code == 200

                    with app.state.session_factory() as db:
                        merlin = db.scalar(
                            select(models.Player).where(models.Player.plyrid == "Merlin")
                        )
                        assert merlin is not None
                        merlin.flags = int(merlin.flags | constants.PlayerFlag.INVISF)
                        merlin.altnam = "Some Unseen Force"
                        merlin.attnam = "Unseen Force"
                        db.commit()

                    player_uri = f"ws://{host}:{port}/ws/rooms/0?token={token}"
                    async with websockets.connect(player_uri) as player_ws:
                        welcome = json.loads(await asyncio.wait_for(player_ws.recv(), timeout=1))
                        assert welcome["type"] == "room_welcome"

                        seen_flash = False
                        for _ in range(4):
                            message = json.loads(await asyncio.wait_for(seer_ws.recv(), timeout=1))
                            payload = message.get("payload", {})
                            if (
                                message.get("type") == "room_broadcast"
                                and payload.get("event") == "room_message"
                                and payload.get("player") == "Merlin"
                            ):
                                assert payload["text"] == (
                                    "*** Some Unseen Force has just appeared in a flash!"
                                )
                                seen_flash = True
                                break
                        assert seen_flash

                        await _assert_no_matching(
                            witness_ws,
                            lambda msg: msg.get("type") == "room_broadcast"
                            and msg.get("payload", {}).get("player") == "Merlin",
                        )
    finally:
        server.should_exit = True
        await server_task


@pytest.mark.anyio
async def test_duplicate_player_login_replaces_active_websocket_session():
    app = create_app()
    host = "127.0.0.1"
    port = _get_open_port()

    config = uvicorn.Config(app, host=host, port=port, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    async with httpx.AsyncClient(base_url=f"http://{host}:{port}") as client:
        first_session = await client.post(
            "/auth/session",
            json={"player_id": "hero", "room_id": 7},
        )
        first_token = first_session.json()["session"]["token"]
        first_uri = f"ws://{host}:{port}/ws/rooms/7?token={first_token}"

        async with websockets.connect(first_uri) as first_ws:
            await _receive_initial_room_payloads(first_ws)
            assert first_token in getattr(app.state, "active_player_sessions", {})

            second_session = await client.post(
                "/auth/session",
                json={"player_id": "hero", "room_id": 7, "allow_multiple": True},
            )
            assert second_session.status_code == 201
            second_payload = second_session.json()["session"]
            second_token = second_payload["token"]
            assert second_payload["replaced_sessions"] == 1

            await _wait_until(lambda: first_ws.closed)
            assert first_token not in getattr(app.state, "active_player_sessions", {})

            old_validation = await client.get(
                "/auth/session", headers={"Authorization": f"Bearer {first_token}"}
            )
            assert old_validation.status_code == 401

            second_uri = f"ws://{host}:{port}/ws/rooms/7?token={second_token}"
            async with websockets.connect(second_uri) as second_ws:
                await _receive_initial_room_payloads(second_ws)
                active_session_players = getattr(app.state, "active_player_sessions", {})
                assert list(active_session_players) == [second_token]
                assert app.state.active_players.get("hero") is active_session_players[second_token]

        await _wait_until(lambda: "hero" not in app.state.active_players)
        assert second_token not in getattr(app.state, "active_player_sessions", {})

    server.should_exit = True
    await server_task


@pytest.mark.anyio
async def test_same_session_websocket_replacement_uses_specific_close_reason():
    app = create_app()
    host = "127.0.0.1"
    port = _get_open_port()

    config = uvicorn.Config(app, host=host, port=port, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    try:
        async with httpx.AsyncClient(base_url=f"http://{host}:{port}") as client:
            session = await client.post(
                "/auth/session",
                json={"player_id": "hero", "room_id": 7},
            )
            token = session.json()["session"]["token"]
            uri = f"ws://{host}:{port}/ws/rooms/7?token={token}"

            async with websockets.connect(uri) as first_ws:
                await _receive_initial_room_payloads(first_ws)

                async with websockets.connect(uri) as second_ws:
                    await _receive_initial_room_payloads(second_ws)
                    await _wait_until(lambda: first_ws.closed)

                    assert first_ws.close_code == 1013
                    assert first_ws.close_reason == "Game session replaced by another connection"
    finally:
        server.should_exit = True
        await server_task


@pytest.mark.anyio
async def test_session_token_expiration():
    """Test that expired tokens are rejected"""
    from datetime import datetime, timedelta, timezone
    from kyrgame import models, repositories
    
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Create a session with very short expiration (simulated by directly manipulating DB)
            create_resp = await client.post(
                "/auth/session", json={"player_id": "tempuser", "create_player": True}
            )
            assert create_resp.status_code == 201
            token = create_resp.json()["session"]["token"]
            
            # Verify the token works initially
            validate_resp = await client.get(
                "/auth/session", headers={"Authorization": f"Bearer {token}"}
            )
            assert validate_resp.status_code == 200
            
            # Now manually expire the token by setting expires_at to the past
            db_session = app.state.session_factory()
            try:
                repo = repositories.PlayerSessionRepository(db_session)
                session_record = repo.get_by_token(token, active_only=False)
                session_record.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
                db_session.commit()
            finally:
                db_session.close()
            
            # Verify the expired token is rejected
            validate_expired = await client.get(
                "/auth/session", headers={"Authorization": f"Bearer {token}"}
            )
            assert validate_expired.status_code == 401
            
            # Resume with expired token should also fail
            resume_resp = await client.post(
                "/auth/session", json={"player_id": "tempuser", "resume_token": token}
            )
            assert resume_resp.status_code == 404
            assert "not found or expired" in resume_resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_session_creation_rate_limiting():
    """Test that rate limiting prevents abuse"""
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Create sessions until rate limit is hit (limit is 5 per second)
            responses = []
            for player_id in ["usera", "userb", "userc", "userd", "usere", "userf", "userg"]:
                resp = await client.post(
                    "/auth/session", json={"player_id": player_id, "create_player": True}
                )
                responses.append(resp)
            
            # First 5 should succeed, subsequent should be rate limited
            success_count = sum(1 for r in responses if r.status_code == 201)
            rate_limited_count = sum(1 for r in responses if r.status_code == 429)
            
            assert success_count == 5
            assert rate_limited_count == 2
            
            # Verify rate limit error message
            for resp in responses:
                if resp.status_code == 429:
                    assert "too many" in resp.json()["detail"].lower()
