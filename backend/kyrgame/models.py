from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import BigInteger, Column, Integer, JSON, String
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
    gpobjs: List[int] = Field(default_factory=list, max_length=constants.MXPOBS)
    nmpdes: Optional[int] = None
    modno: Optional[int] = None
    level: int
    gamloc: int
    pgploc: int
    flags: int
    gold: int
    npobjs: int
    obvals: List[int] = Field(default_factory=list, max_length=constants.MXPOBS)
    nspells: int
    spts: int
    hitpts: int
    charms: List[int] = Field(default_factory=list, max_length=constants.NCHARM)
    offspls: int
    defspls: int
    othspls: int
    spells: List[int] = Field(default_factory=list, max_length=constants.MAXSPL)
    gemidx: Optional[int] = None
    stones: List[int] = Field(default_factory=list, max_length=constants.BIRTHSTONE_SLOTS)
    macros: Optional[int] = None
    stumpi: Optional[int] = None
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

    id = Column(Integer, primary_key=True)
    uidnam = Column(String(constants.UIDSIZ), nullable=False)
    plyrid = Column(String(constants.ALSSIZ), nullable=False)
    altnam = Column(String(constants.APNSIZ), nullable=False)
    attnam = Column(String(constants.APNSIZ), nullable=False)
    gpobjs = Column(JSON, nullable=False)
    nmpdes = Column(Integer, nullable=True)
    modno = Column(Integer, nullable=True)
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
    gemidx = Column(Integer, nullable=True)
    stones = Column(JSON, nullable=False)
    macros = Column(Integer, nullable=True)
    stumpi = Column(Integer, nullable=True)
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
