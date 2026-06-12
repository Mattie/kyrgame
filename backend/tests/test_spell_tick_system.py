from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import select

from kyrgame import constants, fixtures, models
from kyrgame.database import create_session_factory, get_engine, init_db_schema
from kyrgame.spells.tick_system import (
    SQLAlchemySpellTickPlayerRepository,
    SpellTickConstants,
    SpellTickSystem,
)


@dataclass
class StubPlayer:
    plyrid: str
    altnam: str
    attnam: str
    level: int
    spts: int
    macros: int
    gamloc: int
    flags: int
    charms: list[int]


class StubPlayerRepository:
    def __init__(self, players: list[StubPlayer]):
        self.players = players

    def list_players_for_spell_tick(self) -> list[StubPlayer]:
        return self.players


class StubSession:
    def __init__(self):
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class StubMessaging:
    def __init__(self):
        self.direct: list[tuple[str, str]] = []
        self.broadcast: list[tuple[int, str, str]] = []

    def send_direct(self, *, player_id: str, message_id: str, text: str) -> None:
        self.direct.append((player_id, message_id, text))

    def broadcast_room(
        self,
        *,
        room_id: int,
        exclude_player_id: str,
        message_id: str,
        text: str,
    ) -> None:
        self.broadcast.append((room_id, exclude_player_id, message_id, text))


@contextmanager
def _session_scope(session: StubSession):
    yield session


def test_spell_tick_resets_macros_regens_spts_and_decrements_charms():
    session = StubSession()
    messages = StubMessaging()
    player = StubPlayer(
        plyrid="hero",
        altnam="Hero",
        attnam="Hero",
        level=3,
        spts=5,
        macros=9,
        gamloc=42,
        flags=0,
        charms=[1, 0, 2, 0, 0, 0],
    )

    system = SpellTickSystem(
        session_factory=lambda: _session_scope(session),
        player_repository_factory=lambda db: StubPlayerRepository([player]),
        messaging=messages,
        constants=SpellTickConstants(),
        message_lookup=lambda key: key,
    )

    result = system.tick()

    assert player.macros == 0
    assert player.spts == 6
    assert player.charms == [0, 0, 1, 0, 0, 0]
    assert messages.direct == [("hero", "BASMSG", "BASMSG")]
    assert result.touched_players[0].player_id == "hero"
    assert session.commits == 1


def test_spell_tick_does_not_touch_unchanged_player():
    player = StubPlayer(
        plyrid="hero",
        altnam="Hero",
        attnam="Hero",
        level=4,
        spts=8,
        macros=0,
        gamloc=12,
        flags=0,
        charms=[0, 0, 0, 0, 0, 0],
    )

    system = SpellTickSystem(
        session_factory=lambda: _session_scope(StubSession()),
        player_repository_factory=lambda db: StubPlayerRepository([player]),
        messaging=StubMessaging(),
        constants=SpellTickConstants(),
        message_lookup=lambda key: key,
    )

    result = system.tick()

    assert result.touched_players == []


def test_spell_tick_persists_json_charm_timer_decrements():
    engine = get_engine("sqlite+pysqlite:///:memory:")
    init_db_schema(engine)
    session_factory = create_session_factory(engine)
    player = fixtures.build_player().model_copy(
        update={
            "plyrid": "Necro",
            "altnam": "Some willowisp",
            "attnam": "willowisp",
            "level": 10,
            "spts": 20,
            "macros": 0,
            "gamloc": 187,
            "flags": int(constants.PlayerFlag.LOADED | constants.PlayerFlag.WILLOW),
            "charms": [0, 0, 0, 0, 0, 4],
        }
    )
    with session_factory() as session:
        session.add(models.Player(**player.model_dump()))
        session.commit()

    system = SpellTickSystem(
        session_factory=session_factory,
        player_repository_factory=lambda db: SQLAlchemySpellTickPlayerRepository(db),
        messaging=StubMessaging(),
        constants=SpellTickConstants(),
        message_lookup=lambda key: key,
    )

    system.tick()

    with session_factory() as session:
        record = session.scalar(select(models.Player).where(models.Player.plyrid == "Necro"))
        assert record is not None
        assert record.charms[constants.ALTNAM] == 3


def test_spell_tick_handles_altname_expiry_and_reverts_identity_flags():
    session = StubSession()
    messages = StubMessaging()
    constants = SpellTickConstants(
        alt_name_slot=5,
        invisibility_flag=0x04,
        pegasus_flag=0x20,
        willow_flag=0x40,
        pseudo_dragon_flag=0x100,
    )
    player = StubPlayer(
        plyrid="hero",
        altnam="Some willowisp",
        attnam="willowisp",
        level=10,
        spts=1,
        macros=2,
        gamloc=7,
        flags=0x04 | 0x20 | 0x40 | 0x100,
        charms=[0, 0, 0, 0, 0, 1],
    )

    system = SpellTickSystem(
        session_factory=lambda: _session_scope(session),
        player_repository_factory=lambda db: StubPlayerRepository([player]),
        messaging=messages,
        constants=constants,
        message_lookup=lambda key: "RET2" if key == "RET2NM" else key,
    )

    system.tick()

    assert player.altnam == "hero"
    assert player.attnam == "hero"
    assert player.flags == 0
    assert player.charms[5] == 0
    assert messages.direct == [("hero", "BASMSG5", "BASMSG5")]
    assert messages.broadcast == [(7, "hero", "RET2NM", "RET2")]


def test_spell_tick_caps_spell_points_to_double_level():
    player = StubPlayer(
        plyrid="hero",
        altnam="Hero",
        attnam="Hero",
        level=4,
        spts=7,
        macros=1,
        gamloc=12,
        flags=0,
        charms=[0, 0, 0, 0, 0, 0],
    )

    system = SpellTickSystem(
        session_factory=lambda: _session_scope(StubSession()),
        player_repository_factory=lambda db: StubPlayerRepository([player]),
        messaging=StubMessaging(),
        constants=SpellTickConstants(),
        message_lookup=lambda key: key,
    )

    system.tick()

    assert player.spts == 8
