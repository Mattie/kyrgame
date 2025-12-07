import pytest

from kyrgame import commands, fixtures, models


class FakeClock:
    def __init__(self, start: float = 100.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float):
        self.now += seconds


@pytest.fixture
def base_state():
    locations = {location.id: location for location in fixtures.load_locations()}
    objects = {obj.id: obj for obj in fixtures.load_objects()}
    player = fixtures.build_player()
    messages = fixtures.load_messages()
    mappings = fixtures.load_content_mappings().get("locations", {})
    return commands.GameState(
        player=player,
        locations=locations,
        objects=objects,
        messages=messages,
        location_mappings=mappings,
    )


def test_registry_exposes_command_metadata():
    registry = commands.build_default_registry()

    move_entry = registry["move"]
    chat_entry = registry["chat"]

    assert move_entry.metadata.required_level >= 1
    assert chat_entry.metadata.required_level == 0
    assert move_entry.metadata.cooldown_seconds == 0
    assert chat_entry.metadata.cooldown_seconds > 0


@pytest.mark.parametrize(
    "verb,args,expected_location,expected_event_type",
    [
        ("move", {"direction": "north"}, 1, "player_moved"),
        ("chat", {"text": "hello"}, 0, "chat"),
        ("inventory", {}, 0, "inventory"),
    ],
)
@pytest.mark.anyio
async def test_command_handlers_apply_state_and_emit_events(base_state, verb, args, expected_location, expected_event_type):
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry, clock=FakeClock())

    result = await dispatcher.dispatch(verb, args, base_state)

    assert base_state.player.gamloc == expected_location
    assert any(event["type"] == expected_event_type for event in result.events)
    assert result.state.player is base_state.player


@pytest.mark.anyio
async def test_move_tracks_previous_location(base_state):
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry, clock=FakeClock())

    base_state.player.pgploc = 99

    await dispatcher.dispatch("move", {"direction": "north"}, base_state)

    assert base_state.player.pgploc == 0
    assert base_state.player.gamloc == 1


@pytest.mark.anyio
async def test_move_emits_default_description(base_state):
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("move", {"direction": "north"}, base_state)

    update = next(evt for evt in result.events if evt["event"] == "location_update")
    assert update["description"].startswith("...You're on a north/south path")


@pytest.mark.anyio
async def test_insufficient_level_blocks_execution(base_state):
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    base_state.player.level = 0

    with pytest.raises(commands.LevelRequirementError):
        await dispatcher.dispatch("move", {"direction": "north"}, base_state)


@pytest.mark.anyio
async def test_blocked_exit_prevents_move(base_state):
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    base_state.player.gamloc = 7

    with pytest.raises(commands.BlockedExitError):
        await dispatcher.dispatch("move", {"direction": "east"}, base_state)


@pytest.mark.anyio
async def test_cooldown_prevents_spam(base_state):
    clock = FakeClock()
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry, clock=clock)

    await dispatcher.dispatch("chat", {"text": "hello"}, base_state)

    with pytest.raises(commands.CooldownActiveError):
        await dispatcher.dispatch("chat", {"text": "hello again"}, base_state)

    clock.advance(registry["chat"].metadata.cooldown_seconds + 0.1)
    result = await dispatcher.dispatch("chat", {"text": "hello later"}, base_state)

    assert any(
        event["type"] == "chat" and event["text"] == "hello later" for event in result.events
    )


def test_vocabulary_maps_aliases_to_canonical_commands():
    vocabulary = commands.CommandVocabulary(
        fixtures.load_commands(), fixtures.load_messages()
    )

    parsed_move = vocabulary.parse_text("n")
    parsed_chat = vocabulary.parse_text("say hello there")

    assert parsed_move.verb == "move"
    assert parsed_move.args["direction"] == "north"
    assert parsed_move.command_id == 37  # legacy command id for "n"

    assert parsed_chat.verb == "chat"
    assert parsed_chat.args["text"] == "hello there"
    assert parsed_chat.args["mode"] == "say"
    assert parsed_chat.command_id == 53  # legacy command id for "say"


@pytest.mark.anyio
async def test_payonl_commands_require_live_flag(base_state):
    vocabulary = commands.CommandVocabulary(
        fixtures.load_commands(), fixtures.load_messages()
    )
    registry = commands.build_default_registry(vocabulary)
    dispatcher = commands.CommandDispatcher(registry)

    base_state.player.flags = 0
    parsed = vocabulary.parse_text("aim goblin")

    with pytest.raises(commands.FlagRequirementError) as excinfo:
        await dispatcher.dispatch_parsed(parsed, base_state)

    assert excinfo.value.message_id == "CMPCMD1"


@pytest.mark.anyio
async def test_inventory_command_lists_named_items(base_state):
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("inventory", {}, base_state)

    event = next(evt for evt in result.events if evt["event"] == "inventory")
    assert event["inventory"] == ["a ruby", "an emerald"]
    assert event["gold"] == base_state.player.gold


@pytest.mark.anyio
async def test_get_moves_visible_object_into_inventory(base_state):
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    base_state.player.gamloc = 0

    result = await dispatcher.dispatch("get", {"raw": "garnet"}, base_state)

    assert 2 in base_state.player.gpobjs
    assert base_state.player.npobjs == len(base_state.player.gpobjs)
    assert 2 not in base_state.locations[0].objects

    inventory_event = next(evt for evt in result.events if evt["event"] == "inventory")
    assert any("garnet" in item for item in inventory_event["inventory"])


@pytest.mark.anyio
async def test_drop_removes_object_from_inventory(base_state):
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    base_state.player.gamloc = 0
    base_state.player.gpobjs[:] = [2]
    base_state.player.obvals[:] = [0]
    base_state.player.npobjs = 1
    base_state.locations[0].objects[:] = []
    base_state.locations[0].nlobjs = 0

    await dispatcher.dispatch("drop", {"raw": "garnet"}, base_state)

    assert 2 not in base_state.player.gpobjs
    assert base_state.player.npobjs == len(base_state.player.gpobjs)
    assert 2 in base_state.locations[0].objects
    assert base_state.locations[0].nlobjs == len(base_state.locations[0].objects)
