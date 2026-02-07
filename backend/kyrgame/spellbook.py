"""Spellbook + memorized spell helpers.

This module keeps gmplyr spell invariants explicit:
- spellbook ownership bits live in offspls/defspls/othspls
- memorized spells live only in player.spells
- nspells always mirrors len(player.spells)
"""

from __future__ import annotations

import random
from typing import Iterable

from . import constants, models


def _owned_bitfield(player: models.PlayerModel, spell: models.SpellModel) -> int:
    if spell.sbkref == constants.OFFENS:
        return player.offspls
    if spell.sbkref == constants.DEFENS:
        return player.defspls
    return player.othspls


def has_spell_in_book(player: models.PlayerModel, spell: models.SpellModel) -> bool:
    return bool(_owned_bitfield(player, spell) & spell.bitdef)


def add_spell_to_book(player: models.PlayerModel, spell: models.SpellModel) -> None:
    """Set spellbook ownership bit only.

    Legacy parity: room/reader spell grants set the relevant book bit.
    Source: legacy/KYRCMDS.C lines 1088-1100, legacy/KYRROUS.C lines 265-273.
    """

    if spell.sbkref == constants.OFFENS:
        player.offspls |= spell.bitdef
    elif spell.sbkref == constants.DEFENS:
        player.defspls |= spell.bitdef
    else:
        player.othspls |= spell.bitdef


def memorize_spell(player: models.PlayerModel, spell: models.SpellModel) -> None:
    """Append spell id to memorized list, enforcing legacy MAXSPL behavior.

    Legacy parity: memutl drops the previous last entry when at capacity,
    then appends the newly memorized spell.
    Source: legacy/KYRSPEL.C lines 1491-1497.
    """

    if not has_spell_in_book(player, spell):
        raise ValueError("Cannot memorize a spell not owned in spellbook")

    if player.nspells >= constants.MAXSPL:
        player.spells.pop()

    player.spells.append(spell.id)
    player.nspells = len(player.spells)


def forget_memorized_spell(player: models.PlayerModel, spell_id: int) -> None:
    """Forget one memorized spell by id.

    Legacy parity: rmvspl removes by index and swaps in the tail element.
    Source: legacy/KYRSPEL.C lines 1337-1343.
    """

    if spell_id not in player.spells:
        return

    idx = player.spells.index(spell_id)
    last_index = len(player.spells) - 1
    if idx != last_index:
        player.spells[idx] = player.spells[last_index]
    player.spells.pop()
    player.nspells = len(player.spells)


def forget_all_memorized(player: models.PlayerModel) -> None:
    # Legacy parity: dumdum wipes memorized spells (legacy/KYRSPEL.C lines 607-615).
    player.spells.clear()
    player.nspells = 0


def forget_one_random_memorized(
    player: models.PlayerModel, rng: random.Random
) -> int | None:
    """Forget a random memorized spell, mirroring legacy single-loss behavior."""
    if not player.spells:
        return None
    # Legacy parity: saywhat drops one memorized spell (legacy/KYRSPEL.C lines 1047-1055).
    index = rng.randrange(len(player.spells))
    forgotten = player.spells[index]
    last_index = len(player.spells) - 1
    if index != last_index:
        player.spells[index] = player.spells[last_index]
    player.spells.pop()
    player.nspells = len(player.spells)
    return forgotten


def wipe_spellbook_bits(player: models.PlayerModel) -> None:
    """Clear all spellbook ownership bitfields."""
    # Legacy parity: bookworm zeros spellbook bitfields (legacy/KYRSPEL.C lines 497-515).
    player.offspls = 0
    player.defspls = 0
    player.othspls = 0


def list_spellbook_spells(
    player: models.PlayerModel,
    spells_catalog: Iterable[models.SpellModel],
) -> list[models.SpellModel]:
    return [spell for spell in spells_catalog if has_spell_in_book(player, spell)]


def list_memorized_spells(
    player: models.PlayerModel,
    spells_catalog: Iterable[models.SpellModel],
) -> list[models.SpellModel]:
    by_id = {spell.id: spell for spell in spells_catalog}
    return [by_id[spell_id] for spell_id in player.spells if spell_id in by_id]
