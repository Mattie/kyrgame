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


async def _recv_matching(ws, predicate, *, timeout: float = 1.0):
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
        if predicate(message):
            return message


@pytest.mark.anyio
async def test_single_admin_kyraedit_session_with_return(monkeypatch):
    monkeypatch.setenv("KYRGAME_ADMIN_TOKEN", "kyraedit-admin")

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

        hero_uri = f"ws://{host}:{port}/ws/rooms/{room_zero}?token={hero_token}"
        seer_uri = f"ws://{host}:{port}/ws/rooms/{room_zero}?token={seer_token}"

        async with websockets.connect(hero_uri) as hero_ws:
            await _recv_matching(hero_ws, lambda msg: msg.get("type") == "command_response")
            async with websockets.connect(seer_uri) as seer_ws:
                await _recv_matching(seer_ws, lambda msg: msg.get("type") == "command_response")

                admin_uri = (
                    f"ws://{host}:{port}/ws/admin/kyraedit?session_token={hero_token}"
                )
                async with websockets.connect(
                    admin_uri, extra_headers={"Authorization": "Bearer kyraedit-admin"}
                ) as admin_ws:
                    prompt = json.loads(await asyncio.wait_for(admin_ws.recv(), timeout=1))
                    assert prompt["type"] == "kyraedit_prompt"

                    with pytest.raises(
                        (websockets.exceptions.InvalidStatusCode, websockets.ConnectionClosed)
                    ):
                        other_admin = await websockets.connect(
                            admin_uri, extra_headers={"Authorization": "Bearer kyraedit-admin"}
                        )
                        await asyncio.wait_for(other_admin.recv(), timeout=1)

                    await admin_ws.send(
                        json.dumps({"type": "select_player", "player_id": "hero"})
                    )

                    record = json.loads(await asyncio.wait_for(admin_ws.recv(), timeout=1))
                    assert record["type"] == "kyraedit_record"
                    assert record["player"]["plyrid"] == "hero"

                    await admin_ws.send(json.dumps({"type": "exit"}))
                    exit_msg = json.loads(await asyncio.wait_for(admin_ws.recv(), timeout=1))
                    assert exit_msg["type"] == "kyraedit_exit"

                return_broadcast = await _recv_matching(
                    seer_ws,
                    lambda msg: msg.get("type") == "room_broadcast"
                    and msg.get("payload", {}).get("event") == "player_enter",
                )
                assert return_broadcast["payload"]["player"] == "hero"

    server.should_exit = True
    await server_task
