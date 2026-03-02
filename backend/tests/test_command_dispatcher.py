import pytest
from sqlalchemy import select

from kyrgame import commands, constants, fixtures, models
from kyrgame.database import create_session, get_engine, init_db_schema


class FakeClock:
    def __init__(self, start: float = 100.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float):
        self.now += seconds


class StubPresence:
    def __init__(self, occupants):
        self.occupants = occupants

    async def players_in_room(self, room_id: int):  # noqa: ARG002
        return set(self.occupants)


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


def test_command_vocabulary_normalizes_articles_and_prepositions_for_non_chat():
    vocabulary = commands.CommandVocabulary(
        fixtures.load_commands(), fixtures.load_messages()
    )

    parsed = vocabulary.parse_text("get the sword")

    assert parsed.verb == "get"
    assert parsed.args["target"] == "sword"

    parsed = vocabulary.parse_text("put sword in rock")

    assert parsed.verb == "put"
    assert parsed.args["raw"] == "sword rock"


def test_command_vocabulary_preserves_chat_text():
    vocabulary = commands.CommandVocabulary(
        fixtures.load_commands(), fixtures.load_messages()
    )

    parsed = vocabulary.parse_text("say \"hello there\"")

    assert parsed.verb == "say"
    assert parsed.args["text"] == '"hello there"'


def test_command_vocabulary_parses_whisper_target_and_quoted_text():
    vocabulary = commands.CommandVocabulary(
        fixtures.load_commands(), fixtures.load_messages()
    )

    parsed = vocabulary.parse_text("whisper to alice \"hello there\"")

    assert parsed.verb == "whisper"
    assert parsed.args["target_player"] == "alice"
    assert parsed.args["text"] == '"hello there"'


def test_command_vocabulary_preserves_full_whisper_text_without_to_prefix():
    vocabulary = commands.CommandVocabulary(
        fixtures.load_commands(), fixtures.load_messages()
    )

    parsed = vocabulary.parse_text('whisper seer "keep very quiet"')

    assert parsed.verb == "whisper"
    assert parsed.args["target_player"] == "seer"
    assert parsed.args["text"] == '"keep very quiet"'


def test_command_vocabulary_parses_give_gold_and_item_patterns():
    vocabulary = commands.CommandVocabulary(
        fixtures.load_commands(), fixtures.load_messages()
    )

    gold = vocabulary.parse_text("give 5 gold to seer")
    assert gold.verb == "give"
    assert gold.args["gold_amount"] == "5"
    assert gold.args["target_player"] == "seer"

    # Legacy target-first gold form: give <target> <amount> gold (KYRCMDS.C:500-501)
    gold_target_first = vocabulary.parse_text("give seer 5 gold")
    assert gold_target_first.verb == "give"
    assert gold_target_first.args["gold_amount"] == "5"
    assert gold_target_first.args["target_player"] == "seer"

    item = vocabulary.parse_text("give ruby to seer")
    assert item.verb == "give"
    assert item.args["target_item"] == "ruby"
    assert item.args["target_player"] == "seer"

    # Legacy target-first item form: give <target> <item> (KYRCMDS.C:503-504)
    item_target_first = vocabulary.parse_text("give seer ruby")
    assert item_target_first.verb == "give"
    assert item_target_first.args["target_item"] == "ruby"
    assert item_target_first.args["target_player"] == "seer"


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
    parsed_say = vocabulary.parse_text("say hello there")

    assert parsed_move.verb == "move"
    assert parsed_move.args["direction"] == "north"
    assert parsed_move.command_id == 37  # legacy command id for "n"

    assert parsed_say.verb == "say"
    assert parsed_say.args["text"] == "hello there"
    assert parsed_say.command_id == 53  # legacy command id for "say"


def test_vocabulary_parses_player_targeted_get_patterns():
    vocabulary = commands.CommandVocabulary(
        fixtures.load_commands(), fixtures.load_messages()
    )

    parsed_from = vocabulary.parse_text("take ruby from Buddy")
    assert parsed_from.verb == "take"
    assert parsed_from.args["target"] == "ruby"
    assert parsed_from.args["target_player"] == "Buddy"

    parsed_possessive = vocabulary.parse_text("steal Buddy's ruby")
    assert parsed_possessive.verb == "steal"
    assert parsed_possessive.args["target"] == "ruby"
    assert parsed_possessive.args["target_player"] == "Buddy"


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


