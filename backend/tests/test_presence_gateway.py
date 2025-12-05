import asyncio
import json
import socket

import pytest
import uvicorn
import websockets

from kyrgame.presence import PresenceService
from kyrgame.webapp import create_app



def _get_open_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    _, port = sock.getsockname()
    sock.close()
    return port


@pytest.mark.anyio
async def test_presence_service_tracks_membership_and_moves():
    presence = PresenceService()

    await presence.set_location("hero", 0)
    await presence.set_location("seer", 1)

    assert presence.room_for_player("hero") == 0
    assert presence.room_for_player("seer") == 1
    assert presence.players_in_room(0) == {"hero"}

    await presence.set_location("hero", 1)
    assert presence.room_for_player("hero") == 1
    assert presence.players_in_room(0) == set()
    assert presence.players_in_room(1) == {"hero", "seer"}

    await presence.remove("seer")
    assert presence.room_for_player("seer") is None
    assert presence.players_in_room(1) == {"hero"}


@pytest.mark.anyio
async def test_movement_command_switches_room_subscription_and_scopes_broadcasts():
    app = create_app()
    host = "127.0.0.1"
    port = _get_open_port()

    config = uvicorn.Config(app, host=host, port=port, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    uri_room0_hero = f"ws://{host}:{port}/ws/rooms/0?player_id=hero"
    uri_room0_rogue = f"ws://{host}:{port}/ws/rooms/0?player_id=rogue"
    uri_room1_seer = f"ws://{host}:{port}/ws/rooms/1?player_id=seer"

    async with websockets.connect(uri_room0_hero) as hero_ws:
        await asyncio.wait_for(hero_ws.recv(), timeout=1)
        async with websockets.connect(uri_room0_rogue) as rogue_ws:
            await asyncio.wait_for(rogue_ws.recv(), timeout=1)
            join_notice = json.loads(await asyncio.wait_for(hero_ws.recv(), timeout=1))
            assert join_notice["payload"]["player"] == "rogue"
            async with websockets.connect(uri_room1_seer) as seer_ws:
                await asyncio.wait_for(seer_ws.recv(), timeout=1)

                move_payload = {"type": "command", "command": "move", "args": {"direction": "north"}}
                await hero_ws.send(json.dumps(move_payload))

                hero_response = json.loads(await asyncio.wait_for(hero_ws.recv(), timeout=1))
                assert hero_response["type"] == "command_response"
                assert hero_response["room"] == 1

                seer_broadcast = json.loads(await asyncio.wait_for(seer_ws.recv(), timeout=1))
                assert seer_broadcast["type"] == "room_broadcast"
                assert seer_broadcast["room"] == 1
                assert seer_broadcast["payload"]["event"] == "player_enter"
                assert seer_broadcast["payload"]["player"] == "hero"

                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(rogue_ws.recv(), timeout=0.3)

                    chat_payload = {"type": "command", "command": "chat", "args": {"text": "hail"}}
                    await seer_ws.send(json.dumps(chat_payload))
                    await asyncio.wait_for(seer_ws.recv(), timeout=1)

                    chat_fan_out = json.loads(await asyncio.wait_for(hero_ws.recv(), timeout=1))
                    while chat_fan_out.get("type") != "room_broadcast":
                        chat_fan_out = json.loads(await asyncio.wait_for(hero_ws.recv(), timeout=1))

                    assert chat_fan_out["type"] == "room_broadcast"
                    assert chat_fan_out["payload"]["args"]["text"] == "hail"

                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(rogue_ws.recv(), timeout=0.3)

    server.should_exit = True
    await server_task


@pytest.mark.anyio
async def test_rate_limiting_blocks_chat_spam():
    app = create_app()
    host = "127.0.0.1"
    port = _get_open_port()

    config = uvicorn.Config(app, host=host, port=port, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    uri = f"ws://{host}:{port}/ws/rooms/0?player_id=hero"
    async with websockets.connect(uri) as ws:
        await asyncio.wait_for(ws.recv(), timeout=1)

        chat_payload = {"type": "command", "command": "chat", "args": {"text": "spam"}}
        await ws.send(json.dumps(chat_payload))
        await asyncio.wait_for(ws.recv(), timeout=1)
        await ws.send(json.dumps(chat_payload))
        await ws.send(json.dumps(chat_payload))

        responses = [json.loads(await asyncio.wait_for(ws.recv(), timeout=1)) for _ in range(2)]
        assert any(message["type"] == "rate_limited" for message in responses)
        assert any("Too many commands" in message.get("detail", "") for message in responses)

    server.should_exit = True
    await server_task
