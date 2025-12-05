import asyncio
import json
import socket

import httpx
import pytest
import uvicorn
import websockets

from kyrgame.webapp import create_app


def _get_open_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    _, port = sock.getsockname()
    sock.close()
    return port


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