@pytest.mark.anyio
async def test_give_gold_moves_currency_to_target(base_state):
    vocabulary = commands.CommandVocabulary(fixtures.load_commands(), fixtures.load_messages())
    registry = commands.build_default_registry(vocabulary)
    dispatcher = commands.CommandDispatcher(registry)
    target = base_state.player.model_copy(
        update={"plyrid": "seer", "attnam": "seer", "altnam": "Seer", "gamloc": base_state.player.gamloc}
    )
    players = {base_state.player.plyrid: base_state.player, target.plyrid: target}

    base_state.presence = StubPresence({base_state.player.plyrid, target.plyrid})
    base_state.player_lookup = players.get
    base_state.player.gold = 100

    parsed = vocabulary.parse_text("give 5 gold to seer")
    await dispatcher.dispatch_parsed(parsed, base_state)

    assert base_state.player.gold == 95
    assert target.gold >= 5


@pytest.mark.anyio
async def test_give_negative_gold_to_missing_player_returns_givcrd1(base_state):
    """Legacy givcrd() validates amount before target lookup; negative gold returns GIVCRD1 (KYRCMDS.C:523-527)."""
    vocabulary = commands.CommandVocabulary(fixtures.load_commands(), fixtures.load_messages())
    registry = commands.build_default_registry(vocabulary)
    dispatcher = commands.CommandDispatcher(registry)
    base_state.presence = StubPresence({base_state.player.plyrid})
    base_state.player_lookup = {base_state.player.plyrid: base_state.player}.get
    base_state.player.gold = 100

    parsed = vocabulary.parse_text("give -1 gold to nosuch")
    result = await dispatcher.dispatch_parsed(parsed, base_state)

    assert any(evt.get("message_id") == "GIVCRD1" for evt in result.events)


@pytest.mark.anyio
async def test_give_excess_gold_to_missing_player_returns_givcrd2(base_state):
    """Legacy givcrd() validates amount before target lookup; excess gold returns GIVCRD2 (KYRCMDS.C:528-532)."""
    vocabulary = commands.CommandVocabulary(fixtures.load_commands(), fixtures.load_messages())
    registry = commands.build_default_registry(vocabulary)
    dispatcher = commands.CommandDispatcher(registry)
    base_state.presence = StubPresence({base_state.player.plyrid})
    base_state.player_lookup = {base_state.player.plyrid: base_state.player}.get
    base_state.player.gold = 10

    parsed = vocabulary.parse_text("give 999 gold to nosuch")
    result = await dispatcher.dispatch_parsed(parsed, base_state)

    assert any(evt.get("message_id") == "GIVCRD2" for evt in result.events)


@pytest.mark.anyio
async def test_give_gold_to_missing_player_returns_givcrd3(base_state):
    """Valid gold amount with missing target returns GIVCRD3 (KYRCMDS.C:533-536)."""
    vocabulary = commands.CommandVocabulary(fixtures.load_commands(), fixtures.load_messages())
    registry = commands.build_default_registry(vocabulary)
    dispatcher = commands.CommandDispatcher(registry)
    base_state.presence = StubPresence({base_state.player.plyrid})
    base_state.player_lookup = {base_state.player.plyrid: base_state.player}.get
    base_state.player.gold = 100

    parsed = vocabulary.parse_text("give 5 gold to nosuch")
    result = await dispatcher.dispatch_parsed(parsed, base_state)

    assert any(evt.get("message_id") == "GIVCRD3" for evt in result.events)


@pytest.mark.anyio
async def test_give_gold_persists_both_players(tmp_path, base_state):
    engine = get_engine(f"sqlite:///{tmp_path / 'kyrgame.db'}")
    init_db_schema(engine)
    with create_session(engine) as session:
        vocabulary = commands.CommandVocabulary(fixtures.load_commands(), fixtures.load_messages())
        registry = commands.build_default_registry(vocabulary)
        dispatcher = commands.CommandDispatcher(registry)
        target = base_state.player.model_copy(
            update={"plyrid": "seer", "attnam": "seer", "altnam": "Seer", "gamloc": base_state.player.gamloc, "gold": 0}
        )
        session.add(models.Player(**base_state.player.model_dump()))
        session.add(models.Player(**target.model_dump()))
        session.commit()

        players = {base_state.player.plyrid: base_state.player, target.plyrid: target}
        base_state.presence = StubPresence({base_state.player.plyrid, target.plyrid})
        base_state.player_lookup = players.get
        base_state.player.gold = 100
        base_state.db_session = session

        parsed = vocabulary.parse_text("give 5 gold to seer")
        await dispatcher.dispatch_parsed(parsed, base_state)

        giver_record = session.scalar(select(models.Player).where(models.Player.plyrid == base_state.player.plyrid))
        target_record = session.scalar(select(models.Player).where(models.Player.plyrid == target.plyrid))

        assert giver_record is not None
        assert target_record is not None
        assert giver_record.gold == 95
        assert target_record.gold == 5


