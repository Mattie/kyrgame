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
        player=sample_player, spell_id=13, target=None, target_player=None
    )
    assert sample_player.spts < base_points
    assert result.animation == spells[13].splrou
    assert result.message_id == "S14M00"

    with pytest.raises(CooldownActiveError):
        engine.cast_spell(
            player=sample_player, spell_id=13, target=None, target_player=None
        )

    now += engine.effects[13].cooldown
    repeat = engine.cast_spell(
        player=sample_player, spell_id=13, target=None, target_player=None
    )
    assert repeat.context["broadcast_message_id"] == "S14M01"


def test_spell_effects_require_targets_and_resources(sample_player):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    sample_player.spts = 20

    engine = SpellEffectEngine(spells=spells, messages=messages)

    with pytest.raises(TargetingError):
        engine.cast_spell(
            player=sample_player, spell_id=16, target=None, target_player=None
        )

    sample_player.spts = 1
    with pytest.raises(ResourceCostError):
        engine.cast_spell(
            player=sample_player,
            spell_id=16,
            target="ogre",
            target_player=_build_target(),
        )


def test_see_invisibility_spells_apply_legacy_charm_timers(sample_player):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    engine = SpellEffectEngine(spells=spells, messages=messages)

    sample_player.charms[constants.CharmSlot.INVISIBILITY] = 0
    tier_one = engine.cast_spell(player=sample_player, spell_id=6, target=None, target_player=None)
    assert sample_player.charms[constants.CharmSlot.INVISIBILITY] == 2 * 4
    assert tier_one.message_id == "S07M00"

    sample_player.charms[constants.CharmSlot.INVISIBILITY] = 0
    tier_two = engine.cast_spell(player=sample_player, spell_id=38, target=None, target_player=None)
    assert sample_player.charms[constants.CharmSlot.INVISIBILITY] == 2 * 4
    assert tier_two.message_id == "S39M00"

    sample_player.charms[constants.CharmSlot.INVISIBILITY] = 0
    tier_three = engine.cast_spell(player=sample_player, spell_id=37, target=None, target_player=None)
    assert sample_player.charms[constants.CharmSlot.INVISIBILITY] == 2 * 8
    assert tier_three.message_id == "S38M00"


@pytest.mark.parametrize(
    ("spell_id", "start_hp", "level", "expected_hp", "message_id"),
    [
        (1, 7, 9, 36, "SPM002"),
        (14, 10, 9, 35, "S15M00"),
        (42, 10, 9, 14, "S43M00"),
        (57, 10, 9, 22, "S58M00"),
        (42, 35, 9, 36, "S43M00"),
    ],
)
def test_healing_spells_match_legacy_hitpoint_caps(
    spell_id, start_hp, level, expected_hp, message_id
):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    engine = SpellEffectEngine(spells=spells, messages=messages)
    player = _build_caster(hitpts=start_hp, level=level)

    result = engine.cast_spell(
        player=player,
        spell_id=spell_id,
        target=None,
        target_player=None,
        apply_cost=False,
    )

    assert result.message_id == message_id
    assert player.hitpts == expected_hp


@pytest.mark.parametrize(
    ("spell_id", "duration", "message_id", "broadcast_id"),
    [(7, 2 * 2, "S08M00", "S08M01"), (44, 2 * 4, "S45M00", "S45M01")],
)
def test_invisibility_spells_apply_chgbod_state(
    sample_player, spell_id, duration, message_id, broadcast_id
):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    engine = SpellEffectEngine(spells=spells, messages=messages)
    sample_player.flags |= constants.PlayerFlag.PEGASU | constants.PlayerFlag.WILLOW
    sample_player.charms[constants.ALTNAM] = 3

    result = engine.cast_spell(
        player=sample_player,
        spell_id=spell_id,
        target=None,
        target_player=None,
        apply_cost=False,
    )

    assert result.message_id == message_id
    assert result.context["broadcast_message_id"] == broadcast_id
    assert sample_player.altnam == "Some Unseen Force"
    assert sample_player.attnam == "Unseen Force"
    assert sample_player.flags & constants.PlayerFlag.INVISF
    assert not sample_player.flags & constants.PlayerFlag.PEGASU
    assert not sample_player.flags & constants.PlayerFlag.WILLOW
    assert sample_player.charms[constants.ALTNAM] == 3 + duration


