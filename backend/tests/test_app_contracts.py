import asyncio
import json
import socket

import httpx
import pytest
import uvicorn
import websockets

from kyrgame import fixtures
from kyrgame.webapp import create_app



def _get_open_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    _, port = sock.getsockname()
    sock.close()
    return port


@pytest.mark.anyio
async def test_http_endpoints_expose_fixture_shapes():
    app = create_app()
    summary = fixtures.fixture_summary()

    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            session_resp = await client.post("/auth/session", json={"player_id": "hero"})
            assert session_resp.status_code == 201
            session_data = session_resp.json()
            assert session_data["status"] == "ok"
            assert session_data["session"]["player_id"] == "hero"
            assert "message" in session_data["session"]

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

            admin_resp = await client.get("/admin/fixtures")
            assert admin_resp.status_code == 200
            admin_summary = admin_resp.json()
            assert admin_summary == summary


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
    uri1 = f"ws://{host}:{port}/ws/rooms/7?player_id=alpha"
    uri2 = f"ws://{host}:{port}/ws/rooms/7?player_id=bravo"

    async with websockets.connect(uri1) as ws1:
        welcome1 = json.loads(await asyncio.wait_for(ws1.recv(), timeout=1))
        assert welcome1["type"] == "room_welcome"

        async with websockets.connect(uri2) as ws2:
            welcome2 = json.loads(await asyncio.wait_for(ws2.recv(), timeout=1))
            assert welcome2["type"] == "room_welcome"

            join_notice = json.loads(await asyncio.wait_for(ws1.recv(), timeout=1))
            assert join_notice["type"] == "room_broadcast"
            assert join_notice["payload"]["event"] == "player_enter"

            payload = {"type": "command", "command": "chat", "args": {"text": "hi"}}
            await ws1.send(json.dumps(payload))

            self_response = json.loads(await asyncio.wait_for(ws1.recv(), timeout=1))
            fan_out = json.loads(await asyncio.wait_for(ws2.recv(), timeout=1))

            assert self_response["type"] == "command_response"
            assert self_response["payload"] == payload
            assert fan_out["type"] == "room_broadcast"
            assert fan_out["room"] == 7
            assert fan_out["payload"]["args"]["text"] == "hi"

    server.should_exit = True
    await server_task
