import asyncio
import random

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


@pytest.fixture
async def scheduler():
    service = SchedulerService()
    await service.start()
    yield service
    await service.stop()


@pytest.fixture
async def player():
    return fixtures.build_player().model_copy(update={"gold": 0}, deep=True)


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
async def test_sanman_digging_sand_can_grant_gold(engine, player):
    engine.yaml_engine.rng = random.Random(31)

    handled = await engine.handle_command(
        player.plyrid, 189, command="dig", args=["sand"], player=player
    )
    await asyncio.sleep(0.01)

    assert handled is True
    assert player.gold == 1

    direct_ids = {
        event.get("message_id")
        for event in _pending_events(engine, scope="target")
        if event.get("player") == player.plyrid
    }
    broadcast_ids = {
        event.get("message_id") for event in _pending_events(engine, scope="room")
    }
    assert "SANM00" in direct_ids
    assert "SANM01" in broadcast_ids


@pytest.mark.anyio
async def test_sanman_digging_sand_can_fail(engine, player):
    engine.yaml_engine.rng = random.Random(0)

    handled = await engine.handle_command(
        player.plyrid, 189, command="search", args=["sand"], player=player
    )
    await asyncio.sleep(0.01)

    assert handled is True
    assert player.gold == 0

    direct_ids = {
        event.get("message_id")
        for event in _pending_events(engine, scope="target")
        if event.get("player") == player.plyrid
    }
    broadcast_ids = {
        event.get("message_id") for event in _pending_events(engine, scope="room")
    }
    assert "SANM02" in direct_ids
    assert "SANM01" in broadcast_ids
