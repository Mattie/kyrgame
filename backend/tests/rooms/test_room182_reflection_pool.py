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


def _direct_texts(engine: RoomScriptEngine, player_id: str) -> list[str]:
    return [
        message.get("payload", {}).get("text")
        for message in engine.gateway.messages
        if message.get("payload", {}).get("scope") == "direct"
        and message.get("payload", {}).get("player") == player_id
    ]


def _broadcast_texts(engine: RoomScriptEngine) -> list[str]:
    return [
        message.get("payload", {}).get("text")
        for message in engine.gateway.messages
        if message.get("payload", {}).get("scope") == "broadcast"
    ]


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
async def test_reflection_pool_toss_dagger_upgrades_to_sword(engine, player):
    objects = fixtures.load_objects()
    dagger_id = next(obj.id for obj in objects if obj.name == "dagger")
    sword_id = next(obj.id for obj in objects if obj.name == "sword")

    player = player.model_copy(
        update={
            "gpobjs": [dagger_id],
            "obvals": [0],
            "npobjs": 1,
        }
    )
    engine.players[player.plyrid] = player

    handled = await engine.handle_command(
        player.plyrid, 182, command="toss", args=["dagger", "pool"], player=player
    )
    await asyncio.sleep(0.01)

    assert handled is True
    assert dagger_id not in player.gpobjs
    assert sword_id in player.gpobjs

    messages = fixtures.load_messages().messages
    assert messages["REFM00"] in _direct_texts(engine, player.plyrid)
    assert (messages["REFM01"] % player.altnam) in _broadcast_texts(engine)


@pytest.mark.anyio
async def test_reflection_pool_toss_other_item_rejects(engine, player):
    objects = fixtures.load_objects()
    ruby_id = next(obj.id for obj in objects if obj.name == "ruby")
    player = player.model_copy(
        update={
            "gpobjs": [ruby_id],
            "obvals": [0],
            "npobjs": 1,
        }
    )
    engine.players[player.plyrid] = player

    handled = await engine.handle_command(
        player.plyrid, 182, command="drop", args=["ruby", "pool"], player=player
    )
    await asyncio.sleep(0.01)

    assert handled is True
    assert ruby_id in player.gpobjs

    messages = fixtures.load_messages().messages
    assert messages["REFM02"] in _direct_texts(engine, player.plyrid)
    assert (messages["REFM01"] % player.altnam) in _broadcast_texts(engine)


@pytest.mark.anyio
async def test_reflection_pool_see_pool_describes_surface(engine, player):
    handled = await engine.handle_command(
        player.plyrid, 182, command="see", args=["pool"], player=player
    )
    await asyncio.sleep(0.01)

    assert handled is True

    messages = fixtures.load_messages().messages
    assert messages["REFM03"] in _direct_texts(engine, player.plyrid)
    assert (messages["REFM04"] % player.altnam) in _broadcast_texts(engine)
