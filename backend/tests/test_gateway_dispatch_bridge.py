import asyncio
import json
import socket

import httpx
import pytest
import uvicorn
import websockets
from sqlalchemy import delete, select

from kyrgame import constants, models
from session_test_helpers import create_seeded_app as create_app, seed_returning_players


@pytest.fixture
def anyio_backend():
    return "asyncio"


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


def _seed_fountain_scroll_probe(
    app,
    *,
    player_id: str,
    target_room: int,
    inventory: list[int],
    room_objects: list[int],
) -> None:
    with app.state.session_factory() as db:
        player = db.scalar(select(models.Player).where(models.Player.plyrid == player_id))
        location = db.get(models.Location, target_room)
        assert player is not None
        assert location is not None
        player.gpobjs = list(inventory)
        player.obvals = [0 for _ in inventory]
        player.npobjs = len(inventory)
        player.flags = int(player.flags) & ~int(constants.PlayerFlag.BLESSD)
        location.objects = list(room_objects)
        location.nlobjs = len(room_objects)
        db.commit()

    app.state.location_index[target_room] = app.state.location_index[
        target_room
    ].model_copy(update={"objects": list(room_objects), "nlobjs": len(room_objects)})
    app.state.room_scripts.room_picker = lambda low, high: target_room


@pytest.mark.anyio
async def test_websocket_entry_location_description_uses_live_room_objects():
    app = create_app()
    host = "127.0.0.1"
    port = _get_open_port()

    config = uvicorn.Config(app, host=host, port=port, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    try:
        with app.state.session_factory() as db:
            location = db.get(models.Location, 0)
            assert location is not None
            location.objects = []
            location.nlobjs = 0
            db.commit()

        app.state.location_index[0] = app.state.location_index[0].model_copy(
            update={"objects": [], "nlobjs": 0}
        )

        async with httpx.AsyncClient(base_url=f"http://{host}:{port}") as client:
            hero_session = await client.post(
                "/auth/session", json={"player_id": "hero", "room_id": 0}
            )
            hero_token = hero_session.json()["session"]["token"]

        uri = f"ws://{host}:{port}/ws/rooms/0?token={hero_token}"
        async with websockets.connect(uri) as hero_ws:
            description = await _recv_matching(
                hero_ws,
                lambda msg: msg.get("payload", {}).get("event")
                == "location_description",
            )

        assert description["payload"]["objects"] == []
    finally:
        server.should_exit = True
        await server_task


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
async def test_websocket_demong_transfer_wraps_departure_and_arrival_with_player_name():
    app = create_app()
    host = "127.0.0.1"
    port = _get_open_port()
    test_player_ids = ("zthero", "ztseer", "ztwatch")

    config = uvicorn.Config(app, host=host, port=port, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    try:
        seed_returning_players(app, test_player_ids)
        with app.state.session_factory() as db:
            soulstone = db.scalar(
                select(models.GameObject).where(models.GameObject.name == "soulstone")
            )
            assert soulstone is not None
            hero = db.scalar(select(models.Player).where(models.Player.plyrid == "zthero"))
            seer = db.scalar(select(models.Player).where(models.Player.plyrid == "ztseer"))
            watcher = db.scalar(select(models.Player).where(models.Player.plyrid == "ztwatch"))
            assert hero is not None
            assert seer is not None
            assert watcher is not None
            hero.flags |= int(constants.PlayerFlag.LOADED)
            hero.gamloc = 218
            hero.pgploc = 218
            hero.altnam = "Hero Alt"
            hero.attnam = "Hero Alt"
            hero.gpobjs = [soulstone.id]
            hero.obvals = [0]
            hero.npobjs = 1
            seer.flags |= int(constants.PlayerFlag.LOADED)
            seer.gamloc = 218
            seer.pgploc = 218
            watcher.flags |= int(constants.PlayerFlag.LOADED)
            watcher.gamloc = 219
            watcher.pgploc = 219
            db.commit()

        async with httpx.AsyncClient(base_url=f"http://{host}:{port}") as client:
            hero_session = await client.post(
                "/auth/session", json={"player_id": "zthero", "room_id": 218}
            )
            hero_token = hero_session.json()["session"]["token"]
            seer_session = await client.post(
                "/auth/session", json={"player_id": "ztseer", "room_id": 218}
            )
            seer_token = seer_session.json()["session"]["token"]
            watcher_session = await client.post(
                "/auth/session", json={"player_id": "ztwatch", "room_id": 219}
            )
            watcher_token = watcher_session.json()["session"]["token"]

        hero_uri = f"ws://{host}:{port}/ws/rooms/218?token={hero_token}"
        seer_uri = f"ws://{host}:{port}/ws/rooms/218?token={seer_token}"
        watcher_uri = f"ws://{host}:{port}/ws/rooms/219?token={watcher_token}"
        async with (
            websockets.connect(hero_uri) as hero_ws,
            websockets.connect(seer_uri) as seer_ws,
            websockets.connect(watcher_uri) as watcher_ws,
        ):
            for ws in (hero_ws, seer_ws, watcher_ws):
                await _recv_matching(
                    ws,
                    lambda msg: msg.get("payload", {}).get("event")
                    == "location_update",
                )

            await hero_ws.send(
                json.dumps({"type": "command", "command": "put soulstone niche"})
            )

            hero_messages = []
            saw_soukey = False
            saw_location_update = False
            while not saw_location_update:
                message = json.loads(await asyncio.wait_for(hero_ws.recv(), timeout=1.0))
                hero_messages.append(message)
                payload = message.get("payload", {})
                if payload.get("message_id") == "SOUKEY":
                    saw_soukey = True
                if (
                    payload.get("event") == "location_update"
                    and payload.get("location") == 219
                ):
                    saw_location_update = True
            assert saw_soukey is True
            departure = await _recv_matching(
                seer_ws,
                lambda msg: msg.get("type") == "room_broadcast"
                and msg.get("payload", {}).get("text")
                == "*** Hero Alt has just vanished through the demon gate!",
            )
            arrival = await _recv_matching(
                watcher_ws,
                lambda msg: msg.get("type") == "room_broadcast"
                and msg.get("payload", {}).get("text")
                == "*** Hero Alt has just appeared in a column of blue flame!",
            )

            assert departure["room"] == 218
            assert arrival["room"] == 219
            assert not any(
                msg.get("type") == "room_broadcast"
                and "through the demon gate" in msg.get("payload", {}).get("text", "")
                for msg in hero_messages
            )
    finally:
        server.should_exit = True
        await server_task


@pytest.mark.anyio
async def test_websocket_temple_marry_uses_live_player_lookup_and_persists_spouse():
    app = create_app()
    host = "127.0.0.1"
    port = _get_open_port()
    test_player_ids = ("zthero", "ztseer", "ztwitness")

    config = uvicorn.Config(app, host=host, port=port, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    try:
        seed_returning_players(app, test_player_ids)
        async with httpx.AsyncClient(base_url=f"http://{host}:{port}") as client:
            hero_session = await client.post(
                "/auth/session", json={"player_id": "zthero", "room_id": 7}
            )
            seer_session = await client.post(
                "/auth/session", json={"player_id": "ztseer", "room_id": 7}
            )
            witness_session = await client.post(
                "/auth/session", json={"player_id": "ztwitness", "room_id": 7}
            )
            hero_token = hero_session.json()["session"]["token"]
            seer_token = seer_session.json()["session"]["token"]
            witness_token = witness_session.json()["session"]["token"]

            with app.state.session_factory() as db:
                hero = db.scalar(select(models.Player).where(models.Player.plyrid == "zthero"))
                seer = db.scalar(select(models.Player).where(models.Player.plyrid == "ztseer"))
                witness = db.scalar(
                    select(models.Player).where(models.Player.plyrid == "ztwitness")
                )
                assert hero is not None
                assert seer is not None
                assert witness is not None
                hero.altnam = "ZtHero"
                hero.attnam = "ZtHero"
                hero.flags = int(constants.PlayerFlag.LOADED)
                hero.spouse = ""
                hero.gamloc = 7
                hero.pgploc = 7
                seer.altnam = "ZtSeer"
                seer.attnam = "ZtSeer"
                seer.flags = int(constants.PlayerFlag.LOADED | constants.PlayerFlag.FEMALE)
                seer.gamloc = 7
                seer.pgploc = 7
                witness.altnam = "ZtWitness"
                witness.attnam = "ZtWitness"
                witness.flags = int(constants.PlayerFlag.LOADED)
                witness.gamloc = 7
                witness.pgploc = 7
                db.commit()

            hero_uri = f"ws://{host}:{port}/ws/rooms/7?token={hero_token}"
            seer_uri = f"ws://{host}:{port}/ws/rooms/7?token={seer_token}"
            witness_uri = f"ws://{host}:{port}/ws/rooms/7?token={witness_token}"

            async with websockets.connect(hero_uri) as hero_ws:
                await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("payload", {}).get("event") == "location_update",
                )
                async with websockets.connect(seer_uri) as seer_ws:
                    await _recv_matching(
                        seer_ws,
                        lambda msg: msg.get("payload", {}).get("event") == "location_update",
                    )
                    async with websockets.connect(witness_uri) as witness_ws:
                        await _recv_matching(
                            witness_ws,
                            lambda msg: msg.get("payload", {}).get("event")
                            == "location_update",
                        )

                        await hero_ws.send(
                            json.dumps({"type": "command", "command": "marry ztseer"})
                        )

                        hero_direct = await _recv_matching(
                            hero_ws,
                            lambda msg: msg.get("type") == "room_broadcast"
                            and msg.get("payload", {}).get("message_id") == "MARRY4",
                        )
                        seer_direct = await _recv_matching(
                            seer_ws,
                            lambda msg: msg.get("type") == "room_broadcast"
                            and msg.get("payload", {}).get("message_id") == "MARRY5",
                        )
                        witness_room = await _recv_matching(
                            witness_ws,
                            lambda msg: msg.get("type") == "room_broadcast"
                            and msg.get("payload", {}).get("message_id") == "MARRY6",
                        )

                        assert hero_direct["payload"]["text"].endswith("ztseer.")
                        assert seer_direct["payload"]["player"] == "ztseer"
                        assert "ZtHero" in seer_direct["payload"]["text"]
                        assert witness_room["payload"]["exclude_players"] == [
                            "zthero",
                            "ztseer",
                        ]

            with app.state.session_factory() as db:
                hero = db.scalar(select(models.Player).where(models.Player.plyrid == "zthero"))
                assert hero is not None
                assert hero.spouse == "ztseer"
                assert hero.flags & int(constants.PlayerFlag.MARRYD)
    finally:
        if hasattr(app.state, "session_factory"):
            with app.state.session_factory() as db:
                players = db.scalars(
                    select(models.Player).where(models.Player.plyrid.in_(test_player_ids))
                ).all()
                player_db_ids = [player.id for player in players]
                if player_db_ids:
                    db.execute(
                        delete(models.PlayerSession).where(
                            models.PlayerSession.player_id.in_(player_db_ids)
                        )
                    )
                    db.execute(delete(models.Player).where(models.Player.id.in_(player_db_ids)))
                    db.commit()
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
        observer_session = await client.post("/auth/session", json={"player_id": "watcher", "room_id": 0})

        uri_room0_hero = f"ws://{host}:{port}/ws/rooms/0?token={hero_session.json()['session']['token']}"
        uri_room0_seer = f"ws://{host}:{port}/ws/rooms/0?token={seer_session.json()['session']['token']}"
        uri_room0_observer = f"ws://{host}:{port}/ws/rooms/0?token={observer_session.json()['session']['token']}"

        async with websockets.connect(uri_room0_hero) as hero_ws:
            await _recv_matching(hero_ws, lambda msg: msg.get("payload", {}).get("event") == "location_update")
            async with websockets.connect(uri_room0_seer) as seer_ws:
                await _recv_matching(seer_ws, lambda msg: msg.get("payload", {}).get("event") == "location_update")
                await _recv_matching(hero_ws, lambda msg: msg.get("payload", {}).get("event") == "player_enter")
                async with websockets.connect(uri_room0_observer) as observer_ws:
                    await _recv_matching(
                        observer_ws,
                        lambda msg: msg.get("payload", {}).get("event") == "location_update",
                    )

                    await hero_ws.send(json.dumps({"type": "command", "command": "give 0 gold to seer"}))
                    observer_gold = await _recv_matching(
                        observer_ws,
                        lambda msg: msg.get("type") == "room_broadcast"
                        and msg.get("payload", {}).get("message_id") == "GIVCRD6",
                    )
                    assert "Hero Alt has just given" in observer_gold["payload"]["text"]
                    assert "0 gold pieces" in observer_gold["payload"]["text"]

                    # Legacy target-first order: give <target> <item> (KYRCMDS.C:503-504)
                    await hero_ws.send(json.dumps({"type": "command", "command": "give seer ruby"}))

                    seer_msg = await _recv_matching(
                        seer_ws,
                        lambda msg: msg.get("type") == "command_response"
                        and msg.get("payload", {}).get("message_id") == "GIVERU10",
                    )
                    assert "Hero Alt" in seer_msg["payload"]["text"]
                    assert "given you a ruby!" in seer_msg["payload"]["text"]

                    observer_item = await _recv_matching(
                        observer_ws,
                        lambda msg: msg.get("type") == "room_broadcast"
                        and msg.get("payload", {}).get("message_id") == "GIVERU11",
                    )
                    assert "Hero Alt has just given" in observer_item["payload"]["text"]
                    assert "a ruby" in observer_item["payload"]["text"]

    server.should_exit = True
    await server_task


@pytest.mark.anyio
async def test_websocket_give_overflow_broadcasts_room_objects_to_all_clients():
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
        watcher_session = await client.post("/auth/session", json={"player_id": "watcher", "room_id": 0})
        room_zero = hero_session.json()["session"]["room_id"]

        with app.state.session_factory() as db:
            hero = db.scalar(select(models.Player).where(models.Player.plyrid == "hero"))
            seer = db.scalar(select(models.Player).where(models.Player.plyrid == "seer"))
            ruby = db.scalar(select(models.GameObject).where(models.GameObject.name == "ruby"))
            location = db.get(models.Location, room_zero)
            assert hero is not None
            assert seer is not None
            assert ruby is not None
            assert location is not None

            filler_ids = [
                obj_id
                for obj_id in db.scalars(
                    select(models.GameObject.id).order_by(models.GameObject.id)
                ).all()
                if obj_id != ruby.id
            ][: constants.MXPOBS]
            assert len(filler_ids) == constants.MXPOBS

            hero.gpobjs = [ruby.id]
            hero.obvals = [0]
            hero.npobjs = 1
            seer.gpobjs = filler_ids
            seer.obvals = [0] * len(filler_ids)
            seer.npobjs = len(filler_ids)
            location.objects = []
            location.nlobjs = 0
            db.commit()

        app.state.location_index[room_zero] = app.state.location_index[room_zero].model_copy(
            update={"objects": [], "nlobjs": 0}
        )

        hero_uri = f"ws://{host}:{port}/ws/rooms/0?token={hero_session.json()['session']['token']}"
        seer_uri = f"ws://{host}:{port}/ws/rooms/0?token={seer_session.json()['session']['token']}"
        watcher_uri = f"ws://{host}:{port}/ws/rooms/0?token={watcher_session.json()['session']['token']}"

        async with websockets.connect(hero_uri) as hero_ws:
            await _recv_matching(hero_ws, lambda msg: msg.get("payload", {}).get("event") == "location_update")
            async with websockets.connect(seer_uri) as seer_ws:
                await _recv_matching(seer_ws, lambda msg: msg.get("payload", {}).get("event") == "location_update")
                await _recv_matching(hero_ws, lambda msg: msg.get("payload", {}).get("event") == "player_enter")
                async with websockets.connect(watcher_uri) as watcher_ws:
                    await _recv_matching(
                        watcher_ws,
                        lambda msg: msg.get("payload", {}).get("event") == "location_update",
                    )

                    await hero_ws.send(json.dumps({"type": "command", "command": "give seer ruby"}))

                    hero_objects = await _recv_matching(
                        hero_ws,
                        lambda msg: msg.get("type") == "room_broadcast"
                        and msg.get("payload", {}).get("event") == "room_objects",
                    )
                    seer_objects = await _recv_matching(
                        seer_ws,
                        lambda msg: msg.get("type") == "room_broadcast"
                        and msg.get("payload", {}).get("event") == "room_objects",
                    )
                    watcher_objects = await _recv_matching(
                        watcher_ws,
                        lambda msg: msg.get("type") == "room_broadcast"
                        and msg.get("payload", {}).get("event") == "room_objects",
                    )

                    payloads = [
                        hero_objects["payload"],
                        seer_objects["payload"],
                        watcher_objects["payload"],
                    ]
                    assert {payload["location"] for payload in payloads} == {room_zero}
                    assert payloads[0]["objects"]
                    assert payloads[0]["objects"] == payloads[1]["objects"] == payloads[2]["objects"]

    server.should_exit = True
    await server_task


@pytest.mark.anyio
async def test_admin_drop_item_broadcasts_live_room_objects_to_connected_player(monkeypatch):
    monkeypatch.setenv(
        "KYRGAME_ADMIN_TOKENS",
        json.dumps({"admin-token": {"roles": ["content_admin"]}}),
    )
    app = create_app()
    host = "127.0.0.1"
    port = _get_open_port()

    config = uvicorn.Config(app, host=host, port=port, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    try:
        with app.state.session_factory() as db:
            location = db.get(models.Location, 7)
            assert location is not None
            location.objects = []
            location.nlobjs = 0
            db.commit()
        app.state.location_index[7] = app.state.location_index[7].model_copy(
            update={"objects": [], "nlobjs": 0}
        )

        async with httpx.AsyncClient(base_url=f"http://{host}:{port}") as client:
            hero_session = await client.post(
                "/auth/session", json={"player_id": "hero", "room_id": 7}
            )
            assert hero_session.status_code == 201
            token = hero_session.json()["session"]["token"]
            hero_uri = f"ws://{host}:{port}/ws/rooms/7?token={token}"

            async with websockets.connect(hero_uri) as hero_ws:
                await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("payload", {}).get("event") == "location_update",
                )
                initial_objects = await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("payload", {}).get("event") == "room_objects",
                )
                assert initial_objects["payload"]["objects"] == []

                response = await client.post(
                    "/admin/rooms/7/objects/drop",
                    headers={"Authorization": "Bearer admin-token"},
                    json={"object_ref": "emerald"},
                )
                assert response.status_code == 200

                announcement = await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("type") == "room_broadcast"
                    and msg.get("payload", {}).get("source") == "admin_drop_item",
                )
                room_objects = await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("type") == "room_broadcast"
                    and msg.get("payload", {}).get("event") == "room_objects",
                )

                assert announcement["payload"]["text"] == (
                    "***\r\nAn emerald suddenly appears near the altar!"
                )
                assert announcement["payload"]["modeled_after_message_id"] == "ASHM01"
                assert room_objects["payload"]["location"] == 7
                assert room_objects["payload"]["objects"] == [{"id": 1, "name": "emerald"}]

                delete_response = await client.delete(
                    "/admin/rooms/7/objects/0?expected_object_id=1",
                    headers={"Authorization": "Bearer admin-token"},
                )
                assert delete_response.status_code == 200

                vanish = await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("type") == "room_broadcast"
                    and msg.get("payload", {}).get("source") == "admin_delete_item",
                )
                emptied_objects = await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("type") == "room_broadcast"
                    and msg.get("payload", {}).get("event") == "room_objects"
                    and msg.get("payload", {}).get("objects") == [],
                )

                assert vanish["payload"]["text"] == (
                    "***\rThe emerald at the village temple vanishes!\r"
                )
                assert vanish["payload"]["modeled_after_spell"] == "mower"
                assert emptied_objects["payload"]["location"] == 7
                assert emptied_objects["payload"]["include_sender"] is True
    finally:
        server.should_exit = True
        await server_task


