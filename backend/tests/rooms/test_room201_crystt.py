import asyncio

import pytest

from kyrgame import fixtures
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
async def test_crystt_aim_wand_levels_player(engine, player):
    wand = _object_by_name("wand")
    player = player.model_copy(
        update={"gpobjs": [wand.id], "obvals": [0], "npobjs": 1, "level": 10}
    )
    engine.players[player.plyrid] = player

    handled = await engine.handle_command(
        player.plyrid, 201, command="aim", args=["wand", "tree"], player=player
    )
    await asyncio.sleep(0.01)

    assert handled is True
    assert player.level == 11
    assert wand.id in player.gpobjs

    direct_ids = {
        event.get("message_id")
        for event in _pending_events(engine, scope="target")
        if event.get("player") == player.plyrid
    }
    broadcast_ids = {event.get("message_id") for event in _pending_events(engine, scope="room")}
    assert "CTREM0" in direct_ids
    assert "CTREM1" in broadcast_ids


@pytest.mark.anyio
async def test_crystt_aim_wand_rejects_higher_level(engine, player):
    wand = _object_by_name("wand")
    player = player.model_copy(
        update={"gpobjs": [wand.id], "obvals": [0], "npobjs": 1, "level": 11}
    )
    engine.players[player.plyrid] = player

    handled = await engine.handle_command(
        player.plyrid, 201, command="aim", args=["wand", "tree"], player=player
    )
    await asyncio.sleep(0.01)

    assert handled is True
    assert player.level == 11

    direct_ids = {
        event.get("message_id")
        for event in _pending_events(engine, scope="target")
        if event.get("player") == player.plyrid
    }
    broadcast_ids = {event.get("message_id") for event in _pending_events(engine, scope="room")}
    assert "LVLM00" in direct_ids
    assert "LVLM01" in broadcast_ids
