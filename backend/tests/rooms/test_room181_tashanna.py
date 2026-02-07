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


def _direct_texts(engine: RoomScriptEngine, player_id: str) -> list[str]:
    # Check pending events from the engine (scope "target" for player-directed messages)
    return [
        event.get("text")
        for event in engine.pending_events
        if event.get("scope") == "target"
        and event.get("player") == player_id
    ]


def _broadcast_texts(engine: RoomScriptEngine) -> list[str]:
    # Check pending events from the engine (scope "room" for broadcasts)
    return [
        event.get("text")
        for event in engine.pending_events
        if event.get("scope") == "room"
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
async def test_tashanna_imagine_dagger_grants_when_space(engine, player):
    handled = await engine.handle_command(
        player.plyrid, 181, command="imagine", args=["dagger"], player=player
    )
    await asyncio.sleep(0.01)

    assert handled is True

    dagger_id = next(obj.id for obj in fixtures.load_objects() if obj.name == "dagger")
    assert dagger_id in player.gpobjs

    messages = fixtures.load_messages().messages
    assert messages["DAGM00"] in _direct_texts(engine, player.plyrid)
    assert (messages["DAGM01"] % player.altnam) in _broadcast_texts(engine)
    assert (messages["DAGM01"] % player.altnam) not in _direct_texts(engine, player.plyrid)


@pytest.mark.anyio
async def test_tashanna_imagine_dagger_rejects_when_full(engine, player):
    player = player.model_copy(
        update={
            "gpobjs": list(range(constants.MXPOBS)),
            "obvals": [0] * constants.MXPOBS,
            "npobjs": constants.MXPOBS,
        }
    )
    engine.players[player.plyrid] = player

    handled = await engine.handle_command(
        player.plyrid, 181, command="imagine", args=["dagger"], player=player
    )
    await asyncio.sleep(0.01)

    assert handled is True

    dagger_id = next(obj.id for obj in fixtures.load_objects() if obj.name == "dagger")
    assert dagger_id not in player.gpobjs

    messages = fixtures.load_messages().messages
    assert messages["DAGM02"] in _direct_texts(engine, player.plyrid)
    assert (messages["DAGM01"] % player.altnam) in _broadcast_texts(engine)


@pytest.mark.anyio
async def test_tashanna_see_statue_shows_inscription(engine, player):
    handled = await engine.handle_command(
        player.plyrid, 181, command="see", args=["statue"], player=player
    )
    await asyncio.sleep(0.01)

    assert handled is True

    messages = fixtures.load_messages().messages
    assert messages["DAGM03"] in _direct_texts(engine, player.plyrid)
    assert (messages["DAGM04"] % player.altnam) in _broadcast_texts(engine)