@pytest.mark.anyio
async def test_websocket_fountain_pinecones_persist_scroll_spawn_and_refresh_target_room(
    monkeypatch,
):
    monkeypatch.setenv("KYRGAME_WS_COMMAND_RATE_LIMIT_MAX_EVENTS", "10")
    app = create_app()
    host = "127.0.0.1"
    port = _get_open_port()
    target_room = 44

    config = uvicorn.Config(app, host=host, port=port, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    try:
        async with httpx.AsyncClient(base_url=f"http://{host}:{port}") as client:
            _seed_fountain_scroll_probe(
                app,
                player_id="hero",
                target_room=target_room,
                inventory=[32, 32, 32],
                room_objects=[],
            )

            hero_session = await client.post(
                "/auth/session", json={"player_id": "hero", "room_id": 38}
            )
            watcher_session = await client.post(
                "/auth/session", json={"player_id": "watcher", "room_id": target_room}
            )
            hero_token = hero_session.json()["session"]["token"]
            watcher_token = watcher_session.json()["session"]["token"]

            hero_uri = f"ws://{host}:{port}/ws/rooms/38?token={hero_token}"
            watcher_uri = (
                f"ws://{host}:{port}/ws/rooms/{target_room}?token={watcher_token}"
            )

            async with websockets.connect(hero_uri) as hero_ws:
                for event_name in ("location_update", "location_description", "room_objects"):
                    await _recv_matching(
                        hero_ws,
                        lambda msg, event_name=event_name: msg.get("payload", {}).get(
                            "event"
                        )
                        == event_name,
                    )
                async with websockets.connect(watcher_uri) as watcher_ws:
                    for event_name in (
                        "location_update",
                        "location_description",
                        "room_objects",
                    ):
                        await _recv_matching(
                            watcher_ws,
                            lambda msg, event_name=event_name: msg.get(
                                "payload", {}
                            ).get("event")
                            == event_name,
                        )

                    await hero_ws.send(
                        json.dumps(
                            {"type": "command", "command": "offer true love to tashanna"}
                        )
                    )
                    await _recv_matching(
                        hero_ws,
                        lambda msg: "The Goddess blesses you."
                        in msg.get("payload", {}).get("text", ""),
                        timeout=2.0,
                    )
                    await _recv_matching(
                        hero_ws,
                        lambda msg: msg.get("type") == "command_response"
                        and msg.get("payload", {}).get("verb") == "offer",
                        timeout=2.0,
                    )

                    command_expectations = (
                        ("drop pinecone in fountain", "MAGF04"),
                        ("throw pinecone in fountain", "MAGF04"),
                        ("toss pinecone in fountain", "MAGF00"),
                    )
                    for command_text, message_id in command_expectations:
                        await hero_ws.send(
                            json.dumps(
                                {
                                    "type": "command",
                                    "command": command_text,
                                }
                            )
                        )
                        await _recv_matching(
                            hero_ws,
                            lambda msg: msg.get("payload", {}).get("message_id")
                            == message_id,
                            timeout=2.0,
                        )

                    room_objects = await _recv_matching(
                        watcher_ws,
                        lambda msg: msg.get("type") == "room_broadcast"
                        and msg.get("payload", {}).get("event") == "room_objects"
                        and msg.get("payload", {}).get("location") == target_room,
                        timeout=2.0,
                    )

                    assert room_objects["payload"]["objects"] == [
                        {"id": 35, "name": "scroll"}
                    ]

            with app.state.session_factory() as db:
                hero = db.scalar(select(models.Player).where(models.Player.plyrid == "hero"))
                location = db.get(models.Location, target_room)
                assert hero is not None
                assert location is not None
                assert hero.gpobjs == []
                assert hero.obvals == []
                assert hero.npobjs == 0
                assert location.objects == [35]
                assert location.nlobjs == 1
    finally:
        server.should_exit = True
        await server_task


@pytest.mark.anyio
async def test_websocket_shove_moves_target_and_fans_out_to_destination_room():
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
        mystic_session = await client.post("/auth/session", json={"player_id": "mystic", "room_id": 1})

        hero_uri = f"ws://{host}:{port}/ws/rooms/0?token={hero_session.json()['session']['token']}"
        seer_uri = f"ws://{host}:{port}/ws/rooms/0?token={seer_session.json()['session']['token']}"
        mystic_uri = f"ws://{host}:{port}/ws/rooms/1?token={mystic_session.json()['session']['token']}"

        async with websockets.connect(hero_uri) as hero_ws:
            await _recv_matching(hero_ws, lambda msg: msg.get("payload", {}).get("event") == "location_update")
            async with websockets.connect(seer_uri) as seer_ws:
                await _recv_matching(seer_ws, lambda msg: msg.get("payload", {}).get("event") == "location_update")
                await _recv_matching(hero_ws, lambda msg: msg.get("payload", {}).get("event") == "player_enter")
                async with websockets.connect(mystic_uri) as mystic_ws:
                    await _recv_matching(
                        mystic_ws,
                        lambda msg: msg.get("payload", {}).get("event") == "location_update",
                    )

                    await hero_ws.send(json.dumps({"type": "command", "command": "shove seer north"}))

                    hero_result = await _recv_matching(
                        hero_ws,
                        lambda msg: msg.get("type") == "command_response"
                        and msg.get("payload", {}).get("message_id") == "SHVUTL1",
                    )
                    assert hero_result["payload"]["message_id"] == "SHVUTL1"

                    seer_direct = await _recv_matching(
                        seer_ws,
                        lambda msg: msg.get("type") == "command_response"
                        and msg.get("payload", {}).get("message_id") == "SHVUTL2",
                    )
                    assert seer_direct["room"] == 1

                    seer_location = await _recv_matching(
                        seer_ws,
                        lambda msg: msg.get("type") == "command_response"
                        and msg.get("payload", {}).get("event") == "location_update"
                        and msg.get("payload", {}).get("location") == 1,
                    )
                    assert seer_location["room"] == 1

                    seer_occupants = await _recv_matching(
                        seer_ws,
                        lambda msg: msg.get("type") == "command_response"
                        and msg.get("payload", {}).get("event") == "room_occupants"
                        and msg.get("payload", {}).get("location") == 1
                        and "mystic" in msg.get("payload", {}).get("occupants", []),
                    )
                    assert seer_occupants["room"] == 1

                    mystic_entrant = await _recv_matching(
                        mystic_ws,
                        lambda msg: msg.get("type") == "room_broadcast"
                        and msg.get("payload", {}).get("event") == "player_enter"
                        and msg.get("payload", {}).get("player") == "seer",
                    )
                    assert mystic_entrant["room"] == 1

                    mystic_arrival = await _recv_matching(
                        mystic_ws,
                        lambda msg: msg.get("type") == "room_broadcast"
                        and "been shoved from the south" in msg.get("payload", {}).get("text", ""),
                    )
                    assert mystic_arrival["room"] == 1

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
        viewer_id = "looker"
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
async def test_websocket_python_room_level_up_emits_direct_audio_cue(monkeypatch):
    monkeypatch.setenv("KYRGAME_WS_COMMAND_RATE_LIMIT_MAX_EVENTS", "10")
    app = create_app()
    host = "127.0.0.1"
    port = _get_open_port()

    config = uvicorn.Config(app, host=host, port=port, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    try:
        seed_returning_players(app, ("zthero",))
        async with httpx.AsyncClient(base_url=f"http://{host}:{port}") as client:
            session = await client.post(
                "/auth/session", json={"player_id": "zthero", "room_id": 0}
            )
            token = session.json()["session"]["token"]

        with app.state.session_factory() as db:
            hero = db.scalar(select(models.Player).where(models.Player.plyrid == "zthero"))
            assert hero is not None
            hero.level = 1
            hero.nmpdes = constants.level_to_nmpdes(1)
            hero.gamloc = 0
            hero.pgploc = 0
            db.commit()

        uri = f"ws://{host}:{port}/ws/rooms/0?token={token}"
        async with websockets.connect(uri) as ws:
            await _recv_matching(
                ws,
                lambda msg: msg.get("payload", {}).get("event") == "location_update",
            )

            await ws.send(json.dumps({"type": "command", "command": "kneel"}))

            cue = await _recv_matching(
                ws,
                lambda msg: msg.get("type") == "command_response"
                and msg.get("payload", {}).get("event") == "player_level_up",
                timeout=2.0,
            )
            assert cue["payload"] == {
                "scope": "player",
                "event": "player_level_up",
                "type": "player_level_up",
                "player": "zthero",
                "previous_level": 1,
                "level": 2,
                "location": 0,
            }
    finally:
        server.should_exit = True
        await server_task


@pytest.mark.anyio
async def test_websocket_yaml_room_level_up_emits_direct_audio_cue(monkeypatch):
    monkeypatch.setenv("KYRGAME_WS_COMMAND_RATE_LIMIT_MAX_EVENTS", "10")
    app = create_app()
    host = "127.0.0.1"
    port = _get_open_port()

    config = uvicorn.Config(app, host=host, port=port, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    try:
        seed_returning_players(app, ("ztfear",))
        async with httpx.AsyncClient(base_url=f"http://{host}:{port}") as client:
            session = await client.post(
                "/auth/session", json={"player_id": "ztfear", "room_id": 16}
            )
            token = session.json()["session"]["token"]

        with app.state.session_factory() as db:
            hero = db.scalar(select(models.Player).where(models.Player.plyrid == "ztfear"))
            assert hero is not None
            hero.level = 4
            hero.nmpdes = constants.level_to_nmpdes(4)
            hero.gamloc = 16
            hero.pgploc = 16
            db.commit()

        uri = f"ws://{host}:{port}/ws/rooms/16?token={token}"
        async with websockets.connect(uri) as ws:
            await _recv_matching(
                ws,
                lambda msg: msg.get("payload", {}).get("event") == "location_update",
            )

            await ws.send(json.dumps({"type": "command", "command": "fear no evil"}))

            cue = await _recv_matching(
                ws,
                lambda msg: msg.get("type") == "command_response"
                and msg.get("payload", {}).get("event") == "player_level_up",
                timeout=2.0,
            )
            assert cue["payload"] == {
                "scope": "player",
                "event": "player_level_up",
                "type": "player_level_up",
                "player": "ztfear",
                "previous_level": 4,
                "level": 5,
                "location": 16,
            }
    finally:
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
async def test_body_chamber_jump_commands_match_legacy_fallback_and_leveling(
    monkeypatch,
):
    monkeypatch.setenv("KYRGAME_WS_COMMAND_RATE_LIMIT_MAX_EVENTS", "10")
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
            session = await client.post(
                "/auth/session", json={"player_id": "hero", "room_id": 282}
            )
            token = session.json()["session"]["token"]

        with app.state.session_factory() as db:
            hero = db.scalar(select(models.Player).where(models.Player.plyrid == "hero"))
            assert hero is not None
            hero.flags |= int(constants.PlayerFlag.LOADED)
            hero.level = 12
            hero.nmpdes = constants.level_to_nmpdes(12)
            hero.hitpts = 48
            hero.spts = 50
            hero.gamloc = 282
            hero.pgploc = 282
            hero.gpobjs = []
            hero.obvals = []
            hero.npobjs = 0
            hero.charms = [0 for _ in range(constants.NCHARM)]
            hero.spells = [40]
            hero.nspells = 1
            db.commit()

        uri = f"ws://{host}:{port}/ws/rooms/282?token={token}"
        async with websockets.connect(uri) as ws:
            await _recv_matching(
                ws,
                lambda msg: msg.get("payload", {}).get("event") == "location_update",
            )

            await ws.send(json.dumps({"type": "command", "command": "cast makemyd"}))
            await _recv_matching(
                ws,
                lambda msg: msg.get("payload", {}).get("message_id") == "S41M00",
            )

            await ws.send(json.dumps({"type": "command", "command": "jump"}))
            bare_jump = await _recv_matching(
                ws,
                lambda msg: msg.get("payload", {}).get("message_id") == "KYRA5",
            )
            assert bare_jump["payload"]["text"] == "...jump what?"

            await ws.send(json.dumps({"type": "command", "command": "jump into chasm"}))
            into_chasm = await _recv_matching(
                ws,
                lambda msg: msg.get("payload", {}).get("message_id") == "KYRA7",
            )
            assert into_chasm["payload"]["text"] == (
                "...How do you plan to jump into chasm?"
            )

            await ws.send(json.dumps({"type": "command", "command": "jump over chasm"}))
            over_chasm = await _recv_matching(
                ws,
                lambda msg: msg.get("payload", {}).get("message_id") == "KYRA7",
            )
            assert over_chasm["payload"]["text"] == (
                "...How do you plan to jump over chasm?"
            )

            with app.state.session_factory() as db:
                hero = db.scalar(select(models.Player).where(models.Player.plyrid == "hero"))
                assert hero is not None
                assert hero.level == 12
                assert 14 not in hero.gpobjs

            await ws.send(
                json.dumps({"type": "command", "command": "jump across the chasm"})
            )
            await _recv_matching(
                ws,
                lambda msg: msg.get("payload", {}).get("message_id") == "BODM01",
            )

        with app.state.session_factory() as db:
            hero = db.scalar(select(models.Player).where(models.Player.plyrid == "hero"))
            assert hero is not None
            assert hero.level == 13
            assert 23 in hero.gpobjs
            assert 14 not in hero.gpobjs
    finally:
        server.should_exit = True
        await server_task


@pytest.mark.anyio
async def test_body_chamber_unprotected_jump_uses_damage_reset_and_persists(
    monkeypatch,
):
    monkeypatch.setenv("KYRGAME_WS_COMMAND_RATE_LIMIT_MAX_EVENTS", "10")
    app = create_app()
    host = "127.0.0.1"
    port = _get_open_port()

    config = uvicorn.Config(app, host=host, port=port, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    try:
        seed_returning_players(app, ("zthero", "ztseer"))
        async with httpx.AsyncClient(base_url=f"http://{host}:{port}") as client:
            hero_session = await client.post(
                "/auth/session", json={"player_id": "zthero", "room_id": 282}
            )
            observer_session = await client.post(
                "/auth/session", json={"player_id": "ztseer", "room_id": 282}
            )
            hero_token = hero_session.json()["session"]["token"]
            observer_token = observer_session.json()["session"]["token"]

        with app.state.session_factory() as db:
            hero = db.scalar(select(models.Player).where(models.Player.plyrid == "zthero"))
            observer = db.scalar(
                select(models.Player).where(models.Player.plyrid == "ztseer")
            )
            assert hero is not None
            assert observer is not None
            for record in (hero, observer):
                record.flags |= int(constants.PlayerFlag.LOADED)
                record.gamloc = 282
                record.pgploc = 282
            hero.level = 12
            hero.nmpdes = constants.level_to_nmpdes(12)
            hero.hitpts = 48
            hero.charms = [0 for _ in range(constants.NCHARM)]
            hero.gpobjs = []
            hero.obvals = []
            hero.npobjs = 0
            db.commit()

        hero_uri = f"ws://{host}:{port}/ws/rooms/282?token={hero_token}"
        observer_uri = f"ws://{host}:{port}/ws/rooms/282?token={observer_token}"
        async with (
            websockets.connect(hero_uri) as hero_ws,
            websockets.connect(observer_uri) as observer_ws,
        ):
            for ws in (hero_ws, observer_ws):
                await _recv_matching(
                    ws,
                    lambda msg: msg.get("payload", {}).get("event")
                        == "location_update",
                )

            shadow_hero = models.PlayerModel(
                **app.state.active_player_sessions[hero_token].model_dump()
            )
            shadow_hero.gamloc = 282
            shadow_hero.pgploc = 282
            shadow_hero.level = 12
            app.state.active_player_sessions["shadow-zthero-token"] = shadow_hero
            await app.state.presence.set_location(
                "zthero", 282, "shadow-zthero-token"
            )

            await hero_ws.send(json.dumps({"type": "command", "command": "jump chasm"}))

            await _recv_matching(
                hero_ws,
                lambda msg: msg.get("payload", {}).get("message_id") == "BODM04",
            )
            await _recv_matching(
                hero_ws,
                lambda msg: msg.get("payload", {}).get("message_id") == "DIEMSG",
            )
            reset_location = await _recv_matching(
                hero_ws,
                lambda msg: msg.get("payload", {}).get("event") == "location_update"
                and msg.get("payload", {}).get("location") == 0,
            )
            assert reset_location["payload"].get("death_reset") is True
            reset_description = await _recv_matching(
                hero_ws,
                lambda msg: msg.get("payload", {}).get("event")
                == "location_description"
                and msg.get("payload", {}).get("location") == 0,
            )
            assert reset_description["payload"].get("death_reset") is True
            reset_objects = await _recv_matching(
                hero_ws,
                lambda msg: msg.get("payload", {}).get("event") == "room_objects"
                and msg.get("payload", {}).get("location") == 0,
            )
            assert reset_objects["payload"].get("death_reset") is True
            assert shadow_hero.level == 1
            assert shadow_hero.gamloc == 0
            assert shadow_hero.hitpts == 4

            await _recv_matching(
                observer_ws,
                lambda msg: msg.get("payload", {}).get("message_id") == "BODM05",
            )
            await _recv_matching(
                observer_ws,
                lambda msg: msg.get("payload", {}).get("message_id") == "KILLED",
            )

        with app.state.session_factory() as db:
            hero = db.scalar(select(models.Player).where(models.Player.plyrid == "zthero"))
            session_record = db.scalar(
                select(models.PlayerSession).where(
                    models.PlayerSession.session_token == hero_token
                )
            )
            assert hero is not None
            assert session_record is not None
            assert hero.level == 1
            assert hero.hitpts == 4
            assert hero.gamloc == 0
            assert session_record.room_id == 0
    finally:
        server.should_exit = True
        await server_task


@pytest.mark.anyio
async def test_thicket_walk_uses_damage_reset_and_persists(monkeypatch):
    monkeypatch.setenv("KYRGAME_WS_COMMAND_RATE_LIMIT_MAX_EVENTS", "10")
    app = create_app()
    host = "127.0.0.1"
    port = _get_open_port()

    config = uvicorn.Config(app, host=host, port=port, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    try:
        seed_returning_players(app, ("zthero", "ztseer", "ztwatcher"))
        async with httpx.AsyncClient(base_url=f"http://{host}:{port}") as client:
            hero_session = await client.post(
                "/auth/session", json={"player_id": "zthero", "room_id": 19}
            )
            observer_session = await client.post(
                "/auth/session", json={"player_id": "ztseer", "room_id": 19}
            )
            remote_session = await client.post(
                "/auth/session", json={"player_id": "ztwatcher", "room_id": 12}
            )
            hero_token = hero_session.json()["session"]["token"]
            observer_token = observer_session.json()["session"]["token"]
            remote_token = remote_session.json()["session"]["token"]

        with app.state.session_factory() as db:
            hero = db.scalar(
                select(models.Player).where(models.Player.plyrid == "zthero")
            )
            observer = db.scalar(
                select(models.Player).where(models.Player.plyrid == "ztseer")
            )
            remote = db.scalar(
                select(models.Player).where(models.Player.plyrid == "ztwatcher")
            )
            assert hero is not None
            assert observer is not None
            assert remote is not None
            for record in (hero, observer):
                record.flags |= int(constants.PlayerFlag.LOADED)
                record.gamloc = 19
                record.pgploc = 19
            remote.flags |= int(constants.PlayerFlag.LOADED)
            remote.gamloc = 12
            remote.pgploc = 12
            hero.hitpts = 10
            hero.level = 3
            hero.nmpdes = constants.level_to_nmpdes(3)
            db.commit()

        hero_uri = f"ws://{host}:{port}/ws/rooms/19?token={hero_token}"
        observer_uri = f"ws://{host}:{port}/ws/rooms/19?token={observer_token}"
        remote_uri = f"ws://{host}:{port}/ws/rooms/12?token={remote_token}"
        async with (
            websockets.connect(hero_uri) as hero_ws,
            websockets.connect(observer_uri) as observer_ws,
            websockets.connect(remote_uri) as remote_ws,
        ):
            for ws in (hero_ws, observer_ws, remote_ws):
                await _recv_matching(
                    ws,
                    lambda msg: msg.get("payload", {}).get("event")
                    == "location_update",
                )

            shadow_hero = models.PlayerModel(
                **app.state.active_player_sessions[hero_token].model_dump()
            )
            shadow_hero.gamloc = 19
            shadow_hero.pgploc = 19
            shadow_hero.hitpts = 10
            shadow_hero.level = 3
            app.state.active_player_sessions["shadow-zthero-token"] = shadow_hero
            await app.state.presence.set_location(
                "zthero", 19, "shadow-zthero-token"
            )

            await hero_ws.send(json.dumps({"type": "command", "command": "walk thicket"}))

            await _recv_matching(
                hero_ws,
                lambda msg: "...Ouch" in msg.get("payload", {}).get("text", ""),
            )
            await _recv_matching(
                hero_ws,
                lambda msg: msg.get("payload", {}).get("message_id") == "DIEMSG",
            )
            reset_location = await _recv_matching(
                hero_ws,
                lambda msg: msg.get("payload", {}).get("event") == "location_update"
                and msg.get("payload", {}).get("location") == 0,
            )
            assert reset_location["payload"].get("death_reset") is True
            reset_description = await _recv_matching(
                hero_ws,
                lambda msg: msg.get("payload", {}).get("event")
                == "location_description"
                and msg.get("payload", {}).get("location") == 0,
            )
            assert reset_description["payload"].get("death_reset") is True
            reset_objects = await _recv_matching(
                hero_ws,
                lambda msg: msg.get("payload", {}).get("event") == "room_objects"
                and msg.get("payload", {}).get("location") == 0,
            )
            assert reset_objects["payload"].get("death_reset") is True

            await _recv_matching(
                observer_ws,
                lambda msg: "burning in the flaming thicket"
                in msg.get("payload", {}).get("text", ""),
            )
            await _recv_matching(
                observer_ws,
                lambda msg: msg.get("payload", {}).get("message_id") == "KILLED",
            )
            await remote_ws.send(json.dumps({"type": "command", "command": "look"}))
            while True:
                remote_msg = json.loads(
                    await asyncio.wait_for(remote_ws.recv(), timeout=1.0)
                )
                assert remote_msg.get("payload", {}).get("message_id") != "KILLED"
                if (
                    remote_msg.get("type") == "command_response"
                    and remote_msg.get("payload", {}).get("verb") == "look"
                ):
                    break

            assert shadow_hero.level == 1
            assert shadow_hero.gamloc == 0
            assert shadow_hero.hitpts == 4

        with app.state.session_factory() as db:
            hero = db.scalar(
                select(models.Player).where(models.Player.plyrid == "zthero")
            )
            session_record = db.scalar(
                select(models.PlayerSession).where(
                    models.PlayerSession.session_token == hero_token
                )
            )
            assert hero is not None
            assert session_record is not None
            assert hero.level == 1
            assert hero.hitpts == 4
            assert hero.gamloc == 0
            assert session_record.room_id == 0
    finally:
        server.should_exit = True
        await server_task


@pytest.mark.anyio
async def test_room_script_self_target_event_reaches_active_player_session():
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

        first_uri = f"ws://{host}:{port}/ws/rooms/{room_id}?token={first_token}"

        async with websockets.connect(first_uri) as first_ws:
            await _recv_matching(
                first_ws,
                lambda msg: msg.get("payload", {}).get("event") == "location_update",
            )

            await first_ws.send(json.dumps({"type": "command", "command": "imagine dagger"}))

            first_effect = await _recv_matching(
                first_ws,
                lambda msg: msg.get("type") == "room_broadcast"
                and msg.get("payload", {}).get("message_id") == "DAGM00",
            )

            assert first_effect["payload"]["player"] == "hero"

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

        first_uri = f"ws://{host}:{port}/ws/rooms/{room_id}?token={first_token}"
        meta = {"silent": True, "status_card": "room_script"}

        async with websockets.connect(first_uri) as first_ws:
            await _recv_matching(
                first_ws,
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

            assert first_effect["payload"]["player"] == "hero"
            await _assert_no_matching(
                first_ws,
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
async def test_websocket_spell_death_refreshes_target_room_and_arrival_witness(monkeypatch):
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
                "/auth/session", json={"player_id": "target", "room_id": 7}
            )
            witness_session = await client.post(
                "/auth/session", json={"player_id": "witness", "room_id": 0}
            )
            hero_token = hero_session.json()["session"]["token"]
            target_token = target_session.json()["session"]["token"]
            witness_token = witness_session.json()["session"]["token"]

            with app.state.session_factory() as db:
                hero = db.scalar(select(models.Player).where(models.Player.plyrid == "hero"))
                target = db.scalar(select(models.Player).where(models.Player.plyrid == "target"))
                witness = db.scalar(
                    select(models.Player).where(models.Player.plyrid == "witness")
                )
                assert hero is not None
                assert target is not None
                assert witness is not None
                hero.level = 25
                hero.spts = 25
                hero.spells = [47]
                hero.nspells = 1
                hero.gamloc = 7
                hero.pgploc = 7
                target.altnam = "Target Mask"
                target.attnam = "target"
                target.flags = int(
                    constants.PlayerFlag.LOADED
                    | constants.PlayerFlag.FEMALE
                    | constants.PlayerFlag.MARRYD
                )
                target.level = 5
                target.hitpts = 2
                target.spts = 20
                target.gold = 70
                target.gpobjs = [0, 1]
                target.obvals = [10, 20]
                target.npobjs = 2
                target.spells = [1, 23]
                target.nspells = 2
                target.charms = [
                    1 if index != constants.OBJPRO else 0
                    for index in range(constants.NCHARM)
                ]
                target.gamloc = 7
                target.pgploc = 7
                witness.level = 25
                witness.gamloc = 0
                witness.pgploc = 0
                db.commit()

            hero_uri = f"ws://{host}:{port}/ws/rooms/7?token={hero_token}"
            target_uri = f"ws://{host}:{port}/ws/rooms/7?token={target_token}"
            witness_uri = f"ws://{host}:{port}/ws/rooms/0?token={witness_token}"

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
                    shadow_target = models.PlayerModel(
                        **app.state.active_player_sessions[target_token].model_dump()
                    )
                    app.state.active_player_sessions["shadow-target-token"] = shadow_target
                    async with websockets.connect(witness_uri) as witness_ws:
                        await _recv_matching(
                            witness_ws,
                            lambda msg: msg.get("payload", {}).get("event")
                            == "location_update",
                        )

                        await hero_ws.send(
                            json.dumps({"type": "command", "command": "cast pocus target"})
                        )

                        await _recv_matching(
                            target_ws,
                            lambda msg: msg.get("type") == "command_response"
                            and msg.get("payload", {}).get("message_id") == "DIEMSG",
                            timeout=2.0,
                        )
                        description = await _recv_matching(
                            target_ws,
                            lambda msg: msg.get("type") == "command_response"
                            and msg.get("payload", {}).get("event")
                            == "location_description"
                            and msg.get("payload", {}).get("location") == 0,
                            timeout=2.0,
                        )
                        objects = await _recv_matching(
                            target_ws,
                            lambda msg: msg.get("type") == "command_response"
                            and msg.get("payload", {}).get("event") == "room_objects"
                            and msg.get("payload", {}).get("location") == 0,
                            timeout=2.0,
                        )
                        killed = await _recv_matching(
                            hero_ws,
                            lambda msg: msg.get("type") == "room_broadcast"
                            and msg.get("payload", {}).get("message_id") == "KILLED",
                            timeout=2.0,
                        )
                        arrival = await _recv_matching(
                            witness_ws,
                            lambda msg: msg.get("type") == "room_broadcast"
                            and "appeared in a holy light"
                            in msg.get("payload", {}).get("text", ""),
                            timeout=2.0,
                        )

                        assert description["payload"]["message_id"] == "KRD000"
                        assert objects["payload"]["objects"]
                        assert killed["room"] == 7
                        assert killed["payload"]["exclude_player"] == "target"
                        assert arrival["payload"]["exclude_player"] == "target"

                        with app.state.session_factory() as db:
                            target_session_record = db.scalar(
                                select(models.PlayerSession).where(
                                    models.PlayerSession.session_token == target_token
                                )
                            )
                            assert target_session_record is not None
                            assert target_session_record.room_id == 0

                        assert shadow_target.gamloc == 0
                        assert shadow_target.pgploc == 0
                        assert shadow_target.level == 1
                        assert shadow_target.hitpts == 4
                        assert shadow_target.spts == 2
                        assert shadow_target.gold == 0
                        assert shadow_target.spells == []

            with app.state.session_factory() as db:
                target = db.scalar(select(models.Player).where(models.Player.plyrid == "target"))
                assert target is not None
                assert target.gamloc == 0
                assert target.pgploc == 0
                assert target.altnam == "target"
                assert target.attnam == "target"
                assert target.flags == int(
                    constants.PlayerFlag.LOADED | constants.PlayerFlag.FEMALE
                )
                assert target.level == 1
                assert target.hitpts == 4
                assert target.spts == 2
                assert target.gold == 0
                assert target.gpobjs == []
                assert target.obvals == []
                assert target.npobjs == 0
                assert target.nspells == 0
                assert target.spells == []
                assert target.charms == [0] * constants.NCHARM
    finally:
        server.should_exit = True
        await server_task


@pytest.mark.anyio
async def test_websocket_zelastone_self_death_refreshes_registered_player_models(monkeypatch):
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
            caster_token = caster_session.json()["session"]["token"]

            with app.state.session_factory() as db:
                caster = db.scalar(select(models.Player).where(models.Player.plyrid == "caster"))
                assert caster is not None
                caster.level = 25
                caster.spts = 25
                caster.spells = [66]
                caster.nspells = 1
                caster.hitpts = 1
                caster.gold = 80
                caster.gamloc = 7
                caster.pgploc = 7
                db.commit()

            caster_uri = f"ws://{host}:{port}/ws/rooms/7?token={caster_token}"
            async with websockets.connect(caster_uri) as caster_ws:
                await _recv_matching(
                    caster_ws,
                    lambda msg: msg.get("payload", {}).get("event") == "location_update",
                )
                shadow_caster = models.PlayerModel(
                    **app.state.active_player_sessions[caster_token].model_dump()
                )
                app.state.active_player_sessions["shadow-caster-token"] = shadow_caster

                await caster_ws.send(
                    json.dumps({"type": "command", "command": "cast zelastone nobody"})
                )

                await _recv_matching(
                    caster_ws,
                    lambda msg: msg.get("type") == "command_response"
                    and msg.get("payload", {}).get("message_id") == "DIEMSG",
                    timeout=2.0,
                )
                await _recv_matching(
                    caster_ws,
                    lambda msg: msg.get("type") == "command_response"
                    and msg.get("payload", {}).get("event") == "location_description"
                    and msg.get("payload", {}).get("location") == 0,
                    timeout=2.0,
                )

                assert shadow_caster.gamloc == 0
                assert shadow_caster.pgploc == 0
                assert shadow_caster.level == 1
                assert shadow_caster.hitpts == 4
                assert shadow_caster.spts == 2
                assert shadow_caster.gold == 0
                assert shadow_caster.spells == []
    finally:
        server.should_exit = True
        await server_task


@pytest.mark.anyio
async def test_forced_move_syncs_room_script_dispatch_context(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "1000")
    app = create_app()
    host = "127.0.0.1"
    port = _get_open_port()
    handled_rooms: list[int] = []

    async def _record_handle_command(player_id, room_id, *args, **kwargs):
        handled_rooms.append(room_id)
        return await original_handle_command(player_id, room_id, *args, **kwargs)

    config = uvicorn.Config(app, host=host, port=port, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    original_handle_command = app.state.room_scripts.handle_command
    app.state.room_scripts.handle_command = _record_handle_command

    try:
        async with httpx.AsyncClient(base_url=f"http://{host}:{port}") as client:
            hero_session = await client.post("/auth/session", json={"player_id": "hero", "room_id": 302})
            hero_token = hero_session.json()["session"]["token"]

            hero_uri = f"ws://{host}:{port}/ws/rooms/302?token={hero_token}"

            async with websockets.connect(hero_uri) as hero_ws:
                await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("payload", {}).get("event") == "location_update",
                )

                app.state.animation_tick_system.state.zar_location = 302
                app.state.animation_tick_system.state.zar_counter = 0
                app.state.animation_tick_system.state.zar_attack_index = 0
                app.state.animation_rng = _FixedAnimationRng(
                    randrange_values=[2, 3, 4, 5, 12],
                    randint_values=[12],
                )
                await app.state.animation_tick_callback()

                await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("type") == "command_response"
                    and msg.get("payload", {}).get("message_id") == "DIEMSG",
                    timeout=2.0,
                )
                await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("type") == "command_response"
                    and msg.get("payload", {}).get("event") == "location_description"
                    and msg.get("payload", {}).get("location") == 0,
                    timeout=2.0,
                )

                await hero_ws.send(json.dumps({"type": "command", "command": "look"}))

                await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("type") == "command_response"
                    and msg.get("payload", {}).get("verb") == "look",
                    timeout=2.0,
                )

                assert handled_rooms[0] == 0
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
async def test_websocket_mower_vanish_messages_reach_room_occupants(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "1000")
    app = create_app()
    host = "127.0.0.1"
    port = _get_open_port()
    test_player_ids = ("ztmower", "ztwitness")
    room_objects = [0, 1, 45]
    vanish_texts = {
        "***\rThe ruby at the village temple vanishes!\r",
        "***\rThe emerald at the village temple vanishes!\r",
    }

    config = uvicorn.Config(app, host=host, port=port, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    try:
        seed_returning_players(app, test_player_ids)
        async with httpx.AsyncClient(base_url=f"http://{host}:{port}") as client:
            caster_session = await client.post(
                "/auth/session", json={"player_id": "ztmower", "room_id": 7}
            )
            witness_session = await client.post(
                "/auth/session", json={"player_id": "ztwitness", "room_id": 7}
            )
            caster_token = caster_session.json()["session"]["token"]
            witness_token = witness_session.json()["session"]["token"]

        with app.state.session_factory() as db:
            caster = db.scalar(select(models.Player).where(models.Player.plyrid == "ztmower"))
            witness = db.scalar(
                select(models.Player).where(models.Player.plyrid == "ztwitness")
            )
            location = db.get(models.Location, 7)
            assert caster is not None
            assert witness is not None
            assert location is not None
            caster.flags |= int(constants.PlayerFlag.LOADED)
            caster.level = 25
            caster.spts = 25
            caster.gamloc = 7
            caster.pgploc = 7
            caster.spells = [41]
            caster.nspells = 1
            witness.flags |= int(constants.PlayerFlag.LOADED)
            witness.gamloc = 7
            witness.pgploc = 7
            location.objects = list(room_objects)
            location.nlobjs = len(room_objects)
            db.commit()

        app.state.location_index[7] = app.state.location_index[7].model_copy(
            update={"objects": list(room_objects), "nlobjs": len(room_objects)}
        )

        caster_uri = f"ws://{host}:{port}/ws/rooms/7?token={caster_token}"
        witness_uri = f"ws://{host}:{port}/ws/rooms/7?token={witness_token}"

        async with (
            websockets.connect(caster_uri) as caster_ws,
            websockets.connect(witness_uri) as witness_ws,
        ):
            await _recv_matching(
                caster_ws,
                lambda msg: msg.get("payload", {}).get("event") == "location_update",
            )
            await _recv_matching(
                witness_ws,
                lambda msg: msg.get("payload", {}).get("event") == "location_update",
            )

            await caster_ws.send(json.dumps({"type": "command", "command": "cast mower"}))

            caster_cast = await _recv_matching(
                caster_ws,
                lambda msg: msg.get("type") == "command_response"
                and msg.get("payload", {}).get("message_id") == "YOUCASTSPELL",
                timeout=2.0,
            )
            witness_vanishes = []
            while len(witness_vanishes) < len(vanish_texts):
                witness_vanishes.append(
                    await _recv_matching(
                        witness_ws,
                        lambda msg: msg.get("type") == "room_broadcast"
                        and msg.get("payload", {}).get("text") in vanish_texts,
                        timeout=2.0,
                    )
                )
            caster_vanishes = []
            while len(caster_vanishes) < len(vanish_texts):
                caster_vanishes.append(
                    await _recv_matching(
                        caster_ws,
                        lambda msg: msg.get("type") == "room_broadcast"
                        and msg.get("payload", {}).get("text") in vanish_texts,
                        timeout=2.0,
                    )
                )
            caster_room_objects = await _recv_matching(
                caster_ws,
                lambda msg: msg.get("type") == "command_response"
                and msg.get("payload", {}).get("event") == "room_objects"
                and msg.get("payload", {}).get("location") == 7,
                timeout=2.0,
            )

            assert caster_cast["payload"]["scope"] == "player"
            assert {msg["payload"]["text"] for msg in witness_vanishes} == vanish_texts
            assert {msg["payload"]["message_id"] for msg in witness_vanishes} == {None}
            assert {msg["payload"]["scope"] for msg in witness_vanishes} == {"room"}
            assert all("exclude_player" not in msg["payload"] for msg in witness_vanishes)
            assert {msg["payload"]["include_sender"] for msg in witness_vanishes} == {True}
            assert {msg["payload"]["text"] for msg in caster_vanishes} == vanish_texts
            assert {msg["payload"]["message_id"] for msg in caster_vanishes} == {None}
            assert {msg["payload"]["scope"] for msg in caster_vanishes} == {"room"}
            assert all("exclude_player" not in msg["payload"] for msg in caster_vanishes)
            assert {msg["payload"]["include_sender"] for msg in caster_vanishes} == {True}
            assert [obj["id"] for obj in caster_room_objects["payload"]["objects"]] == [45]

        with app.state.session_factory() as db:
            location = db.get(models.Location, 7)
            assert location is not None
            assert location.objects == [45]
    finally:
        if hasattr(app.state, "session_factory"):
            with app.state.session_factory() as db:
                players = db.scalars(
                    select(models.Player).where(models.Player.plyrid.in_(test_player_ids))
                ).all()
                player_db_ids = [player.id for player in players]
                if player_db_ids:
                    db.execute(
                        delete(models.PlayerSession).where(
                            models.PlayerSession.player_id.in_(player_db_ids)
                        )
                    )
                    db.execute(delete(models.Player).where(models.Player.id.in_(player_db_ids)))
                    db.commit()
        server.should_exit = True
        await server_task


@pytest.mark.anyio
async def test_websocket_macros_fatigue_blocks_command_until_spell_tick_reset(monkeypatch):
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
                "/auth/session", json={"player_id": "hero", "room_id": 0}
            )
            hero_token = hero_session.json()["session"]["token"]

            with app.state.session_factory() as db:
                hero = db.scalar(select(models.Player).where(models.Player.plyrid == "hero"))
                assert hero is not None
                hero.macros = 18
                hero.flags |= int(constants.PlayerFlag.LOADED)
                db.commit()

            uri = f"ws://{host}:{port}/ws/rooms/0?token={hero_token}"
            async with websockets.connect(uri) as hero_ws:
                await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("payload", {}).get("event") == "location_update",
                )
                await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("payload", {}).get("event")
                    == "location_description",
                )
                await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("payload", {}).get("event") == "room_objects",
                )

                await hero_ws.send(json.dumps({"type": "command", "command": "look"}))
                await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("type") == "command_response"
                    and msg.get("payload", {}).get("verb") == "look",
                )
                await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("type") == "command_response"
                    and msg.get("payload", {}).get("event") == "location_description",
                )

                with app.state.session_factory() as db:
                    hero = db.scalar(
                        select(models.Player).where(models.Player.plyrid == "hero")
                    )
                    assert hero is not None
                    assert hero.macros == 19

                await hero_ws.send(json.dumps({"type": "command", "command": "look"}))
                tired = await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("type") == "command_response"
                    and msg.get("payload", {}).get("message_id") == "TIRED",
                )

                assert tired["payload"]["scope"] == "player"
                await _assert_no_matching(
                    hero_ws,
                    lambda msg: msg.get("payload", {}).get("event")
                    == "location_description",
                    timeout=0.2,
                )
                with app.state.session_factory() as db:
                    hero = db.scalar(
                        select(models.Player).where(models.Player.plyrid == "hero")
                    )
                    assert hero is not None
                    assert hero.macros == 19

                app.state.spell_tick_system.tick()
                await asyncio.sleep(0.6)

                await hero_ws.send(json.dumps({"type": "command", "command": "look"}))
                await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("type") == "command_response"
                    and msg.get("payload", {}).get("verb") == "look",
                )
                await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("type") == "command_response"
                    and msg.get("payload", {}).get("event") == "location_description",
                )
                with app.state.session_factory() as db:
                    hero = db.scalar(
                        select(models.Player).where(models.Player.plyrid == "hero")
                    )
                    assert hero is not None
                    assert hero.macros == 1
    finally:
        server.should_exit = True
        await server_task


