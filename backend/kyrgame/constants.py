"""Constants derived from the legacy KYRANDIA.H header."""

from enum import IntEnum, IntFlag
from typing import Iterable, List


# Player and gameplay limits
APNSIZ = 20  # alternate player name length
ALSSIZ = 10  # alias length
UIDSIZ = 25  # user id length (host constant, sized to legacy buffer)
MXPOBS = 6   # maximum objects a player can hold
MAXSPL = 10  # maximum memorized spells per player
NCHARM = 6   # charm timer slots
BIRTHSTONE_SLOTS = 4  # birthstones tracked per player
NGSPLS = 67  # number of spells defined
NGOBJS = 54  # number of objects defined
NGLOCS = 305 # number of locations defined
MXLOBS = 6   # maximum objects present at a location

# Spellbook types
OFFENS = 1
DEFENS = 2
OTHERS = 3

# Charm timer slots
CINVIS = 0
FIRPRO = 1
ICEPRO = 2
LIGPRO = 3
OBJPRO = 4
ALTNAM = 5

# Field sizes inside structs
SPELL_NAME_LEN = 10
BRFDES_LEN = 40
OBJLDS_LEN = 30

# Object flag bitmasks
OBJECT_FLAGS = {
    "NEEDAN": 0x0001,
    "VISIBL": 0x0002,
    "PICKUP": 0x0004,
    "REDABL": 0x0008,
    "AIMABL": 0x0010,
    "THIABL": 0x0020,
    "RUBABL": 0x0040,
    "DRIABL": 0x0080,
}


class PlayerFlag(IntFlag):
    LOADED = 0x00000001
    FEMALE = 0x00000002
    INVISF = 0x00000004
    BRFSTF = 0x00000008
    MARRYD = 0x00000010
    PEGASU = 0x00000020
    WILLOW = 0x00000040
    GOTKYG = 0x00000080
    PDRAGN = 0x00000100
    BLESSD = 0x00000200


class CharmSlot(IntEnum):
    INVISIBILITY = CINVIS
    FIRE_PROTECTION = FIRPRO
    ICE_PROTECTION = ICEPRO
    LIGHTNING_PROTECTION = LIGPRO
    OBJECT_PROTECTION = OBJPRO
    ALTERNATE_NAME = ALTNAM


def encode_player_flags(flag_names: Iterable[str]) -> int:
    """Return the bitmask for a collection of player flag names."""

    mask = PlayerFlag(0)
    for name in flag_names:
        try:
            mask |= PlayerFlag[name]
        except KeyError as exc:  # pragma: no cover - defensive guard
            raise ValueError(f"Unknown player flag: {name}") from exc
    return int(mask)


def decode_player_flags(mask: int) -> List[str]:
    """Return the list of flag names present in ``mask``."""

    active = []
    for flag in PlayerFlag:
        if mask & flag:
            active.append(flag.name)
    return active


# Player flags preserved for compatibility in simple dict form
PLAYER_FLAGS = {flag.name: flag.value for flag in PlayerFlag}
