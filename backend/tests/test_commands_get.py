import pytest

from sqlalchemy import select

from kyrgame import commands, constants, fixtures, models
from kyrgame.database import create_session, get_engine, init_db_schema


class FakePresence:
    def __init__(self, rooms: dict[int, set[str]]):
        self.rooms = rooms

    async def players_in_room(self, room_id: int) -> set[str]:
        return set(self.rooms.get(room_id, set()))


class ReverseIterSet(set):
    def __iter__(self):
        return iter(sorted(list(super().__iter__()), reverse=True))


class ReversePresence:
    def __init__(self, occupants: set[str]):
        self.occupants = ReverseIterSet(occupants)

    async def players_in_room(self, room_id: int) -> set[str]:  # noqa: ARG002
        return self.occupants


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


class FixedRng:
    def __init__(self, value: int):
        self.value = value

    def randrange(self, _upper: int) -> int:
        return self.value


def _persist_player(session, player: models.PlayerModel) -> models.Player:
    record = models.Player(**player.model_dump())
    session.add(record)
    session.commit()
    return record


def _player_model_from_record(record: models.Player) -> models.PlayerModel:
    return models.PlayerModel(
        uidnam=record.uidnam,
        plyrid=record.plyrid,
        altnam=record.altnam,
        attnam=record.attnam,
        gpobjs=record.gpobjs,
        nmpdes=record.nmpdes,
        modno=record.modno,
        level=record.level,
        gamloc=record.gamloc,
        pgploc=record.pgploc,
        flags=record.flags,
        gold=record.gold,
        npobjs=record.npobjs,
        obvals=record.obvals,
        nspells=record.nspells,
        spts=record.spts,
        hitpts=record.hitpts,
        charms=record.charms,
        offspls=record.offspls,
        defspls=record.defspls,
        othspls=record.othspls,
        spells=record.spells,
        gemidx=record.gemidx,
        stones=record.stones,
        macros=record.macros,
        stumpi=record.stumpi,
        spouse=record.spouse,
    )


def _place_object_in_room(state: commands.GameState, object_id: int):
    location = state.locations[state.player.gamloc]
    updated = location.model_copy(update={"objects": [object_id], "nlobjs": 1})
    state.locations[location.id] = updated
    return updated


@pytest.mark.anyio
async def test_get_pickup_emits_room_broadcast_getloc7():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        gpobjs=[],
        obvals=[],
        npobjs=0,
    )
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
    room_event = next(event for event in room_events if event.get("message_id") == "GETLOC7")
    assert room_event.get("exclude_player") == player.plyrid


@pytest.mark.anyio
async def test_get_pickup_emits_its_yours_actor_line():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        gpobjs=[],
        obvals=[],
        npobjs=0,
    )
    state = _build_state(player, [])
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)
    _place_object_in_room(state, 2)

    result = await dispatcher.dispatch("get", {"target": "garnet"}, state)

    actor_event = next(event for event in result.events if event.get("message_id") == "ITSYOURS")
    assert actor_event["scope"] == "player"
    assert actor_event["text"] == "...It's yours!"


@pytest.mark.anyio
async def test_get_full_inventory_uses_getloc6_and_sndutl_room_line():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        gpobjs=[0, 1, 2, 3, 4, 5],
        obvals=[0, 0, 0, 0, 0, 0],
        npobjs=constants.MXPOBS,
    )
    state = _build_state(player, [])
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)
    _place_object_in_room(state, 6)

    result = await dispatcher.dispatch("get", {"target": "sapphire"}, state)

    assert result.events[0]["message_id"] == "GETLOC6"
    assert "too full" in result.events[0]["text"]
    room_event = next(event for event in result.events if event.get("scope") == "room")
    assert room_event["message_id"] is None
    assert room_event["text"] == f"*** {player.altnam} is looking very greedy."
    assert room_event["exclude_player"] == player.plyrid
    assert 6 in state.locations[player.gamloc].objects


@pytest.mark.anyio
async def test_get_missing_room_object_uses_getloc4_and_sndutl_room_line():
    player = _build_player(flags=int(constants.PlayerFlag.LOADED))
    state = _build_state(player, [])
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)
    location = state.locations[player.gamloc]
    state.locations[player.gamloc] = location.model_copy(update={"objects": [], "nlobjs": 0})

    result = await dispatcher.dispatch("get", {"target": "garnet"}, state)

    assert result.events[0]["message_id"] == "GETLOC4"
    assert "no garnet" in result.events[0]["text"]
    room_event = next(event for event in result.events if event.get("scope") == "room")
    assert room_event["message_id"] is None
    assert room_event["text"] == f"*** {player.altnam} is beyond all hope."
    assert room_event["exclude_player"] == player.plyrid


