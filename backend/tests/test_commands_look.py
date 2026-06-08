import pytest

from kyrgame import commands, constants, fixtures


class FakePresence:
    def __init__(self, rooms: dict[int, set[str]]):
        self.rooms = rooms

    async def players_in_room(self, room_id: int) -> set[str]:
        return set(self.rooms.get(room_id, set()))


def _build_state(player, other_players):
    locations = {location.id: location for location in fixtures.load_locations()}
    objects = {obj.id: obj for obj in fixtures.load_objects()}
    messages = fixtures.load_messages()
    content_mappings = fixtures.load_content_mappings()

    roster = {player.plyrid: player, **{other.plyrid: other for other in other_players}}
    presence = FakePresence({player.gamloc: set(roster.keys())})

    return commands.GameState(
        player=player,
        locations=locations,
        objects=objects,
        messages=messages,
        content_mappings=content_mappings,
        presence=presence,
        player_lookup=roster.get,
    )


def _build_player(**updates):
    player = fixtures.build_player()
    data = player.model_dump()
    data.update(updates)
    return player.model_copy(update=data)


@pytest.mark.anyio
async def test_look_room_object_emits_description_and_looker1():
    player = _build_player(flags=0)
    state = _build_state(player, [])
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    location = state.locations[player.gamloc]
    obj_id = location.objects[0]
    obj_name = state.objects[obj_id].name

    result = await dispatcher.dispatch("look", {"raw": obj_name}, state)

    message_ids = {event.get("message_id") for event in result.events}
    assert f"KID{obj_id:03d}" in message_ids
    assert "LOOKER1" in message_ids
    room_event = next(event for event in result.events if event.get("message_id") == "LOOKER1")
    assert room_event.get("exclude_player") == player.plyrid


@pytest.mark.anyio
async def test_look_room_object_uses_legacy_prefix_match():
    player = _build_player(flags=0)
    state = _build_state(player, [])
    location = state.locations[player.gamloc]
    state.locations[player.gamloc] = location.model_copy(
        update={"objects": [2], "nlobjs": 1}
    )
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("look", {"raw": "g"}, state)

    message_ids = {event.get("message_id") for event in result.events}
    assert "KID002" in message_ids
    room_event = next(event for event in result.events if event.get("message_id") == "LOOKER1")
    assert "garnet" in room_event["text"]


@pytest.mark.anyio
async def test_look_inventory_object_emits_description_and_looker2():
    obj_id = 1
    player = _build_player(
        flags=0,
        gpobjs=[obj_id],
        obvals=[0],
        npobjs=1,
    )
    state = _build_state(player, [])
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    obj_name = state.objects[obj_id].name
    result = await dispatcher.dispatch("look", {"raw": obj_name}, state)

    message_ids = {event.get("message_id") for event in result.events}
    assert f"KID{obj_id:03d}" in message_ids
    assert "LOOKER2" in message_ids
    room_event = next(event for event in result.events if event.get("message_id") == "LOOKER2")
    assert room_event.get("exclude_player") == player.plyrid


@pytest.mark.anyio
async def test_look_inventory_object_uses_legacy_prefix_match():
    player = _build_player(
        flags=0,
        gpobjs=[2],
        obvals=[0],
        npobjs=1,
    )
    state = _build_state(player, [])
    location = state.locations[player.gamloc]
    state.locations[player.gamloc] = location.model_copy(update={"objects": [], "nlobjs": 0})
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("look", {"raw": "g"}, state)

    message_ids = {event.get("message_id") for event in result.events}
    assert "KID002" in message_ids
    room_event = next(event for event in result.events if event.get("message_id") == "LOOKER2")
    assert "garnet" in room_event["text"]


