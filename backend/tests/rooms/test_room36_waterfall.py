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


def _broadcast_payloads(engine: RoomScriptEngine) -> list[dict]:
    # Check pending events from the engine (scope "room" for broadcasts)
    return [
        event
        for event in engine.pending_events
        if event.get("scope") == "room"
    ]


def _payload_for_text(payloads: list[dict], text: str) -> dict:
    return next(payload for payload in payloads if payload.get("text") == text)


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
async def test_waterfall_drink_water(engine, player):
    handled = await engine.handle_command(
        player.plyrid, 36, command="drink", args=["water"], player=player
    )
    await asyncio.sleep(0.01)

    assert handled is True

    messages = fixtures.load_messages().messages
    assert messages["DRINK0"] in _direct_texts(engine, player.plyrid)
    broadcast_text = messages["DRINK1"] % player.altnam
    assert broadcast_text in _broadcast_texts(engine)
    payload = _payload_for_text(_broadcast_payloads(engine), broadcast_text)
    assert payload.get("exclude_player") == player.plyrid


@pytest.mark.anyio
async def test_waterfall_get_rose_grants_when_space(engine, player):
    handled = await engine.handle_command(
        player.plyrid, 36, command="get", args=["rose"], player=player
    )
    await asyncio.sleep(0.01)

    assert handled is True
    assert 40 in player.gpobjs

    messages = fixtures.load_messages().messages
    assert messages["GROSE1"] in _direct_texts(engine, player.plyrid)
    broadcast_text = messages["GROSE2"] % player.altnam
    assert broadcast_text in _broadcast_texts(engine)
    payload = _payload_for_text(_broadcast_payloads(engine), broadcast_text)
    assert payload.get("exclude_player") == player.plyrid


@pytest.mark.anyio
async def test_waterfall_get_rose_rejects_when_full(engine, player):
    player = player.model_copy(
        update={
            "gpobjs": list(range(constants.MXPOBS)),
            "obvals": [0] * constants.MXPOBS,
            "npobjs": constants.MXPOBS,
        }
    )
    engine.players[player.plyrid] = player

    handled = await engine.handle_command(
        player.plyrid, 36, command="get", args=["rose"], player=player
    )
    await asyncio.sleep(0.01)

    assert handled is True
    assert 40 not in player.gpobjs

    messages = fixtures.load_messages().messages
    assert messages["GROSE3"] in _direct_texts(engine, player.plyrid)
    broadcast_text = messages["GROSE4"] % player.altnam
    assert broadcast_text in _broadcast_texts(engine)
    payload = _payload_for_text(_broadcast_payloads(engine), broadcast_text)
    assert payload.get("exclude_player") == player.plyrid
