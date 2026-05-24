import asyncio
import json
import socket

import httpx
import pytest
import uvicorn
import websockets
from sqlalchemy import select

from kyrgame import constants, models, repositories
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


class _FixedAnimationRng:
    def __init__(self, *, randrange_values=(), randint_values=()) -> None:
        self._randrange_values = list(randrange_values)
        self._randint_values = list(randint_values)

    def randrange(self, low: int, high: int) -> int:  # noqa: ARG002
        return self._randrange_values.pop(0)

    def randint(self, low: int, high: int) -> int:  # noqa: ARG002
        return self._randint_values.pop(0)


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
async def test_websocket_clutzopho_drop_lines_reach_caster_and_bystanders():
    app = create_app()
    host = "127.0.0.1"
    port = _get_open_port()

    config = uvicorn.Config(app, host=host, port=port, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    async with httpx.AsyncClient(base_url=f"http://{host}:{port}") as client:
        hero_session = await client.post("/auth/session", json={"player_id": "hero", "room_id": 7})
        hero_token = hero_session.json()["session"]["token"]
        room_id = hero_session.json()["session"]["room_id"]

        seer_session = await client.post("/auth/session", json={"player_id": "seer", "room_id": room_id})
        seer_token = seer_session.json()["session"]["token"]

        mystic_session = await client.post("/auth/session", json={"player_id": "mystic", "room_id": room_id})
        mystic_token = mystic_session.json()["session"]["token"]

        with app.state.session_factory() as db:
            hero = db.scalar(select(models.Player).where(models.Player.plyrid == "hero"))
            seer = db.scalar(select(models.Player).where(models.Player.plyrid == "seer"))
            mystic = db.scalar(select(models.Player).where(models.Player.plyrid == "mystic"))
            location = db.get(models.Location, room_id)
            assert hero is not None
            assert seer is not None
            assert mystic is not None
            assert location is not None

            hero.flags |= int(constants.PlayerFlag.LOADED)
            hero.level = 25
            hero.spts = 25
            hero.spells = [10]
            hero.nspells = 1
            hero.gamloc = room_id
            hero.pgploc = room_id
            seer.gamloc = room_id
            seer.pgploc = room_id
            seer.gpobjs = [0]
            seer.obvals = [10]
            seer.npobjs = 1
            mystic.gamloc = room_id
            mystic.pgploc = room_id
            location.objects = []
            location.nlobjs = 0
            db.commit()

        uri_room_hero = f"ws://{host}:{port}/ws/rooms/{room_id}?token={hero_token}"
        uri_room_seer = f"ws://{host}:{port}/ws/rooms/{room_id}?token={seer_token}"
        uri_room_mystic = f"ws://{host}:{port}/ws/rooms/{room_id}?token={mystic_token}"

        async with websockets.connect(uri_room_hero) as hero_ws:
            await _recv_matching(
                hero_ws,
                lambda msg: msg.get("payload", {}).get("event") == "location_update",
            )
            async with websockets.connect(uri_room_seer) as seer_ws:
                await _recv_matching(
                    seer_ws,
                    lambda msg: msg.get("payload", {}).get("event") == "location_update",
                )
                async with websockets.connect(uri_room_mystic) as mystic_ws:
                    await _recv_matching(
                        mystic_ws,
                        lambda msg: msg.get("payload", {}).get("event") == "location_update",
                    )

                    await hero_ws.send(
                        json.dumps({"type": "command", "command": "cast clutzopho seer"})
                    )

                    hero_drop = await _recv_matching(
                        hero_ws,
                        lambda msg: msg.get("type") == "command_response"
                        and msg.get("payload", {}).get("message_id") == "S11M06",
                    )
                    seer_drop = await _recv_matching(
                        seer_ws,
                        lambda msg: msg.get("type") == "command_response"
                        and msg.get("payload", {}).get("message_id") == "S11M05",
                    )
                    mystic_drop = await _recv_matching(
                        mystic_ws,
                        lambda msg: msg.get("type") == "room_broadcast"
                        and msg.get("payload", {}).get("message_id") == "S11M06",
                    )

                    assert hero_drop["payload"]["scope"] == "player"
                    assert seer_drop["payload"]["scope"] == "target"
                    assert mystic_drop["payload"]["scope"] == "room"

    server.should_exit = True
    await server_task


@pytest.mark.anyio
async def test_websocket_whisper_emits_targeted_and_room_payloads():
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
        seer_session = await client.post("/auth/session", json={"player_id": "seer", "room_id": 0})

        uri_room0_hero = f"ws://{host}:{port}/ws/rooms/0?token={hero_session.json()['session']['token']}"
        uri_room0_seer = f"ws://{host}:{port}/ws/rooms/0?token={seer_session.json()['session']['token']}"

        async with websockets.connect(uri_room0_hero) as hero_ws:
            await _recv_matching(hero_ws, lambda msg: msg.get("payload", {}).get("event") == "location_update")
            async with websockets.connect(uri_room0_seer) as seer_ws:
                await _recv_matching(seer_ws, lambda msg: msg.get("payload", {}).get("event") == "location_update")
                await _recv_matching(hero_ws, lambda msg: msg.get("payload", {}).get("event") == "player_enter")

                await hero_ws.send(json.dumps({"type": "command", "command": "whisper seer hush"}))

                hero_ack = await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("type") == "command_response"
                    and msg.get("payload", {}).get("message_id") == "WHISPR2",
                )
                assert hero_ack["payload"]["message_id"] == "WHISPR2"

                seer_msg = await _recv_matching(
                    seer_ws,
                    lambda msg: msg.get("type") == "command_response"
                    and msg.get("payload", {}).get("message_id") == "WHISPR1",
                )
                assert seer_msg["payload"]["message_id"] == "WHISPR1"

    server.should_exit = True
    await server_task


