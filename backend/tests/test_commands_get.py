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


def _place_object_in_room(state: commands.GameState, object_id: int):
    location = state.locations[state.player.gamloc]
    updated = location.model_copy(update={"objects": [object_id], "nlobjs": 1})
    state.locations[location.id] = updated
    return updated


@pytest.mark.anyio
async def test_get_pickup_emits_room_broadcast_getloc7():
    player = _build_player(flags=int(constants.PlayerFlag.LOADED))
    state = _build_state(player, [])
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    location = state.locations[player.gamloc]
    obj_id = next(
        obj_id for obj_id in location.objects if "PICKUP" in state.objects[obj_id].flags
    )
    obj_name = state.objects[obj_id].name

    result = await dispatcher.dispatch("get", {"target": obj_name}, state)

    room_events = [event for event in result.events if event.get("scope") == "room"]
    assert any(event.get("message_id") == "GETLOC7" for event in room_events)


@pytest.mark.anyio
async def test_get_non_pickup_emits_room_broadcast_getloc5():
    player = _build_player(flags=int(constants.PlayerFlag.LOADED))
    state = _build_state(player, [])
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    non_pickup = next(obj for obj in state.objects.values() if "PICKUP" not in obj.flags)
    _place_object_in_room(state, non_pickup.id)

    result = await dispatcher.dispatch("get", {"target": non_pickup.name}, state)

    room_events = [event for event in result.events if event.get("scope") == "room"]
    assert any(event.get("message_id") == "GETLOC5" for event in room_events)


@pytest.mark.anyio
async def test_get_player_target_emits_room_broadcast_excluding_target():
    other = _build_player(
        plyrid="buddy",
        attnam="Buddy",
        altnam="Buddy Alt",
    )
    player = _build_player(flags=int(constants.PlayerFlag.LOADED))
    state = _build_state(player, [other])
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("get", {"target": "Buddy"}, state)

    message_ids = {event.get("message_id") for event in result.events}
    assert {"GETLOC1", "GETLOC2", "GETLOC3"}.issubset(message_ids)
    room_event = next(event for event in result.events if event.get("message_id") == "GETLOC3")
    assert room_event.get("exclude_player") == other.plyrid
