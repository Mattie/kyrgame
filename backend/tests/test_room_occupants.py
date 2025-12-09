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


async def _receive_until(websocket, predicate, timeout: float = 1.5):
    while True:
        message = json.loads(await asyncio.wait_for(websocket.recv(), timeout=timeout))
        if predicate(message):
            return message


@pytest.mark.anyio
async def test_room_description_lists_other_occupants():
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
            "/auth/session", json={"player_id": "alpha", "room_id": 0}
        )
        alpha_token = alpha_session.json()["session"]["token"]

        bravo_session = await client.post(
            "/auth/session", json={"player_id": "bravo", "room_id": 0}
        )
        bravo_token = bravo_session.json()["session"]["token"]

    uri_room0_alpha = f"ws://{host}:{port}/ws/rooms/0?token={alpha_token}"
    uri_room0_bravo = f"ws://{host}:{port}/ws/rooms/0?token={bravo_token}"

    async with websockets.connect(uri_room0_alpha) as alpha_ws:
        await asyncio.wait_for(alpha_ws.recv(), timeout=1)

        async with websockets.connect(uri_room0_bravo) as bravo_ws:
            await asyncio.wait_for(bravo_ws.recv(), timeout=1)

            occupant_event = await _receive_until(
                bravo_ws,
                lambda msg: msg.get("payload", {}).get("event") == "room_occupants",
                timeout=2,
            )

            occupants = occupant_event["payload"].get("occupants", [])
            assert "alpha" in occupants
            assert "bravo" not in occupants
            assert "alpha" in occupant_event["payload"].get("text", "")

    server.should_exit = True
    await server_task


@pytest.mark.anyio
async def test_room_broadcasts_arrival_message_to_occupants():
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

        seer_session = await client.post("/auth/session", json={"player_id": "seer", "room_id": 1})
        seer_token = seer_session.json()["session"]["token"]

    uri_room0_hero = f"ws://{host}:{port}/ws/rooms/0?token={hero_token}"
    uri_room1_seer = f"ws://{host}:{port}/ws/rooms/1?token={seer_token}"

    async with websockets.connect(uri_room0_hero) as hero_ws:
        await asyncio.wait_for(hero_ws.recv(), timeout=1)

        async with websockets.connect(uri_room1_seer) as seer_ws:
            await asyncio.wait_for(seer_ws.recv(), timeout=1)

            move_payload = {"type": "command", "command": "move", "args": {"direction": "north"}}
            await hero_ws.send(json.dumps(move_payload))

            await asyncio.wait_for(hero_ws.recv(), timeout=1)

            arrival_notice = await _receive_until(
                seer_ws,
                lambda msg: (
                    msg.get("type") == "room_broadcast"
                    and msg.get("payload", {}).get("event") == "room_message"
                ),
                timeout=2,
            )

            text = arrival_notice["payload"].get("text", "").lower()
            assert "hero" in text
            assert "appeared from the south" in text

    server.should_exit = True
    await server_task