@pytest.mark.anyio
async def test_get_resolves_room_object_by_legacy_prefix_match():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        gpobjs=[],
        obvals=[],
        npobjs=0,
    )
    state = _build_state(player, [])
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    location = _place_object_in_room(state, 2)  # garnet
    assert state.objects[location.objects[0]].name == "garnet"

    result = await dispatcher.dispatch("grab", {"target": "g", "verb": "grab"}, state)

    assert 2 in state.player.gpobjs
    assert 2 not in state.locations[player.gamloc].objects
    room_event = next(event for event in result.events if event.get("message_id") == "GETLOC7")
    assert "garnet" in room_event["text"]


def test_legacy_prefix_match_ignores_blank_targets():
    assert commands._legacy_prefix_match("   ", "garnet") is False


@pytest.mark.anyio
async def test_get_prefix_removes_only_first_duplicate_room_object_slot():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        gpobjs=[],
        obvals=[],
        npobjs=0,
    )
    state = _build_state(player, [])
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    location = state.locations[player.gamloc]
    updated = location.model_copy(update={"objects": [2, 2, 2, 2], "nlobjs": 4})
    state.locations[location.id] = updated

    result = await dispatcher.dispatch("grab", {"target": "g", "verb": "grab"}, state)

    assert state.player.gpobjs == [2]
    assert state.locations[player.gamloc].objects == [2, 2, 2]
    room_objects = next(event for event in result.events if event.get("type") == "room_objects")
    assert room_objects["objects"] == [
        {"id": 2, "name": "garnet"},
        {"id": 2, "name": "garnet"},
        {"id": 2, "name": "garnet"},
    ]


@pytest.mark.anyio
async def test_get_prefix_uses_legacy_slot_swap_for_mixed_room_objects():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        gpobjs=[],
        obvals=[],
        npobjs=0,
    )
    state = _build_state(player, [])
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    location = state.locations[player.gamloc]
    updated = location.model_copy(update={"objects": [2, 0, 1], "nlobjs": 3})
    state.locations[location.id] = updated

    result = await dispatcher.dispatch("grab", {"target": "g", "verb": "grab"}, state)

    assert state.player.gpobjs == [2]
    assert state.locations[player.gamloc].objects == [1, 0]
    room_objects = next(event for event in result.events if event.get("type") == "room_objects")
    assert [obj["id"] for obj in room_objects["objects"]] == [1, 0]


@pytest.mark.anyio
async def test_get_true_id_does_not_bypass_legacy_attnam_matching():
    other = _build_player(
        plyrid="truth",
        attnam="Mirror Mask",
        altnam="A Willowisp",
        gamloc=0,
        flags=int(constants.PlayerFlag.WILLOW),
    )
    other.charms[constants.CharmSlot.ALTERNATE_NAME] = 6
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        gpobjs=[],
        obvals=[],
        npobjs=0,
    )
    player.charms[constants.CharmSlot.FIRE_PROTECTION] = 3
    state = _build_state(player, [other])
    location = state.locations[player.gamloc]
    state.locations[player.gamloc] = location.model_copy(update={"objects": [], "nlobjs": 0})
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("grab", {"target": "truth", "verb": "grab"}, state)

    assert result.events[0]["message_id"] == "GETLOC4"
    assert "no truth" in result.events[0]["text"]


@pytest.mark.anyio
async def test_get_non_pickup_emits_room_broadcast_getloc5():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        gpobjs=[],
        obvals=[],
        npobjs=0,
    )
    state = _build_state(player, [])
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    non_pickup = next(obj for obj in state.objects.values() if "PICKUP" not in obj.flags)
    _place_object_in_room(state, non_pickup.id)

    result = await dispatcher.dispatch("get", {"target": non_pickup.name}, state)

    room_events = [event for event in result.events if event.get("scope") == "room"]
    room_event = next(event for event in room_events if event.get("message_id") == "GETLOC5")
    assert room_event.get("exclude_player") == player.plyrid


@pytest.mark.anyio
async def test_get_player_target_emits_room_broadcast_excluding_target():
    other = _build_player(
        plyrid="buddy",
        attnam="Buddy",
        altnam="Buddy Alt",
    )
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        gpobjs=[],
        obvals=[],
        npobjs=0,
    )
    state = _build_state(player, [other])
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("get", {"target": "Buddy"}, state)

    message_ids = {event.get("message_id") for event in result.events}
    assert {"GETLOC1", "GETLOC2", "GETLOC3"}.issubset(message_ids)
    room_event = next(event for event in result.events if event.get("message_id") == "GETLOC3")
    assert room_event.get("exclude_player") == other.plyrid
    assert room_event.get("exclude_players") == [player.plyrid, other.plyrid]


@pytest.mark.anyio
async def test_get_resolves_visible_player_before_room_object_by_legacy_prefix_match():
    other = _build_player(
        plyrid="guest",
        attnam="Galen",
        altnam="Galen Alt",
    )
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        gpobjs=[],
        obvals=[],
        npobjs=0,
    )
    state = _build_state(player, [other])
    _place_object_in_room(state, 2)  # garnet
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("grab", {"target": "g", "verb": "grab"}, state)

    assert 2 not in state.player.gpobjs
    assert result.events[0]["message_id"] == "GETLOC1"
    assert "Galen Alt" in result.events[0]["text"]


