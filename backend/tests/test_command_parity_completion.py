import re
from pathlib import Path

import pytest

from kyrgame import commands, constants, fixtures


class StubPresence:
    def __init__(self, occupants):
        self.occupants = set(occupants)

    async def players_in_room(self, room_id: int):  # noqa: ARG002
        return set(self.occupants)


class FixedRandom:
    def __init__(self, value: int):
        self.value = value

    def randrange(self, stop: int):  # noqa: ARG002
        return self.value


@pytest.fixture
def base_state():
    return commands.GameState(
        player=fixtures.build_player(),
        locations={location.id: location for location in fixtures.load_locations()},
        objects={obj.id: obj for obj in fixtures.load_objects()},
        messages=fixtures.load_messages(),
        content_mappings=fixtures.load_content_mappings(),
    )


def _dispatcher():
    vocabulary = commands.CommandVocabulary(fixtures.load_commands(), fixtures.load_messages())
    return vocabulary, commands.CommandDispatcher(commands.build_default_registry(vocabulary))


def _legacy_kyr_cmds_source() -> str:
    return (
        Path(__file__).resolve().parents[2] / "legacy" / "KYRCMDS.C"
    ).read_text(encoding="latin-1")


def _legacy_command_rows() -> list[tuple[str, str, bool]]:
    source = _legacy_kyr_cmds_source()
    command_block = re.search(r"gi_cmdarr\[\]=\{(.*?)\};", source, re.S)
    assert command_block is not None
    return [
        (command, routine, payonl == "1")
        for command, routine, payonl in re.findall(
            r'\{"([^"]+)",\s*([a-zA-Z0-9_]+),\s*([01])\}',
            command_block.group(1),
        )
    ]


def _legacy_simple_emote_commands() -> set[str]:
    source = _legacy_kyr_cmds_source()
    emote_block = re.search(r"smparr\[\]=\{(.*?)\};", source, re.S)
    assert emote_block is not None
    return set(re.findall(r'\{"([^"]+)"', emote_block.group(1)))


def _add_room_target(base_state, *, spouse: bool = False):
    target = base_state.player.model_copy(
        deep=True,
        update={
            "plyrid": "seer",
            "attnam": "seer",
            "altnam": "Seer",
            "gamloc": base_state.player.gamloc,
            "pgploc": base_state.player.gamloc,
            "gpobjs": [],
            "obvals": [],
            "npobjs": 0,
        }
    )
    if spouse:
        base_state.player.spouse = target.plyrid
    players = {base_state.player.plyrid: base_state.player, target.plyrid: target}
    base_state.presence = StubPresence(players.keys())
    base_state.player_lookup = players.get
    base_state.global_player_lookup = players.get
    return target


def _fill_target_inventory(base_state, target, *, exclude: int):
    object_ids = [
        obj_id
        for obj_id in sorted(base_state.objects)
        if obj_id != exclude
    ][: constants.MXPOBS]
    target.gpobjs.clear()
    target.gpobjs.extend(object_ids)
    target.obvals.clear()
    target.obvals.extend([0] * len(object_ids))
    target.npobjs = len(object_ids)
    return object_ids


def _fill_current_room(base_state, *, exclude: set[int] | None = None):
    excluded = exclude or set()
    object_ids = [
        obj_id
        for obj_id in sorted(base_state.objects)
        if obj_id not in excluded
    ][: constants.MXLOBS]
    location = base_state.locations[base_state.player.gamloc].model_copy(
        update={"objects": object_ids, "nlobjs": len(object_ids)}
    )
    base_state.locations[location.id] = location
    return object_ids


def test_legacy_command_registry_has_no_stubbed_gameplay_handlers():
    vocabulary = commands.CommandVocabulary(fixtures.load_commands(), fixtures.load_messages())
    registry = commands.build_default_registry(vocabulary)

    for command in vocabulary.iter_commands():
        parsed = vocabulary.parse_text(command.command)
        entry = registry.get(parsed.verb)
        assert entry is not None, command.command
        assert entry.handler is not commands._handle_stub, command.command

    for verb in commands.SIMPLE_EMOTES:
        entry = registry.get(verb)
        assert entry is not None, verb
        assert entry.handler is not commands._handle_stub, verb


def test_legacy_command_fixture_matches_legacy_command_table():
    fixture_rows = [
        (command.command, command.cmdrou, command.payonl)
        for command in fixtures.load_commands()
        if command.command != "spoiler"
    ]

    assert fixture_rows == _legacy_command_rows()
    assert set(commands.SIMPLE_EMOTES) == _legacy_simple_emote_commands()


