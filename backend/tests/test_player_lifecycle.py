from kyrgame import constants, fixtures
from kyrgame.player_lifecycle import initialize_player_for_first_login, reset_player_after_death


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