def test_destroy_one_item_spell_removes_targets_first_inventory_item(sample_player):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    engine = SpellEffectEngine(spells=spells, messages=messages)
    target = _build_target(
        altnam="Target",
        attnam="target",
        gpobjs=[0, 1],
        obvals=[10, 20],
        npobjs=2,
    )

    result = engine.cast_spell(
        player=sample_player,
        spell_id=2,
        target="target",
        target_player=target,
        apply_cost=False,
    )

    assert result.message_id == "SPM004"
    assert result.context["target_message_id"] == "SPM005"
    assert result.context["broadcast_message_id"] == "SPM006"
    assert result.context["destroyed_object_id"] == 0
    assert target.gpobjs == [1]
    assert target.obvals == [20]
    assert target.npobjs == 1


def test_destroy_all_items_spell_clears_target_inventory(sample_player):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    engine = SpellEffectEngine(spells=spells, messages=messages)
    target = _build_target(
        altnam="Target",
        attnam="target",
        gpobjs=[0, 1],
        obvals=[10, 20],
        npobjs=2,
    )

    result = engine.cast_spell(
        player=sample_player,
        spell_id=3,
        target="target",
        target_player=target,
        apply_cost=False,
    )

    assert result.message_id == "SPM007"
    assert result.context["target_message_id"] == "SPM008"
    assert result.context["broadcast_message_id"] == "SPM009"
    assert target.gpobjs == []
    assert target.obvals == []
    assert target.npobjs == 0


def test_clutzopho_drops_target_inventory_into_caster_room(sample_player):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    objects = fixtures.load_objects()
    locations = fixtures.load_locations()
    engine = SpellEffectEngine(
        spells=spells, messages=messages, objects=objects, locations=locations
    )
    sample_player.gamloc = 7
    location = engine.locations[7]
    object.__setattr__(location, "objects", [2])
    object.__setattr__(location, "nlobjs", 1)
    target = _build_target(
        altnam="Target",
        attnam="target",
        gpobjs=[0, 1],
        obvals=[10, 20],
        npobjs=2,
    )

    result = engine.cast_spell(
        player=sample_player,
        spell_id=10,
        target="target",
        target_player=target,
        apply_cost=False,
    )

    assert result.message_id == "S11M02"
    assert result.context["target_message_id"] == "S11M03"
    assert result.context["broadcast_message_id"] == "S11M04"
    assert result.context["room_objects_update"] == {"location": 7, "objects": [2, 1, 0]}
    assert result.context["dropped_object_ids"] == [1, 0]
    assert target.gpobjs == []
    assert target.obvals == []
    assert target.npobjs == 0
    assert engine.locations[7].objects == [2, 1, 0]


def test_mower_destroys_pickup_ground_items_only(sample_player):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    objects = fixtures.load_objects()
    locations = fixtures.load_locations()
    engine = SpellEffectEngine(
        spells=spells, messages=messages, objects=objects, locations=locations
    )
    sample_player.gamloc = 7
    location = engine.locations[7]
    object.__setattr__(location, "objects", [0, 1, 45])
    object.__setattr__(location, "nlobjs", 3)

    result = engine.cast_spell(
        player=sample_player,
        spell_id=41,
        target=None,
        target_player=None,
        apply_cost=False,
    )

    assert result.message_id == "YOUCASTSPELL"
    assert messages.messages[result.message_id] == "...You cast the spell!"
    assert result.context["destroyed_object_ids"] == [0, 1]
    assert result.context["room_messages"] == [
        {
            "message_id": None,
            "text": "***\rThe ruby at the village temple vanishes!\r",
        },
        {
            "message_id": None,
            "text": "***\rThe emerald at the village temple vanishes!\r",
        },
    ]
    assert result.context["room_objects_update"] == {"location": 7, "objects": [45]}
    assert engine.locations[7].objects == [45]