@pytest.mark.anyio
async def test_websocket_give_item_target_payload_includes_giver_name():
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
        seer_session = await client.post("/auth/session", json={"player_id": "seer", "room_id": 0})

        uri_room0_hero = f"ws://{host}:{port}/ws/rooms/0?token={hero_session.json()['session']['token']}"
        uri_room0_seer = f"ws://{host}:{port}/ws/rooms/0?token={seer_session.json()['session']['token']}"

        async with websockets.connect(uri_room0_hero) as hero_ws:
            await _recv_matching(hero_ws, lambda msg: msg.get("payload", {}).get("event") == "location_update")
            async with websockets.connect(uri_room0_seer) as seer_ws:
                await _recv_matching(seer_ws, lambda msg: msg.get("payload", {}).get("event") == "location_update")
                await _recv_matching(hero_ws, lambda msg: msg.get("payload", {}).get("event") == "player_enter")

                # Legacy target-first order: give <target> <item> (KYRCMDS.C:503-504)
                await hero_ws.send(json.dumps({"type": "command", "command": "give seer ruby"}))

                seer_msg = await _recv_matching(
                    seer_ws,
                    lambda msg: msg.get("type") == "command_response"
                    and msg.get("payload", {}).get("message_id") == "GIVERU10",
                )
                assert "Hero Alt" in seer_msg["payload"]["text"]
                assert "given you a ruby!" in seer_msg["payload"]["text"]

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
            await _recv_matching(
                hero_ws,
                lambda msg: msg.get("payload", {}).get("event") == "location_update",
            )
            await _recv_matching(
                hero_ws,
                lambda msg: msg.get("payload", {}).get("event") == "location_description",
            )
            room_objects_event = await _recv_matching(
                hero_ws,
                lambda msg: msg.get("payload", {}).get("event") == "room_objects",
            )
            assert room_objects_event["payload"]["location"] == room_zero

            meta = {"silent": True, "status_card": "inventory"}
            await hero_ws.send(
                json.dumps(
                    {
                        "type": "command",
                        "command": "inventory",
                        "meta": meta,
                    }
                )
            )

            ack = await _recv_matching(
                hero_ws,
                lambda msg: msg.get("meta") == meta
                and msg.get("payload", {}).get("verb") == "inventory",
            )
            assert ack["meta"] == meta

            inventory_event = await _recv_matching(
                hero_ws,
                lambda msg: msg.get("meta") == meta
                and msg.get("payload", {}).get("event") == "inventory",
            )
            assert inventory_event["meta"] == meta

    server.should_exit = True
    await server_task


