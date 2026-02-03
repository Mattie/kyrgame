import pytest

from kyrgame import commands, constants, fixtures, models


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
    return commands.GameState(
        player=player,
        locations=locations,
        objects=objects,
        messages=fixtures.load_messages(),
        content_mappings=fixtures.load_content_mappings(),
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
async def test_move_blocks_missing_exit_and_sets_message_id(base_state):
    vocabulary = commands.CommandVocabulary(
        fixtures.load_commands(), fixtures.load_messages()
    )
    registry = commands.build_default_registry(vocabulary)
    dispatcher = commands.CommandDispatcher(registry)

    base_state.player.gamloc = 7
    parsed = vocabulary.parse_text("east")

    with pytest.raises(commands.BlockedExitError) as excinfo:
        await dispatcher.dispatch_parsed(parsed, base_state)

    assert excinfo.value.message_id == "MOVUTL"
    assert base_state.player.gamloc == 7


@pytest.mark.anyio
async def test_move_emits_default_description(base_state):
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry, clock=FakeClock())

    result = await dispatcher.dispatch("move", {"direction": "north"}, base_state)

    descriptions = [evt for evt in result.events if evt.get("type") == "location_description"]
    assert descriptions, "expected a location description event"

    description = descriptions[0]
    assert description["message_id"] == "KRD001"
    assert description["text"].startswith("...You're on a north/south path")


@pytest.mark.anyio
async def test_move_respects_brief_flag_for_room_entry(base_state):
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry, clock=FakeClock())

    base_state.player.flags |= int(constants.PlayerFlag.BRFSTF)

    result = await dispatcher.dispatch("move", {"direction": "north"}, base_state)

    description_events = [
        evt for evt in result.events if evt.get("type") == "location_description"
    ]
    assert description_events
    assert description_events[0]["text"] == base_state.locations[1].brfdes
    assert description_events[0]["message_id"] is None


@pytest.mark.anyio
async def test_inventory_reports_empty_pack_and_gold_total(base_state):
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry, clock=FakeClock())

    base_state.player = base_state.player.model_copy(
        update={"gpobjs": [], "obvals": [], "npobjs": 0, "gold": 1}
    )

    result = await dispatcher.dispatch("inventory", {}, base_state)

    inventory_events = [evt for evt in result.events if evt.get("type") == "inventory"]
    assert inventory_events

    inventory = inventory_events[0]
    assert inventory["items"] == []
    assert inventory["text"] == "...You have your spellbook and 1 piece of gold."


@pytest.mark.anyio
async def test_inventory_lists_items_in_order_with_values(base_state):
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry, clock=FakeClock())

    base_state.player = base_state.player.model_copy(
        update={"gpobjs": [1, 0], "obvals": [7, 3], "npobjs": 2}
    )

    result = await dispatcher.dispatch("inventory", {}, base_state)

    inventory_events = [evt for evt in result.events if evt.get("type") == "inventory"]
    assert inventory_events

    inventory = inventory_events[0]
    assert [item["id"] for item in inventory["items"]] == [1, 0]
    assert [item["value"] for item in inventory["items"]] == [7, 3]
    assert [item["name"] for item in inventory["items"]] == ["emerald", "ruby"]
    assert inventory["text"].startswith("...You have an emerald, a ruby, your spellbook")


@pytest.mark.anyio
async def test_inventory_message_id_travels_with_command(base_state):
    vocabulary = commands.CommandVocabulary(
        fixtures.load_commands(), fixtures.load_messages()
    )
    registry = commands.build_default_registry(vocabulary)
    dispatcher = commands.CommandDispatcher(registry, clock=FakeClock())

    parsed = vocabulary.parse_text("inv")
    result = await dispatcher.dispatch_parsed(parsed, base_state)

    inventory_events = [evt for evt in result.events if evt.get("type") == "inventory"]
    assert inventory_events
    assert inventory_events[0]["message_id"] == "CMD029"


@pytest.mark.parametrize(
    "input_text,direction,expected_command_id",
    [
        ("n", "north", 37),
        ("north", "north", 38),
        ("s", "south", 52),
        ("south", "south", 63),
        ("e", "east", 13),
        ("east", "east", 14),
        ("w", "west", 73),
        ("west", "west", 74),
    ],
)
@pytest.mark.anyio
async def test_move_aliases_require_loaded_and_emit_message_ids(
    base_state, input_text, direction, expected_command_id
):
    vocabulary = commands.CommandVocabulary(
        fixtures.load_commands(), fixtures.load_messages()
    )
    registry = commands.build_default_registry(vocabulary)
    dispatcher = commands.CommandDispatcher(registry)

    base_state.player.flags = 0
    parsed = vocabulary.parse_text(input_text)

    with pytest.raises(commands.FlagRequirementError):
        await dispatcher.dispatch_parsed(parsed, base_state)

    base_state.player.flags = int(constants.PlayerFlag.LOADED)
    parsed = vocabulary.parse_text(input_text)

    result = await dispatcher.dispatch_parsed(parsed, base_state)

    assert base_state.player.gamloc == base_state.locations[0].__getattribute__(
        commands._DIRECTION_FIELDS[direction]
    )
    location_events = [evt for evt in result.events if evt.get("type") == "location_update"]
    assert location_events
    assert location_events[0]["message_id"] == f"CMD{expected_command_id:03d}"


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


