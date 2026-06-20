import asyncio
import json
import socket

import httpx
import pytest
import uvicorn
import websockets
from sqlalchemy import select
from starlette.websockets import WebSocketState

from kyrgame import constants, fixtures, models
from kyrgame.gateway import RoomGateway
from kyrgame.presence import PresenceService
from kyrgame.webapp import _room_occupants_event
from session_test_helpers import create_seeded_app as create_app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_room_occupants_event_includes_player_flags_for_ui_styling():
    presence = PresenceService()
    await presence.set_location("Hero", 0, "hero-token")
    await presence.set_location("Merlin", 0, "merlin-token")

    event = await _room_occupants_event(
        presence,
        "Merlin",
        0,
        fixtures.load_message_bundle(),
        {"Hero": int(constants.PlayerFlag.LOADED | constants.PlayerFlag.FEMALE)},
    )

    assert event is not None
    assert event["occupants"] == ["Hero"]
    assert event["text"] == "Hero is here."
    assert event["occupant_details"] == [
        {
            "player_id": "Hero",
            "display_name": "Hero",
            "flags": int(constants.PlayerFlag.LOADED | constants.PlayerFlag.FEMALE),
        }
    ]


@pytest.mark.anyio
async def test_room_occupants_event_deduplicates_trimmed_presence_ids():
    presence = PresenceService()
    await presence.set_location("Hero", 0, "hero-token")
    await presence.set_location("Merlin", 0, "merlin-token")
    await presence.set_location("Necro", 0, "necro-token")
    await presence.set_location("Necro ", 0, "necro-stale-token")

    event = await _room_occupants_event(
        presence,
        "Hero",
        0,
        fixtures.load_message_bundle(),
        {"Necro": int(constants.PlayerFlag.LOADED)},
    )

    assert event is not None
    assert event["occupants"] == ["Merlin", "Necro"]
    assert event["text"] == "Merlin and Necro are here."
    assert "Merlin" in event["text"]
    assert event["text"].count("Necro") == 1


@pytest.mark.anyio
async def test_room_occupants_event_uses_active_transformed_altnam():
    presence = PresenceService()
    await presence.set_location("Hero", 0, "hero-token")
    await presence.set_location("Necro", 0, "necro-token")
    necro = fixtures.build_player().model_copy(
        update={
            "plyrid": "Necro",
            "attnam": "pegasus",
            "altnam": "Some pegasus",
            "gamloc": 0,
        }
    )

    event = await _room_occupants_event(
        presence,
        "Hero",
        0,
        fixtures.load_message_bundle(),
        {"Necro": int(constants.PlayerFlag.LOADED)},
        lambda player_id: necro if player_id.strip() == "Necro" else None,
    )

    assert event is not None
    assert event["occupants"] == ["Some pegasus"]
    assert event["text"] == "Some pegasus is here."
    assert event["occupant_details"] == [
        {
            "player_id": "Necro",
            "display_name": "Some pegasus",
            "flags": int(necro.flags),
        }
    ]


class DummyWebSocket:
    application_state = WebSocketState.CONNECTED



def _get_open_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    _, port = sock.getsockname()
    sock.close()
    return port


async def _receive_until(websocket, predicate, timeout: float = 1.5):
    end_time = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = end_time - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise asyncio.TimeoutError("Timed out waiting for matching message")
        message = json.loads(await asyncio.wait_for(websocket.recv(), timeout=remaining))
        if predicate(message):
            return message


async def _drain_pending_messages(websocket):
    while True:
        try:
            await asyncio.wait_for(websocket.recv(), timeout=0.05)
        except asyncio.TimeoutError:
            break


async def _wait_until(predicate, timeout: float = 1.5):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("Timed out waiting for condition")


@pytest.mark.anyio
async def test_presence_service_tracks_membership_and_moves():
    presence = PresenceService()

    await presence.set_location("hero", 0)
    await presence.set_location("seer", 1)

    assert await presence.room_for_player("hero") == 0
    assert await presence.room_for_player("seer") == 1
    assert await presence.players_in_room(0) == {"hero"}

    await presence.set_location("hero", 1)
    assert await presence.room_for_player("hero") == 1
    assert await presence.players_in_room(0) == set()
    assert await presence.players_in_room(1) == {"hero", "seer"}

    await presence.remove("seer")
    assert await presence.room_for_player("seer") is None
    assert await presence.players_in_room(1) == {"hero"}


@pytest.mark.anyio
async def test_presence_service_relabels_session_in_same_room():
    presence = PresenceService()

    await presence.set_location("hero", 0, "token")
    await presence.set_location("herox", 0, "token")

    assert await presence.room_for_player("hero") is None
    assert await presence.room_for_player("herox") == 0
    assert await presence.sessions_for_player("hero") == set()
    assert await presence.sessions_for_player("herox") == {"token"}
    assert await presence.players_in_room(0) == {"herox"}