def test_pickpoc_steals_first_target_item_when_caster_has_space(sample_player):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    engine = SpellEffectEngine(spells=spells, messages=messages)
    sample_player = _build_caster(gpobjs=[2], obvals=[30], npobjs=1)
    target = _build_target(
        altnam="Target",
        attnam="target",
        gpobjs=[0, 1],
        obvals=[10, 20],
        npobjs=2,
    )

    result = engine.cast_spell(
        player=sample_player,
        spell_id=46,
        target="target",
        target_player=target,
        apply_cost=False,
    )

    assert result.message_id == "S47M03"
    assert result.context["target_message_id"] == "S47M04"
    assert result.context["broadcast_message_id"] == "S47M05"
    assert result.context["stolen_object_id"] == 0
    assert sample_player.gpobjs == [2, 0]
    assert sample_player.obvals == [30, 0]
    assert sample_player.npobjs == 2
    assert target.gpobjs == [1]
    assert target.obvals == [20]
    assert target.npobjs == 1


def test_pickpoc_failure_uses_legacy_room_failure_message(sample_player):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    engine = SpellEffectEngine(spells=spells, messages=messages)
    sample_player = _build_caster(gpobjs=[2], obvals=[30], npobjs=1)
    target = _build_target(
        altnam="Target",
        attnam="target",
        charms=[0] * constants.NCHARM,
        gpobjs=[],
        obvals=[],
        npobjs=0,
    )

    result = engine.cast_spell(
        player=sample_player,
        spell_id=46,
        target="target",
        target_player=target,
        apply_cost=False,
    )

    assert result.success is False
    assert result.message_id == "S47M00"
    assert result.context["target_message_id"] == "S47M01"
    assert result.context["broadcast_message_id"] == "S47M00"
    assert result.context["broadcast"] == (
        "...You cast the spell but some magical resistance prevents it from succeeding."
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


def test_object_gems_and_curios_are_message_only_effects():
    objects = fixtures.load_objects()
    messages = fixtures.load_messages()
    engine = ObjectEffectEngine(objects=objects, messages=messages)

    for object_id in (0, 6, 11, 13, 29, 39, 44):
        result = engine.use_object(player_id="hero", object_id=object_id, room_id=1)
        assert result.message_id == f"KID{object_id:03d}"


def test_drinkable_object_consumes_inventory_item_and_has_drink_action():
    objects = fixtures.load_objects()
    messages = fixtures.load_messages()
    engine = ObjectEffectEngine(objects=objects, messages=messages)
    player = _build_target(gpobjs=[12, 31], obvals=[0, 0], npobjs=2, hitpts=10, level=10)

    result = engine.use_object(
        player_id="hero", object_id=31, room_id=7, player=player, action="drink"
    )

    assert result.message_id == "OBJM08"
    assert player.gpobjs == [12]
    assert player.npobjs == 1


def test_drinkable_object_rejects_wrong_action():
    objects = fixtures.load_objects()
    messages = fixtures.load_messages()
    engine = ObjectEffectEngine(objects=objects, messages=messages)
    player = _build_target(gpobjs=[12], obvals=[0], npobjs=1)

    with pytest.raises(TargetingError):
        engine.use_object(
            player_id="hero", object_id=12, room_id=7, player=player, action="read"
        )


def test_readable_object_requires_read_action_and_consumes_scroll():
    objects = fixtures.load_objects()
    messages = fixtures.load_messages()
    engine = ObjectEffectEngine(objects=objects, messages=messages)
    player = _build_target(gpobjs=[35], obvals=[0], npobjs=1)

    result = engine.use_object(
        player_id="hero", object_id=35, room_id=1, player=player, action="read"
    )

    assert result.message_id == "KID035"
    assert player.gpobjs == []


def test_dragonstaff_rub_requires_callback_and_reports_pending_when_missing():
    objects = fixtures.load_objects()
    messages = fixtures.load_messages()
    player = _build_target(gpobjs=[30], obvals=[0], npobjs=1)

    engine = ObjectEffectEngine(objects=objects, messages=messages)
    pending = engine.use_object(
        player_id="hero", object_id=30, room_id=42, player=player, action="rub"
    )
    assert pending.message_id == "ZMSG14"

    calls: list[tuple[str, int]] = []

    def dragonstaff_callback(player, room_id):
        calls.append((player.plyrid, room_id))
        return "ZMSG13"

    engine = ObjectEffectEngine(
        objects=objects, messages=messages, dragonstaff_callback=dragonstaff_callback
    )
    player = _build_target(gpobjs=[30], obvals=[0], npobjs=1)
    summoned = engine.use_object(
        player_id="hero", object_id=30, room_id=42, player=player, action="rub"
    )
    assert summoned.message_id == "ZMSG13"
    assert calls == [(player.plyrid, 42)]


def test_aim_items_require_target_and_non_props_enforce_room_context():
    objects = fixtures.load_objects()
    messages = fixtures.load_messages()
    engine = ObjectEffectEngine(objects=objects, messages=messages)

    with pytest.raises(TargetingError):
        engine.use_object(player_id="hero", object_id=34, room_id=7, action="aim")

    with pytest.raises(TargetingError):
        engine.use_object(player_id="hero", object_id=45, room_id=7, action="get")


def test_transformation_spells_toggle_player_flags(sample_player):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    engine = SpellEffectEngine(spells=spells, messages=messages)

    result = engine.cast_spell(
        player=sample_player, spell_id=15, target=None, target_player=None
    )
    assert result.message_id == "S16M00"
    assert constants.PlayerFlag.PEGASU & sample_player.flags

    willow = engine.cast_spell(
        player=sample_player, spell_id=61, target=None, target_player=None
    )
    assert willow.message_id == "S62M00"
    assert constants.PlayerFlag.WILLOW & sample_player.flags

    dragon = engine.cast_spell(
        player=sample_player, spell_id=23, target=None, target_player=None
    )
    assert dragon.message_id == "S24M00"
    assert constants.PlayerFlag.PDRAGN & sample_player.flags
    assert not (constants.PlayerFlag.WILLOW & sample_player.flags)




def test_goto_spell_moves_player_and_applies_legacy_room_validation(sample_player):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    locations = fixtures.load_locations()
    engine = SpellEffectEngine(spells=spells, messages=messages, locations=locations)

    sample_player.gamloc = 0
    sample_player.pgploc = 0

    success = engine.cast_spell(
        player=sample_player,
        spell_id=22,
        target="1",
        target_player=None,
    )
    assert success.message_id == "S23M02"
    assert sample_player.pgploc == 0
    assert sample_player.gamloc == 1
    assert success.context["move_from_room"] == 0
    assert success.context["move_to_room"] == 1

    fresh_engine = SpellEffectEngine(spells=spells, messages=messages, locations=locations)
    fail = fresh_engine.cast_spell(
        player=sample_player,
        spell_id=22,
        target="999",
        target_player=None,
    )
    assert fail.success is False
    assert fail.message_id == "S23M00"

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


def _build_caster(**updates):
    player = fixtures.build_player()
    data = player.model_dump()
    data["spts"] = 50
    data.update(updates)
    return player.model_copy(update=data)


class _FeeluckBoundaryRng:
    def randrange(self, low, high):
        assert (low, high) == (0, 218)
        return 217

    def randint(self, low, high):
        assert (low, high) == (0, 218)
        return 218


@pytest.mark.parametrize(
    ("spell_id", "expected_charms"),
    [
        (8, {constants.FIRPRO: 4, constants.ICEPRO: 4, constants.LIGPRO: 4, constants.OBJPRO: 4}),
        (24, {constants.OBJPRO: 4}),
        (25, {constants.ICEPRO: 16}),
        (32, {constants.ICEPRO: 6}),
        (34, {constants.FIRPRO: 16}),
        (40, {constants.OBJPRO: 6}),
        (48, {constants.ICEPRO: 20}),
        (52, {constants.FIRPRO: 6}),
        (54, {constants.LIGPRO: 6}),
        (55, {constants.LIGPRO: 20}),
        (59, {constants.LIGPRO: 16}),
        (63, {constants.FIRPRO: 20}),
    ],
)
def test_protection_spells_set_charm_values(spell_id, expected_charms):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    engine = SpellEffectEngine(spells=spells, messages=messages)
    player = _build_caster()
    player.charms = [1 for _ in player.charms]

    engine.cast_spell(
        player=player,
        spell_id=spell_id,
        target=None,
        target_player=None,
        apply_cost=False,
    )

    for slot, expected in expected_charms.items():
        assert player.charms[slot] == expected


def test_abbracada_adds_object_protection():
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    engine = SpellEffectEngine(spells=spells, messages=messages)
    player = _build_caster()
    player.charms[constants.OBJPRO] = 3

    result = engine.cast_spell(
        player=player,
        spell_id=0,
        target=None,
        target_player=None,
        apply_cost=False,
    )

    assert result.message_id == "SPM000"
    assert player.charms[constants.OBJPRO] == 11


def test_ibebad_requires_sapphire_and_sets_protection():
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    objects = fixtures.load_objects()
    sapphire_id = _find_object_id(objects, "sapphire")
    engine = SpellEffectEngine(spells=spells, messages=messages, objects=objects)
    player = _build_caster(gpobjs=[sapphire_id], obvals=[0], npobjs=1)

    result = engine.cast_spell(
        player=player,
        spell_id=35,
        target=None,
        target_player=None,
        apply_cost=False,
    )

    assert result.message_id == "S36M00"
    assert player.gpobjs == []
    assert player.npobjs == 0
    assert player.charms[constants.FIRPRO] == 8
    assert player.charms[constants.ICEPRO] == 8
    assert player.charms[constants.LIGPRO] == 8
    assert player.charms[constants.OBJPRO] == 8


def test_ibebad_fails_without_sapphire():
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    objects = fixtures.load_objects()
    engine = SpellEffectEngine(spells=spells, messages=messages, objects=objects)
    player = _build_caster()
    player.charms = [0 for _ in player.charms]

    result = engine.cast_spell(
        player=player,
        spell_id=35,
        target=None,
        target_player=None,
        apply_cost=False,
    )

    assert result.message_id == "MISS00"
    assert player.charms[constants.FIRPRO] == 0
    assert player.charms[constants.ICEPRO] == 0
    assert player.charms[constants.LIGPRO] == 0
    assert player.charms[constants.OBJPRO] == 0


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


def test_whoub_reports_true_identity_without_changing_target_aliases(sample_player):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    engine = SpellEffectEngine(spells=spells, messages=messages)
    target = _build_target(plyrid="truth", attnam="Mirror Mask", altnam="A Willowisp")
    target.charms[constants.CharmSlot.ALTERNATE_NAME] = 6

    result = engine.cast_spell(
        player=sample_player,
        spell_id=64,
        target="Mirror Mask",
        target_player=target,
        apply_cost=False,
    )

    assert result.message_id == "S65M00"
    assert result.text == messages.messages["S65M00"] % target.plyrid
    assert result.context["target_message_id"] == "S65M01"
    assert result.context["broadcast_message_id"] == "S65M02"
    assert target.altnam == "A Willowisp"
    assert target.attnam == "Mirror Mask"
    assert target.charms[constants.CharmSlot.ALTERNATE_NAME] == 6


def test_nosey_reports_targets_memorized_spells_with_legacy_list_format(sample_player):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    engine = SpellEffectEngine(spells=spells, messages=messages)
    target = _build_target(altnam="Target", spells=[16, 39, 65], nspells=3)

    result = engine.cast_spell(
        player=sample_player,
        spell_id=43,
        target="Target",
        target_player=target,
        apply_cost=False,
    )

    assert result.message_id == "S44M00"
    assert '"fpandl", "koolit", and "zapher" memorized.' in result.text
    assert result.context["target_message_id"] == "S44M01"
    assert result.context["broadcast_message_id"] == "S44M02"
    assert result.context["broadcast_exclude_player"] == target.plyrid


def test_nosey_uses_shared_memorized_spell_lookup_even_if_nspells_is_stale(sample_player):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    engine = SpellEffectEngine(spells=spells, messages=messages)
    target = _build_target(altnam="Target", spells=[16], nspells=0)

    result = engine.cast_spell(
        player=sample_player,
        spell_id=43,
        target="Target",
        target_player=target,
        apply_cost=False,
    )

    assert result.message_id == "S44M00"
    assert '"fpandl" memorized.' in result.text


@pytest.mark.parametrize(
    ("target_spells", "target_nspells", "expected_suffix"),
    [
        ([], 0, "no spells memorized."),
        ([16], 1, '"fpandl" memorized.'),
        ([16, 39], 2, '"fpandl" and "koolit" memorized.'),
    ],
)
def test_nosey_formats_empty_one_and_two_spell_lists(
    sample_player, target_spells, target_nspells, expected_suffix
):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    engine = SpellEffectEngine(spells=spells, messages=messages)
    target = _build_target(altnam="Target", spells=target_spells, nspells=target_nspells)

    result = engine.cast_spell(
        player=sample_player,
        spell_id=43,
        target="Target",
        target_player=target,
        apply_cost=False,
    )

    assert result.message_id == "S44M00"
    assert result.text.endswith(expected_suffix)


def test_whereami_reports_coordinate_and_broadcasts_to_room(sample_player):
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    engine = SpellEffectEngine(spells=spells, messages=messages)
    sample_player.gamloc = 123

    result = engine.cast_spell(
        player=sample_player,
        spell_id=62,
        target=None,
        target_player=None,
        apply_cost=False,
    )

    expected_broadcast = messages.messages["S63M01"] % (
        sample_player.altnam,
        models.possessive_pronoun(sample_player),
    )

    assert result.message_id == "S63M00"
    assert result.text == messages.messages["S63M00"] % 123
    assert result.context["broadcast_message_id"] == "S63M01"
    assert result.context["broadcast"] == expected_broadcast


def test_world_mutation_spells_emit_room_object_updates_and_teleport_context():
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    objects = fixtures.load_objects()
    locations = fixtures.load_locations()
    rose_id = _find_object_id(objects, "rose")
    room = locations[7].model_copy(update={"objects": [0, 45, rose_id], "nlobjs": 3})
    indexed_locations = [room if location.id == 7 else location for location in locations]
    engine = SpellEffectEngine(
        spells=spells,
        messages=messages,
        rng=random.Random(4),
        objects=objects,
        locations=indexed_locations,
    )
    player = _build_caster(gamloc=7, pgploc=7, gpobjs=[rose_id], obvals=[0], npobjs=1)

    luck = engine.cast_spell(
        player=player,
        spell_id=13,
        target=None,
        target_player=None,
        apply_cost=False,
    )
    assert luck.message_id == "S14M00"
    assert luck.context["broadcast_message_id"] == "S14M01"
    assert luck.context["move_from_room"] == 7
    assert luck.context["move_to_room"] == 60
    assert "blue light" in luck.context["departure_emote"]
    assert "appeared in a blue" in luck.context["arrival_text"]

    earthquake = engine.cast_spell(
        player=player,
        spell_id=58,
        target=None,
        target_player=None,
        apply_cost=False,
    )
    assert earthquake.message_id == "S59M00"
    assert player.gpobjs == []
    assert earthquake.context["room_objects_update"] == {"location": 60, "objects": []}
    assert earthquake.context["area_damage"]["damage"] == 50
    assert earthquake.context["global_broadcast_message_id"] == "S59M02"
    assert earthquake.context["room_broadcast_message_id"] == "S59M03"
    assert earthquake.context["room_broadcast_include_sender"] is True


def test_feeluck_uses_legacy_exclusive_room_bound():
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    engine = SpellEffectEngine(
        spells=spells,
        messages=messages,
        rng=_FeeluckBoundaryRng(),
    )
    player = _build_caster(
        gamloc=7,
        pgploc=7,
        plyrid="Necro",
        altnam="Some Unseen Force",
        attnam="Unseen Force",
        flags=int(constants.PlayerFlag.LOADED | constants.PlayerFlag.INVISF),
    )

    luck = engine.cast_spell(
        player=player,
        spell_id=13,
        target=None,
        target_player=None,
        apply_cost=False,
    )

    assert luck.message_id == "S14M00"
    assert luck.context["broadcast_message_id"] == "S14M01"
    assert luck.context["move_from_room"] == 7
    assert luck.context["move_to_room"] == 217
    assert luck.context["move_to_room"] != 218
    assert player.gamloc == 217
    assert player.pgploc == 7
    assert "blue light" in luck.context["departure_emote"]
    assert luck.context["arrival_text"] == (
        "*** Some Unseen Force has just appeared in a blue!"
    )


def test_hocus_detect_scry_and_servant_spells_surface_legacy_payloads():
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    objects = fixtures.load_objects()
    locations = fixtures.load_locations()
    bloodstone_id = _find_object_id(objects, "bloodstone")
    engine = SpellEffectEngine(
        spells=spells,
        messages=messages,
        rng=random.Random(3),
        objects=objects,
        locations=locations,
    )
    caster = _build_caster(gpobjs=[bloodstone_id], obvals=[0], npobjs=1)
    target = _build_target(altnam="Target", attnam="Target", spts=17, gamloc=1)
    target.charms[constants.FIRPRO] = 2
    target.charms[constants.ICEPRO] = 2
    target.charms[constants.LIGPRO] = 2
    target.charms[constants.OBJPRO] = 2

    detect = engine.cast_spell(
        player=caster,
        spell_id=11,
        target="target",
        target_player=target,
        apply_cost=False,
    )
    assert detect.message_id == "S12M00"
    assert detect.context["target_message_id"] == "S12M01"
    assert detect.context["broadcast_message_id"] == "S12M02"
    assert "17" in detect.text

    dispel = engine.cast_spell(
        player=caster,
        spell_id=27,
        target="target",
        target_player=target,
        apply_cost=False,
    )
    assert dispel.message_id == "S28M00"
    assert dispel.context["target_message_id"] == "S28M01"
    assert dispel.context["broadcast_message_id"] == "S28M02"
    assert caster.gpobjs == []
    assert target.charms[constants.FIRPRO] == 0
    assert target.charms[constants.ICEPRO] == 0
    assert target.charms[constants.LIGPRO] == 0
    assert target.charms[constants.OBJPRO] == 0

    scry = engine.cast_spell(
        player=caster,
        spell_id=45,
        target="target",
        target_player=target,
        apply_cost=False,
    )
    assert scry.message_id == "KSPM04"
    assert scry.context["target_message_id"] == "KSPM06"
    assert scry.context["broadcast_message_id"] == "KSPM07"
    assert scry.context["scry_location"] == target.gamloc
    assert scry.context["scry_message_id"] == "KRD001"
    assert engine.effects[45].global_target_player
    assert engine.effects[45].allow_missing_target_player

    servant = engine.cast_spell(
        player=caster,
        spell_id=66,
        target="target",
        target_player=target,
        apply_cost=False,
    )
    assert servant.message_id == "S67M02"
    assert servant.context["target_room_message_id"] == "S67M04"
    assert servant.context["target_message_id"] in {"S67M05", "S67M08"}
    assert servant.context["target_room_result_message_id"] in {"S67M06", "S67M09"}
    assert servant.context["target_message_after_room_events"] is True
    assert engine.effects[66].global_target_player
    assert engine.effects[66].allow_missing_target_player


def _message_id_with_offset(base_id: str, offset: int) -> str:
    prefix, value = base_id[:-2], int(base_id[-2:])
    return f"{prefix}{value + offset:02d}"


@pytest.mark.parametrize(
    ("spell_id", "base_id", "damage", "protection", "mercy_level"),
    [
        (16, "S17M00", 4, constants.FIRPRO, 0),
        (18, "S19M00", 16, constants.ICEPRO, 1),
        (20, "S21M00", 22, constants.FIRPRO, 1),
        (21, "S22M00", 18, constants.LIGPRO, 2),
        (28, "S29M00", 24, constants.LIGPRO, 2),
        (31, "S32M00", 10, constants.FIRPRO, 1),
        (39, "S40M00", 6, constants.ICEPRO, 0),
        (47, "S48M00", 2, constants.OBJPRO, 0),
        (53, "S54M00", 20, constants.ICEPRO, 2),
        (65, "S66M00", 8, constants.LIGPRO, 1),
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
        spell_id=16,
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
        spell_id=21,
        target="target",
        target_player=target,
        apply_cost=False,
    )

    assert result.message_id == "MERCYA"
    assert result.context["target_message_id"] == "MERCYB"
    assert result.context["broadcast_message_id"] == "MERCYC"
    assert target.hitpts == 40
