from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import declarative_base

from . import constants

Base = declarative_base()


# Pydantic models ---------------------------------------------------------


class SpellModel(BaseModel):
    id: int
    name: str = Field(max_length=constants.SPELL_NAME_LEN)
    sbkref: int
    bitdef: int
    level: int
    splrou: Optional[str] = None

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class GameObjectModel(BaseModel):
    id: int
    name: str
    objdes: int
    auxmsg: int
    flags: List[str] = Field(default_factory=list)
    objrou: Optional[str] = None

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    @field_validator("flags")
    def validate_flags(cls, value: List[str]):
        unknown = [flag for flag in value if flag not in constants.OBJECT_FLAGS]
        if unknown:
            raise ValueError(f"Unknown object flags: {unknown}")
        return value


class LocationModel(BaseModel):
    id: int
    brfdes: str = Field(max_length=constants.BRFDES_LEN)
    objlds: str = Field(max_length=constants.OBJLDS_LEN)
    nlobjs: int
    objects: List[int] = Field(default_factory=list, max_length=constants.MXLOBS)
    gi_north: int
    gi_south: int
    gi_east: int
    gi_west: int

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    @model_validator(mode="after")
    def validate_object_count(self):
        if self.nlobjs != len(self.objects):
            raise ValueError("nlobjs must equal the number of object ids present")
        return self


class PlayerModel(BaseModel):
    uidnam: str = Field(max_length=constants.UIDSIZ)
    plyrid: str = Field(max_length=constants.ALSSIZ)
    altnam: str = Field(max_length=constants.APNSIZ)
    attnam: str = Field(max_length=constants.APNSIZ)
    gpobjs: List[int] = Field(max_length=constants.MXPOBS)
    nmpdes: int
    modno: int
    level: int
    gamloc: int
    pgploc: int
    flags: int
    gold: int
    npobjs: int
    obvals: List[int] = Field(max_length=constants.MXPOBS)
    nspells: int
    spts: int
    hitpts: int
    charms: List[int] = Field(max_length=constants.NCHARM)
    offspls: int
    defspls: int
    othspls: int
    spells: List[int] = Field(max_length=constants.MAXSPL)
    gemidx: int
    stones: List[int] = Field(max_length=constants.BIRTHSTONE_SLOTS)
    macros: int
    stumpi: int
    spouse: str = Field(max_length=constants.ALSSIZ)

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    @model_validator(mode="after")
    def validate_counts(self):
        if self.npobjs != len(self.gpobjs) or self.npobjs != len(self.obvals):
            raise ValueError("npobjs must match gpobjs/obvals length")
        if self.nspells != len(self.spells):
            raise ValueError("nspells must match the number of memorized spells")
        if len(self.charms) != constants.NCHARM:
            raise ValueError(f"charms must contain exactly {constants.NCHARM} timers")
        if len(self.stones) != constants.BIRTHSTONE_SLOTS:
            raise ValueError(
                f"stones must contain exactly {constants.BIRTHSTONE_SLOTS} birthstones"
            )
        unknown_flags = self.flags & ~constants.PLAYER_FLAG_MASK
        if unknown_flags:
            raise ValueError("flags contains unknown bits")
        if not constants.GEM_INDEX_MIN <= self.gemidx <= constants.GEM_INDEX_MAX:
            raise ValueError(
                f"gemidx must be between {constants.GEM_INDEX_MIN} and {constants.GEM_INDEX_MAX}"
            )
        if not constants.MACROS_MIN <= self.macros <= constants.MACROS_MAX:
            raise ValueError(
                f"macros must be between {constants.MACROS_MIN} and {constants.MACROS_MAX}"
            )
        if not constants.STUMPI_MIN <= self.stumpi <= constants.STUMPI_MAX:
            raise ValueError(
                f"stumpi must be between {constants.STUMPI_MIN} and {constants.STUMPI_MAX}"
            )
        if any(
            charm < constants.CHARM_TIMER_MIN or charm > constants.CHARM_TIMER_MAX
            for charm in self.charms
        ):
            raise ValueError(
                f"charms must be between {constants.CHARM_TIMER_MIN} and {constants.CHARM_TIMER_MAX}"
            )
        if any(
            stone < constants.BIRTHSTONE_MIN or stone > constants.BIRTHSTONE_MAX
            for stone in self.stones
        ):
            raise ValueError(
                f"stones must be between {constants.BIRTHSTONE_MIN} and {constants.BIRTHSTONE_MAX}"
            )
        if any(
            spell_id < constants.SPELL_ID_MIN or spell_id > constants.SPELL_ID_MAX
            for spell_id in self.spells
        ):
            raise ValueError(
                f"spells must be between {constants.SPELL_ID_MIN} and {constants.SPELL_ID_MAX}"
            )
        return self


class CommandModel(BaseModel):
    id: int
    command: str = Field(max_length=32)
    payonl: bool = False
    cmdrou: Optional[str] = None

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class MessageBundleModel(BaseModel):
    version: str
    locale: str
    catalog_id: str
    messages: Dict[str, str]

    model_config = ConfigDict(extra="forbid")


class MessageCatalogModel(MessageBundleModel):
    """Backward compatible alias for legacy naming."""


# SQLAlchemy ORM models ---------------------------------------------------


