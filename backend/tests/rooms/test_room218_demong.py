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
async def test_demong_place_soulstone_triggers_gate(engine, player):
    soulstone = _object_by_name("soulstone")
    player = player.model_copy(
        update={"gpobjs": [soulstone.id], "obvals": [0], "npobjs": 1, "gamloc": 218}
    )
    engine.players[player.plyrid] = player

    handled = await engine.handle_command(
        player.plyrid, 218, command="put", args=["soulstone", "niche"], player=player
    )
    await asyncio.sleep(0.01)

    assert handled is True
    assert player.pgploc == 218
    assert player.gamloc == 219
    assert soulstone.id in player.gpobjs

    direct_ids = {
        event.get("message_id")
        for event in _pending_events(engine, scope="target")
        if event.get("player") == player.plyrid
    }
    assert "SOUKEY" in direct_ids

    transfer_event = next(
        event for event in _pending_events(engine) if event.get("event") == "room_transfer"
    )
    assert transfer_event["target_room"] == 219
    assert transfer_event["leave_text"] == "vanished through the demon gate"
    assert transfer_event["arrive_text"] == "appeared in a column of blue flame"