@pytest.mark.anyio
async def test_give_item_persists_both_players_inventory(tmp_path, base_state):
    engine = get_engine(f"sqlite:///{tmp_path / 'kyrgame.db'}")
    init_db_schema(engine)
    with create_session(engine) as session:
        vocabulary = commands.CommandVocabulary(fixtures.load_commands(), fixtures.load_messages())
        registry = commands.build_default_registry(vocabulary)
        dispatcher = commands.CommandDispatcher(registry)
        target = base_state.player.model_copy(
            update={
                "plyrid": "seer",
                "attnam": "seer",
                "altnam": "Seer",
                "gamloc": base_state.player.gamloc,
                "gpobjs": [],
                "obvals": [],
                "npobjs": 0,
            }
        )
        session.add(models.Player(**base_state.player.model_dump()))
        session.add(models.Player(**target.model_dump()))
        session.commit()

        players = {base_state.player.plyrid: base_state.player, target.plyrid: target}
        base_state.presence = StubPresence({base_state.player.plyrid, target.plyrid})
        base_state.player_lookup = players.get
        base_state.db_session = session

        given_obj_id = base_state.player.gpobjs[0]
        given_obj_name = base_state.objects[given_obj_id].name

        # Legacy order: give <target> <item>  (KYRCMDS.C:503-504)
        parsed = vocabulary.parse_text(f"give seer {given_obj_name}")
        await dispatcher.dispatch_parsed(parsed, base_state)

        giver_record = session.scalar(select(models.Player).where(models.Player.plyrid == base_state.player.plyrid))
        target_record = session.scalar(select(models.Player).where(models.Player.plyrid == target.plyrid))

        assert giver_record is not None
        assert target_record is not None
        assert given_obj_id not in giver_record.gpobjs
        assert given_obj_id in target_record.gpobjs


@pytest.mark.anyio
async def test_give_item_target_message_includes_giver_name(base_state):
    vocabulary = commands.CommandVocabulary(fixtures.load_commands(), fixtures.load_messages())
    registry = commands.build_default_registry(vocabulary)
    dispatcher = commands.CommandDispatcher(registry)
    target = base_state.player.model_copy(
        update={"plyrid": "seer", "attnam": "seer", "altnam": "Seer", "gamloc": base_state.player.gamloc}
    )
    players = {base_state.player.plyrid: base_state.player, target.plyrid: target}
    base_state.presence = StubPresence({base_state.player.plyrid, target.plyrid})
    base_state.player_lookup = players.get

    # Legacy order: give <target> <item>  (KYRCMDS.C:503-504)
    parsed = vocabulary.parse_text("give seer ruby")
    result = await dispatcher.dispatch_parsed(parsed, base_state)

    target_event = next(evt for evt in result.events if evt.get("scope") == "target")
    assert target_event["message_id"] == "GIVERU10"
    assert base_state.player.altnam in target_event["text"]
    assert "given you a ruby!" in target_event["text"]


