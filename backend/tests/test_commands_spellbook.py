import pytest
from sqlalchemy import select

from kyrgame import commands, constants, fixtures
from kyrgame.database import create_session, get_engine, init_db_schema
from kyrgame import models


class FakePresence:
    async def players_in_room(self, room_id: int) -> set[str]:  # noqa: ARG002
        return set()


class FixedRng:
    def __init__(self, values):
        self._values = list(values)

    def randint(self, low, high):
        value = self._values.pop(0)
        assert low <= value <= high
        return value


def _build_state(player):
    locations = {location.id: location for location in fixtures.load_locations()}
    objects = {obj.id: obj for obj in fixtures.load_objects()}
    messages = fixtures.load_messages()
    content_mappings = fixtures.load_content_mappings()
    return commands.GameState(
        player=player,
        locations=locations,
        objects=objects,
        messages=messages,
        content_mappings=content_mappings,
        presence=FakePresence(),
        player_lookup=lambda _player_id: None,
    )


def _build_player(**updates):
    player = fixtures.build_player()
    data = player.model_dump()
    data.update(updates)
    return player.model_copy(update=data)


def _set_owned_spells(player, spell_ids):
    spells = fixtures.load_spells()
    for spell_id in spell_ids:
        spell = spells[spell_id]
        if spell.sbkref == constants.OFFENS:
            player.offspls |= spell.bitdef
        elif spell.sbkref == constants.DEFENS:
            player.defspls |= spell.bitdef
        else:
            player.othspls |= spell.bitdef


@pytest.mark.anyio
async def test_look_spellbook_renders_header_rows_and_footer_in_fixture_order():
    player = _build_player(flags=0, offspls=0, defspls=0, othspls=0)
    _set_owned_spells(player, [10, 5, 2, 0])
    state = _build_state(player)
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("look", {"raw": "spellbook"}, state)

    message_ids = [event.get("message_id") for event in result.events]
    assert message_ids == ["SBOOK1", "SBOOK2", "SBOOK2", "SBOOK4"]

    spell_rows = [event["text"] for event in result.events if event.get("message_id") == "SBOOK2"]
    assert "abbracada" in spell_rows[0]
    assert "blowitawa" in spell_rows[0]
    assert "burnup" in spell_rows[0]
    assert "clutzopho" in spell_rows[1]


@pytest.mark.anyio
async def test_look_spellbook_uses_empty_state_when_player_knows_no_spells():
    player = _build_player(flags=0, offspls=0, defspls=0, othspls=0)
    state = _build_state(player)
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("look", {"raw": "spellbook"}, state)

    message_ids = [event.get("message_id") for event in result.events]
    assert message_ids == ["SBOOK1", "SBOOK3", "SBOOK4"]


@pytest.mark.anyio
async def test_read_spellbook_routes_to_spellbook_rendering_path():
    player = _build_player(
        flags=int(constants.PlayerFlag.FEMALE | constants.PlayerFlag.LOADED),
        offspls=0,
        defspls=0,
        othspls=0,
    )
    _set_owned_spells(player, [0])
    state = _build_state(player)
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("read", {"raw": "spellbook"}, state)

    message_ids = [event.get("message_id") for event in result.events]
    assert message_ids == ["SBOOK1", "SBOOK2", "SBOOK4"]
    assert "Lady" in result.events[0]["text"]


@pytest.mark.anyio
async def test_read_scroll_consumes_item_and_grants_spellbook_spell():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        gpobjs=[35],
        obvals=[0],
        npobjs=1,
        offspls=0,
        defspls=0,
        othspls=0,
    )
    state = _build_state(player)
    state.rng = FixedRng([0])
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("read", {"raw": "scroll"}, state)

    assert state.player.gpobjs == []
    assert state.player.npobjs == 0
    assert (state.player.offspls | state.player.defspls | state.player.othspls) != 0
    assert [event["message_id"] for event in result.events] == [None, "URSCRL"]
    assert result.events[0]["exclude_player"] == state.player.plyrid


@pytest.mark.anyio
async def test_read_scroll_failure_clears_inventory_except_spellbook_conceptually():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        gpobjs=[35, 30, 31],
        obvals=[0, 0, 0],
        npobjs=3,
        offspls=0,
        defspls=0,
        othspls=0,
    )
    state = _build_state(player)
    state.rng = FixedRng([80, 1])
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("read", {"raw": "scroll"}, state)

    assert state.player.gpobjs == []
    assert state.player.npobjs == 0
    assert result.events[-1]["message_id"] == "SCRLM1"


@pytest.mark.anyio
async def test_read_non_readable_inventory_item_emits_reader1():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        gpobjs=[30],
        obvals=[0],
        npobjs=1,
    )
    state = _build_state(player)
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("read", {"raw": "dragonstaff"}, state)

    assert [event["message_id"] for event in result.events] == ["READER1"]