@pytest.mark.anyio
async def test_websocket_fatigue_gate_blocks_room_script_before_mutation(monkeypatch):
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
                "/auth/session", json={"player_id": "hero", "room_id": 34}
            )
            hero_token = hero_session.json()["session"]["token"]

            with app.state.session_factory() as db:
                hero = db.scalar(select(models.Player).where(models.Player.plyrid == "hero"))
                assert hero is not None
                hero.macros = 19
                hero.flags |= int(constants.PlayerFlag.LOADED)
                db.commit()

            script_calls = []

            async def fake_handle_command(*args, **kwargs):
                script_calls.append((args, kwargs))
                return True

            app.state.room_scripts.handle_command = fake_handle_command

            uri = f"ws://{host}:{port}/ws/rooms/34?token={hero_token}"
            async with websockets.connect(uri) as hero_ws:
                await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("payload", {}).get("event") == "location_update",
                )
                await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("payload", {}).get("event")
                    == "location_description",
                )
                await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("payload", {}).get("event") == "room_objects",
                )

                await hero_ws.send(json.dumps({"type": "command", "command": "anything"}))
                tired = await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("type") == "command_response"
                    and msg.get("payload", {}).get("message_id") == "TIRED",
                )

                assert tired["payload"]["scope"] == "player"
                assert script_calls == []
    finally:
        server.should_exit = True
        await server_task


