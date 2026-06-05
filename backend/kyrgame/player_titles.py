"""Legacy player rank titles."""

from __future__ import annotations


# Legacy titles array used by shwsutl output (legacy/KYRANDIA.C:106-133).
LEGACY_TITLES_BY_LEVEL = [
    "",
    "Apprentice",
    "Magic-user",
    "Evoker",
    "Conjurer",
    "Magician",
    "Mystic",
    "Enchanter",
    "Warlock",
    "Sorcerer",
    "Green Wizard",
    "Blue Wizard",
    "Red Wizard",
    "Grey Wizard",
    "White Wizard",
    "Mage",
    "Mage of Ice",
    "Mage of Wind",
    "Mage of Fire",
    "Mage of Light",
    "Arch-Mage",
    "Arch-Mage of Wands",
    "Arch Mage of Staves",
    "Arch-Mage of Swords",
    "Arch-Mage of Jewels",
    "Arch-Mage of Legends",
]


def legacy_title_for_level(level: int) -> str:
    index = max(0, min(level, len(LEGACY_TITLES_BY_LEVEL) - 1))
    return LEGACY_TITLES_BY_LEVEL[index]