@pytest.mark.anyio
async def test_read_scroll_failure_teleports_and_persists_player_state():
    engine = get_engine("sqlite+pysqlite:///:memory:")
    init_db_schema(engine)
    session = create_session(engine)

    base_player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        gamloc=4,
        pgploc=4,
        gpobjs=[36],
        obvals=[0],
        npobjs=1,
    )
    session.add(models.Player(**base_player.model_dump()))
    session.commit()

    state = _build_state(base_player)
    state.db_session = session
    state.rng = FixedRng([90, 4, 99])
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("read", {"raw": "codex"}, state)

    assert state.player.gamloc == 99
    assert state.player.pgploc == 4
    assert [event["message_id"] for event in result.events][-2:] == ["SCRLM4", "SCRLM42"]

    record = session.scalar(select(models.Player).where(models.Player.plyrid == base_player.plyrid))
    assert record is not None
    assert record.gamloc == 99
    assert record.pgploc == 4


@pytest.mark.anyio
async def test_memorize_requires_owned_spell_and_emits_kspm09():
    player = _build_player(flags=int(constants.PlayerFlag.LOADED), offspls=0, defspls=0, othspls=0)
    state = _build_state(player)
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("memorize", {"raw": "zapher"}, state)

    assert result.events == [
        {
            "scope": "player",
            "event": "room_message",
            "type": "room_message",
            "text": fixtures.load_messages().messages["KSPM09"],
            "message_id": "KSPM09",
            "command_id": None,
        }
    ]


@pytest.mark.anyio
async def test_memorize_at_maxspl_evicts_last_slot_and_broadcasts_memspl():
    spells = fixtures.load_spells()
    overflow_spell = spells[10]
    forgotten_spell = spells[9]
    player = _build_player(flags=int(constants.PlayerFlag.LOADED), offspls=0, defspls=0, othspls=0)
    _set_owned_spells(player, list(range(0, 11)))
    player = player.model_copy(
        update={
            "spells": list(range(constants.MAXSPL)),
            "nspells": constants.MAXSPL,
        }
    )
    state = _build_state(player)
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("learn", {"raw": overflow_spell.name}, state)

    assert state.player.spells == [0, 1, 2, 3, 4, 5, 6, 7, 8, overflow_spell.id]
    assert state.player.nspells == constants.MAXSPL
    assert result.events[0]["message_id"] == "LOSSPL"
    assert forgotten_spell.name in result.events[0]["text"]
    assert result.events[1]["message_id"] == "MEMSPL"
    assert result.events[1]["exclude_player"] == state.player.plyrid


@pytest.mark.anyio
async def test_memorize_persists_player_state():
    engine = get_engine("sqlite+pysqlite:///:memory:")
    init_db_schema(engine)
    session = create_session(engine)

    base_player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        offspls=0,
        defspls=0,
        othspls=0,
        spells=[],
        nspells=0,
    )
    _set_owned_spells(base_player, [0])
    session.add(models.Player(**base_player.model_dump()))
    session.commit()

    state = _build_state(base_player)
    state.db_session = session
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    await dispatcher.dispatch("memorize", {"raw": "abbracada"}, state)

    record = session.scalar(select(models.Player).where(models.Player.plyrid == base_player.plyrid))
    assert record is not None
    assert record.spells == [0]
    assert record.nspells == 1


@pytest.mark.anyio
async def test_spells_command_renders_legacy_memorized_grammar_and_status_payload():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        level=7,
        spts=19,
        spells=[0, 2, 5],
        nspells=3,
    )
    state = _build_state(player)
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("spells", {}, state)

    assert len(result.events) == 1
    event = result.events[0]
    assert event["type"] == "room_message"
    assert (
        event["text"]
        == '"abbracada", "blowitawa", and "burnup" memorized, and 19 spell points of energy.  '
        'You are at level 7, titled "Enchanter".'
    )
    assert event["memorized_spell_ids"] == [0, 2, 5]
    assert event["memorized_spell_names"] == ["abbracada", "blowitawa", "burnup"]
    assert event["spts"] == 19
    assert event["level"] == 7
    assert event["title"] == "Enchanter"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("spells", "expected_text"),
    [
        (
            [],
            'no spells memorized, and 4 spell points of energy.  You are at level 1, titled "Apprentice".',
        ),
        (
            [0],
            '"abbracada" memorized, and 4 spell points of energy.  You are at level 1, titled "Apprentice".',
        ),
        (
            [0, 1],
            '"abbracada" and "allbettoo" memorized, and 4 spell points of energy.  '
            'You are at level 1, titled "Apprentice".',
        ),
    ],
)
async def test_spells_command_matches_legacy_grammar_for_zero_one_two(
    spells, expected_text
):
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        level=1,
        spts=4,
        spells=spells,
        nspells=len(spells),
    )
    state = _build_state(player)
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("spells", {}, state)

    assert result.events[0]["text"] == expected_text