@pytest.mark.anyio
async def test_websocket_fatigue_bypass_allows_status_refresh_without_increment(monkeypatch):
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
                "/auth/session", json={"player_id": "hero", "room_id": 0}
            )
            hero_token = hero_session.json()["session"]["token"]

            with app.state.session_factory() as db:
                hero = db.scalar(select(models.Player).where(models.Player.plyrid == "hero"))
                assert hero is not None
                hero.macros = 19
                hero.flags |= int(constants.PlayerFlag.LOADED)
                db.commit()

            uri = f"ws://{host}:{port}/ws/rooms/0?token={hero_token}"
            async with websockets.connect(uri) as hero_ws:
                await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("payload", {}).get("event") == "location_update",
                )
                await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("payload", {}).get("event")
                    == "location_description",
                )
                await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("payload", {}).get("event") == "room_objects",
                )

                await hero_ws.send(
                    json.dumps(
                        {
                            "type": "command",
                            "command": "look",
                            "meta": {
                                "silent": True,
                                "status_card": "description",
                                "fatigue_bypass": True,
                            },
                        }
                    )
                )
                description = await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("type") == "command_response"
                    and msg.get("payload", {}).get("event") == "location_description",
                )

                assert description["meta"]["fatigue_bypass"] is True
                await _assert_no_matching(
                    hero_ws,
                    lambda msg: msg.get("payload", {}).get("message_id") == "TIRED",
                    timeout=0.2,
                )
                with app.state.session_factory() as db:
                    hero = db.scalar(
                        select(models.Player).where(models.Player.plyrid == "hero")
                    )
                    assert hero is not None
                    assert hero.macros == 19
    finally:
        server.should_exit = True
        await server_task