@pytest.mark.anyio
async def test_kissr1_targets_player_with_best_friend_fanout(base_state):
    vocabulary, dispatcher = _dispatcher()
    target = _add_room_target(base_state)

    result = await dispatcher.dispatch_parsed(
        vocabulary.parse_text("comfort seer"),
        base_state,
    )

    assert [event.get("message_id") for event in result.events] == [
        "BEST",
        "KISUTL12",
        "KISUTL13",
    ]
    assert result.events[1]["scope"] == "target"
    assert result.events[1]["player"] == target.plyrid
    assert result.events[2]["scope"] == "room"
    assert result.events[2]["exclude_player"] == target.plyrid


@pytest.mark.anyio
async def test_kissr2_spouse_kiss_uses_legacy_spouse_messages(base_state):
    vocabulary, dispatcher = _dispatcher()
    target = _add_room_target(base_state, spouse=True)

    result = await dispatcher.dispatch_parsed(vocabulary.parse_text("kiss seer"), base_state)

    assert [event.get("message_id") for event in result.events] == [
        "SKISSR",
        "SKISSU",
        "SKISSO",
    ]
    assert result.events[1]["player"] == target.plyrid
    assert result.events[2]["exclude_player"] == target.plyrid


@pytest.mark.anyio
async def test_kissr2_dryad_uses_special_escape_messages(base_state):
    vocabulary, dispatcher = _dispatcher()
    base_state.locations[base_state.player.gamloc] = base_state.locations[
        base_state.player.gamloc
    ].model_copy(update={"objects": [45], "nlobjs": 1})

    result = await dispatcher.dispatch_parsed(vocabulary.parse_text("kiss dryad"), base_state)

    assert [event.get("message_id") for event in result.events] == ["UKISSD", "OKISSD"]
    assert result.events[1]["scope"] == "room"
    assert result.events[1]["exclude_player"] == base_state.player.plyrid


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("raw_command", "expected_ids"),
    [
        ("comfort", ["KISUTL1", None]),
        ("comfort ruby", ["KISUTL2", "KISUTL5"]),
        ("kiss ruby", ["KISUTL2", "KISUTL4"]),
        ("comfort missing", ["KISUTL14", None]),
    ],
)
async def test_kiss_utility_message_id_branches(base_state, raw_command, expected_ids):
    vocabulary, dispatcher = _dispatcher()

    result = await dispatcher.dispatch_parsed(vocabulary.parse_text(raw_command), base_state)

    assert [event.get("message_id") for event in result.events] == expected_ids


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("raw_command", "room_objects", "expected_ids"),
    [
        ("comfort garnet", [2], ["KISUTL6", "KISUTL9"]),
        ("kiss garnet", [2], ["KISUTL6", "KISUTL8"]),
    ],
)
async def test_kiss_utility_room_object_branches(
    base_state, raw_command, room_objects, expected_ids
):
    vocabulary, dispatcher = _dispatcher()
    base_state.locations[base_state.player.gamloc] = base_state.locations[
        base_state.player.gamloc
    ].model_copy(update={"objects": room_objects, "nlobjs": len(room_objects)})

    result = await dispatcher.dispatch_parsed(vocabulary.parse_text(raw_command), base_state)

    assert [event.get("message_id") for event in result.events] == expected_ids


@pytest.mark.anyio
async def test_think_with_amulet_sends_telepathy_to_global_player(base_state):
    vocabulary, dispatcher = _dispatcher()
    target = _add_room_target(base_state)
    base_state.player = base_state.player.model_copy(
        update={"gpobjs": [16], "obvals": [0], "npobjs": 1}
    )

    result = await dispatcher.dispatch_parsed(
        vocabulary.parse_text("think seer keep going"),
        base_state,
    )

    assert result.events[0]["message_id"] == "OBJM02"
    assert result.events[1]["scope"] == "target"
    assert result.events[1]["player"] == target.plyrid
    assert result.events[1]["text"] == "A voice in your mind says: keep going"


@pytest.mark.anyio
async def test_think_non_thinkable_inventory_item_returns_objm04(base_state):
    vocabulary, dispatcher = _dispatcher()
    base_state.player = base_state.player.model_copy(
        update={"gpobjs": [13], "obvals": [0], "npobjs": 1}
    )

    result = await dispatcher.dispatch_parsed(vocabulary.parse_text("think staff"), base_state)

    assert [event.get("message_id") for event in result.events] == ["OBJM04", None]
    assert result.events[1]["text"] == "*** Hero Alt is thinking of her possesions."


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("raw_command", "expected_ids"),
    [
        ("think", ["OBJM03", None]),
        ("think missing", ["OBJM09", None]),
    ],
)
async def test_think_fallback_message_id_branches(base_state, raw_command, expected_ids):
    vocabulary, dispatcher = _dispatcher()

    result = await dispatcher.dispatch_parsed(vocabulary.parse_text(raw_command), base_state)

    assert [event.get("message_id") for event in result.events] == expected_ids