@pytest.mark.anyio
async def test_websocket_room_command_handles_unknown_verbs():
    app = create_app()
    host = "127.0.0.1"
    port = _get_open_port()

    config = uvicorn.Config(app, host=host, port=port, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    async with httpx.AsyncClient(base_url=f"http://{host}:{port}") as client:
        hero_session = await client.post("/auth/session", json={"player_id": "hero", "room_id": 181})
        hero_token = hero_session.json()["session"]["token"]
        room_id = hero_session.json()["session"]["room_id"]

        uri = f"ws://{host}:{port}/ws/rooms/{room_id}?token={hero_token}"

        async with websockets.connect(uri) as hero_ws:
            await _recv_matching(
                hero_ws,
                lambda msg: msg.get("payload", {}).get("event") == "location_update",
            )
            await _recv_matching(
                hero_ws,
                lambda msg: msg.get("payload", {}).get("event") == "location_description",
            )

            await hero_ws.send(json.dumps({"type": "command", "command": "imagine dagger"}))

            saw_ack = False
            saw_dagger = False
            while not (saw_ack and saw_dagger):
                message = json.loads(await asyncio.wait_for(hero_ws.recv(), timeout=1))
                if (
                    message.get("type") == "command_response"
                    and message.get("payload", {}).get("verb") == "imagine"
                ):
                    saw_ack = True
                if (
                    message.get("type") == "room_broadcast"
                    and message.get("payload", {}).get("message_id") == "DAGM00"
                ):
                    saw_dagger = True
            await _assert_no_matching(
                hero_ws,
                lambda msg: msg.get("type") == "command_error",
            )

    server.should_exit = True
    await server_task


@pytest.mark.anyio
async def test_room_script_self_target_event_reaches_all_player_sessions():
    app = create_app()
    host = "127.0.0.1"
    port = _get_open_port()

    config = uvicorn.Config(app, host=host, port=port, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    async with httpx.AsyncClient(base_url=f"http://{host}:{port}") as client:
        first_session = await client.post("/auth/session", json={"player_id": "hero", "room_id": 181})
        first_token = first_session.json()["session"]["token"]
        room_id = first_session.json()["session"]["room_id"]
        second_token = "hero-second-active-session"

        with app.state.session_factory() as db:
            player = db.scalar(select(models.Player).where(models.Player.plyrid == "hero"))
            assert player is not None
            repositories.PlayerSessionRepository(db).create_session(
                player_id=player.id,
                session_token=second_token,
                room_id=room_id,
            )
            db.commit()

        first_uri = f"ws://{host}:{port}/ws/rooms/{room_id}?token={first_token}"
        second_uri = f"ws://{host}:{port}/ws/rooms/{room_id}?token={second_token}"

        async with websockets.connect(first_uri) as first_ws:
            await _recv_matching(
                first_ws,
                lambda msg: msg.get("payload", {}).get("event") == "location_update",
            )
            async with websockets.connect(second_uri) as second_ws:
                await _recv_matching(
                    second_ws,
                    lambda msg: msg.get("payload", {}).get("event") == "location_update",
                )

                await first_ws.send(json.dumps({"type": "command", "command": "imagine dagger"}))

                first_effect = await _recv_matching(
                    first_ws,
                    lambda msg: msg.get("type") == "room_broadcast"
                    and msg.get("payload", {}).get("message_id") == "DAGM00",
                )
                second_effect = await _recv_matching(
                    second_ws,
                    lambda msg: msg.get("type") == "room_broadcast"
                    and msg.get("payload", {}).get("message_id") == "DAGM00",
                )

                assert first_effect["payload"]["player"] == "hero"
                assert second_effect["payload"]["player"] == "hero"

    server.should_exit = True
    await server_task


@pytest.mark.anyio
async def test_silent_room_script_self_target_event_uses_command_response_envelope():
    app = create_app()
    host = "127.0.0.1"
    port = _get_open_port()

    config = uvicorn.Config(app, host=host, port=port, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    async with httpx.AsyncClient(base_url=f"http://{host}:{port}") as client:
        first_session = await client.post("/auth/session", json={"player_id": "hero", "room_id": 181})
        first_token = first_session.json()["session"]["token"]
        room_id = first_session.json()["session"]["room_id"]
        second_token = "hero-second-silent-session"

        with app.state.session_factory() as db:
            player = db.scalar(select(models.Player).where(models.Player.plyrid == "hero"))
            assert player is not None
            repositories.PlayerSessionRepository(db).create_session(
                player_id=player.id,
                session_token=second_token,
                room_id=room_id,
            )
            db.commit()

        first_uri = f"ws://{host}:{port}/ws/rooms/{room_id}?token={first_token}"
        second_uri = f"ws://{host}:{port}/ws/rooms/{room_id}?token={second_token}"
        meta = {"silent": True, "status_card": "room_script"}

        async with websockets.connect(first_uri) as first_ws:
            await _recv_matching(
                first_ws,
                lambda msg: msg.get("payload", {}).get("event") == "location_update",
            )
            async with websockets.connect(second_uri) as second_ws:
                await _recv_matching(
                    second_ws,
                    lambda msg: msg.get("payload", {}).get("event") == "location_update",
                )

                await first_ws.send(
                    json.dumps(
                        {
                            "type": "command",
                            "command": "imagine dagger",
                            "meta": meta,
                        }
                    )
                )

                first_effect = await _recv_matching(
                    first_ws,
                    lambda msg: msg.get("type") == "command_response"
                    and msg.get("meta") == meta
                    and msg.get("payload", {}).get("message_id") == "DAGM00",
                )
                second_effect = await _recv_matching(
                    second_ws,
                    lambda msg: msg.get("type") == "command_response"
                    and msg.get("meta") == meta
                    and msg.get("payload", {}).get("message_id") == "DAGM00",
                )

                assert first_effect["payload"]["player"] == "hero"
                assert second_effect["payload"]["player"] == "hero"
                await _assert_no_matching(
                    first_ws,
                    lambda msg: msg.get("type") == "room_broadcast"
                    and msg.get("payload", {}).get("message_id") == "DAGM00",
                )
                await _assert_no_matching(
                    second_ws,
                    lambda msg: msg.get("type") == "room_broadcast"
                    and msg.get("payload", {}).get("message_id") == "DAGM00",
                )

    server.should_exit = True
    await server_task


@pytest.mark.anyio
async def test_websocket_room_command_overrides_stubbed_drink():
    app = create_app()
    host = "127.0.0.1"
    port = _get_open_port()

    config = uvicorn.Config(app, host=host, port=port, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    async with httpx.AsyncClient(base_url=f"http://{host}:{port}") as client:
        hero_session = await client.post("/auth/session", json={"player_id": "hero", "room_id": 36})
        hero_token = hero_session.json()["session"]["token"]
        room_id = hero_session.json()["session"]["room_id"]

        uri = f"ws://{host}:{port}/ws/rooms/{room_id}?token={hero_token}"

        async with websockets.connect(uri) as hero_ws:
            await _recv_matching(
                hero_ws,
                lambda msg: msg.get("payload", {}).get("event") == "location_update",
            )
            await _recv_matching(
                hero_ws,
                lambda msg: msg.get("payload", {}).get("event") == "location_description",
            )

            await hero_ws.send(json.dumps({"type": "command", "command": "drink water"}))

            saw_ack = False
            saw_drink = False
            while not (saw_ack and saw_drink):
                message = json.loads(await asyncio.wait_for(hero_ws.recv(), timeout=1))
                if (
                    message.get("type") == "command_response"
                    and message.get("payload", {}).get("verb") == "drink"
                ):
                    saw_ack = True
                if (
                    message.get("type") == "room_broadcast"
                    and message.get("payload", {}).get("message_id") == "DRINK0"
                ):
                    saw_drink = True

            await _assert_no_matching(
                hero_ws,
                lambda msg: msg.get("type") == "command_response"
                and msg.get("payload", {}).get("event") == "unimplemented",
            )

    server.should_exit = True
    await server_task


@pytest.mark.anyio
async def test_websocket_room_command_overrides_stubbed_toss():
    app = create_app()
    host = "127.0.0.1"
    port = _get_open_port()

    config = uvicorn.Config(app, host=host, port=port, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    async with httpx.AsyncClient(base_url=f"http://{host}:{port}") as client:
        hero_session = await client.post("/auth/session", json={"player_id": "hero", "room_id": 182})
        hero_token = hero_session.json()["session"]["token"]
        room_id = hero_session.json()["session"]["room_id"]

        uri = f"ws://{host}:{port}/ws/rooms/{room_id}?token={hero_token}"

        async with websockets.connect(uri) as hero_ws:
            await _recv_matching(
                hero_ws,
                lambda msg: msg.get("payload", {}).get("event") == "location_update",
            )
            await _recv_matching(
                hero_ws,
                lambda msg: msg.get("payload", {}).get("event") == "location_description",
            )

            await hero_ws.send(json.dumps({"type": "command", "command": "toss dagger pool"}))

            saw_ack = False
            saw_reflection = False
            while not (saw_ack and saw_reflection):
                message = json.loads(await asyncio.wait_for(hero_ws.recv(), timeout=1))
                if (
                    message.get("type") == "command_response"
                    and message.get("payload", {}).get("verb") == "toss"
                ):
                    saw_ack = True
                if (
                    message.get("type") == "room_broadcast"
                    and message.get("payload", {}).get("message_id") == "REFM02"
                ):
                    saw_reflection = True

            await _assert_no_matching(
                hero_ws,
                lambda msg: msg.get("type") == "command_response"
                and msg.get("payload", {}).get("event") == "unimplemented",
            )

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


@pytest.mark.anyio
async def test_websocket_zelastone_notifies_remote_target(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "1000")
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
            hero_session = await client.post(
                "/auth/session", json={"player_id": "hero", "room_id": 7}
            )
            target_session = await client.post(
                "/auth/session", json={"player_id": "target", "room_id": 12}
            )
            hero_token = hero_session.json()["session"]["token"]
            target_token = target_session.json()["session"]["token"]

            with app.state.session_factory() as db:
                hero = db.scalar(select(models.Player).where(models.Player.plyrid == "hero"))
                target = db.scalar(
                    select(models.Player).where(models.Player.plyrid == "target")
                )
                assert hero is not None
                assert target is not None
                hero.level = 25
                hero.spts = 25
                hero.spells = [66]
                hero.nspells = 1
                hero.gamloc = 7
                hero.pgploc = 7
                target.gamloc = 12
                target.pgploc = 12
                target.attnam = "Target"
                target.altnam = "Target"
                target_charms = list(target.charms)
                target_charms[constants.OBJPRO] = 1
                target.charms = target_charms
                db.commit()

            hero_uri = f"ws://{host}:{port}/ws/rooms/7?token={hero_token}"
            target_uri = f"ws://{host}:{port}/ws/rooms/12?token={target_token}"

            async with websockets.connect(hero_uri) as hero_ws:
                await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("payload", {}).get("event") == "location_update",
                )
                async with websockets.connect(target_uri) as target_ws:
                    await _recv_matching(
                        target_ws,
                        lambda msg: msg.get("payload", {}).get("event")
                        == "location_update",
                    )

                    await hero_ws.send(
                        json.dumps({"type": "command", "command": "cast zelastone target"})
                    )

                    target_room = await _recv_matching(
                        target_ws,
                        lambda msg: msg.get("type") == "room_broadcast"
                        and msg.get("payload", {}).get("message_id") == "S67M04",
                        timeout=2.0,
                    )
                    target_direct = await _recv_matching(
                        target_ws,
                        lambda msg: msg.get("type") == "command_response"
                        and msg.get("payload", {}).get("message_id") == "S67M08",
                        timeout=2.0,
                    )

                    assert target_room["room"] == 12
                    assert target_direct["room"] == 12
                    assert target_direct["payload"]["player"] == "target"
                    assert target_direct["payload"]["room_id"] == 12
    finally:
        server.should_exit = True
        await server_task


@pytest.mark.anyio
async def test_websocket_peepint_tags_remote_target_response_with_target_room(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "1000")
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
            hero_session = await client.post(
                "/auth/session", json={"player_id": "hero", "room_id": 7}
            )
            target_session = await client.post(
                "/auth/session", json={"player_id": "target", "room_id": 12}
            )
            hero_token = hero_session.json()["session"]["token"]
            target_token = target_session.json()["session"]["token"]

            with app.state.session_factory() as db:
                hero = db.scalar(select(models.Player).where(models.Player.plyrid == "hero"))
                target = db.scalar(
                    select(models.Player).where(models.Player.plyrid == "target")
                )
                assert hero is not None
                assert target is not None
                hero.level = 25
                hero.spts = 25
                hero.spells = [45]
                hero.nspells = 1
                hero.gamloc = 7
                hero.pgploc = 7
                target.gamloc = 12
                target.pgploc = 12
                target.attnam = "Target"
                target.altnam = "Target"
                db.commit()

            hero_uri = f"ws://{host}:{port}/ws/rooms/7?token={hero_token}"
            target_uri = f"ws://{host}:{port}/ws/rooms/12?token={target_token}"

            async with websockets.connect(hero_uri) as hero_ws:
                await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("payload", {}).get("event") == "location_update",
                )
                async with websockets.connect(target_uri) as target_ws:
                    await _recv_matching(
                        target_ws,
                        lambda msg: msg.get("payload", {}).get("event")
                        == "location_update",
                    )

                    await hero_ws.send(
                        json.dumps({"type": "command", "command": "cast peepint target"})
                    )

                    target_direct = await _recv_matching(
                        target_ws,
                        lambda msg: msg.get("type") == "command_response"
                        and msg.get("payload", {}).get("message_id") == "KSPM06",
                        timeout=2.0,
                    )

                    assert target_direct["room"] == 12
                    assert target_direct["payload"]["room_id"] == 12
                    assert target_direct["payload"]["player"] == "target"
    finally:
        server.should_exit = True
        await server_task


@pytest.mark.anyio
async def test_websocket_global_target_spells_ignore_db_only_players(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "1000")
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
            hero_session = await client.post(
                "/auth/session", json={"player_id": "hero", "room_id": 7}
            )
            await client.post(
                "/auth/session", json={"player_id": "target", "room_id": 12}
            )
            hero_token = hero_session.json()["session"]["token"]

            with app.state.session_factory() as db:
                hero = db.scalar(select(models.Player).where(models.Player.plyrid == "hero"))
                target = db.scalar(
                    select(models.Player).where(models.Player.plyrid == "target")
                )
                assert hero is not None
                assert target is not None
                hero.level = 25
                hero.spts = 25
                hero.spells = [45]
                hero.nspells = 1
                hero.gamloc = 7
                hero.pgploc = 7
                target.gamloc = 12
                target.pgploc = 12
                target.attnam = "Target"
                target.altnam = "Target"
                db.commit()

            hero_uri = f"ws://{host}:{port}/ws/rooms/7?token={hero_token}"

            async with websockets.connect(hero_uri) as hero_ws:
                await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("payload", {}).get("event") == "location_update",
                )

                await hero_ws.send(
                    json.dumps({"type": "command", "command": "cast peepint target"})
                )

                failure = await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("type") == "command_response"
                    and msg.get("payload", {}).get("message_id") == "KSPM03",
                    timeout=2.0,
                )

                assert failure["payload"]["scope"] == "player"
                await _assert_no_matching(
                    hero_ws,
                    lambda msg: msg.get("type") == "command_response"
                    and msg.get("payload", {}).get("message_id") == "KSPM04",
                    timeout=0.25,
                )
    finally:
        server.should_exit = True
        await server_task


@pytest.mark.anyio
async def test_websocket_tiltowait_global_and_room_messages_reach_visible_clients(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "1000")
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
            caster_session = await client.post(
                "/auth/session", json={"player_id": "caster", "room_id": 7}
            )
            witness_session = await client.post(
                "/auth/session", json={"player_id": "witness", "room_id": 12}
            )
            caster_token = caster_session.json()["session"]["token"]
            witness_token = witness_session.json()["session"]["token"]

            rose_id = next(
                obj.id for obj in app.state.fixture_cache["objects"] if obj.name == "rose"
            )
            with app.state.session_factory() as db:
                caster = db.scalar(
                    select(models.Player).where(models.Player.plyrid == "caster")
                )
                assert caster is not None
                caster.level = 25
                caster.spts = 25
                caster.spells = [58]
                caster.nspells = 1
                caster.gpobjs = [rose_id]
                caster.obvals = [0]
                caster.npobjs = 1
                db.commit()

            caster_uri = f"ws://{host}:{port}/ws/rooms/7?token={caster_token}"
            witness_uri = f"ws://{host}:{port}/ws/rooms/12?token={witness_token}"

            async with websockets.connect(caster_uri) as caster_ws:
                await _recv_matching(
                    caster_ws,
                    lambda msg: msg.get("payload", {}).get("event") == "location_update",
                )
                async with websockets.connect(witness_uri) as witness_ws:
                    await _recv_matching(
                        witness_ws,
                        lambda msg: msg.get("payload", {}).get("event")
                        == "location_update",
                    )

                    await caster_ws.send(
                        json.dumps({"type": "command", "command": "cast tiltowait"})
                    )

                    caster_room = await _recv_matching(
                        caster_ws,
                        lambda msg: msg.get("type") == "room_broadcast"
                        and msg.get("payload", {}).get("message_id") == "S59M03",
                        timeout=2.0,
                    )
                    witness_global = await _recv_matching(
                        witness_ws,
                        lambda msg: msg.get("type") == "system_broadcast"
                        and msg.get("payload", {}).get("message_id") == "S59M02",
                        timeout=2.0,
                    )

                    assert caster_room["room"] == 7
                    assert witness_global["payload"]["scope"] == "global"
    finally:
        server.should_exit = True
        await server_task


@pytest.mark.anyio
async def test_websocket_zar_death_refreshes_target_room_and_arrival_witness(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "1000")
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
            hero_session = await client.post(
                "/auth/session", json={"player_id": "hero", "room_id": 302}
            )
            witness_session = await client.post(
                "/auth/session", json={"player_id": "witness", "room_id": 0}
            )
            hero_token = hero_session.json()["session"]["token"]
            witness_token = witness_session.json()["session"]["token"]

            with app.state.session_factory() as db:
                hero = db.scalar(select(models.Player).where(models.Player.plyrid == "hero"))
                witness = db.scalar(
                    select(models.Player).where(models.Player.plyrid == "witness")
                )
                assert hero is not None
                assert witness is not None
                hero.altnam = "Some psuedo dragon"
                hero.attnam = "psuedo dragon"
                hero.nmpdes = 12
                hero.flags = int(
                    constants.PlayerFlag.LOADED
                    | constants.PlayerFlag.FEMALE
                    | constants.PlayerFlag.MARRYD
                    | constants.PlayerFlag.GOTKYG
                    | constants.PlayerFlag.PDRAGN
                )
                hero.level = 10
                hero.hitpts = 8
                hero.spts = 21
                hero.gold = 77
                hero.gpobjs = [0, 1]
                hero.obvals = [10, 20]
                hero.npobjs = 2
                hero.nspells = 2
                hero.spells = [1, 23]
                hero.offspls = 123
                hero.defspls = 456
                hero.othspls = 789
                hero.charms = [1] * constants.NCHARM
                hero.gemidx = 3
                hero.stones = [9, 8, 7, 6]
                hero.macros = 19
                hero.stumpi = 8
                hero.spouse = "beloved"
                hero.gamloc = 302
                hero.pgploc = 302
                witness.level = 25
                witness.gamloc = 0
                witness.pgploc = 0
                db.commit()

            hero_uri = f"ws://{host}:{port}/ws/rooms/302?token={hero_token}"
            witness_uri = f"ws://{host}:{port}/ws/rooms/0?token={witness_token}"

            async with websockets.connect(hero_uri) as hero_ws:
                await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("payload", {}).get("event") == "location_update",
                )
                async with websockets.connect(witness_uri) as witness_ws:
                    await _recv_matching(
                        witness_ws,
                        lambda msg: msg.get("payload", {}).get("event")
                        == "location_update",
                    )

                    app.state.animation_tick_system.state.zar_location = 302
                    app.state.animation_tick_system.state.zar_counter = 0
                    app.state.animation_tick_system.state.zar_attack_index = 0
                    app.state.animation_rng = _FixedAnimationRng(
                        randrange_values=[2, 3, 4, 5],
                        randint_values=[12],
                    )
                    await app.state.animation_tick_callback()

                    await _recv_matching(
                        hero_ws,
                        lambda msg: msg.get("type") == "command_response"
                        and msg.get("payload", {}).get("message_id") == "DIEMSG",
                        timeout=2.0,
                    )
                    description = await _recv_matching(
                        hero_ws,
                        lambda msg: msg.get("type") == "command_response"
                        and msg.get("payload", {}).get("event") == "location_description"
                        and msg.get("payload", {}).get("location") == 0,
                        timeout=2.0,
                    )
                    objects = await _recv_matching(
                        hero_ws,
                        lambda msg: msg.get("type") == "command_response"
                        and msg.get("payload", {}).get("event") == "room_objects"
                        and msg.get("payload", {}).get("location") == 0,
                        timeout=2.0,
                    )
                    arrival = await _recv_matching(
                        witness_ws,
                        lambda msg: msg.get("type") == "room_broadcast"
                        and "appeared in a holy light" in msg.get("payload", {}).get("text", ""),
                        timeout=2.0,
                    )

                    assert description["payload"]["message_id"] == "KRD000"
                    assert objects["payload"]["objects"]
                    assert arrival["payload"]["exclude_player"] == "hero"

            with app.state.session_factory() as db:
                hero = db.scalar(select(models.Player).where(models.Player.plyrid == "hero"))
                assert hero is not None
                assert hero.gamloc == 0
                assert hero.pgploc == 0
                assert hero.altnam == "hero"
                assert hero.attnam == "hero"
                assert hero.nmpdes == constants.level_to_nmpdes(1)
                assert hero.flags == int(
                    constants.PlayerFlag.LOADED | constants.PlayerFlag.FEMALE
                )
                assert hero.level == 1
                assert hero.hitpts == 4
                assert hero.spts == 2
                assert hero.gold == 0
                assert hero.gpobjs == []
                assert hero.obvals == []
                assert hero.npobjs == 0
                assert hero.nspells == 0
                assert hero.spells == []
                assert hero.offspls == 0
                assert hero.defspls == 0
                assert hero.othspls == 0
                assert hero.charms == [0] * constants.NCHARM
                assert hero.gemidx == 0
                assert hero.stones == [2, 3, 4, 5]
                assert hero.macros == 0
                assert hero.stumpi == 0
                assert hero.spouse == ""
    finally:
        server.should_exit = True
        await server_task
