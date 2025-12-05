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
async def test_websocket_bridge_emits_legacy_command_metadata():
    app = create_app()
    host = "127.0.0.1"
    port = _get_open_port()

    config = uvicorn.Config(app, host=host, port=port, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    async with httpx.AsyncClient(base_url=f"http://{host}:{port}") as client:
        hero_session = await client.post("/auth/session", json={"player_id": "hero", "room_id": 0})
        hero_token = hero_session.json()["session"]["token"]
        room_zero = hero_session.json()["session"]["room_id"]

        seer_session = await client.post("/auth/session", json={"player_id": "seer", "room_id": room_zero})
        seer_token = seer_session.json()["session"]["token"]

        mystic_session = await client.post("/auth/session", json={"player_id": "mystic", "room_id": 1})
        mystic_token = mystic_session.json()["session"]["token"]
        room_one = mystic_session.json()["session"]["room_id"]

        uri_room0_hero = f"ws://{host}:{port}/ws/rooms/{room_zero}?token={hero_token}"
        uri_room0_seer = f"ws://{host}:{port}/ws/rooms/{room_zero}?token={seer_token}"
        uri_room1_mystic = f"ws://{host}:{port}/ws/rooms/{room_one}?token={mystic_token}"

        async with websockets.connect(uri_room0_hero) as hero_ws:
            await asyncio.wait_for(hero_ws.recv(), timeout=1)
            async with websockets.connect(uri_room0_seer) as seer_ws:
                await asyncio.wait_for(seer_ws.recv(), timeout=1)
                await asyncio.wait_for(hero_ws.recv(), timeout=1)
                async with websockets.connect(uri_room1_mystic) as mystic_ws:
                    await asyncio.wait_for(mystic_ws.recv(), timeout=1)

                    await hero_ws.send(json.dumps({"type": "command", "command": "say hello room"}))

                    hero_ack = json.loads(await asyncio.wait_for(hero_ws.recv(), timeout=1))
                    assert hero_ack["type"] == "command_response"
                    assert hero_ack["payload"]["command_id"] == 53

                    seer_broadcast = json.loads(await asyncio.wait_for(seer_ws.recv(), timeout=1))
                    assert seer_broadcast["type"] == "room_broadcast"
                    assert seer_broadcast["payload"]["command_id"] == 53
                    assert seer_broadcast["payload"]["message_id"] == "CMD053"

                    await hero_ws.send(json.dumps({"type": "command", "command": "north"}))

                    move_ack = json.loads(await asyncio.wait_for(hero_ws.recv(), timeout=1))
                    assert move_ack["payload"]["command_id"] == 38
                    move_broadcast = json.loads(await asyncio.wait_for(mystic_ws.recv(), timeout=1))
                    assert move_broadcast["payload"]["command_id"] == 38
                    assert move_broadcast["payload"]["event"] == "player_enter"

    server.should_exit = True
    await server_task
