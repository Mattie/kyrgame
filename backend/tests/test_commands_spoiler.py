import pytest

from kyrgame import commands, fixtures


@pytest.fixture
def base_state():
    locations = {location.id: location for location in fixtures.load_locations()}
    objects = {obj.id: obj for obj in fixtures.load_objects()}
    player = fixtures.build_player()
    return commands.GameState(
        player=player,
        locations=locations,
        objects=objects,
        messages=fixtures.load_messages(),
        content_mappings=fixtures.load_content_mappings(),
    )


@pytest.mark.anyio
async def test_spoiler_emits_room_summary_and_interaction(base_state):
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    base_state.player.gamloc = 8

    result = await dispatcher.dispatch("spoiler", {}, base_state)

    assert result.events
    event = result.events[0]
    assert event["type"] == "spoiler"
    assert event["location"] == 8
    assert event["summary"] == (
        "Gem cutter's hut where a jeweler quietly evaluates offered stones and pays out discreetly."
    )
    assert "trade" in event["interaction"]


@pytest.mark.anyio
async def test_spoiler_skips_rooms_without_metadata(base_state):
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    base_state.player.gamloc = 1

    result = await dispatcher.dispatch("spoiler", {}, base_state)

    assert result.events == []


@pytest.mark.anyio
async def test_spoiler_uses_yaml_room_metadata(base_state):
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    base_state.player.gamloc = 8

    result = await dispatcher.dispatch("spoiler", {}, base_state)

    event = result.events[0]
    assert event["summary"].startswith("Gem cutter's hut")
    assert "kyragem" in event["interaction"]
