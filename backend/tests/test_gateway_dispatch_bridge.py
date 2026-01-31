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


async def _assert_no_matching(ws, predicate, *, timeout: float = 0.5):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return
        try:
            message = json.loads(await asyncio.wait_for(ws.recv(), timeout=remaining))
        except asyncio.TimeoutError:
            return
        if predicate(message):
            raise AssertionError(f"Unexpected message received: {message}")


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
            await _recv_matching(
                hero_ws,
                lambda msg: msg.get("payload", {}).get("event") == "location_update",
            )
            async with websockets.connect(uri_room0_seer) as seer_ws:
                await _recv_matching(
                    seer_ws,
                    lambda msg: msg.get("payload", {}).get("event") == "location_update",
                )
                await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("payload", {}).get("event") == "player_enter",
                )
                async with websockets.connect(uri_room1_mystic) as mystic_ws:
                    await _recv_matching(
                        mystic_ws,
                        lambda msg: msg.get("payload", {}).get("event") == "location_update",
                    )

                    await hero_ws.send(json.dumps({"type": "command", "command": "say hello room"}))

                    hero_ack = await _recv_matching(
                        hero_ws,
                        lambda msg: msg.get("type") == "command_response"
                        and msg.get("payload", {}).get("command_id") == 53,
                    )
                    assert hero_ack["type"] == "command_response"
                    assert hero_ack["payload"]["command_id"] == 53

                    seer_broadcast = await _recv_matching(
                        seer_ws,
                        lambda msg: msg.get("type") == "room_broadcast"
                        and msg.get("payload", {}).get("command_id") == 53,
                    )
                    assert seer_broadcast["type"] == "room_broadcast"
                    assert seer_broadcast["payload"]["command_id"] == 53
                    assert seer_broadcast["payload"]["message_id"] == "CMD053"

                    await hero_ws.send(json.dumps({"type": "command", "command": "north"}))

                    move_ack = await _recv_matching(
                        hero_ws,
                        lambda msg: msg.get("type") == "command_response"
                        and msg.get("payload", {}).get("command_id") == 38,
                    )
                    assert move_ack["payload"]["command_id"] == 38
                    move_broadcast = await _recv_matching(
                        mystic_ws,
                        lambda msg: msg.get("type") == "room_broadcast"
                        and msg.get("payload", {}).get("command_id") == 38,
                    )
                    assert move_broadcast["payload"]["command_id"] == 38
                    assert move_broadcast["payload"]["event"] == "player_enter"

    server.should_exit = True
    await server_task