class Spell(Base):
    __tablename__ = "spells"

    id = Column(Integer, primary_key=True)
    name = Column(String(constants.SPELL_NAME_LEN), nullable=False)
    sbkref = Column(Integer, nullable=False)
    bitdef = Column(BigInteger, nullable=False)
    level = Column(Integer, nullable=False)
    splrou = Column(String(64), nullable=True)


class GameObject(Base):
    __tablename__ = "objects"

    id = Column(Integer, primary_key=True)
    name = Column(String(80), nullable=False)
    objdes = Column(Integer, nullable=False)
    auxmsg = Column(Integer, nullable=False)
    flags = Column(String(64), nullable=False)
    objrou = Column(String(64), nullable=True)


class Location(Base):
    __tablename__ = "locations"

    id = Column(Integer, primary_key=True)
    brfdes = Column(String(constants.BRFDES_LEN), nullable=False)
    objlds = Column(String(constants.OBJLDS_LEN), nullable=False)
    nlobjs = Column(Integer, nullable=False)
    objects = Column(JSON, nullable=False)
    gi_north = Column(Integer, nullable=False)
    gi_south = Column(Integer, nullable=False)
    gi_east = Column(Integer, nullable=False)
    gi_west = Column(Integer, nullable=False)


class Player(Base):
    __tablename__ = "players"
    __table_args__ = (
        CheckConstraint(
            f"gemidx >= {constants.GEM_INDEX_MIN} AND gemidx <= {constants.GEM_INDEX_MAX}",
            name="ck_players_gemidx_range",
        ),
        CheckConstraint(
            f"stumpi >= {constants.STUMPI_MIN} AND stumpi <= {constants.STUMPI_MAX}",
            name="ck_players_stumpi_range",
        ),
        CheckConstraint(
            f"macros >= {constants.MACROS_MIN} AND macros <= {constants.MACROS_MAX}",
            name="ck_players_macros_range",
        ),
    )

    id = Column(Integer, primary_key=True)
    uidnam = Column(String(constants.UIDSIZ), nullable=False)
    plyrid = Column(String(constants.ALSSIZ), nullable=False)
    altnam = Column(String(constants.APNSIZ), nullable=False)
    attnam = Column(String(constants.APNSIZ), nullable=False)
    gpobjs = Column(JSON, nullable=False)
    nmpdes = Column(Integer, nullable=False)
    modno = Column(Integer, nullable=False)
    level = Column(Integer, nullable=False)
    gamloc = Column(Integer, nullable=False)
    pgploc = Column(Integer, nullable=False)
    flags = Column(BigInteger, nullable=False)
    gold = Column(Integer, nullable=False)
    npobjs = Column(Integer, nullable=False)
    obvals = Column(JSON, nullable=False)
    nspells = Column(Integer, nullable=False)
    spts = Column(Integer, nullable=False)
    hitpts = Column(Integer, nullable=False)
    offspls = Column(BigInteger, nullable=False)
    defspls = Column(BigInteger, nullable=False)
    othspls = Column(BigInteger, nullable=False)
    charms = Column(JSON, nullable=False)
    spells = Column(JSON, nullable=False)
    gemidx = Column(Integer, nullable=False)
    stones = Column(JSON, nullable=False)
    macros = Column(Integer, nullable=False)
    stumpi = Column(Integer, nullable=False)
    spouse = Column(String(constants.ALSSIZ), nullable=False)


class Command(Base):
    __tablename__ = "commands"

    id = Column(Integer, primary_key=True)
    command = Column(String(32), nullable=False)
    payonl = Column(Integer, nullable=False, default=0)
    cmdrou = Column(String(64), nullable=True)


class Message(Base):
    __tablename__ = "messages"

    id = Column(String(64), primary_key=True)
    text = Column(String(255), nullable=False)


class PlayerSession(Base):
    __tablename__ = "player_sessions"

    id = Column(Integer, primary_key=True)
    player_id = Column(
        Integer, ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_token = Column(String(128), nullable=False, unique=True)
    room_id = Column(Integer, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    expires_at = Column(DateTime(timezone=True), nullable=False)


class PlayerInventory(Base):
    __tablename__ = "player_inventories"
    __table_args__ = (UniqueConstraint("player_id", "slot_index", name="uq_player_slot"),)

    id = Column(Integer, primary_key=True)
    player_id = Column(
        Integer, ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True
    )
    slot_index = Column(Integer, nullable=False)
    object_id = Column(Integer, nullable=False)
    object_value = Column(Integer, nullable=False)


class SpellTimer(Base):
    __tablename__ = "spell_timers"
    __table_args__ = (
        UniqueConstraint("player_id", "spell_id", name="uq_player_spell_timer"),
    )

    id = Column(Integer, primary_key=True)
    player_id = Column(
        Integer, ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True
    )
    spell_id = Column(Integer, nullable=False)
    remaining_ticks = Column(Integer, nullable=False)


class RoomOccupant(Base):
    __tablename__ = "room_occupants"
    __table_args__ = (UniqueConstraint("room_id", "player_id", name="uq_room_player"),)

    id = Column(Integer, primary_key=True)
    room_id = Column(Integer, nullable=False, index=True)
    player_id = Column(
        Integer, ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entered_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