@pytest.mark.anyio
async def test_fly_willow_moves_between_chasm_rooms(base_state):
    vocabulary, dispatcher = _dispatcher()
    base_state.player.flags |= int(constants.PlayerFlag.WILLOW)
    base_state.player.gamloc = 179
    base_state.player.pgploc = 179

    result = await dispatcher.dispatch_parsed(vocabulary.parse_text("fly"), base_state)

    assert base_state.player.gamloc == 180
    assert result.events[0]["message_id"] == "WILFLY"
    assert any(
        event.get("scope") == "nearby_room"
        and event.get("room_id") == 179
        and "gracefully flown across the chasm" in event.get("text", "")
        for event in result.events
    )
    assert any(
        event.get("type") == "location_update" and event.get("location") == 180
        for event in result.events
    )


@pytest.mark.anyio
async def test_fly_without_flight_form_uses_human_failure_fanout(base_state):
    vocabulary, dispatcher = _dispatcher()
    base_state.player.flags &= ~int(
        constants.PlayerFlag.WILLOW
        | constants.PlayerFlag.PEGASU
        | constants.PlayerFlag.PDRAGN
    )

    result = await dispatcher.dispatch_parsed(vocabulary.parse_text("fly"), base_state)

    assert [event.get("message_id") for event in result.events] == ["HUNFLY", "ATFLY1"]
    assert result.events[1]["scope"] == "room"
    assert result.events[1]["exclude_player"] == base_state.player.plyrid


@pytest.mark.anyio
async def test_fly_pegasus_moves_between_sea_rooms(base_state):
    vocabulary, dispatcher = _dispatcher()
    base_state.player.flags |= int(constants.PlayerFlag.PEGASU)
    base_state.player.gamloc = 22
    base_state.player.pgploc = 22

    result = await dispatcher.dispatch_parsed(vocabulary.parse_text("fly"), base_state)

    assert base_state.player.gamloc == 189
    assert result.events[0]["message_id"] == "PEGFLY"
    assert any(
        event.get("type") == "location_update" and event.get("location") == 189
        for event in result.events
    )


@pytest.mark.anyio
async def test_fly_wrong_room_for_flight_form_uses_uno_failure(base_state):
    vocabulary, dispatcher = _dispatcher()
    base_state.player.flags |= int(constants.PlayerFlag.WILLOW)
    base_state.player.gamloc = 0

    result = await dispatcher.dispatch_parsed(vocabulary.parse_text("fly"), base_state)

    assert [event.get("message_id") for event in result.events] == ["UNOFLY", "ATFLY1"]


@pytest.mark.anyio
async def test_shove_moves_target_and_notifies_actor_target_and_rooms(base_state):
    vocabulary, dispatcher = _dispatcher()
    target = _add_room_target(base_state)

    result = await dispatcher.dispatch_parsed(
        vocabulary.parse_text("push seer north"),
        base_state,
    )

    assert target.gamloc == 1
    assert result.events[0]["message_id"] == "SHVUTL1"
    assert any(
        event.get("scope") == "target"
        and event.get("message_id") == "SHVUTL2"
        and event.get("player") == target.plyrid
        for event in result.events
    )
    assert any(
        event.get("scope") == "target"
        and event.get("type") == "location_update"
        and event.get("location") == 1
        for event in result.events
    )
    assert any(
        event.get("scope") == "nearby_room"
        and event.get("event") == "player_enter"
        and event.get("room_id") == 1
        and event.get("player") == target.plyrid
        and event.get("exclude_player") == target.plyrid
        for event in result.events
    )
    assert any(
        event.get("scope") == "nearby_room"
        and event.get("room_id") == 1
        and "been shoved from the south" in event.get("text", "")
        for event in result.events
    )


