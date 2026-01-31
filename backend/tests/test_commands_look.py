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
