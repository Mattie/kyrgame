from kyrgame import constants, fixtures
from kyrgame.player_lifecycle import (
    apply_death_recovery_plan,
    build_modern_death_recovery_plan,
    initialize_player_for_first_login,
    reset_player_after_death,
)


class FixedRecoveryRng:
    def __init__(self, *, shuffle_result=None, randrange_values=None):
        self.shuffle_result = shuffle_result
        self.randrange_values = list(randrange_values or [])

    def shuffle(self, values):
        if self.shuffle_result is None:
            return
        values[:] = list(self.shuffle_result)

    def randrange(self, low, high):
        if not self.randrange_values:
            raise AssertionError(f"Unexpected randrange({low}, {high})")
        return self.randrange_values.pop(0)


def test_reset_player_after_death_matches_legacy_initgp_state():
    player = fixtures.build_player().model_copy(
        update={
            "uidnam": "uid-123",
            "plyrid": "hero",
            "altnam": "Some psuedo dragon",
            "attnam": "psuedo dragon",
            "gpobjs": [0, 1],
            "nmpdes": 12,
            "level": 10,
            "gamloc": 302,
            "pgploc": 301,
            "flags": int(
                constants.PlayerFlag.LOADED
                | constants.PlayerFlag.FEMALE
                | constants.PlayerFlag.MARRYD
                | constants.PlayerFlag.GOTKYG
                | constants.PlayerFlag.PDRAGN
            ),
            "gold": 77,
            "npobjs": 2,
            "obvals": [10, 20],
            "nspells": 2,
            "spts": 21,
            "hitpts": 0,
            "offspls": 123,
            "defspls": 456,
            "othspls": 789,
            "charms": [1] * constants.NCHARM,
            "spells": [1, 23],
            "gemidx": 3,
            "stones": [9, 8, 7, 6],
            "macros": 19,
            "stumpi": 8,
            "spouse": "beloved",
        }
    )
    birthstones = iter([2, 3, 4, 5])

    reset = reset_player_after_death(
        player,
        lambda low, high: next(birthstones),
    )

    assert reset.old_room == 302
    assert reset.old_name == "Some psuedo dragon"
    assert reset.player_id == "hero"
    assert player.uidnam == "uid-123"
    assert player.plyrid == "hero"
    assert player.altnam == "hero"
    assert player.attnam == "hero"
    assert player.gamloc == 0
    assert player.pgploc == 0
    assert player.nmpdes == constants.level_to_nmpdes(1)
    assert player.flags == int(constants.PlayerFlag.LOADED | constants.PlayerFlag.FEMALE)
    assert player.level == 1
    assert player.hitpts == 4
    assert player.spts == 2
    assert player.gold == 0
    assert player.gpobjs == []
    assert player.obvals == []
    assert player.npobjs == 0
    assert player.nspells == 0
    assert player.spells == []
    assert player.offspls == 0
    assert player.defspls == 0
    assert player.othspls == 0
    assert player.charms == [0] * constants.NCHARM
    assert player.gemidx == 0
    assert player.stones == [2, 3, 4, 5]
    assert player.macros == 0
    assert player.stumpi == 0
    assert player.spouse == ""


def test_initialize_player_for_first_login_matches_legacy_initgp_state():
    player = fixtures.build_player()
    birthstones = iter([1, 4, 7, 10])

    initialize_player_for_first_login(
        player,
        player_id="Merlin",
        uidnam="Merlin",
        birthstone_picker=lambda low, high: next(birthstones),
    )

    assert player.uidnam == "Merlin"
    assert player.plyrid == "Merlin"
    assert player.altnam == "Merlin"
    assert player.attnam == "Merlin"
    assert player.gamloc == 0
    assert player.pgploc == 0
    assert player.nmpdes == constants.level_to_nmpdes(1)
    assert player.flags == int(constants.PlayerFlag.LOADED)
    assert player.level == 1
    assert player.hitpts == 4
    assert player.spts == 2
    assert player.gold == 0
    assert player.gpobjs == []
    assert player.obvals == []
    assert player.npobjs == 0
    assert player.nspells == 0
    assert player.spells == []
    assert player.offspls == 0
    assert player.defspls == 0
    assert player.othspls == 0
    assert player.charms == [0] * constants.NCHARM
    assert player.gemidx == 0
    assert player.stones == [1, 4, 7, 10]
    assert player.macros == 0
    assert player.stumpi == 0
    assert player.spouse == ""