@pytest.mark.anyio
async def test_shove_single_target_delegates_to_kissr2_fallback(base_state):
    vocabulary, dispatcher = _dispatcher()
    target = _add_room_target(base_state)

    result = await dispatcher.dispatch_parsed(vocabulary.parse_text("shove seer"), base_state)

    assert [event.get("message_id") for event in result.events] == [
        "DONE",
        "KISUTL10",
        "KISUTL11",
    ]
    assert result.events[1]["player"] == target.plyrid


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("raw_command", "expected_first_id"),
    [
        ("shove", "SHOVER3"),
        ("shove missing north", "SHOVER2"),
        ("shove seer upward", "SHOVER1"),
    ],
)
async def test_shove_failure_message_id_branches(
    base_state, raw_command, expected_first_id
):
    vocabulary, dispatcher = _dispatcher()
    if "seer" in raw_command:
        _add_room_target(base_state)

    result = await dispatcher.dispatch_parsed(vocabulary.parse_text(raw_command), base_state)

    assert result.events[0]["message_id"] == expected_first_id


@pytest.mark.anyio
async def test_simple_emote_without_text_uses_smputl_messages(base_state):
    vocabulary, dispatcher = _dispatcher()

    result = await dispatcher.dispatch_parsed(vocabulary.parse_text("blink"), base_state)

    assert [event.get("message_id") for event in result.events] == ["SMPUTL1", "SMPUTL2"]
    assert result.events[0]["text"] == "...Blink!"
    assert result.events[1]["text"] == "***\r\nHero Alt is blinking her eyes in disbelief!"
    assert result.events[1]["exclude_player"] == base_state.player.plyrid


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("raw_command", "expected_text"),
    [
        ("cheer for tashanna", "for tashanna"),
        ("laugh at bob", "at bob"),
        ("sing to seer", "to seer"),
    ],
)
async def test_simple_emote_with_speak_flag_delegates_to_speech(
    base_state, raw_command, expected_text
):
    vocabulary, dispatcher = _dispatcher()

    result = await dispatcher.dispatch_parsed(
        vocabulary.parse_text(raw_command),
        base_state,
    )

    assert any(event.get("message_id") == "SAIDIT" for event in result.events)
    assert any(
        event.get("scope") == "room" and expected_text in event.get("text", "")
        for event in result.events
    )


@pytest.mark.anyio
async def test_toss_routes_through_giveit_for_player_item_transfer(base_state):
    vocabulary, dispatcher = _dispatcher()
    target = _add_room_target(base_state)
    item_id = base_state.player.gpobjs[0]

    result = await dispatcher.dispatch_parsed(
        vocabulary.parse_text("toss seer ruby"),
        base_state,
    )

    assert item_id not in base_state.player.gpobjs
    assert item_id in target.gpobjs
    assert result.events[0]["message_id"] == "DONE"
    assert result.events[1]["message_id"] == "GIVERU10"
    assert "tossed" in result.events[1]["text"]
    assert result.events[1]["player"] == target.plyrid
    assert result.events[2]["message_id"] == "GIVERU11"
    assert result.events[2]["scope"] == "room"
    assert result.events[2]["exclude_player"] == target.plyrid
    assert "tossed Seer a ruby" in result.events[2]["text"]


@pytest.mark.anyio
async def test_give_gold_sends_legacy_bystander_fanout(base_state):
    vocabulary, dispatcher = _dispatcher()
    base_state.player.gold = 5
    target = _add_room_target(base_state)
    target_start_gold = target.gold

    result = await dispatcher.dispatch_parsed(
        vocabulary.parse_text("give 2 gold to seer"),
        base_state,
    )

    assert base_state.player.gold == 3
    assert target.gold == target_start_gold + 2
    assert [event.get("message_id") for event in result.events] == [
        "GIVCRD4",
        "GIVCRD5",
        "GIVCRD6",
    ]
    assert result.events[1]["player"] == target.plyrid
    assert result.events[2]["scope"] == "room"
    assert result.events[2]["exclude_player"] == target.plyrid
    assert "Hero Alt has just given Seer 2 gold pieces" in result.events[2]["text"]


@pytest.mark.anyio
async def test_give_missing_item_target_uses_giveru_failure_and_sndutl(base_state):
    vocabulary, dispatcher = _dispatcher()

    result = await dispatcher.dispatch_parsed(
        vocabulary.parse_text("give missing ruby"),
        base_state,
    )

    assert [event.get("message_id") for event in result.events] == ["GIVERU1", None]
    assert "Missing does not appear to be here" in result.events[0]["text"]
    assert result.events[1]["scope"] == "room"
    assert result.events[1]["text"] == "*** Hero Alt is having hallucinations."


