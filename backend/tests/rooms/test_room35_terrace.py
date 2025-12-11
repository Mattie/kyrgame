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
async def test_terrace_drink_water_uses_helper(engine, player, scheduler):
    handled = await engine.handle_command(
        player.plyrid, 35, command="drink", args=["water"], player=player
    )
    await asyncio.sleep(0.01)

    assert handled is True

    messages = fixtures.load_messages().messages
    direct_texts = [
        message.get("payload", {}).get("text")
        for message in engine.gateway.messages
        if message.get("payload", {}).get("scope") == "direct"
        and message.get("payload", {}).get("player") == player.plyrid
    ]
    broadcast_texts = [
        message.get("payload", {}).get("text")
        for message in engine.gateway.messages
        if message.get("payload", {}).get("scope") == "broadcast"
    ]

    assert messages["DRINK0"] in direct_texts
    assert (messages["DRINK1"] % player.altnam) in broadcast_texts


@pytest.mark.anyio
async def test_unhandled_terrace_commands_fall_through(engine, player):
    handled = await engine.handle_command(player.plyrid, 35, command="look", args=[], player=player)
    await asyncio.sleep(0.01)

    assert handled is False
