"""Constants derived from the legacy KYRANDIA.H header."""

# Player and gameplay limits
APNSIZ = 20  # alternate player name length
ALSSIZ = 10  # alias length
UIDSIZ = 25  # user id length (host constant, sized to legacy buffer)
MXPOBS = 6   # maximum objects a player can hold
MAXSPL = 10  # maximum memorized spells per player
NCHARM = 6   # charm timer slots
NGSPLS = 67  # number of spells defined
NGOBJS = 54  # number of objects defined
NGLOCS = 305 # number of locations defined
MXLOBS = 6   # maximum objects present at a location

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

# Player flags (subset for early validation/use)
PLAYER_FLAGS = {
    "LOADED": 0x00000001,
    "FEMALE": 0x00000002,
    "INVISF": 0x00000004,
    "BRFSTF": 0x00000008,
    "MARRYD": 0x00000010,
    "PEGASU": 0x00000020,
    "WILLOW": 0x00000040,
    "GOTKYG": 0x00000080,
    "PDRAGN": 0x00000100,
    "BLESSD": 0x00000200,
}
