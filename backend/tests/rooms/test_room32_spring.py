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


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def scheduler():
    service = SchedulerService()
    await service.start()
    yield service
    await service.stop()


@pytest.fixture
async def player():
    return fixtures.build_player().model_copy(
        update={"gpobjs": [], "obvals": [], "npobjs": 0}, deep=True
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


def _gateway_payloads(engine: RoomScriptEngine) -> list[dict]:
    return [message["payload"] for message in engine.gateway.messages]


def _direct_texts(engine: RoomScriptEngine, player_id: str) -> list[str]:
    return [
        payload.get("text")
        for payload in _gateway_payloads(engine)
        if payload.get("scope") == "direct" and payload.get("player") == player_id
    ]


def _broadcast_payloads(engine: RoomScriptEngine) -> list[dict]:
    return [
        payload
        for payload in _gateway_payloads(engine)
        if payload.get("scope") == "broadcast"
    ]


@pytest.mark.anyio
async def test_spring_pick_rose_grants_when_inventory_has_space(engine, player):
    handled = await engine.handle_command(
        player.plyrid, 32, command="pick", args=["rose"], player=player
    )
    await asyncio.sleep(0.01)

    assert handled is True
    assert player.gpobjs == [40]
    assert player.obvals == [0]
    assert player.npobjs == 1

    messages = fixtures.load_messages().messages
    assert messages["GROSE1"] in _direct_texts(engine, player.plyrid)
    broadcast_text = messages["GROSE2"] % player.altnam
    assert any(
        payload.get("text") == broadcast_text
        and payload.get("message_id") == "GROSE2"
        and payload.get("exclude_player") == player.plyrid
        for payload in _broadcast_payloads(engine)
    )


@pytest.mark.anyio
async def test_spring_pick_rose_rejects_when_inventory_is_full(engine, player):
    player = player.model_copy(
        update={
            "gpobjs": list(range(constants.MXPOBS)),
            "obvals": [0] * constants.MXPOBS,
            "npobjs": constants.MXPOBS,
        },
        deep=True,
    )
    engine.players[player.plyrid] = player

    handled = await engine.handle_command(
        player.plyrid, 32, command="pick", args=["rose"], player=player
    )
    await asyncio.sleep(0.01)

    assert handled is True
    assert 40 not in player.gpobjs
    assert player.npobjs == constants.MXPOBS

    messages = fixtures.load_messages().messages
    assert messages["GROSE3"] in _direct_texts(engine, player.plyrid)
    broadcast_text = messages["GROSE4"] % player.altnam
    assert any(
        payload.get("text") == broadcast_text
        and payload.get("message_id") == "GROSE4"
        and payload.get("exclude_player") == player.plyrid
        for payload in _broadcast_payloads(engine)
    )


@pytest.mark.anyio
async def test_spring_grab_rose_alias_matches_other_rose_rooms(engine, player):
    handled = await engine.handle_command(
        player.plyrid, 32, command="grab", args=["rose"], player=player
    )
    await asyncio.sleep(0.01)

    assert handled is True
    assert player.gpobjs == [40]