@pytest.mark.anyio
async def test_websocket_fatigue_bypass_rejected_for_mutating_command(monkeypatch):
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
                "/auth/session", json={"player_id": "hero", "room_id": 0}
            )
            hero_token = hero_session.json()["session"]["token"]

            with app.state.session_factory() as db:
                hero = db.scalar(select(models.Player).where(models.Player.plyrid == "hero"))
                assert hero is not None
                hero.macros = 19
                hero.flags |= int(constants.PlayerFlag.LOADED)
                hero.gamloc = 0
                hero.pgploc = 0
                db.commit()

            uri = f"ws://{host}:{port}/ws/rooms/0?token={hero_token}"
            async with websockets.connect(uri) as hero_ws:
                await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("payload", {}).get("event") == "location_update",
                )
                await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("payload", {}).get("event")
                    == "location_description",
                )
                await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("payload", {}).get("event") == "room_objects",
                )

                await hero_ws.send(
                    json.dumps(
                        {
                            "type": "command",
                            "command": "north",
                            "meta": {
                                "silent": True,
                                "status_card": "description",
                                "fatigue_bypass": True,
                            },
                        }
                    )
                )
                tired = await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("type") == "command_response"
                    and msg.get("payload", {}).get("message_id") == "TIRED",
                )

                assert tired["payload"]["scope"] == "player"
                with app.state.session_factory() as db:
                    hero = db.scalar(
                        select(models.Player).where(models.Player.plyrid == "hero")
                    )
                    assert hero is not None
                    assert hero.gamloc == 0
                    assert hero.macros == 19
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
                live_hero = app.state.active_player_sessions[hero_token]
                shadow_hero = models.PlayerModel(**live_hero.model_dump())
                app.state.active_player_sessions["shadow-hero-token"] = shadow_hero
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
                        randrange_values=[2, 3, 4, 5, 12],
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
                    assert live_hero.gamloc == 0
                    assert live_hero.pgploc == 0
                    assert live_hero.level == 1
                    assert live_hero.hitpts == 4
                    assert live_hero.spts == 2
                    assert live_hero.spells == []
                    assert shadow_hero.gamloc == 0
                    assert shadow_hero.pgploc == 0
                    assert shadow_hero.level == 1
                    assert shadow_hero.hitpts == 4
                    assert shadow_hero.spts == 2
                    assert shadow_hero.spells == []

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


