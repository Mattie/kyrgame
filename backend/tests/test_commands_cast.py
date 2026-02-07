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

        def __init__(self, spells, messages, clock=None, rng=None):  # noqa: D401, ARG002
            self.spells = {spell.id: spell for spell in spells}
            self.messages = messages

        def cast_spell(self, player, spell_id, target, *, apply_cost=True):
            StubEffectEngine.last_call = {
                "spell_id": spell_id,
                "target": target,
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
    assert StubEffectEngine.last_call == {"spell_id": 42, "target": None, "apply_cost": False}
    assert result.events[0]["message_id"] == "SPLTEST"
