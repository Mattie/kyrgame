import pytest

from kyrgame import commands, constants, fixtures


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
