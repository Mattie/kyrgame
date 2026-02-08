import random

import pytest

from kyrgame import commands, constants, fixtures
from kyrgame.effects import EffectResult


class FakePresence:
    async def players_in_room(self, room_id: int) -> set[str]:  # noqa: ARG002
        return set()


def _build_state(player):
    locations = {location.id: location for location in fixtures.load_locations()}
    objects = {obj.id: obj for obj in fixtures.load_objects()}
    messages = fixtures.load_messages()
    content_mappings = fixtures.load_content_mappings()
    return commands.GameState(
        player=player,
        locations=locations,
        objects=objects,
        messages=messages,
        content_mappings=content_mappings,
        presence=FakePresence(),
        player_lookup=lambda _player_id: None,
    )


def _build_player(**updates):
    player = fixtures.build_player()
    data = player.model_dump()
    data.update(updates)
    return player.model_copy(update=data)


class TrackingPresence:
    def __init__(self, occupants: set[str]):
        self._occupants = occupants

    async def players_in_room(self, room_id: int) -> set[str]:  # noqa: ARG002
        return self._occupants


@pytest.mark.anyio
async def test_cast_requires_spell_name():
    player = _build_player(flags=int(constants.PlayerFlag.LOADED))
    state = _build_state(player)
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": ""}, state)

    assert [event["message_id"] for event in result.events] == ["OBJM07"]


@pytest.mark.anyio
async def test_cast_rejects_non_memorized_spells_with_broadcast():
    player = _build_player(flags=int(constants.PlayerFlag.LOADED), spells=[], nspells=0)
    state = _build_state(player)
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "noouch"}, state)

    assert [event["message_id"] for event in result.events] == ["NOTMEM", "SPFAIL"]
    assert result.events[1]["exclude_player"] == state.player.plyrid


@pytest.mark.anyio
async def test_cast_enforces_level_gate_with_sndutl_emote():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        level=1,
        spts=20,
        spells=[0],
        nspells=1,
    )
    state = _build_state(player)
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "abbracada"}, state)

    assert result.events[0]["message_id"] == "KSPM10"
    assert result.events[1]["text"] == f"*** {state.player.altnam} is mouthing off."


@pytest.mark.anyio
async def test_cast_enforces_spell_point_gate_with_sndutl_emote():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        level=10,
        spts=1,
        spells=[0],
        nspells=1,
    )
    state = _build_state(player)
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "abbracada"}, state)

    assert result.events[0]["message_id"] == "KSPM10"
    assert result.events[1]["text"] == f"*** {state.player.altnam} is waving his arms."


@pytest.mark.anyio
async def test_cast_consumes_memorized_spell_and_triggers_effects(monkeypatch):
    class StubEffectEngine:
        last_call = None

        def __init__(self, spells, messages, clock=None, rng=None, objects=None):  # noqa: D401, ARG002
            self.spells = {spell.id: spell for spell in spells}
            self.messages = messages
            self.effects = {}

        def cast_spell(self, player, spell_id, target, target_player=None, *, apply_cost=True):
            StubEffectEngine.last_call = {
                "spell_id": spell_id,
                "target": target,
                "target_player": target_player,
                "apply_cost": apply_cost,
            }
            return EffectResult(
                success=True,
                message_id="SPLTEST",
                text="cast ok",
                animation="sparkle",
                context={"target": target},
            )

    monkeypatch.setattr(commands, "SpellEffectEngine", StubEffectEngine)

    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        level=5,
        spts=4,
        spells=[42],
        nspells=1,
    )
    state = _build_state(player)
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "noouch"}, state)

    assert state.player.spells == []
    assert state.player.nspells == 0
    assert state.player.spts == 3
    assert StubEffectEngine.last_call == {
        "spell_id": 42,
        "target": None,
        "target_player": None,
        "apply_cost": False,
    }
    assert result.events[0]["message_id"] == "SPLTEST"


@pytest.mark.anyio
async def test_cast_target_missing_emits_phantom_failure():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        level=25,
        spts=25,
        spells=[4],
        nspells=1,
    )
    state = _build_state(player)
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "bookworm nobody"}, state)

    assert result.events[0]["message_id"] == "KSPM02"
    assert result.events[1]["scope"] == "room"


@pytest.mark.anyio
async def test_cast_target_object_emits_kspm_resist_messages():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        level=25,
        spts=25,
        spells=[4],
        nspells=1,
    )
    state = _build_state(player)
    location = state.locations[state.player.gamloc]
    pearl_id = next(obj.id for obj in state.objects.values() if obj.name == "pearl")
    location = location.model_copy(update={"objects": [pearl_id], "nlobjs": 1})
    state.locations[location.id] = location

    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "bookworm pearl"}, state)

    assert [event["message_id"] for event in result.events] == ["KSPM00", "KSPM01"]


@pytest.mark.anyio
async def test_cast_bookworm_broadcast_excludes_target_player():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        level=25,
        spts=25,
        spells=[4],
        nspells=1,
    )
    target = _build_player(
        plyrid="target",
        attnam="target",
        altnam="Target",
        gamloc=player.gamloc,
        offspls=1,
    )
    state = _build_state(player)
    state.presence = TrackingPresence({player.plyrid, target.plyrid})
    state.player_lookup = lambda pid: target if pid == target.plyrid else player

    moonstone_id = next(obj.id for obj in state.objects.values() if obj.name == "moonstone")
    player = player.model_copy(
        update={"gpobjs": [moonstone_id], "obvals": [0], "npobjs": 1}
    )
    state.player = player

    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "bookworm target"}, state)

    assert [event["message_id"] for event in result.events] == ["S05M03", "S05M04", "S05M05"]
    assert result.events[1]["player"] == target.plyrid
    assert result.events[2]["exclude_player"] == target.plyrid


@pytest.mark.anyio
async def test_cast_targeting_dragon_backfires_on_caster():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        level=25,
        spts=25,
        spells=[4],
        nspells=1,
        hitpts=60,
    )
    state = _build_state(player)
    state.rng = random.Random(5)
    location = state.locations[state.player.gamloc]
    dragon_id = next(obj.id for obj in state.objects.values() if obj.name == "dragon")
    location = location.model_copy(update={"objects": [dragon_id], "nlobjs": 1})
    state.locations[location.id] = location

    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "bookworm dragon"}, state)

    expected_damage = random.Random(5).randint(20, 46)
    assert [event["message_id"] for event in result.events[:2]] == ["ZMSG08", "ZMSG09"]
    assert state.player.hitpts == 60 - expected_damage
