import asyncio

import pytest

from kyrgame import constants, fixtures
from kyrgame.rooms import RoomScriptEngine
from kyrgame.scheduler import SchedulerService


class FakeGateway:
    def __init__(self):
        self.messages: list[dict] = []

    async def broadcast(self, room_id: int, message: dict, sender=None):  # noqa: ARG002
        self.messages.append(message)


def _pending_events(engine: RoomScriptEngine, scope: str | None = None) -> list[dict]:
    if scope is None:
        return list(engine.pending_events)
    return [event for event in engine.pending_events if event.get("scope") == scope]


def _object_by_name(name: str):
    return next(obj for obj in fixtures.load_objects() if obj.name == name)


@pytest.fixture
async def scheduler():
    service = SchedulerService()
    await service.start()
    yield service
    await service.stop()


@pytest.fixture
async def player():
    return fixtures.build_player().model_copy(deep=True)


@pytest.fixture
async def engine(player, scheduler):
    gateway = FakeGateway()
    messages = fixtures.load_messages()
    engine = RoomScriptEngine(
        gateway=gateway,
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=messages,
        players=[player],
        room_scripts=fixtures.load_room_scripts(),
        objects=fixtures.load_objects(),
        spells=fixtures.load_spells(),
    )
    return engine


@pytest.mark.anyio
async def test_mistyr_touch_orb_transfers_player(engine, player):
    player.gamloc = 188

    handled = await engine.handle_command(
        player.plyrid, 188, command="touch", args=["orb"], player=player
    )
    await asyncio.sleep(0.01)

    assert handled is True
    assert player.pgploc == 188
    assert player.gamloc == 34

    direct_ids = {
        event.get("message_id")
        for event in _pending_events(engine, scope="target")
        if event.get("player") == player.plyrid
    }
    assert "MISM00" in direct_ids

    transfer_event = next(
        event for event in _pending_events(engine) if event.get("event") == "room_transfer"
    )
    assert transfer_event["target_room"] == 34
    assert transfer_event["leave_text"] == "vanished in a bright blue flash"
    assert transfer_event["arrive_text"] == "appeared in a bright blue flash"


@pytest.mark.anyio
async def test_mistyr_concentrate_orb_grants_charm(engine, player):
    handled = await engine.handle_command(
        player.plyrid, 188, command="concentrate", args=["orb"], player=player
    )
    await asyncio.sleep(0.01)

    assert handled is True
    charm = _object_by_name("charm")
    assert charm.id in player.gpobjs

    direct_ids = {
        event.get("message_id")
        for event in _pending_events(engine, scope="target")
        if event.get("player") == player.plyrid
    }
    broadcast_ids = {
        event.get("message_id") for event in _pending_events(engine, scope="room")
    }
    assert "MISM01" in direct_ids
    assert "MISM02" in broadcast_ids


@pytest.mark.anyio
async def test_mistyr_concentrate_orb_rejects_when_full(engine, player):
    player = player.model_copy(
        update={
            "gpobjs": list(range(constants.MXPOBS)),
            "obvals": [0] * constants.MXPOBS,
            "npobjs": constants.MXPOBS,
        }
    )
    engine.players[player.plyrid] = player

    handled = await engine.handle_command(
        player.plyrid, 188, command="meditate", args=["about", "orb"], player=player
    )
    await asyncio.sleep(0.01)

    assert handled is True
    assert _object_by_name("charm").id not in player.gpobjs

    direct_ids = {
        event.get("message_id")
        for event in _pending_events(engine, scope="target")
        if event.get("player") == player.plyrid
    }
    broadcast_ids = {
        event.get("message_id") for event in _pending_events(engine, scope="room")
    }
    assert "MISM03" in direct_ids
    assert "MISM02" in broadcast_ids


@pytest.mark.anyio
async def test_mistyr_drop_dagger_levels_player(engine, player):
    dagger = _object_by_name("dagger")
    player = player.model_copy(
        update={"gpobjs": [dagger.id], "obvals": [0], "npobjs": 1, "level": 7}
    )
    engine.players[player.plyrid] = player

    handled = await engine.handle_command(
        player.plyrid, 188, command="drop", args=["dagger", "orb"], player=player
    )
    await asyncio.sleep(0.01)

    assert handled is True
    assert dagger.id not in player.gpobjs
    assert player.level == 8

    direct_ids = {
        event.get("message_id")
        for event in _pending_events(engine, scope="target")
        if event.get("player") == player.plyrid
    }
    broadcast_ids = {
        event.get("message_id") for event in _pending_events(engine, scope="room")
    }
    assert "MISM04" in direct_ids
    assert "MISM05" in broadcast_ids