def test_initialize_player_for_first_login_uses_legacy_birthstone_range():
    player = fixtures.build_player()
    calls = []

    def picker(low, high):
        calls.append((low, high))
        return high - 1

    initialize_player_for_first_login(
        player,
        player_id="Merlin",
        uidnam="Merlin",
        birthstone_picker=picker,
    )

    assert calls == [(0, 12)] * constants.BIRTHSTONE_SLOTS
    assert player.stones == [11, 11, 11, 11]


def test_modern_death_recovery_clears_memorized_spells_but_preserves_spellbook():
    player = fixtures.build_player().model_copy(
        update={
            "uidnam": "uid-123",
            "plyrid": "hero",
            "altnam": "Some willowisp",
            "attnam": "willowisp",
            "level": 10,
            "nmpdes": constants.level_to_nmpdes(10),
            "gamloc": 218,
            "pgploc": 217,
            "hitpts": 0,
            "spts": 1,
            "gold": 77,
            "gpobjs": [0, 1],
            "obvals": [10, 20],
            "npobjs": 2,
            "spells": [1, 23],
            "nspells": 2,
            "offspls": 123,
            "defspls": 456,
            "othspls": 789,
            "charms": [1] * constants.NCHARM,
            "flags": int(
                constants.PlayerFlag.LOADED
                | constants.PlayerFlag.FEMALE
                | constants.PlayerFlag.BRFSTF
                | constants.PlayerFlag.MARRYD
                | constants.PlayerFlag.BLESSD
                | constants.PlayerFlag.GOTKYG
                | constants.PlayerFlag.WILLOW
            ),
            "gemidx": 3,
            "stones": [9, 8, 7, 6],
            "macros": 2,
            "stumpi": 8,
            "spouse": "beloved",
            "honor_mode": False,
        }
    )
    locations = {location.id: location for location in fixtures.load_locations()}
    locations[218] = locations[218].model_copy(update={"objects": [], "nlobjs": 0})

    plan = build_modern_death_recovery_plan(
        player,
        locations=locations,
        rng=FixedRecoveryRng(),
    )
    apply_death_recovery_plan(player, locations, plan)

    assert plan.mode == "modern_death_recovery"
    assert plan.old_room == 218
    assert plan.old_level == 10
    assert plan.new_level == 9
    assert player.uidnam == "uid-123"
    assert player.plyrid == "hero"
    assert player.altnam == "hero"
    assert player.attnam == "hero"
    assert player.level == 9
    assert player.gamloc == constants.WILLOW_ROOM_ID
    assert player.pgploc == constants.WILLOW_ROOM_ID
    assert player.nmpdes == constants.level_to_nmpdes(9)
    assert player.hitpts == 36
    assert player.spts == 18
    assert player.gold == 0
    assert player.gpobjs == []
    assert player.obvals == []
    assert player.npobjs == 0
    assert player.spells == []
    assert player.nspells == 0
    assert player.offspls == 123
    assert player.defspls == 456
    assert player.othspls == 789
    assert player.charms == [0] * constants.NCHARM
    assert player.gemidx == 3
    assert player.stones == [9, 8, 7, 6]
    assert player.macros == constants.MODERN_DEATH_EXHAUSTION_MACROS
    assert player.stumpi == 8
    assert player.spouse == "beloved"
    assert player.honor_mode is False
    assert player.flags == int(
        constants.PlayerFlag.LOADED
        | constants.PlayerFlag.FEMALE
        | constants.PlayerFlag.BRFSTF
        | constants.PlayerFlag.MARRYD
        | constants.PlayerFlag.BLESSD
        | constants.PlayerFlag.GOTKYG
    )
    assert plan.room_object_updates[0].room_id == 218
    assert plan.room_object_updates[0].dropped_items == (0, 1)
    assert locations[218].objects == [0, 1]


def test_modern_death_recovery_clears_gotkyg_below_level_9():
    player = fixtures.build_player().model_copy(
        update={
            "level": 9,
            "gamloc": 218,
            "pgploc": 218,
            "flags": int(constants.PlayerFlag.LOADED | constants.PlayerFlag.GOTKYG),
            "honor_mode": False,
        }
    )
    locations = {location.id: location for location in fixtures.load_locations()}
    locations[218] = locations[218].model_copy(update={"objects": [], "nlobjs": 0})

    plan = build_modern_death_recovery_plan(
        player,
        locations=locations,
        rng=FixedRecoveryRng(),
    )
    apply_death_recovery_plan(player, locations, plan)

    assert plan.new_level == 8
    assert not player.flags & int(constants.PlayerFlag.GOTKYG)