@pytest.mark.anyio
async def test_websocket_zar_death_uses_modern_recovery_for_non_honor_player(monkeypatch):
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
    seed_returning_players(app, ("zthero", "ztdeath", "ztwill"))

    try:
        async with httpx.AsyncClient(base_url=f"http://{host}:{port}") as client:
            hero_session = await client.post(
                "/auth/session",
                json={"player_id": "zthero", "room_id": 302, "honor_mode": False},
            )
            death_witness_session = await client.post(
                "/auth/session", json={"player_id": "ztdeath", "room_id": 302}
            )
            willow_witness_session = await client.post(
                "/auth/session", json={"player_id": "ztwill", "room_id": 0}
            )
            hero_token = hero_session.json()["session"]["token"]
            death_witness_token = death_witness_session.json()["session"]["token"]
            willow_witness_token = willow_witness_session.json()["session"]["token"]

            with app.state.session_factory() as db:
                hero = db.scalar(select(models.Player).where(models.Player.plyrid == "zthero"))
                death_witness = db.scalar(
                    select(models.Player).where(models.Player.plyrid == "ztdeath")
                )
                willow_witness = db.scalar(
                    select(models.Player).where(models.Player.plyrid == "ztwill")
                )
                location = db.scalar(select(models.Location).where(models.Location.id == 302))
                assert hero is not None
                assert death_witness is not None
                assert willow_witness is not None
                assert location is not None
                hero.altnam = "Some psuedo dragon"
                hero.attnam = "psuedo dragon"
                hero.flags = int(
                    constants.PlayerFlag.LOADED
                    | constants.PlayerFlag.GOTKYG
                    | constants.PlayerFlag.INVISF
                    | constants.PlayerFlag.PEGASU
                    | constants.PlayerFlag.WILLOW
                    | constants.PlayerFlag.PDRAGN
                )
                hero.honor_mode = False
                hero.level = 10
                hero.hitpts = 8
                hero.spts = 21
                hero.gold = 77
                hero.gpobjs = [
                    constants.SOULSTONE_OBJECT_ID,
                    constants.KYRAGEM_OBJECT_ID,
                    0,
                ]
                hero.obvals = [10, 20, 30]
                hero.npobjs = 3
                hero.nspells = 2
                hero.spells = [1, 23]
                hero.offspls = 123
                hero.defspls = 456
                hero.othspls = 789
                hero.charms = [1] * constants.NCHARM
                hero.macros = 0
                hero.gamloc = 302
                hero.pgploc = 302
                death_witness.level = 25
                death_witness.gamloc = 302
                death_witness.pgploc = 302
                willow_witness.level = 25
                willow_witness.gamloc = 0
                willow_witness.pgploc = 0
                location.objects = [52]
                location.nlobjs = 1
                db.commit()
                app.state.location_index[302] = app.state.location_index[302].model_copy(
                    update={"objects": [52], "nlobjs": 1}
                )

            hero_uri = f"ws://{host}:{port}/ws/rooms/302?token={hero_token}"
            death_witness_uri = (
                f"ws://{host}:{port}/ws/rooms/302?token={death_witness_token}"
            )
            willow_witness_uri = (
                f"ws://{host}:{port}/ws/rooms/0?token={willow_witness_token}"
            )

            async with websockets.connect(hero_uri) as hero_ws:
                await _recv_matching(
                    hero_ws,
                    lambda msg: msg.get("payload", {}).get("event") == "location_update",
                )
                live_hero = app.state.active_player_sessions[hero_token]
                async with websockets.connect(death_witness_uri) as death_witness_ws:
                    await _recv_matching(
                        death_witness_ws,
                        lambda msg: msg.get("payload", {}).get("event")
                        == "location_update",
                    )
                    async with websockets.connect(willow_witness_uri) as willow_witness_ws:
                        await _recv_matching(
                            willow_witness_ws,
                            lambda msg: msg.get("payload", {}).get("event")
                            == "location_update",
                        )

                        app.state.animation_tick_system.state.zar_location = 302
                        app.state.animation_tick_system.state.zar_counter = 0
                        app.state.animation_tick_system.state.zar_attack_index = 0
                        app.state.animation_rng = _FixedAnimationRng(
                            randrange_values=[2, 3, 4, 5, 12],
                            randint_values=[12],
                        )
                        await app.state.animation_tick_callback()

                        death = await _recv_matching(
                            hero_ws,
                            lambda msg: msg.get("type") == "command_response"
                            and msg.get("payload", {}).get("message_id") == "DIEMSG",
                            timeout=2.0,
                        )
                        location_update = await _recv_matching(
                            hero_ws,
                            lambda msg: msg.get("type") == "command_response"
                            and msg.get("payload", {}).get("event") == "location_update"
                            and msg.get("payload", {}).get("location") == 0,
                            timeout=2.0,
                        )
                        drop_refresh = await _recv_matching(
                            death_witness_ws,
                            lambda msg: msg.get("type") == "room_broadcast"
                            and msg.get("payload", {}).get("event") == "room_objects"
                            and msg.get("payload", {}).get("location") == 302,
                            timeout=2.0,
                        )
                        drop_message = await _recv_matching(
                            death_witness_ws,
                            lambda msg: msg.get("type") == "room_broadcast"
                            and msg.get("payload", {}).get("message_id") == "DROPIT3",
                            timeout=2.0,
                        )
                        arrival = await _recv_matching(
                            willow_witness_ws,
                            lambda msg: msg.get("type") == "room_broadcast"
                            and "appeared in a holy light"
                            in msg.get("payload", {}).get("text", ""),
                            timeout=2.0,
                        )

                        assert death["payload"]["modern_death_recovery"] is True
                        assert death["payload"]["old_level"] == 10
                        assert death["payload"]["new_level"] == 9
                        assert death["payload"]["filtered_items"] == [
                            constants.SOULSTONE_OBJECT_ID,
                            constants.KYRAGEM_OBJECT_ID,
                        ]
                        assert location_update["payload"]["modern_death_recovery"] is True
                        assert drop_refresh["payload"]["modern_death_recovery"] is True
                        assert {"id": 0} in drop_refresh["payload"]["objects"]
                        assert {"id": constants.SOULSTONE_OBJECT_ID} not in drop_refresh[
                            "payload"
                        ]["objects"]
                        assert {"id": constants.KYRAGEM_OBJECT_ID} not in drop_refresh[
                            "payload"
                        ]["objects"]
                        assert drop_message["payload"]["object_id"] == 0
                        assert arrival["payload"]["exclude_player"] == "zthero"
                        assert live_hero.gamloc == 0
                        assert live_hero.pgploc == 0
                        assert live_hero.level == 9
                        assert live_hero.hitpts == 36
                        assert live_hero.spts == 18
                        assert live_hero.gold == 0
                        assert live_hero.spells == []
                        assert live_hero.offspls == 123
                        assert live_hero.defspls == 456
                        assert live_hero.othspls == 789
                        assert live_hero.charms == [0] * constants.NCHARM
                        assert live_hero.macros == constants.MODERN_DEATH_EXHAUSTION_MACROS

            with app.state.session_factory() as db:
                hero = db.scalar(select(models.Player).where(models.Player.plyrid == "zthero"))
                location = db.scalar(select(models.Location).where(models.Location.id == 302))
                assert hero is not None
                assert location is not None
                assert hero.gamloc == 0
                assert hero.pgploc == 0
                assert hero.level == 9
                assert hero.nmpdes == constants.level_to_nmpdes(9)
                assert hero.hitpts == 36
                assert hero.spts == 18
                assert hero.gold == 0
                assert hero.gpobjs == []
                assert hero.obvals == []
                assert hero.npobjs == 0
                assert hero.nspells == 0
                assert hero.spells == []
                assert hero.offspls == 123
                assert hero.defspls == 456
                assert hero.othspls == 789
                assert hero.charms == [0] * constants.NCHARM
                assert hero.macros == constants.MODERN_DEATH_EXHAUSTION_MACROS
                assert hero.flags == int(constants.PlayerFlag.LOADED)
                assert location.objects == [52, 0]
    finally:
        server.should_exit = True
        await server_task