@pytest.mark.anyio
async def test_look_player_emits_description_inventory_and_room_broadcasts():
    other = _build_player(
        plyrid="buddy",
        attnam="Buddy",
        altnam="Buddy Alt",
        nmpdes=1,
        gpobjs=[0],
        obvals=[0],
        npobjs=1,
        flags=0,
    )
    player = _build_player(flags=0)
    state = _build_state(player, [other])
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("look", {"raw": "Buddy"}, state)

    description_event = next(
        event for event in result.events if event.get("message_id") == "MDES01"
    )
    assert "spellbook" in description_event.get("text", "")
    message_ids = {event.get("message_id") for event in result.events}
    assert "LOOKER3" in message_ids
    assert "LOOKER4" in message_ids
    room_event = next(event for event in result.events if event.get("message_id") == "LOOKER4")
    assert room_event.get("exclude_players") == [player.plyrid, other.plyrid]


@pytest.mark.anyio
async def test_look_player_uses_legacy_attnam_prefix_match():
    other = _build_player(
        plyrid="buddy",
        attnam="Galen",
        altnam="Galen Alt",
        nmpdes=1,
        flags=0,
    )
    player = _build_player(flags=0)
    state = _build_state(player, [other])
    location = state.locations[player.gamloc]
    state.locations[player.gamloc] = location.model_copy(update={"objects": [], "nlobjs": 0})
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("look", {"raw": "g"}, state)

    description_event = next(
        event for event in result.events if event.get("message_id") == "MDES01"
    )
    assert "spellbook" in description_event.get("text", "")
    target_event = next(event for event in result.events if event.get("message_id") == "LOOKER3")
    assert target_event["player"] == "buddy"


@pytest.mark.anyio
async def test_look_uses_attnam_for_player_matching():
    other = _build_player(
        plyrid="buddy",
        attnam="Seer",
        altnam="Seer Alt",
        nmpdes=1,
        flags=0,
    )
    player = _build_player(flags=0)
    state = _build_state(player, [other])
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("look", {"raw": "buddy"}, state)

    description_event = next(
        event for event in result.events if event.get("type") == "location_description"
    )
    assert description_event["message_id"] == "KRD000"


@pytest.mark.anyio
async def test_look_female_player_emits_female_description():
    other = _build_player(
        plyrid="lady",
        attnam="Lady",
        altnam="Lady Alt",
        nmpdes=1,
        flags=int(constants.PlayerFlag.FEMALE),
    )
    player = _build_player(flags=0)
    state = _build_state(player, [other])
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("look", {"raw": "Lady"}, state)

    message_ids = {event.get("message_id") for event in result.events}
    assert "FDES01" in message_ids


@pytest.mark.anyio
async def test_look_self_allows_invisible_description():
    player = _build_player(flags=int(constants.PlayerFlag.INVISF))
    state = _build_state(player, [])
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("look", {"raw": player.attnam}, state)

    message_ids = {event.get("message_id") for event in result.events}
    assert "INVDES" in message_ids


@pytest.mark.anyio
async def test_look_invisible_player_falls_back_to_room_description():
    other = _build_player(
        plyrid="ghost",
        attnam="Ghost",
        altnam="Ghost Alt",
        flags=int(constants.PlayerFlag.INVISF),
        nmpdes=1,
    )
    player = _build_player(flags=0)
    state = _build_state(player, [other])
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("look", {"raw": "Ghost"}, state)

    description_event = next(
        event for event in result.events if event.get("type") == "location_description"
    )
    assert description_event["message_id"] == "KRD000"


@pytest.mark.anyio
async def test_look_transformed_player_uses_transformation_message():
    other = _build_player(
        plyrid="pegasus",
        attnam="Peg",
        altnam="Peg Alt",
        flags=int(constants.PlayerFlag.PEGASU),
    )
    player = _build_player(flags=0)
    state = _build_state(player, [other])
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("look", {"raw": "Peg"}, state)

    message_ids = {event.get("message_id") for event in result.events}
    assert "PEGDES" in message_ids