@pytest.mark.anyio
async def test_get_moves_object_from_room_to_inventory(base_state):
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry, clock=FakeClock())

    base_state.player = base_state.player.model_copy(
        update={"gpobjs": [], "obvals": [], "npobjs": 0}
    )

    location = base_state.locations[base_state.player.gamloc]
    target_id = next(
        obj_id
        for obj_id in location.objects
        if "PICKUP" in base_state.objects[obj_id].flags
    )
    target_name = base_state.objects[target_id].name

    result = await dispatcher.dispatch("get", {"target": target_name}, base_state)

    location = base_state.locations[base_state.player.gamloc]
    assert target_id in base_state.player.gpobjs
    assert base_state.player.npobjs == 1
    assert target_id not in location.objects
    assert location.nlobjs == len(location.objects)

    inventory_events = [evt for evt in result.events if evt.get("type") == "inventory"]
    assert inventory_events
    assert any(item["id"] == target_id for item in inventory_events[0]["items"])


@pytest.mark.anyio
async def test_drop_places_object_in_room(base_state):
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry, clock=FakeClock())

    location = base_state.locations[base_state.player.gamloc]
    target_id = location.objects[0]
    target_name = base_state.objects[target_id].name

    base_state.locations[location.id] = location.model_copy(update={"objects": [], "nlobjs": 0})
    location = base_state.locations[location.id]
    base_state.player = base_state.player.model_copy(
        update={"gpobjs": [target_id], "obvals": [0], "npobjs": 1}
    )

    result = await dispatcher.dispatch("drop", {"target": target_name}, base_state)

    location = base_state.locations[location.id]
    assert target_id in location.objects
    assert location.nlobjs == len(location.objects)
    assert target_id not in base_state.player.gpobjs
    assert base_state.player.npobjs == 0

    object_events = [evt for evt in result.events if evt.get("type") == "room_objects"]
    assert object_events
    assert any(obj["id"] == target_id for obj in object_events[0]["objects"])


@pytest.mark.anyio
async def test_move_emits_room_objects_from_updated_state(base_state):
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry, clock=FakeClock())

    base_state.player = base_state.player.model_copy(
        update={"gpobjs": [], "obvals": [], "npobjs": 0}
    )

    starting_location = base_state.locations[base_state.player.gamloc]
    target_id = next(
        obj_id
        for obj_id in starting_location.objects
        if "PICKUP" in base_state.objects[obj_id].flags
    )
    target_name = base_state.objects[target_id].name

    await dispatcher.dispatch("get", {"target": target_name}, base_state)
    await dispatcher.dispatch("move", {"direction": "north"}, base_state)
    result = await dispatcher.dispatch("move", {"direction": "south"}, base_state)

    object_events = [evt for evt in result.events if evt.get("type") == "room_objects"]
    assert object_events
    assert all(obj["id"] != target_id for obj in object_events[0]["objects"])


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
async def test_pickup_synonyms_route_to_get_handler(base_state):
    vocabulary = commands.CommandVocabulary(
        fixtures.load_commands(), fixtures.load_messages()
    )
    registry = commands.build_default_registry(vocabulary)
    dispatcher = commands.CommandDispatcher(registry, clock=FakeClock())

    starting_location = base_state.locations[base_state.player.gamloc]
    target_id = next(
        obj_id
        for obj_id in starting_location.objects
        if "PICKUP" in base_state.objects[obj_id].flags
    )
    target_name = base_state.objects[target_id].name

    parsed = vocabulary.parse_text(f"take {target_name}")
    result = await dispatcher.dispatch_parsed(parsed, base_state)

    assert parsed.verb == "take"
    assert parsed.args["target"] == target_name
    assert parsed.command_id == 68  # legacy command id for "take"
    assert target_id in base_state.player.gpobjs

    base_state.player = base_state.player.model_copy(
        update={"gpobjs": [], "obvals": [], "npobjs": 0}
    )
    base_state.locations[base_state.player.gamloc].objects.append(target_id)

    parsed_snatch = vocabulary.parse_text(f"snatch {target_name}")
    await dispatcher.dispatch_parsed(parsed_snatch, base_state)

    assert parsed_snatch.verb == "snatch"
    assert parsed_snatch.command_id == 62  # legacy command id for "snatch"
    assert target_id in base_state.player.gpobjs


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
