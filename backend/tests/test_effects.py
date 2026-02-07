import random

import pytest

from kyrgame import constants, fixtures, models
from kyrgame.effects import (
    CooldownActiveError,
    ObjectEffectEngine,
    ResourceCostError,
    SpellEffectEngine,
    TargetingError,
)


@pytest.fixture
def sample_player():
    player = fixtures.build_player()
    player.spts = 50
    player.level = max(player.level, 10)
    return player


def test_spell_effects_respect_costs_and_cooldowns(sample_player):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    now = 0.0

    def clock():
        return now

    engine = SpellEffectEngine(spells=spells, messages=messages, clock=clock)
    base_points = sample_player.spts

    result = engine.cast_spell(player=sample_player, spell_id=2, target="goblin")
    assert sample_player.spts < base_points
    assert result.animation == spells[2].splrou

    with pytest.raises(CooldownActiveError):
        engine.cast_spell(player=sample_player, spell_id=2, target="goblin")

    now += engine.effects[2].cooldown
    repeat = engine.cast_spell(player=sample_player, spell_id=2, target="ogre")
    assert repeat.context["target"] == "ogre"


def test_spell_effects_require_targets_and_resources(sample_player):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    sample_player.spts = 20

    engine = SpellEffectEngine(spells=spells, messages=messages)

    with pytest.raises(TargetingError):
        engine.cast_spell(player=sample_player, spell_id=5, target=None)

    sample_player.spts = 1
    with pytest.raises(ResourceCostError):
        engine.cast_spell(player=sample_player, spell_id=5, target="ogre")


def test_object_effects_apply_cooldowns_and_require_targets():
    objects = fixtures.load_objects()
    messages = fixtures.load_messages()

    engine = ObjectEffectEngine(objects=objects, messages=messages)
    player = fixtures.build_player()

    toss_result = engine.use_object(player_id="hero", object_id=32, room_id=38)
    assert toss_result.animation == "obj32"

    with pytest.raises(TargetingError):
        engine.use_object(player_id="hero", object_id=33, room_id=1)

    with pytest.raises(CooldownActiveError):
        engine.use_object(player_id="hero", object_id=32, room_id=38)


def test_transformation_spells_toggle_player_flags(sample_player):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    engine = SpellEffectEngine(spells=spells, messages=messages)

    result = engine.cast_spell(player=sample_player, spell_id=16, target=None)
    assert result.message_id == "S16M00"
    assert constants.PlayerFlag.PEGASU & sample_player.flags

    willow = engine.cast_spell(player=sample_player, spell_id=62, target=None)
    assert willow.message_id == "S62M00"
    assert constants.PlayerFlag.WILLOW & sample_player.flags


def test_forget_spells_apply_spellbook_effects(sample_player):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    engine = SpellEffectEngine(spells=spells, messages=messages, rng=random.Random(1))

    sample_player.spells.clear()
    sample_player.spells.extend([1, 2, 3])
    sample_player.nspells = 3

    dumdum = engine.cast_spell(player=sample_player, spell_id=12, target=None)
    assert dumdum.message_id == "S13M03"
    assert sample_player.spells == []
    assert sample_player.nspells == 0

    sample_player.spells.clear()
    sample_player.spells.extend([4, 5, 6])
    sample_player.nspells = 3

    saywhat = engine.cast_spell(player=sample_player, spell_id=50, target=None)
    assert saywhat.message_id == "S51M03"
    assert saywhat.context["forgot_spell_id"] in {4, 5, 6}
    assert len(sample_player.spells) == 2
    assert sample_player.nspells == 2