@pytest.mark.anyio
async def test_gateway_unregister_removes_socket_from_registered_room_when_caller_room_is_stale():
    gateway = RoomGateway()
    websocket = DummyWebSocket()

    await gateway.register(0, websocket, announce=False)
    await gateway.register(1, websocket, announce=False)
    await gateway.unregister(0, websocket)

    assert websocket not in gateway.connections
    assert websocket not in gateway.rooms.get(0, set())
    assert websocket not in gateway.rooms.get(1, set())


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

    async with httpx.AsyncClient(base_url=f"http://{host}:{port}") as client:
        hero_session = await client.post("/auth/session", json={"player_id": "hero", "room_id": 0})
        hero_token = hero_session.json()["session"]["token"]
        rogue_session = await client.post("/auth/session", json={"player_id": "rogue", "room_id": 0})
        rogue_token = rogue_session.json()["session"]["token"]
        seer_session = await client.post("/auth/session", json={"player_id": "seer", "room_id": 1})
        seer_token = seer_session.json()["session"]["token"]
        with app.state.session_factory() as db:
            hero = db.scalar(select(models.Player).where(models.Player.plyrid == "hero"))
            assert hero is not None
            hero.altnam = "Some pegasus"
            hero.attnam = "Some pegasus"
            db.commit()

    uri_room0_hero = f"ws://{host}:{port}/ws/rooms/0?token={hero_token}"
    uri_room0_rogue = f"ws://{host}:{port}/ws/rooms/0?token={rogue_token}"
    uri_room1_seer = f"ws://{host}:{port}/ws/rooms/1?token={seer_token}"

    async with websockets.connect(uri_room0_hero) as hero_ws:
        await asyncio.wait_for(hero_ws.recv(), timeout=1)
        await _drain_pending_messages(hero_ws)
        async with websockets.connect(uri_room0_rogue) as rogue_ws:
            await asyncio.wait_for(rogue_ws.recv(), timeout=1)
            await _drain_pending_messages(rogue_ws)
            join_notice = await _receive_until(
                hero_ws,
                lambda msg: msg.get("type") == "room_broadcast"
                and msg.get("payload", {}).get("event") == "player_enter",
            )
            assert join_notice["payload"]["player"] == "rogue"
            await _drain_pending_messages(hero_ws)

            async with websockets.connect(uri_room1_seer) as seer_ws:
                await asyncio.wait_for(seer_ws.recv(), timeout=1)

                move_payload = {
                    "type": "command",
                    "command": "move",
                    "args": {"direction": "north"},
                }
                await hero_ws.send(json.dumps(move_payload))

                hero_response = json.loads(await asyncio.wait_for(hero_ws.recv(), timeout=1))
                assert hero_response["type"] == "command_response"
                assert hero_response["room"] == 1

                seer_broadcast = await _receive_until(
                    seer_ws,
                    lambda msg: msg.get("type") == "room_broadcast"
                    and msg.get("payload", {}).get("event") == "player_enter",
                )
                assert seer_broadcast["type"] == "room_broadcast"
                assert seer_broadcast["room"] == 1
                assert seer_broadcast["payload"]["player"] == "hero"
                assert seer_broadcast["payload"]["display_name"] == "Some pegasus"

                departure_notice = await _receive_until(
                    rogue_ws,
                    lambda msg: msg.get("type") == "room_broadcast"
                    and msg.get("payload", {}).get("event") == "room_message",
                )
                assert departure_notice["room"] == 0
                assert departure_notice["payload"]["text"] == (
                    "*** Some pegasus has just moved off to the north!"
                )

                chat_payload = {"type": "command", "command": "chat", "args": {"text": "hail"}}
                await seer_ws.send(json.dumps(chat_payload))
                await asyncio.wait_for(seer_ws.recv(), timeout=1)

                chat_fan_out = json.loads(await asyncio.wait_for(hero_ws.recv(), timeout=1))
                while chat_fan_out.get("type") != "room_broadcast":
                    chat_fan_out = json.loads(await asyncio.wait_for(hero_ws.recv(), timeout=1))

                assert chat_fan_out["type"] == "room_broadcast"
                assert chat_fan_out["payload"]["args"]["text"] == "hail"

                await _drain_pending_messages(rogue_ws)
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(rogue_ws.recv(), timeout=0.3)

    server.should_exit = True
    await server_task


@pytest.mark.anyio
async def test_x_command_broadcasts_departure_and_deactivates_session():
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
        rogue_session = await client.post("/auth/session", json={"player_id": "rogue", "room_id": 0})
        rogue_token = rogue_session.json()["session"]["token"]

        uri_room0_hero = f"ws://{host}:{port}/ws/rooms/0?token={hero_token}"
        uri_room0_rogue = f"ws://{host}:{port}/ws/rooms/0?token={rogue_token}"

        async with websockets.connect(uri_room0_hero) as hero_ws:
            await asyncio.wait_for(hero_ws.recv(), timeout=1)
            await _drain_pending_messages(hero_ws)

            async with websockets.connect(uri_room0_rogue) as rogue_ws:
                await asyncio.wait_for(rogue_ws.recv(), timeout=1)
                await _drain_pending_messages(rogue_ws)
                await _drain_pending_messages(hero_ws)

                await hero_ws.send(json.dumps({"type": "command", "command": "x"}))

                exit_message = await _receive_until(
                    hero_ws,
                    lambda msg: msg.get("payload", {}).get("message_id") == "EXIKYR",
                )
                assert exit_message["payload"]["text"] == "...Exiting Kyrandia..."

                departure_notice = await _receive_until(
                    rogue_ws,
                    lambda msg: msg.get("type") == "room_broadcast"
                    and msg.get("payload", {}).get("event") == "room_message",
                )
                assert departure_notice["payload"]["text"] == (
                    "*** Hero Alt has just vanished in sparkling light!"
                )

                await _wait_until(
                    lambda: hero_token not in getattr(app.state, "active_player_sessions", {})
                )
                assert await app.state.presence.room_for_session(hero_token) is None

                validate = await client.get(
                    "/auth/session", headers={"Authorization": f"Bearer {hero_token}"}
                )
                assert validate.status_code == 401

    server.should_exit = True
    await server_task


