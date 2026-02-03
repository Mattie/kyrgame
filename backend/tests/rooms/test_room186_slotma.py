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
    garnet = _object_by_name("garnet")
    return fixtures.build_player().model_copy(
        update={"gpobjs": [garnet.id], "obvals": [0], "npobjs": 1}
    )


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
async def test_slotma_grants_random_item_on_win(engine, player):
    engine.yaml_engine.rng = random.Random(1)

    handled = await engine.handle_command(
        player.plyrid, 186, command="drop", args=["garnet", "slot"], player=player
    )
    await asyncio.sleep(0.01)

    assert handled is True
    assert _object_by_name("garnet").id not in player.gpobjs
    assert len(player.gpobjs) == 1

    prize = _object_by_name("bloodstone")
    assert prize.id in player.gpobjs

    messages = fixtures.load_messages().messages
    direct_ids = {
        event.get("message_id")
        for event in _pending_events(engine, scope="target")
        if event.get("player") == player.plyrid
    }
    broadcast_ids = {
        event.get("message_id") for event in _pending_events(engine, scope="room")
    }

    assert "SLOT00" in direct_ids
    assert "SLOT01" in broadcast_ids
    assert "SLOT02" in direct_ids

    slot02_event = next(
        event
        for event in _pending_events(engine, scope="target")
        if event.get("message_id") == "SLOT02"
    )
    expected_article = engine.yaml_engine._article_for_object(prize)
    assert slot02_event["text"] == messages["SLOT02"] % expected_article


@pytest.mark.anyio
async def test_slotma_plays_loss_message_on_failure(engine, player):
    engine.yaml_engine.rng = random.Random(0)

    handled = await engine.handle_command(
        player.plyrid, 186, command="drop", args=["garnet", "slot"], player=player
    )
    await asyncio.sleep(0.01)

    assert handled is True
    assert player.npobjs == 0
    assert player.gpobjs == []

    direct_ids = {
        event.get("message_id")
        for event in _pending_events(engine, scope="target")
        if event.get("player") == player.plyrid
    }
    broadcast_ids = {
        event.get("message_id") for event in _pending_events(engine, scope="room")
    }
    assert "SLOT03" in direct_ids
    assert "SLOT04" in broadcast_ids
