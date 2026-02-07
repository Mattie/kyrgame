import random

import pytest

from kyrgame import constants, fixtures
from kyrgame.spellbook import (
    add_spell_to_book,
    forget_all_memorized,
    forget_memorized_spell,
    forget_one_random_memorized,
    has_spell_in_book,
    list_memorized_spells,
    list_spellbook_spells,
    memorize_spell,
    wipe_spellbook_bits,
)


def _find_spell(name: str):
    return next(spell for spell in fixtures.load_spells() if spell.name == name)


def _fresh_player():
    return fixtures.build_player().model_copy(
        update={"offspls": 0, "defspls": 0, "othspls": 0, "spells": [], "nspells": 0},
        deep=True,
    )


def test_add_spell_to_book_sets_book_bit_only():
    player = _fresh_player()
    zapher = _find_spell("zapher")

    add_spell_to_book(player, zapher)

    assert has_spell_in_book(player, zapher)
    assert player.offspls & zapher.bitdef
    assert player.spells == []
    assert player.nspells == 0


def test_memorize_spell_requires_spellbook_ownership():
    player = _fresh_player()
    zapher = _find_spell("zapher")

    with pytest.raises(ValueError):
        memorize_spell(player, zapher)


def test_memorize_spell_applies_legacy_maxspl_replacement_policy():
    player = _fresh_player()
    spells = fixtures.load_spells()

    owned = spells[: constants.MAXSPL + 1]
    for spell in owned:
        add_spell_to_book(player, spell)

    for spell in owned[: constants.MAXSPL]:
        memorize_spell(player, spell)

    assert len(player.spells) == constants.MAXSPL

    overflow_spell = owned[constants.MAXSPL]
    displaced_spell_id = player.spells[-1]
    memorize_spell(player, overflow_spell)

    assert len(player.spells) == constants.MAXSPL
    assert overflow_spell.id == player.spells[-1]
    assert displaced_spell_id not in player.spells
    assert player.nspells == len(player.spells)


def test_forget_memorized_spell_and_forget_all_keep_nspells_in_sync():
    player = _fresh_player()
    zapher = _find_spell("zapher")
    hotseat = _find_spell("hotseat")

    add_spell_to_book(player, zapher)
    add_spell_to_book(player, hotseat)
    memorize_spell(player, zapher)
    memorize_spell(player, hotseat)

    forget_memorized_spell(player, zapher.id)
    assert player.spells == [hotseat.id]
    assert player.nspells == 1

    forget_all_memorized(player)
    assert player.spells == []
    assert player.nspells == 0


def test_forget_one_random_memorized_removes_single_spell():
    player = _fresh_player()
    rng = random.Random(0)
    player.spells.extend([1, 2, 3])
    player.nspells = 3

    removed = forget_one_random_memorized(player, rng)

    assert removed in {1, 2, 3}
    assert removed not in player.spells
    assert len(player.spells) == 2
    assert player.nspells == 2


def test_wipe_spellbook_bits_clears_all_book_flags():
    player = _fresh_player()
    spells = fixtures.load_spells()

    add_spell_to_book(player, spells[0])
    add_spell_to_book(player, spells[1])
    add_spell_to_book(player, spells[2])

    wipe_spellbook_bits(player)

    assert player.offspls == 0
    assert player.defspls == 0
    assert player.othspls == 0


def test_list_spellbook_spells_and_memorized_spells_are_distinct():
    player = _fresh_player()
    zapher = _find_spell("zapher")
    hotseat = _find_spell("hotseat")
    catalog = fixtures.load_spells()

    add_spell_to_book(player, zapher)
    add_spell_to_book(player, hotseat)
    memorize_spell(player, zapher)

    spellbook_spells = list_spellbook_spells(player, catalog)
    memorized_spells = list_memorized_spells(player, catalog)

    assert {spell.id for spell in spellbook_spells} == {zapher.id, hotseat.id}
    assert [spell.id for spell in memorized_spells] == [zapher.id]