@pytest.mark.anyio
async def test_room_broadcast_on_login_uses_entrance_text():
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
        rogue_session = await client.post("/auth/session", json={"player_id": "rogue", "room_id": 0})
        rogue_token = rogue_session.json()["session"]["token"]

    uri_room0_hero = f"ws://{host}:{port}/ws/rooms/0?token={hero_token}"
    uri_room0_rogue = f"ws://{host}:{port}/ws/rooms/0?token={rogue_token}"

    async with websockets.connect(uri_room0_hero) as hero_ws:
        await asyncio.wait_for(hero_ws.recv(), timeout=1)
        await _drain_pending_messages(hero_ws)

        async with websockets.connect(uri_room0_rogue) as rogue_ws:
            await asyncio.wait_for(rogue_ws.recv(), timeout=1)
            await _drain_pending_messages(rogue_ws)

            entrance_message = await _receive_until(
                hero_ws,
                lambda msg: msg.get("type") == "room_broadcast"
                and msg.get("payload", {}).get("event") == "room_message",
            )

            payload = entrance_message["payload"]
            assert payload["type"] == "room_message"
            assert payload["player"] == "rogue"
            assert payload["text"] == "*** rogue has just appeared in a cloud of mists!"

    server.should_exit = True
    await server_task


@pytest.mark.anyio
async def test_room_broadcast_on_login_uses_transformed_entrance_name():
    app = create_app()
    host = "127.0.0.1"
    port = _get_open_port()

    config = uvicorn.Config(app, host=host, port=port, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    try:
        while not server.started:
            await asyncio.sleep(0.05)

        async with httpx.AsyncClient(base_url=f"http://{host}:{port}") as client:
            hero_session = await client.post("/auth/session", json={"player_id": "hero", "room_id": 0})
            hero_token = hero_session.json()["session"]["token"]
            rogue_session = await client.post("/auth/session", json={"player_id": "rogue", "room_id": 0})
            rogue_token = rogue_session.json()["session"]["token"]

        with app.state.session_factory() as db:
            rogue = db.scalar(select(models.Player).where(models.Player.plyrid == "rogue"))
            assert rogue is not None
            rogue.altnam = "Some pegasus"
            rogue.attnam = "pegasus"
            db.commit()

        uri_room0_hero = f"ws://{host}:{port}/ws/rooms/0?token={hero_token}"
        uri_room0_rogue = f"ws://{host}:{port}/ws/rooms/0?token={rogue_token}"

        async with websockets.connect(uri_room0_hero) as hero_ws:
            await asyncio.wait_for(hero_ws.recv(), timeout=1)
            await _drain_pending_messages(hero_ws)

            async with websockets.connect(uri_room0_rogue) as rogue_ws:
                await asyncio.wait_for(rogue_ws.recv(), timeout=1)
                await _drain_pending_messages(rogue_ws)

                entrance_message = await _receive_until(
                    hero_ws,
                    lambda msg: msg.get("type") == "room_broadcast"
                    and msg.get("payload", {}).get("event") == "room_message",
                )

                payload = entrance_message["payload"]
                assert payload["player"] == "rogue"
                assert payload["text"] == "*** Some pegasus has just appeared in a cloud of mists!"
    finally:
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

    async with httpx.AsyncClient(base_url=f"http://{host}:{port}") as client:
        session = await client.post("/auth/session", json={"player_id": "hero", "room_id": 0})
        token = session.json()["session"]["token"]

        uri = f"ws://{host}:{port}/ws/rooms/0?token={token}"
        async with websockets.connect(uri) as ws:
            await asyncio.wait_for(ws.recv(), timeout=1)

            chat_payload = {"type": "command", "command": "chat", "args": {"text": "spam"}}
            await ws.send(json.dumps(chat_payload))
            await asyncio.wait_for(ws.recv(), timeout=1)
            await ws.send(json.dumps(chat_payload))
            await ws.send(json.dumps(chat_payload))

            rate_limited = await _receive_until(
                ws, lambda msg: msg.get("type") == "rate_limited", timeout=2
            )
            assert rate_limited["type"] == "rate_limited"
            assert "Too many commands" in rate_limited.get("detail", "")

    server.should_exit = True
    await server_task