@pytest.mark.anyio
async def test_whisper_emits_target_and_room_events(base_state):
    vocabulary = commands.CommandVocabulary(fixtures.load_commands(), fixtures.load_messages())
    registry = commands.build_default_registry(vocabulary)
    dispatcher = commands.CommandDispatcher(registry)
    target = base_state.player.model_copy(
        update={"plyrid": "seer", "attnam": "seer", "altnam": "Seer", "gamloc": base_state.player.gamloc}
    )
    players = {base_state.player.plyrid: base_state.player, target.plyrid: target}

    base_state.presence = StubPresence({base_state.player.plyrid, target.plyrid})
    base_state.player_lookup = players.get

    parsed = vocabulary.parse_text('whisper seer "keep quiet"')
    result = await dispatcher.dispatch_parsed(parsed, base_state)

    assert any(evt.get("scope") == "target" and evt.get("message_id") == "WHISPR1" for evt in result.events)
    assert any(evt.get("scope") == "room" and evt.get("message_id") == "WHISPR3" for evt in result.events)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "raw_command,expected_message_id",
    [
        ('whisper seer "keep quiet"', "NOSUCHP"),
        ("give 5 gold to seer", "GIVCRD3"),
        ("wink seer", "WINKER5"),
    ],
)
async def test_targeted_commands_cannot_find_invisible_players_without_see_invis(base_state, raw_command, expected_message_id):
    vocabulary = commands.CommandVocabulary(fixtures.load_commands(), fixtures.load_messages())
    registry = commands.build_default_registry(vocabulary)
    dispatcher = commands.CommandDispatcher(registry)
    target = base_state.player.model_copy(
        update={
            "plyrid": "seer",
            "attnam": "seer",
            "altnam": "Seer",
            "gamloc": base_state.player.gamloc,
            "flags": int(base_state.player.flags | constants.PlayerFlag.INVISF),
        }
    )
    players = {base_state.player.plyrid: base_state.player, target.plyrid: target}

    base_state.presence = StubPresence({base_state.player.plyrid, target.plyrid})
    base_state.player_lookup = players.get

    parsed = vocabulary.parse_text(raw_command)
    result = await dispatcher.dispatch_parsed(parsed, base_state)

    assert len(result.events) == 1
    assert result.events[0]["scope"] == "player"
    assert result.events[0]["message_id"] == expected_message_id


@pytest.mark.anyio
async def test_whisper_can_target_invisible_player_with_see_invis_charm(base_state):
    vocabulary = commands.CommandVocabulary(fixtures.load_commands(), fixtures.load_messages())
    registry = commands.build_default_registry(vocabulary)
    dispatcher = commands.CommandDispatcher(registry)
    target = base_state.player.model_copy(
        update={
            "plyrid": "seer",
            "attnam": "seer",
            "altnam": "Seer",
            "gamloc": base_state.player.gamloc,
            "flags": int(base_state.player.flags | constants.PlayerFlag.INVISF),
        }
    )
    players = {base_state.player.plyrid: base_state.player, target.plyrid: target}

    base_state.presence = StubPresence({base_state.player.plyrid, target.plyrid})
    base_state.player_lookup = players.get
    base_state.player.charms[constants.CharmSlot.INVISIBILITY] = 2

    parsed = vocabulary.parse_text('whisper seer "keep quiet"')
    result = await dispatcher.dispatch_parsed(parsed, base_state)

    assert any(evt.get("scope") == "target" and evt.get("message_id") == "WHISPR1" for evt in result.events)


@pytest.mark.anyio
async def test_yell_with_text_broadcasts_to_nearby_rooms(base_state):
    """Legacy yeller() calls sndnear() to send YELLER6 to adjacent rooms.

    See legacy/KYRCMDS.C:319-322 and legacy/KYRUTIL.C:193-208.
    """
    vocabulary = commands.CommandVocabulary(fixtures.load_commands(), fixtures.load_messages())
    registry = commands.build_default_registry(vocabulary)
    dispatcher = commands.CommandDispatcher(registry)

    parsed = vocabulary.parse_text("yell hello world")
    result = await dispatcher.dispatch_parsed(parsed, base_state)

    nearby_events = [e for e in result.events if e.get("scope") == "nearby_room"]
    loc = base_state.locations[base_state.player.gamloc]
    expected_rooms = {r for r in (loc.gi_north, loc.gi_south, loc.gi_east, loc.gi_west) if r >= 0 and r != base_state.player.gamloc}
    assert len(nearby_events) == len(expected_rooms)
    for evt in nearby_events:
        assert evt["message_id"] == "YELLER6"
        assert evt["room_id"] in expected_rooms
        assert "HELLO WORLD" in (evt.get("text") or "")


