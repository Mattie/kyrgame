import asyncio
import json
import socket

import httpx
import pytest
import uvicorn
import websockets
from sqlalchemy import func, select

from kyrgame import constants, models
from kyrgame.webapp import create_app, _websocket_command_rate_limiter


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

            create_resp = await client.post("/auth/session", json={"player_id": "rook"})
            assert create_resp.status_code == 201
            created = create_resp.json()["session"]

            assert created["player_id"] == "rook"
            assert created["first_login"] is True
            assert created["token"]

            resume_resp = await client.post(
                "/auth/session", json={"player_id": "rook", "resume_token": created["token"]}
            )
            assert resume_resp.status_code == 200
            resumed = resume_resp.json()["session"]

            assert resumed["token"] == created["token"]
            assert resumed["resumed"] is True


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
async def test_default_first_login_rejects_bad_player_ids_with_legacy_messages(player_id):
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
async def test_default_first_login_rejects_reserved_player_ids_with_legacy_messages(player_id):
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/auth/session", json={"player_id": player_id})

            assert response.status_code == 409
            detail = response.json()["detail"]
            assert detail["message_ids"] == ["NTGOOD", "B4PLA2"]


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
            assert second_session["room_id"] == 7
            assert second_session["first_login"] is False
            assert second_session["replaced_sessions"] == 1

            old_validation = await client.get(
                "/auth/session", headers={"Authorization": f"Bearer {first_session['token']}"}
            )
            assert old_validation.status_code == 401

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
        session_resp = await client.post("/auth/session", json={"player_id": "scout"})
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
async def test_explicit_first_login_blocks_room_socket_until_intro_finishes_and_enters_in_flash():
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
                "/auth/session", json={"player_id": "seer", "room_id": 0}
            )
            witness_session = witness_resp.json()["session"]
            witness_uri = (
                f"ws://{host}:{port}/ws/rooms/0?token={witness_session['token']}"
            )

            async with websockets.connect(witness_uri) as witness_ws:
                await _receive_initial_room_payloads(witness_ws)

                create_resp = await client.post(
                    "/auth/session",
                    json={"player_id": "Merlin", "create_player": True},
                )
                session_data = create_resp.json()["session"]
                token = session_data["token"]
                gated_uri = f"ws://{host}:{port}/ws/rooms/0?token={token}"

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
async def test_session_token_expiration():
    """Test that expired tokens are rejected"""
    from datetime import datetime, timedelta, timezone
    from kyrgame import models, repositories
    
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Create a session with very short expiration (simulated by directly manipulating DB)
            create_resp = await client.post("/auth/session", json={"player_id": "tempuser"})
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
                resp = await client.post("/auth/session", json={"player_id": player_id})
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