def test_modern_death_recovery_filters_castle_soulstone_and_kyragem():
    player = fixtures.build_player().model_copy(
        update={
            "level": 12,
            "gamloc": constants.MODERN_DEATH_CASTLE_MIN_ROOM,
            "pgploc": constants.MODERN_DEATH_CASTLE_MIN_ROOM,
            "flags": int(constants.PlayerFlag.LOADED | constants.PlayerFlag.GOTKYG),
            "gpobjs": [
                constants.SOULSTONE_OBJECT_ID,
                0,
                constants.KYRAGEM_OBJECT_ID,
            ],
            "obvals": [1, 2, 3],
            "npobjs": 3,
            "honor_mode": False,
        }
    )
    locations = {location.id: location for location in fixtures.load_locations()}
    locations[constants.MODERN_DEATH_CASTLE_MIN_ROOM] = locations[
        constants.MODERN_DEATH_CASTLE_MIN_ROOM
    ].model_copy(update={"objects": [], "nlobjs": 0})

    plan = build_modern_death_recovery_plan(
        player,
        locations=locations,
        rng=FixedRecoveryRng(),
    )
    apply_death_recovery_plan(player, locations, plan)

    assert plan.filtered_items == (
        constants.SOULSTONE_OBJECT_ID,
        constants.KYRAGEM_OBJECT_ID,
    )
    assert plan.room_object_updates[0].dropped_items == (0,)
    assert not player.flags & int(constants.PlayerFlag.GOTKYG)
    assert locations[constants.MODERN_DEATH_CASTLE_MIN_ROOM].objects == [0]


def test_modern_death_recovery_spills_to_adjacent_and_dark_forest_rooms():
    player = fixtures.build_player().model_copy(
        update={
            "level": 10,
            "gamloc": 1,
            "pgploc": 1,
            "gpobjs": [0, 1, 2, 3, 4, 5],
            "obvals": [0, 0, 0, 0, 0, 0],
            "npobjs": 6,
            "honor_mode": False,
        }
    )
    locations = {location.id: location for location in fixtures.load_locations()}
    locations[1] = locations[1].model_copy(
        update={"objects": [10, 11, 12, 13, 14], "nlobjs": 5}
    )
    locations[2] = locations[2].model_copy(
        update={"objects": [20, 21, 22, 23, 24], "nlobjs": 5}
    )
    locations[0] = locations[0].model_copy(
        update={"objects": [30, 31, 32, 33, 34], "nlobjs": 5}
    )
    locations[95] = locations[95].model_copy(
        update={"objects": [40, 41, 42, 43, 44, 45], "nlobjs": 6}
    )
    locations[72] = locations[72].model_copy(
        update={"objects": [50, 51, 52, 53, 54, 55], "nlobjs": 6}
    )
    locations[44] = locations[44].model_copy(
        update={"objects": [60, 61, 62], "nlobjs": 3}
    )

    plan = build_modern_death_recovery_plan(
        player,
        locations=locations,
        rng=FixedRecoveryRng(shuffle_result=[2, 0, 95, 72], randrange_values=[44, 44, 44]),
    )
    apply_death_recovery_plan(player, locations, plan)

    assert locations[1].objects == [10, 11, 12, 13, 14, 0]
    assert locations[2].objects == [20, 21, 22, 23, 24, 1]
    assert locations[0].objects == [30, 31, 32, 33, 34, 2]
    assert locations[44].objects == [60, 61, 62, 3, 4, 5]
    assert plan.vanished_items == ()
    assert [update.room_id for update in plan.room_object_updates] == [1, 2, 0, 44]


def test_modern_death_recovery_reports_vanished_items_when_all_destinations_full():
    player = fixtures.build_player().model_copy(
        update={
            "level": 10,
            "gamloc": 1,
            "gpobjs": [0],
            "obvals": [0],
            "npobjs": 1,
            "honor_mode": False,
        }
    )
    locations = {location.id: location for location in fixtures.load_locations()}
    for location_id, location in list(locations.items()):
        if (
            location_id == 1
            or location_id in {locations[1].gi_north, locations[1].gi_south, locations[1].gi_east, locations[1].gi_west}
            or constants.MODERN_DEATH_DARK_FOREST_MIN_ROOM <= location_id <= constants.MODERN_DEATH_DARK_FOREST_MAX_ROOM
        ):
            locations[location_id] = location.model_copy(
                update={"objects": [0, 1, 2, 3, 4, 5], "nlobjs": 6}
            )

    plan = build_modern_death_recovery_plan(
        player,
        locations=locations,
        rng=FixedRecoveryRng(shuffle_result=[2, 0, 95, 72], randrange_values=[44]),
    )

    assert plan.room_object_updates == ()
    assert plan.vanished_items == (0,)