@pytest.mark.anyio
async def test_look_brief_emits_brief_description_objects_and_occupants():
    other = _build_player(plyrid="buddy", attnam="Buddy", altnam="Buddy Alt")
    player = _build_player(flags=0)
    state = _build_state(player, [other])
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("look", {"raw": "brief"}, state)

    message_ids = {event.get("message_id") for event in result.events}
    assert "LOOKER5" in message_ids
    assert any(event.get("type") == "room_objects" for event in result.events)
    assert any(event.get("type") == "room_occupants" for event in result.events)


@pytest.mark.anyio
async def test_look_default_respects_brief_flag_and_emits_room_state():
    other = _build_player(plyrid="buddy", attnam="Buddy", altnam="Buddy Alt")
    player = _build_player(flags=int(constants.PlayerFlag.BRFSTF))
    state = _build_state(player, [other])
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("look", {"raw": ""}, state)

    description_event = next(
        event for event in result.events if event.get("type") == "location_description"
    )
    assert description_event["message_id"] is None
    assert description_event["text"] == state.locations[player.gamloc].brfdes
    assert any(event.get("type") == "room_objects" for event in result.events)
    assert any(event.get("type") == "room_occupants" for event in result.events)


@pytest.mark.anyio
async def test_look_keeps_transform_description_when_viewer_has_whoub_charm():
    other = _build_player(
        plyrid="truth",
        attnam="Mirror Mask",
        altnam="A Willowisp",
        nmpdes=1,
        flags=int(constants.PlayerFlag.WILLOW),
    )
    other.charms[constants.CharmSlot.ALTERNATE_NAME] = 6
    player = _build_player(flags=0)
    player.charms[constants.CharmSlot.FIRE_PROTECTION] = 3
    state = _build_state(player, [other])
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("look", {"raw": "Mirror Mask"}, state)

    description_event = next(event for event in result.events if event.get("scope") == "player")
    assert description_event["message_id"] == "WILDES"


@pytest.mark.anyio
async def test_look_true_id_does_not_bypass_legacy_attnam_matching():
    other = _build_player(
        plyrid="truth",
        attnam="Mirror Mask",
        altnam="A Willowisp",
        nmpdes=1,
        flags=int(constants.PlayerFlag.WILLOW),
    )
    other.charms[constants.CharmSlot.ALTERNATE_NAME] = 6
    player = _build_player(flags=0)
    player.charms[constants.CharmSlot.FIRE_PROTECTION] = 3
    state = _build_state(player, [other])
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("look", {"raw": "truth"}, state)

    description_event = next(
        event for event in result.events if event.get("type") == "location_description"
    )
    assert description_event["message_id"] == "KRD000"


@pytest.mark.anyio
async def test_look_whoub_reveal_still_requires_invisibility_visibility():
    other = _build_player(
        plyrid="ghost",
        attnam="Ghost",
        altnam="Ghost Alt",
        flags=int(constants.PlayerFlag.INVISF),
        nmpdes=1,
    )
    player = _build_player(flags=0)
    player.charms[constants.CharmSlot.FIRE_PROTECTION] = 3
    state = _build_state(player, [other])
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("look", {"raw": "Ghost"}, state)

    description_event = next(
        event for event in result.events if event.get("type") == "location_description"
    )
    assert description_event["message_id"] == "KRD000"


@pytest.mark.anyio
async def test_look_true_id_stays_hidden_after_fire_protection_timer_changes():
    other = _build_player(
        plyrid="truth",
        attnam="Mirror Mask",
        altnam="A Willowisp",
        nmpdes=1,
        flags=int(constants.PlayerFlag.WILLOW),
    )
    other.charms[constants.CharmSlot.ALTERNATE_NAME] = 6
    player = _build_player(flags=0)
    state = _build_state(player, [other])
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    for timer_value in (1, 0):
        state.player.charms[constants.CharmSlot.FIRE_PROTECTION] = timer_value
        result = await dispatcher.dispatch("look", {"raw": "truth"}, state)
        description_event = next(
            event for event in result.events if event.get("type") == "location_description"
        )
        assert description_event["message_id"] == "KRD000"
