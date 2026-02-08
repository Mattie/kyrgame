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

    result = engine.cast_spell(
        player=sample_player, spell_id=2, target="goblin", target_player=None
    )
    assert sample_player.spts < base_points
    assert result.animation == spells[2].splrou

    with pytest.raises(CooldownActiveError):
        engine.cast_spell(
            player=sample_player, spell_id=2, target="goblin", target_player=None
        )

    now += engine.effects[2].cooldown
    repeat = engine.cast_spell(
        player=sample_player, spell_id=2, target="ogre", target_player=None
    )
    assert repeat.context["target"] == "ogre"


def test_spell_effects_require_targets_and_resources(sample_player):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    sample_player.spts = 20

    engine = SpellEffectEngine(spells=spells, messages=messages)

    with pytest.raises(TargetingError):
        engine.cast_spell(
            player=sample_player, spell_id=5, target=None, target_player=None
        )

    sample_player.spts = 1
    with pytest.raises(ResourceCostError):
        engine.cast_spell(
            player=sample_player, spell_id=5, target="ogre", target_player=None
        )


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

    result = engine.cast_spell(
        player=sample_player, spell_id=16, target=None, target_player=None
    )
    assert result.message_id == "S16M00"
    assert constants.PlayerFlag.PEGASU & sample_player.flags

    willow = engine.cast_spell(
        player=sample_player, spell_id=62, target=None, target_player=None
    )
    assert willow.message_id == "S62M00"
    assert constants.PlayerFlag.WILLOW & sample_player.flags


def test_forget_spells_apply_spellbook_effects(sample_player):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    engine = SpellEffectEngine(spells=spells, messages=messages, rng=random.Random(1))

    target = _build_target(spells=[1, 2, 3], nspells=3)

    dumdum = engine.cast_spell(
        player=sample_player, spell_id=12, target="target", target_player=target
    )
    assert dumdum.message_id == "S13M03"
    assert target.spells == []
    assert target.nspells == 0

    target = _build_target(spells=[4, 5, 6], nspells=3)

    saywhat = engine.cast_spell(
        player=sample_player, spell_id=50, target="target", target_player=target
    )
    assert saywhat.message_id == "S51M03"
    assert saywhat.context["forgot_spell_id"] in {4, 5, 6}
    assert len(target.spells) == 2
    assert target.nspells == 2


def _build_target(**updates):
    player = fixtures.build_player()
    data = player.model_dump()
    data.update(updates)
    return player.model_copy(update=data)


def _find_object_id(objects, name):
    for obj in objects:
        if obj.name == name:
            return obj.id
    raise AssertionError(f"Missing object {name}")


def test_bookworm_wipes_target_spellbook_and_consumes_moonstone(sample_player):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    objects = fixtures.load_objects()
    moonstone_id = _find_object_id(objects, "moonstone")
    engine = SpellEffectEngine(spells=spells, messages=messages, objects=objects)

    sample_player = sample_player.model_copy(
        update={"gpobjs": [moonstone_id], "obvals": [0], "npobjs": 1}
    )
    target = _build_target(offspls=1, defspls=2, othspls=3)

    result = engine.cast_spell(
        player=sample_player,
        spell_id=4,
        target="target",
        target_player=target,
        apply_cost=False,
    )

    assert result.message_id == "S05M03"
    assert result.context["target_message_id"] == "S05M04"
    assert result.context["broadcast_message_id"] == "S05M05"
    assert target.offspls == 0
    assert target.defspls == 0
    assert target.othspls == 0
    assert sample_player.gpobjs == []
    assert sample_player.npobjs == 0


def test_bookworm_blocks_objpro_without_consuming_moonstone(sample_player):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    objects = fixtures.load_objects()
    moonstone_id = _find_object_id(objects, "moonstone")
    engine = SpellEffectEngine(spells=spells, messages=messages, objects=objects)

    sample_player = sample_player.model_copy(
        update={"gpobjs": [moonstone_id], "obvals": [0], "npobjs": 1}
    )
    target = _build_target(offspls=1, defspls=2, othspls=3)
    target.charms[constants.OBJPRO] = 1

    result = engine.cast_spell(
        player=sample_player,
        spell_id=4,
        target="target",
        target_player=target,
        apply_cost=False,
    )

    assert result.message_id == "S05M00"
    assert result.context["target_message_id"] == "S05M01"
    assert result.context["broadcast_message_id"] == "S05M02"
    assert target.offspls == 1
    assert sample_player.gpobjs == [moonstone_id]