@pytest.mark.anyio
async def test_yell_without_text_broadcasts_yeller2_to_nearby_rooms(base_state):
    """Legacy yeller() also calls sndnear() with YELLER2 when no text given.

    See legacy/KYRCMDS.C:308 and legacy/KYRUTIL.C:193-208.
    """
    vocabulary = commands.CommandVocabulary(fixtures.load_commands(), fixtures.load_messages())
    registry = commands.build_default_registry(vocabulary)
    dispatcher = commands.CommandDispatcher(registry)

    parsed = vocabulary.parse_text("yell")
    result = await dispatcher.dispatch_parsed(parsed, base_state)

    nearby_events = [e for e in result.events if e.get("scope") == "nearby_room"]
    loc = base_state.locations[base_state.player.gamloc]
    expected_rooms = {r for r in (loc.gi_north, loc.gi_south, loc.gi_east, loc.gi_west) if r >= 0 and r != base_state.player.gamloc}
    assert len(nearby_events) == len(expected_rooms)
    for evt in nearby_events:
        assert evt["message_id"] == "YELLER2"
        assert evt["room_id"] in expected_rooms


@pytest.mark.anyio
async def test_say_broadcasts_speak3_to_nearby_rooms(base_state):
    """Legacy speakr() calls sndnear() to send SPEAK3 to adjacent rooms.

    See legacy/KYRCMDS.C:260-261 and legacy/KYRUTIL.C:193-208.
    """
    vocabulary = commands.CommandVocabulary(fixtures.load_commands(), fixtures.load_messages())
    registry = commands.build_default_registry(vocabulary)
    dispatcher = commands.CommandDispatcher(registry)

    parsed = vocabulary.parse_text("say hello")
    result = await dispatcher.dispatch_parsed(parsed, base_state)

    nearby_events = [e for e in result.events if e.get("scope") == "nearby_room"]
    loc = base_state.locations[base_state.player.gamloc]
    expected_rooms = {r for r in (loc.gi_north, loc.gi_south, loc.gi_east, loc.gi_west) if r >= 0 and r != base_state.player.gamloc}
    assert len(nearby_events) == len(expected_rooms)
    for evt in nearby_events:
        assert evt["message_id"] == "SPEAK3"
        assert evt["room_id"] in expected_rooms


@pytest.mark.anyio
async def test_say_room_broadcast_includes_player_context(base_state):
    """Legacy speakr() sends SPEAK1 (actor context) + SPEAK2 (text) via sndoth().

    The room event text must include the player name so other players know who spoke.
    See legacy/KYRCMDS.C:254-259.
    """
    vocabulary = commands.CommandVocabulary(fixtures.load_commands(), fixtures.load_messages())
    registry = commands.build_default_registry(vocabulary)
    dispatcher = commands.CommandDispatcher(registry)

    parsed = vocabulary.parse_text("say hello world")
    result = await dispatcher.dispatch_parsed(parsed, base_state)

    room_events = [e for e in result.events if e.get("scope") == "room"]
    assert len(room_events) == 1
    room_text = room_events[0].get("text") or ""
    assert base_state.player.altnam in room_text
    assert "hello world" in room_text


@pytest.mark.anyio
async def test_yell_room_broadcast_includes_player_context(base_state):
    """Legacy yeller() sends YELLER4 (actor context) + YELLER5 (text) via sndoth().

    The room event text must include the player name so other players know who yelled.
    See legacy/KYRCMDS.C:314-319.
    """
    vocabulary = commands.CommandVocabulary(fixtures.load_commands(), fixtures.load_messages())
    registry = commands.build_default_registry(vocabulary)
    dispatcher = commands.CommandDispatcher(registry)

    parsed = vocabulary.parse_text("yell hello world")
    result = await dispatcher.dispatch_parsed(parsed, base_state)

    room_events = [e for e in result.events if e.get("scope") == "room"]
    assert len(room_events) == 1
    room_text = room_events[0].get("text") or ""
    assert base_state.player.altnam in room_text
    assert "HELLO WORLD" in room_text


@pytest.mark.anyio
async def test_yell_without_text_room_broadcast_includes_player_context(base_state):
    """Legacy yeller() sends YELLER1 (actor context) to room when no text given.

    See legacy/KYRCMDS.C:305-306.
    """
    vocabulary = commands.CommandVocabulary(fixtures.load_commands(), fixtures.load_messages())
    registry = commands.build_default_registry(vocabulary)
    dispatcher = commands.CommandDispatcher(registry)

    parsed = vocabulary.parse_text("yell")
    result = await dispatcher.dispatch_parsed(parsed, base_state)

    room_events = [e for e in result.events if e.get("scope") == "room"]
    assert len(room_events) == 1
    assert room_events[0]["message_id"] == "YELLER1"
    room_text = room_events[0].get("text") or ""
    assert base_state.player.altnam in room_text
