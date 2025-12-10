import asyncio

import pytest

from kyrgame import fixtures
from kyrgame.rooms import RoomScriptEngine
from kyrgame.scheduler import SchedulerService


class FakeGateway:
    def __init__(self):
        self.messages = []

    async def broadcast(self, room_id: int, message: dict, sender=None):  # noqa: ARG002
        self.messages.append(message)


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
async def test_walk_thicket_damages_player_and_announces_burn(engine, player, scheduler):
    handled = await engine.handle_command(player.plyrid, 19, command="walk", args=["thicket"])
    await asyncio.sleep(0.01)

    assert handled is True
    assert player.hitpts == 2

    broadcast_texts = [
        message.get("payload", {}).get("text")
        for message in engine.gateway.messages
        if message.get("type") == "room_broadcast"
        and message.get("payload", {}).get("scope") == "broadcast"
    ]
    assert any("burning in the flaming thicket" in text for text in broadcast_texts)


@pytest.mark.anyio
async def test_walk_thicket_surfaces_pain_even_without_inventory(engine, player, scheduler):
    empty_player = player.model_copy(update={"gpobjs": [], "obvals": [], "npobjs": 0})
    engine.players[player.plyrid] = empty_player
    player = empty_player

    await engine.handle_command(player.plyrid, 19, command="walk", args=["thicket"])
    await asyncio.sleep(0.01)

    room_texts = [
        message.get("payload", {}).get("text")
        for message in engine.gateway.messages
        if message.get("type") == "room_broadcast"
        and message.get("payload", {}).get("scope") == "broadcast"
    ]
    assert any("...Ouch" in text for text in room_texts)


@pytest.mark.anyio
async def test_unrelated_commands_pass_through(engine, player, scheduler):
    handled = await engine.handle_command(player.plyrid, 19, command="look", args=["around"])
    await asyncio.sleep(0.01)

    assert handled is False
    assert player.hitpts == 12