@pytest.mark.anyio
async def test_websocket_look_uses_persisted_altnam_for_looker3():
    app = create_app()
    host = "127.0.0.1"
    port = _get_open_port()

    config = uvicorn.Config(app, host=host, port=port, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    async with httpx.AsyncClient(base_url=f"http://{host}:{port}") as client:
        viewer_id = "looker3"
        target_id = "target"
        viewer_session = await client.post("/auth/session", json={"player_id": viewer_id, "room_id": 0})
        viewer_token = viewer_session.json()["session"]["token"]
        room_zero = viewer_session.json()["session"]["room_id"]

        target_session = await client.post("/auth/session", json={"player_id": target_id, "room_id": room_zero})
        target_token = target_session.json()["session"]["token"]

        viewer_uri = f"ws://{host}:{port}/ws/rooms/{room_zero}?token={viewer_token}"
        target_uri = f"ws://{host}:{port}/ws/rooms/{room_zero}?token={target_token}"

        async with websockets.connect(viewer_uri) as viewer_ws:
            await _recv_matching(
                viewer_ws,
                lambda msg: msg.get("payload", {}).get("event") == "location_update",
            )
            async with websockets.connect(target_uri) as target_ws:
                await _recv_matching(
                    target_ws,
                    lambda msg: msg.get("payload", {}).get("event") == "location_update",
                )
                await viewer_ws.send(json.dumps({"type": "command", "command": f"look {target_id}"}))

                looker3_event = await _recv_matching(
                    target_ws,
                    lambda msg: msg.get("payload", {}).get("message_id") == "LOOKER3",
                )
                assert looker3_event["payload"]["text"] == f"*** {viewer_id} is looking at you carefully."

    server.should_exit = True
    await server_task


@pytest.mark.anyio
async def test_websocket_bridge_echoes_silent_metadata_on_responses():
    app = create_app()
    host = "127.0.0.1"
    port = _get_open_port()

    config = uvicorn.Config(app, host=host, port=port, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    async with httpx.AsyncClient(base_url=f"http://{host}:{port}") as client:
        session_response = await client.post("/auth/session", json={"player_id": "hero", "room_id": 0})
        hero_token = session_response.json()["session"]["token"]
        room_zero = session_response.json()["session"]["room_id"]

        uri = f"ws://{host}:{port}/ws/rooms/{room_zero}?token={hero_token}"

        async with websockets.connect(uri) as hero_ws:
            # Drain initial location + occupants payloads
            await asyncio.wait_for(hero_ws.recv(), timeout=1)
            await asyncio.wait_for(hero_ws.recv(), timeout=1)
            await asyncio.wait_for(hero_ws.recv(), timeout=1)

            await hero_ws.send(
                json.dumps(
                    {
                        "type": "command",
                        "command": "inventory",
                        "meta": {"silent": True, "status_card": "inventory"},
                    }
                )
            )

            ack = json.loads(await asyncio.wait_for(hero_ws.recv(), timeout=1))
            assert ack["meta"] == {"silent": True, "status_card": "inventory"}

            inventory_event = json.loads(await asyncio.wait_for(hero_ws.recv(), timeout=1))
            assert inventory_event["meta"] == {"silent": True, "status_card": "inventory"}

    server.should_exit = True
    await server_task


@pytest.mark.anyio
async def test_room_broadcast_excludes_look_target():
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

        mystic_session = await client.post("/auth/session", json={"player_id": "mystic", "room_id": room_zero})
        mystic_token = mystic_session.json()["session"]["token"]

        uri_room0_hero = f"ws://{host}:{port}/ws/rooms/{room_zero}?token={hero_token}"
        uri_room0_seer = f"ws://{host}:{port}/ws/rooms/{room_zero}?token={seer_token}"
        uri_room0_mystic = f"ws://{host}:{port}/ws/rooms/{room_zero}?token={mystic_token}"

        async with websockets.connect(uri_room0_hero) as hero_ws:
            await _recv_matching(
                hero_ws,
                lambda msg: msg.get("payload", {}).get("event") == "location_update",
            )
            async with websockets.connect(uri_room0_seer) as seer_ws:
                await _recv_matching(
                    seer_ws,
                    lambda msg: msg.get("payload", {}).get("event") == "location_update",
                )
                await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("payload", {}).get("event") == "player_enter",
                )
                async with websockets.connect(uri_room0_mystic) as mystic_ws:
                    await _recv_matching(
                        mystic_ws,
                        lambda msg: msg.get("payload", {}).get("event") == "location_update",
                    )

                    await hero_ws.send(json.dumps({"type": "command", "command": "look seer"}))

                    seer_target = await _recv_matching(
                        seer_ws,
                        lambda msg: msg.get("type") == "command_response"
                        and msg.get("payload", {}).get("message_id") == "LOOKER3",
                    )
                    assert seer_target["payload"]["message_id"] == "LOOKER3"

                    mystic_room = await _recv_matching(
                        mystic_ws,
                        lambda msg: msg.get("type") == "room_broadcast"
                        and msg.get("payload", {}).get("message_id") == "LOOKER4",
                    )
                    assert mystic_room["payload"]["message_id"] == "LOOKER4"

                    await _assert_no_matching(
                        seer_ws,
                        lambda msg: msg.get("type") == "room_broadcast"
                        and msg.get("payload", {}).get("message_id") == "LOOKER4",
                    )

    server.should_exit = True
    await server_task
