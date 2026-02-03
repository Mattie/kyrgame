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

# Spell bitflags (legacy KYRSPLS.H)
SBD001_OTHERPRO2            = 0x00000001
SBD002_ULTHEAL              = 0x00000002
SBD003_DESTONE              = 0x00000001
SBD004_DESTALL              = 0x00000002
SBD005_ZAPBOOK              = 0x00000004
SBD006_FIREBALL1            = 0x00000001
SBD007_OTHERPRO1            = 0x00000004
SBD008_INVIS1               = 0x00000008
SBD009_ULTPRO1              = 0x00000010
SBD010_ICESTORM2            = 0x00000002
SBD011_DROPALL              = 0x00000008
SBD012_DETECTPOWER          = 0x00000010
SBD013_FORGETALL            = 0x00000020
SBD014_TELEPORT_RANDOM      = 0x00000040
SBD015_HEAL3                = 0x00000020
SBD016_PEGASUS              = 0x00000080
SBD017_FIREBOLT1            = 0x00000004
SBD018_ICEBALL2             = 0x00000008
SBD019_CONE_COLD2           = 0x00000010
SBD020_ICEBALL1             = 0x00000020
SBD021_FIREBOLT3            = 0x00000040
SBD022_LIGHTNING_BOLT2      = 0x00000080
SBD023_TELEPORT_SPECIFIC    = 0x00000100
SBD024_PSEUDO_DRAGON        = 0x00000200
SBD025_OBJPROT1             = 0x00000040
SBD026_ICEPROT2             = 0x00000080
SBD027_LIGHTNING_STORM      = 0x00000100
SBD028_DISPEL_MAGIC         = 0x00000400
SBD029_LIGHTNING_BOLT3      = 0x00000200
SBD030_LIGHTNING_BALL       = 0x00000400
SBD031_FIREBALL2            = 0x00000800
SBD032_FIREBOLT2            = 0x00001000
SBD033_ICEPROT1             = 0x00000100
SBD034_DETECT_HEALTH        = 0x00000800
SBD035_FIREPROT2            = 0x00000200
SBD036_ULTPRO2              = 0x00000400
SBD037_ICESTORM1            = 0x00002000
SBD038_SEEINVIS2            = 0x00001000
SBD039_SEEINVIS1            = 0x00002000
SBD040_CONE_COLD1           = 0x00004000
SBD041_OBJPROT2             = 0x00000800
SBD042_DESTROY_GROUND       = 0x00004000
SBD043_HEAL1                = 0x00001000
SBD044_READ_SPELLS          = 0x00008000
SBD045_INVIS2               = 0x00002000
SBD046_SCRY                 = 0x00010000
SBD047_STEAL_ITEM           = 0x00020000
SBD048_MAGIC_MISSILE        = 0x00008000
SBD049_ICEPROT3             = 0x00004000
SBD050_SAP_SP2              = 0x00010000
SBD051_FORGET_ONE           = 0x00040000
SBD052_FIRE_STORM           = 0x00020000
SBD053_FIREPROT1            = 0x00008000
SBD054_CONE_COLD3           = 0x00040000
SBD055_LIGHTNING_PROT1      = 0x00010000
SBD056_LIGHTNING_PROT3      = 0x00020000
SBD057_SAP_SP1              = 0x00080000
SBD058_HEAL2                = 0x00040000
SBD059_EARTHQUAKE           = 0x00100000
SBD060_LIGHTNING_PROT2      = 0x00080000
SBD061_FIREBALL3            = 0x00200000
SBD062_WILLOWISP            = 0x00080000
SBD063_LOCATION_FINDER      = 0x00100000
SBD064_FIREPROT3            = 0x00100000
SBD065_DETECT_TRUE_ID       = 0x00200000
SBD066_LIGHTNING_BOLT1      = 0x00400000
SBD067_ARIEL_SERVANT        = 0x00800000

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


def level_to_nmpdes(level: int) -> int:
    """Return the nmpdes index for a given level (1-25)."""
    # Legacy: KYRANDIA.C initgp sets MDES00/FDES00 at level 1 and KYRSYSP.C EDT002
    # derives nmpdes from level when admin edits a player (lines 333-351, 129-146).
    return max(0, min(level - 1, 24))