@pytest.mark.anyio
async def test_get_resolves_self_prefix_before_room_object_by_legacy_findgp_order():
    player = _build_player(
        attnam="Galen",
        altnam="Galen Alt",
        flags=int(constants.PlayerFlag.LOADED),
        gpobjs=[],
        obvals=[],
        npobjs=0,
    )
    state = _build_state(player, [])
    _place_object_in_room(state, 2)  # garnet
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("grab", {"target": "g", "verb": "grab"}, state)

    assert state.player.gpobjs == []
    assert state.locations[player.gamloc].objects == [2]
    assert result.events[0]["message_id"] == "GETLOC1"
    assert "Galen Alt" in result.events[0]["text"]


@pytest.mark.anyio
async def test_get_prefix_player_match_uses_deterministic_occupant_order():
    alice = _build_player(
        plyrid="alice",
        attnam="Alaric",
        altnam="Alaric Alt",
    )
    zara = _build_player(
        plyrid="zara",
        attnam="Alice",
        altnam="Alice Alt",
    )
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        gpobjs=[],
        obvals=[],
        npobjs=0,
    )
    state = _build_state(player, [alice, zara])
    state.presence = ReversePresence({player.plyrid, alice.plyrid, zara.plyrid})
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("grab", {"target": "al", "verb": "grab"}, state)

    target_event = next(event for event in result.events if event.get("message_id") == "GETLOC2")
    assert target_event["player"] == "alice"


@pytest.mark.anyio
async def test_get_from_player_failure_notifies_target_and_room():
    target_obj = next(iter(fixtures.load_objects()))
    target = _build_player(
        plyrid="buddy",
        attnam="Buddy",
        altnam="Buddy Alt",
        gpobjs=[target_obj.id],
        obvals=[5],
        npobjs=1,
    )
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        gpobjs=[],
        obvals=[],
        npobjs=0,
    )
    state = _build_state(player, [target])
    state.rng = FixedRng(2)
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch(
        "get",
        {"target": target_obj.name, "target_player": "Buddy"},
        state,
    )

    assert target_obj.id in target.gpobjs
    assert target_obj.id not in state.player.gpobjs
    message_ids = {event.get("message_id") for event in result.events}
    assert {"GETGP5", "GETGP6", "GETGP7"}.issubset(message_ids)
    room_event = next(event for event in result.events if event.get("message_id") == "GETGP7")
    assert room_event.get("exclude_player") == target.plyrid


@pytest.mark.anyio
async def test_get_from_player_success_transfers_item():
    target_obj = next(iter(fixtures.load_objects()))
    target = _build_player(
        plyrid="buddy",
        attnam="Buddy",
        altnam="Buddy Alt",
        gpobjs=[target_obj.id],
        obvals=[7],
        npobjs=1,
    )
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        gpobjs=[],
        obvals=[],
        npobjs=0,
    )
    state = _build_state(player, [target])
    state.rng = FixedRng(0)
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch(
        "get",
        {"target": target_obj.name, "target_player": "Buddy"},
        state,
    )

    assert target_obj.id in state.player.gpobjs
    assert target_obj.id not in target.gpobjs
    message_ids = {event.get("message_id") for event in result.events}
    assert {"GETGP8", "GETGP9", "GETGP10"}.issubset(message_ids)


@pytest.mark.anyio
async def test_get_from_player_updates_persistent_inventory(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'kyrgame.db'}")
    init_db_schema(engine)
    session = create_session(engine)

    target_obj = next(iter(fixtures.load_objects()))
    target = _build_player(
        plyrid="buddy",
        attnam="Buddy",
        altnam="Buddy Alt",
        gpobjs=[target_obj.id],
        obvals=[4],
        npobjs=1,
    )
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        gpobjs=[],
        obvals=[],
        npobjs=0,
    )
    _persist_player(session, player)
    _persist_player(session, target)

    def lookup_player(player_alias: str) -> models.PlayerModel | None:
        record = session.scalar(select(models.Player).where(models.Player.plyrid == player_alias))
        if not record:
            return None
        return _player_model_from_record(record)

    state = commands.GameState(
        player=player,
        locations={location.id: location for location in fixtures.load_locations()},
        objects={obj.id: obj for obj in fixtures.load_objects()},
        messages=fixtures.load_messages(),
        content_mappings=fixtures.load_content_mappings(),
        presence=FakePresence({player.gamloc: {player.plyrid, target.plyrid}}),
        player_lookup=lookup_player,
        db_session=session,
    )
    state.rng = FixedRng(0)
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    await dispatcher.dispatch(
        "get",
        {"target": target_obj.name, "target_player": "Buddy"},
        state,
    )

    updated_target = session.scalar(
        select(models.Player).where(models.Player.plyrid == target.plyrid)
    )
    assert updated_target is not None
    assert target_obj.id not in updated_target.gpobjs