@pytest.mark.anyio
@pytest.mark.parametrize(
    "raw_command",
    [
        "give 2 gold to seer extra",
        "give seer 2 gold extra",
        "give ruby to seer extra",
        "give seer ruby extra",
    ],
)
async def test_give_rejects_extra_words_like_legacy_giveit(base_state, raw_command):
    vocabulary, dispatcher = _dispatcher()
    base_state.player.gold = 5
    target = _add_room_target(base_state)
    target_start_gold = target.gold
    item_id = base_state.player.gpobjs[0]

    result = await dispatcher.dispatch_parsed(vocabulary.parse_text(raw_command), base_state)

    assert base_state.player.gold == 5
    assert target.gold == target_start_gold
    assert item_id in base_state.player.gpobjs
    assert item_id not in target.gpobjs
    assert [event.get("message_id") for event in result.events] == ["GIVIT1", None]


@pytest.mark.anyio
async def test_give_recipient_full_and_room_full_leaves_item_with_actor(base_state):
    vocabulary, dispatcher = _dispatcher()
    target = _add_room_target(base_state)
    item_id = base_state.player.gpobjs[0]
    _fill_target_inventory(base_state, target, exclude=item_id)
    _fill_current_room(base_state, exclude={item_id, *target.gpobjs})

    result = await dispatcher.dispatch_parsed(
        vocabulary.parse_text("give seer ruby"),
        base_state,
    )

    assert item_id in base_state.player.gpobjs
    assert item_id not in target.gpobjs
    assert [event.get("message_id") for event in result.events] == ["GIVERU4", None]
    assert result.events[1]["text"] == "*** Hero Alt is wrestling with supernatural powers!"


@pytest.mark.anyio
async def test_give_recipient_full_random_drop_puts_actor_item_in_room(base_state):
    vocabulary, dispatcher = _dispatcher()
    target = _add_room_target(base_state)
    item_id = base_state.player.gpobjs[0]
    _fill_target_inventory(base_state, target, exclude=item_id)
    location = base_state.locations[base_state.player.gamloc].model_copy(
        update={"objects": [], "nlobjs": 0}
    )
    base_state.locations[location.id] = location
    base_state.rng = FixedRandom(0)

    parsed = vocabulary.parse_text("pass seer ruby")
    result = await dispatcher.dispatch_parsed(parsed, base_state)

    location = base_state.locations[base_state.player.gamloc]
    assert item_id not in base_state.player.gpobjs
    assert item_id not in target.gpobjs
    assert item_id in location.objects
    assert [event.get("message_id") for event in result.events] == [
        "GIVERU5",
        parsed.message_id,
        "GIVERU6",
    ]
    assert result.events[1]["event"] == "room_objects"
    assert result.events[1]["scope"] == "room"
    assert result.events[1]["include_sender"] is True
    assert result.events[1]["objects"] == [{"id": item_id, "name": "ruby"}]
    assert "Hero Alt just dropped her ruby by mistake" in result.events[2]["text"]


@pytest.mark.anyio
async def test_give_recipient_full_random_swap_drops_target_first_item(base_state):
    vocabulary, dispatcher = _dispatcher()
    target = _add_room_target(base_state)
    item_id = base_state.player.gpobjs[0]
    target_item_ids = _fill_target_inventory(base_state, target, exclude=item_id)
    dropped_item_id = target_item_ids[0]
    dropped_name = base_state.objects[dropped_item_id].name
    location = base_state.locations[base_state.player.gamloc].model_copy(
        update={"objects": [], "nlobjs": 0}
    )
    base_state.locations[location.id] = location
    base_state.rng = FixedRandom(1)

    parsed = vocabulary.parse_text("hand seer ruby")
    result = await dispatcher.dispatch_parsed(parsed, base_state)

    location = base_state.locations[base_state.player.gamloc]
    assert item_id not in base_state.player.gpobjs
    assert item_id in target.gpobjs
    assert dropped_item_id not in target.gpobjs
    assert dropped_item_id in location.objects
    assert [event.get("message_id") for event in result.events] == [
        "GIVERU7",
        parsed.message_id,
        "GIVERU8",
        "GIVERU9",
    ]
    assert f"drop her {dropped_name}" in result.events[0]["text"]
    assert result.events[1]["event"] == "room_objects"
    assert result.events[1]["scope"] == "room"
    assert result.events[1]["include_sender"] is True
    assert result.events[1]["objects"] == [
        {"id": dropped_item_id, "name": dropped_name}
    ]
    assert result.events[2]["player"] == target.plyrid
    assert "handed you a ruby" in result.events[2]["text"]
    assert result.events[3]["exclude_player"] == target.plyrid
    assert "handed Seer a ruby" in result.events[3]["text"]
