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
async def test_sunshi_cast_zapher_transforms_tulip(engine, player):
    tulip = _object_by_name("tulip")
    wand = _object_by_name("wand")
    player = player.model_copy(
        update={"gpobjs": [tulip.id], "obvals": [0], "npobjs": 1}
    )
    engine.players[player.plyrid] = player

    handled = await engine.handle_command(
        player.plyrid, 213, command="cast", args=["zapher", "tulip"], player=player
    )
    await asyncio.sleep(0.01)

    assert handled is True
    assert tulip.id not in player.gpobjs
    assert wand.id in player.gpobjs

    direct_ids = {
        event.get("message_id")
        for event in _pending_events(engine, scope="target")
        if event.get("player") == player.plyrid
    }
    broadcast_ids = {event.get("message_id") for event in _pending_events(engine, scope="room")}
    assert "SUNM00" in direct_ids
    assert "SUNM01" in broadcast_ids


@pytest.mark.anyio
async def test_sunshi_cast_zennyra_shows_vision(engine, player):
    handled = await engine.handle_command(
        player.plyrid, 213, command="cast", args=["zennyra"], player=player
    )
    await asyncio.sleep(0.01)

    assert handled is True

    direct_ids = {
        event.get("message_id")
        for event in _pending_events(engine, scope="target")
        if event.get("player") == player.plyrid
    }
    broadcast_ids = {event.get("message_id") for event in _pending_events(engine, scope="room")}
    assert "SUNM02" in direct_ids
    assert "SUNM01" in broadcast_ids


@pytest.mark.anyio
async def test_sunshi_offer_kyragem_levels_player(engine, player):
    kyragem = _object_by_name("kyragem")
    player = player.model_copy(
        update={"gpobjs": [kyragem.id], "obvals": [0], "npobjs": 1, "level": 11}
    )
    engine.players[player.plyrid] = player

    handled = await engine.handle_command(
        player.plyrid, 213, command="offer", args=["kyragem"], player=player
    )
    await asyncio.sleep(0.01)

    assert handled is True
    assert player.level == 12
    assert kyragem.id in player.gpobjs

    direct_ids = {
        event.get("message_id")
        for event in _pending_events(engine, scope="target")
        if event.get("player") == player.plyrid
    }
    broadcast_ids = {event.get("message_id") for event in _pending_events(engine, scope="room")}
    assert "SUNM03" in direct_ids
    assert "SUNM04" in broadcast_ids
