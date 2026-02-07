import asyncio
import random

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
    base = fixtures.build_player()
    return base.model_copy(
        update={
            "gpobjs": [24],
            "obvals": [0],
            "npobjs": 1,
            "offspls": 0,
            "spells": [],
            "nspells": 0,
        }
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
    engine.yaml_engine.rng = random.Random(0)
    return engine


@pytest.mark.anyio
async def test_touching_orb_consumes_sceptre_and_grants_spell(engine, player):
    handled = await engine.handle_command(
        player.plyrid, 34, command="touch", args=["orb", "with", "sceptre"], player=player
    )
    await asyncio.sleep(0.01)

    assert handled is True
    assert player.npobjs == 0
    assert player.gpobjs == []

    spells = fixtures.load_spells()
    candidate_bits = {spell.bitdef for spell in spells if spell.id in {10, 18, 19, 21, 30}}
    assert player.offspls in candidate_bits

    direct_texts = _direct_texts(engine, player.plyrid)
    broadcast_texts = _broadcast_texts(engine)
    messages = fixtures.load_messages().messages
    assert messages["DRUID0"] in direct_texts
    broadcast_text = messages["DRUID1"] % player.altnam
    assert broadcast_text in broadcast_texts
    payload = _payload_for_text(_broadcast_payloads(engine), broadcast_text)
    assert payload.get("exclude_player") == player.plyrid


@pytest.mark.anyio
async def test_touching_orb_without_sceptre_rejects(engine, player):
    player = player.model_copy(update={"gpobjs": [], "obvals": [], "npobjs": 0})
    engine.players[player.plyrid] = player

    handled = await engine.handle_command(
        player.plyrid, 34, command="touch", args=["orb", "with", "sceptre"], player=player
    )
    await asyncio.sleep(0.01)

    assert handled is True
    assert player.offspls == 0

    messages = fixtures.load_messages().messages
    direct_texts = _direct_texts(engine, player.plyrid)
    broadcast_texts = _broadcast_texts(engine)
    assert messages["DRUID2"] in direct_texts
    broadcast_text = messages["DRUID1"] % player.altnam
    assert broadcast_text in broadcast_texts
    payload = _payload_for_text(_broadcast_payloads(engine), broadcast_text)
    assert payload.get("exclude_player") == player.plyrid


@pytest.mark.anyio
async def test_random_spell_selection_covers_all_options(engine, player):
    spells = fixtures.load_spells()
    candidate_bits = {spell.bitdef for spell in spells if spell.id in {10, 18, 19, 21, 30}}

    seen: set[int] = set()
    for seed in range(20):
        engine.yaml_engine.rng.seed(seed)
        fresh_player = player.model_copy(
            update={
                "gpobjs": [24],
                "obvals": [0],
                "npobjs": 1,
                "offspls": 0,
                "spells": [],
                "nspells": 0,
            }
        )
        engine.players[player.plyrid] = fresh_player
        await engine.handle_command(
            fresh_player.plyrid,
            34,
            command="touch",
            args=["orb", "with", "sceptre"],
            player=fresh_player,
        )
        await asyncio.sleep(0.001)
        seen.add(fresh_player.offspls)

    assert candidate_bits.issubset(seen)


@pytest.mark.anyio
async def test_consumes_sceptre_even_when_inventory_was_full(engine, player):
    player = player.model_copy(
        update={
            "gpobjs": list(range(constants.MXPOBS - 1)) + [24],
            "obvals": [0] * constants.MXPOBS,
            "npobjs": constants.MXPOBS,
        }
    )
    engine.players[player.plyrid] = player

    handled = await engine.handle_command(
        player.plyrid, 34, command="touch", args=["orb", "with", "sceptre"], player=player
    )
    await asyncio.sleep(0.01)

    assert handled is True
    assert player.npobjs == constants.MXPOBS - 1
    assert 24 not in player.gpobjs