def test_bookworm_requires_moonstone(sample_player):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    objects = fixtures.load_objects()
    engine = SpellEffectEngine(spells=spells, messages=messages, objects=objects)
    target = _build_target(offspls=1, defspls=2, othspls=3)
    sample_player = sample_player.model_copy(
        update={"gpobjs": [], "obvals": [], "npobjs": 0}
    )

    result = engine.cast_spell(
        player=sample_player,
        spell_id=4,
        target="target",
        target_player=target,
        apply_cost=False,
    )

    assert result.message_id == "MISS00"
    assert result.context["broadcast_message_id"] == "MISS01"
    assert target.offspls == 1


def test_dumdum_targets_other_player(sample_player):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    engine = SpellEffectEngine(spells=spells, messages=messages, rng=random.Random(1))
    target = _build_target(spells=[1, 2, 3], nspells=3)

    result = engine.cast_spell(
        player=sample_player,
        spell_id=12,
        target="target",
        target_player=target,
        apply_cost=False,
    )

    assert result.message_id == "S13M03"
    assert result.context["target_message_id"] == "S13M04"
    assert result.context["broadcast_message_id"] == "S13M05"
    assert target.spells == []
    assert target.nspells == 0


def test_dumdum_respects_objpro(sample_player):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    engine = SpellEffectEngine(spells=spells, messages=messages, rng=random.Random(1))
    target = _build_target(spells=[1], nspells=1)
    target.charms[constants.OBJPRO] = 1

    result = engine.cast_spell(
        player=sample_player,
        spell_id=12,
        target="target",
        target_player=target,
        apply_cost=False,
    )

    assert result.message_id == "S13M00"
    assert result.context["target_message_id"] == "S13M01"
    assert result.context["broadcast_message_id"] == "S13M02"
    assert target.nspells == 1


def test_saywhat_forgets_one_spell_on_target(sample_player):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    engine = SpellEffectEngine(spells=spells, messages=messages, rng=random.Random(2))
    target = _build_target(spells=[4, 5, 6], nspells=3)

    result = engine.cast_spell(
        player=sample_player,
        spell_id=50,
        target="target",
        target_player=target,
        apply_cost=False,
    )

    assert result.message_id == "S51M03"
    assert result.context["target_message_id"] == "S51M04"
    assert result.context["broadcast_message_id"] == "S51M05"
    assert result.context["forgot_spell_id"] in {4, 5, 6}
    assert result.context["forgot_spell_id"] not in target.spells
    assert len(target.spells) == 2
    assert target.nspells == 2


def test_saywhat_respects_objpro(sample_player):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    engine = SpellEffectEngine(spells=spells, messages=messages, rng=random.Random(2))
    target = _build_target(spells=[4, 5], nspells=2, spts=12)
    target.charms[constants.OBJPRO] = 1

    result = engine.cast_spell(
        player=sample_player,
        spell_id=50,
        target="target",
        target_player=target,
        apply_cost=False,
    )

    assert result.message_id == "S51M00"
    assert result.context["target_message_id"] == "S51M01"
    assert result.context["broadcast_message_id"] == "S51M02"
    assert target.spells == [4, 5]
    assert target.nspells == 2
    assert target.spts == 12


def test_saywhat_fails_when_target_has_no_spells(sample_player):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    engine = SpellEffectEngine(spells=spells, messages=messages, rng=random.Random(2))
    target = _build_target(spells=[], nspells=0)

    result = engine.cast_spell(
        player=sample_player,
        spell_id=50,
        target="target",
        target_player=target,
        apply_cost=False,
    )

    assert result.message_id == "S51M00"
    assert result.context["target_message_id"] == "S51M01"
    assert result.context["broadcast_message_id"] == "S51M02"
    assert target.spells == []
    assert target.nspells == 0


@pytest.mark.parametrize(
    ("spell_id", "failure_ids"),
    [
        (49, ("S50M00", "S50M01", "S50M02")),
        (56, ("S57M00", "S57M01", "S57M02")),
    ],
)
def test_sap_spells_fail_on_objpro(sample_player, spell_id, failure_ids):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    engine = SpellEffectEngine(spells=spells, messages=messages)
    target = _build_target(spts=20)
    target.charms[constants.OBJPRO] = 1

    result = engine.cast_spell(
        player=sample_player,
        spell_id=spell_id,
        target="target",
        target_player=target,
        apply_cost=False,
    )

    assert result.message_id == failure_ids[0]
    assert result.context["target_message_id"] == failure_ids[1]
    assert result.context["broadcast_message_id"] == failure_ids[2]
    assert target.spts == 20


