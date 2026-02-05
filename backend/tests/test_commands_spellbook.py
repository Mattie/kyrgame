import pytest
from sqlalchemy import select

from kyrgame import commands, constants, fixtures
from kyrgame.database import create_session, get_engine, init_db_schema
from kyrgame import models


class FakePresence:
    async def players_in_room(self, room_id: int) -> set[str]:  # noqa: ARG002
        return set()


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
