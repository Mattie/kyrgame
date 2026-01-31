import asyncio
import json
import socket

import httpx
import pytest
import uvicorn
import websockets
from starlette import status

from kyrgame import fixtures
from kyrgame import models
from kyrgame.webapp import create_app

ADMIN_TOKEN = "test-admin-token"

def _get_open_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    _, port = sock.getsockname()
    sock.close()
    return port


ADMIN_HEADERS = {"Authorization": f"Bearer {ADMIN_TOKEN}"}


@pytest.mark.anyio
async def test_http_endpoints_expose_fixture_shapes(monkeypatch):
    monkeypatch.setenv("KYRGAME_ADMIN_TOKEN", ADMIN_TOKEN)
    app = create_app()
    summary = fixtures.fixture_summary()

    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            session_resp = await client.post("/auth/session", json={"player_id": "hero"})
            assert session_resp.status_code == 201
            session_data = session_resp.json()
            assert session_data["status"] == "created"
            assert session_data["session"]["player_id"] == "hero"
            assert session_data["session"]["token"]

            commands_resp = await client.get("/commands")
            assert commands_resp.status_code == 200
            commands = commands_resp.json()
            assert len(commands) == summary["commands"]
            assert {"id", "command", "payonl", "cmdrou"} <= set(commands[0])

            locations_resp = await client.get("/world/locations")
            assert locations_resp.status_code == 200
            locations = locations_resp.json()
            assert len(locations) == summary["locations"]
            assert {"id", "brfdes", "gi_north", "gi_south", "gi_east", "gi_west"} <= set(
                locations[0]
            )

            objects_resp = await client.get("/objects")
            assert objects_resp.status_code == 200
            objects = objects_resp.json()
            assert len(objects) == summary["objects"]
            assert {"id", "name", "flags"} <= set(objects[0])

            spells_resp = await client.get("/spells")
            assert spells_resp.status_code == 200
            spells = spells_resp.json()
            assert len(spells) == summary["spells"]
            assert {"id", "name", "level"} <= set(spells[0])

            locales_resp = await client.get("/i18n/locales")
            assert locales_resp.status_code == 200
            assert summary["locales"] == locales_resp.json()

            bundle_resp = await client.get("/i18n/en-US/messages")
            assert bundle_resp.status_code == 200
            assert bundle_resp.json()["locale"] == "en-US"
            assert len(bundle_resp.json()["messages"]) == summary["messages"]

            admin_resp = await client.get("/admin/fixtures", headers=ADMIN_HEADERS)
            assert admin_resp.status_code == 200
            admin_summary = admin_resp.json()
            assert admin_summary == summary


@pytest.mark.anyio
async def test_cors_headers_allow_dev_frontend():
    app = create_app()

    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.options(
                "/world/locations",
                headers={
                    "Origin": "http://127.0.0.1:5173",
                    "Access-Control-Request-Method": "GET",
                },
            )

            assert response.status_code == status.HTTP_200_OK
            assert response.headers.get("access-control-allow-origin") in {
                "*",
                "http://127.0.0.1:5173",
            }


@pytest.mark.anyio
async def test_player_serialization_round_trip():
    app = create_app()
    sample_player = fixtures.build_player()

    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            example_resp = await client.get("/players/example")
            assert example_resp.status_code == 200
            assert example_resp.json() == sample_player.model_dump()

            echo_resp = await client.post("/players/echo", json=sample_player.model_dump())
            assert echo_resp.status_code == 200
            echoed = models.PlayerModel(**echo_resp.json()["player"])
            assert echoed.model_dump() == sample_player.model_dump()


@pytest.mark.anyio
async def test_websocket_gateway_broadcasts_and_echoes_commands():
    app = create_app()
    host = "127.0.0.1"
    port = _get_open_port()

    config = uvicorn.Config(app, host=host, port=port, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    async with httpx.AsyncClient(base_url=f"http://{host}:{port}") as client:
        alpha_session = await client.post(
            "/auth/session", json={"player_id": "alpha", "room_id": 7}
        )
        alpha_token = alpha_session.json()["session"]["token"]
        room_id = alpha_session.json()["session"]["room_id"]

        bravo_session = await client.post(
            "/auth/session", json={"player_id": "bravo", "room_id": room_id}
        )
        bravo_token = bravo_session.json()["session"]["token"]

        uri1 = f"ws://{host}:{port}/ws/rooms/{room_id}?token={alpha_token}"
        uri2 = f"ws://{host}:{port}/ws/rooms/{room_id}?token={bravo_token}"

        async with websockets.connect(uri1) as ws1:
            welcome1 = json.loads(await asyncio.wait_for(ws1.recv(), timeout=1))
            assert welcome1["type"] == "room_welcome"
            
            # Consume initial room state messages (location_update, location_description, room_objects, occupants)
            for _ in range(4):
                msg = json.loads(await asyncio.wait_for(ws1.recv(), timeout=1))
                assert msg["type"] == "command_response"

            async with websockets.connect(uri2) as ws2:
                welcome2 = json.loads(await asyncio.wait_for(ws2.recv(), timeout=1))
                assert welcome2["type"] == "room_welcome"
                
                # Consume initial room state messages for ws2
                for _ in range(4):
                    msg = json.loads(await asyncio.wait_for(ws2.recv(), timeout=1))
                    assert msg["type"] == "command_response"

                # ws1 receives two broadcasts when ws2 joins: player_enter and entrance message
                join_notice = json.loads(await asyncio.wait_for(ws1.recv(), timeout=1))
                assert join_notice["type"] == "room_broadcast"
                assert join_notice["payload"]["event"] == "player_enter"
                
                entrance_msg = json.loads(await asyncio.wait_for(ws1.recv(), timeout=1))
                assert entrance_msg["type"] == "room_broadcast"

                payload = {"type": "command", "command": "chat", "args": {"text": "hi"}}
                await ws1.send(json.dumps(payload))

                self_response = json.loads(await asyncio.wait_for(ws1.recv(), timeout=1))
                fan_out = json.loads(await asyncio.wait_for(ws2.recv(), timeout=2))
                while fan_out.get("type") != "room_broadcast":
                    fan_out = json.loads(await asyncio.wait_for(ws2.recv(), timeout=2))

                assert self_response["type"] == "command_response"
                assert self_response["payload"]["command_id"] == 53
                assert fan_out["type"] == "room_broadcast"
                assert fan_out["room"] == room_id
                assert fan_out["payload"]["args"]["text"] == "hi"

    server.should_exit = True
    await server_task


@pytest.mark.anyio
async def test_websocket_sends_location_description_on_connect():
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
        token = session_resp.json()["session"]["token"]
        room_id = session_resp.json()["session"]["room_id"]

        uri = f"ws://{host}:{port}/ws/rooms/{room_id}?token={token}"

        async with websockets.connect(uri) as ws:
            welcome = json.loads(await asyncio.wait_for(ws.recv(), timeout=1))
            assert welcome["type"] == "room_welcome"

            first_event = json.loads(await asyncio.wait_for(ws.recv(), timeout=1))
            description_event = first_event

            if first_event["payload"].get("event") != "location_description":
                description_event = json.loads(await asyncio.wait_for(ws.recv(), timeout=1))

            assert description_event["type"] == "command_response"
            assert description_event["room"] == room_id
            assert description_event["payload"]["event"] == "location_description"
            assert description_event["payload"]["location"] == room_id

    server.should_exit = True
    await server_task