@pytest.mark.parametrize(
    ("spell_id", "failure_ids"),
    [
        (49, ("S50M00", "S50M01", "S50M02")),
        (56, ("S57M00", "S57M01", "S57M02")),
    ],
)
def test_sap_spells_fail_on_zero_spell_points(
    sample_player, spell_id, failure_ids
):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    engine = SpellEffectEngine(spells=spells, messages=messages)
    target = _build_target(spts=0)

    result = engine.cast_spell(
        player=sample_player,
        spell_id=spell_id,
        target="target",
        target_player=target,
        apply_cost=False,
    )

    assert result.message_id == failure_ids[0]
    assert result.context["target_message_id"] == failure_ids[1]
    assert result.context["broadcast_message_id"] == failure_ids[2]
    assert target.spts == 0


@pytest.mark.parametrize(
    ("spell_id", "success_ids", "starting_points", "expected_points"),
    [
        (49, ("S50M03", "S50M04", "S50M05"), 10, 0),
        (56, ("S57M03", "S57M04", "S57M05"), 12, 4),
    ],
)
def test_sap_spells_decrement_spell_points(
    sample_player,
    spell_id,
    success_ids,
    starting_points,
    expected_points,
):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    engine = SpellEffectEngine(spells=spells, messages=messages)
    target = _build_target(spts=starting_points)

    result = engine.cast_spell(
        player=sample_player,
        spell_id=spell_id,
        target="target",
        target_player=target,
        apply_cost=False,
    )

    assert result.message_id == success_ids[0]
    assert result.context["target_message_id"] == success_ids[1]
    assert result.context["broadcast_message_id"] == success_ids[2]
    assert target.spts == expected_points


def test_howru_uses_target_hp_in_message(sample_player):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    engine = SpellEffectEngine(spells=spells, messages=messages)
    target = _build_target(hitpts=17)

    result = engine.cast_spell(
        player=sample_player,
        spell_id=33,
        target="target",
        target_player=target,
        apply_cost=False,
    )

    expected_text = messages.messages["S34M00"] % target.hitpts
    assert result.message_id == "S34M00"
    assert result.text == expected_text
    assert result.context["target_message_id"] == "S34M01"
    assert result.context["broadcast_message_id"] == "S34M02"


def _message_id_with_offset(base_id: str, offset: int) -> str:
    prefix, value = base_id[:-2], int(base_id[-2:])
    return f"{prefix}{value + offset:02d}"


@pytest.mark.parametrize(
    ("spell_id", "base_id", "damage", "protection", "mercy_level"),
    [
        (17, "S17M00", 4, constants.FIRPRO, 0),
        (19, "S19M00", 16, constants.ICEPRO, 1),
        (21, "S21M00", 22, constants.FIRPRO, 1),
        (22, "S22M00", 18, constants.LIGPRO, 2),
        (29, "S29M00", 24, constants.LIGPRO, 2),
        (32, "S32M00", 10, constants.FIRPRO, 1),
        (40, "S40M00", 6, constants.ICEPRO, 0),
        (48, "S48M00", 2, constants.OBJPRO, 0),
        (54, "S54M00", 20, constants.ICEPRO, 2),
        (66, "S66M00", 8, constants.LIGPRO, 1),
    ],
)
def test_direct_damage_spells_apply_damage(
    sample_player, spell_id, base_id, damage, protection, mercy_level
):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    engine = SpellEffectEngine(spells=spells, messages=messages)
    target = _build_target(hitpts=40, level=mercy_level + 1)
    target.charms[protection] = 0

    result = engine.cast_spell(
        player=sample_player,
        spell_id=spell_id,
        target="target",
        target_player=target,
        apply_cost=False,
    )

    assert result.message_id == _message_id_with_offset(base_id, 3)
    assert result.context["target_message_id"] == _message_id_with_offset(base_id, 4)
    assert result.context["broadcast_message_id"] == _message_id_with_offset(base_id, 5)
    assert target.hitpts == 40 - damage


def test_direct_damage_spells_respect_protection(sample_player):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    engine = SpellEffectEngine(spells=spells, messages=messages)
    target = _build_target(hitpts=40)
    target.charms[constants.FIRPRO] = 2

    result = engine.cast_spell(
        player=sample_player,
        spell_id=17,
        target="target",
        target_player=target,
        apply_cost=False,
    )

    assert result.message_id == "S17M00"
    assert result.context["target_message_id"] == "S17M01"
    assert result.context["broadcast_message_id"] == "S17M02"
    assert target.hitpts == 40


def test_direct_damage_spells_respect_mercy(sample_player):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    engine = SpellEffectEngine(spells=spells, messages=messages)
    target = _build_target(hitpts=40, level=2)

    result = engine.cast_spell(
        player=sample_player,
        spell_id=22,
        target="target",
        target_player=target,
        apply_cost=False,
    )

    assert result.message_id == "MERCYA"
    assert result.context["target_message_id"] == "MERCYB"
    assert result.context["broadcast_message_id"] == "MERCYC"
    assert target.hitpts == 40
