from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from . import constants


@dataclass(frozen=True)
class DeathResetResult:
    player_id: str
    old_name: str
    old_room: int


@dataclass(frozen=True)
class RoomObjectUpdate:
    room_id: int
    object_ids: tuple[int, ...]
    dropped_items: tuple[int, ...] = ()


@dataclass(frozen=True)
class DeathRecoveryPlan:
    mode: str
    player_id: str
    old_name: str
    old_room: int
    old_level: int
    new_level: int
    player_updates: dict[str, Any] = field(default_factory=dict)
    room_object_updates: tuple[RoomObjectUpdate, ...] = ()
    filtered_items: tuple[int, ...] = ()
    vanished_items: tuple[int, ...] = ()
    dropped_rooms: tuple[int, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


def initialize_player_for_first_login(
    player: Any,
    *,
    player_id: str,
    uidnam: str,
    birthstone_picker: Callable[[int, int], int],
    female: bool = False,
    room_id: int = 0,
) -> None:
    """Initialize a first-login player using legacy initgp() defaults."""

    # Legacy initgp() zeroes the gmplyr record, writes uidnam/plyrid/altnam/attnam,
    # sets level-one HP/SP/name-description, marks LOADED, and rerolls birthstones.
    # The web flow places first-login players into room 0 immediately after intro.
    # See legacy/KYRANDIA.C:325-356 and kyrand() cases 1-6 at 231-297.
    _set(player, "uidnam", uidnam)
    _set(player, "plyrid", player_id)
    _apply_initgp_defaults(
        player,
        display_name=player_id,
        flags=(
            int(constants.PlayerFlag.LOADED)
            | (int(constants.PlayerFlag.FEMALE) if female else 0)
        ),
        room_id=room_id,
        birthstone_picker=birthstone_picker,
    )


def reset_player_after_death(
    player: Any,
    birthstone_picker: Callable[[int, int], int],
) -> DeathResetResult:
    """Reset a killed player to legacy initgp()/hitoth() room-0 state."""

    result = DeathResetResult(
        player_id=player.plyrid,
        old_name=player.altnam,
        old_room=player.gamloc,
    )
    old_flags = int(player.flags)

    # Legacy initgp() zeroes the gmplyr record, preserves true identity and sex,
    # rerolls birthstones, then hitoth()/entrgp() place the player at room 0.
    # (legacy/KYRANDIA.C:325-356; legacy/KYRSPEL.C:303-321)
    _apply_initgp_defaults(
        player,
        display_name=player.plyrid,
        flags=int(constants.PlayerFlag.LOADED)
        | (old_flags & int(constants.PlayerFlag.FEMALE)),
        room_id=0,
        birthstone_picker=birthstone_picker,
    )
    return result


def build_modern_death_recovery_plan(
    player: Any,
    *,
    locations: dict[int, Any],
    rng: Any,
) -> DeathRecoveryPlan:
    """Build the modern_death_recovery plan without mutating game state.

    This is intentionally separate from legacy `hitoth()`/`initgp()` behavior.
    See docs/MODERN_FEATURES.md for the modern feature contract.
    """

    old_room = int(player.gamloc)
    old_level = int(player.level)
    new_level = max(1, old_level - 1)
    carried_items = tuple(int(item) for item in player.gpobjs)
    filtered_items = _modern_death_filtered_items(old_room, carried_items)
    filtered_set = {
        constants.SOULSTONE_OBJECT_ID,
        constants.KYRAGEM_OBJECT_ID,
    } if filtered_items else set()
    droppable_items = tuple(item for item in carried_items if item not in filtered_set)
    room_object_updates, vanished_items = _place_modern_death_items(
        droppable_items,
        old_room=old_room,
        locations=locations,
        rng=rng,
    )

    flags = _modern_death_flags_after_recovery(
        int(player.flags),
        new_level=new_level,
        filtered_items=filtered_items,
    )
    player_updates = {
        "altnam": player.plyrid,
        "attnam": player.plyrid,
        "gamloc": constants.WILLOW_ROOM_ID,
        "pgploc": constants.WILLOW_ROOM_ID,
        "nmpdes": constants.level_to_nmpdes(new_level),
        "level": new_level,
        "hitpts": 4 * new_level,
        "spts": 2 * new_level,
        "gold": 0,
        "gpobjs": [],
        "obvals": [],
        "npobjs": 0,
        "spells": [],
        "nspells": 0,
        "charms": [0] * constants.NCHARM,
        "macros": constants.MODERN_DEATH_EXHAUSTION_MACROS,
        "flags": flags,
    }
    dropped_rooms = tuple(update.room_id for update in room_object_updates)
    metadata = {
        "death_reset": True,
        "modern_death_recovery": True,
        "old_level": old_level,
        "new_level": new_level,
        "filtered_items": list(filtered_items),
        "vanished_items": list(vanished_items),
        "dropped_rooms": list(dropped_rooms),
    }
    return DeathRecoveryPlan(
        mode="modern_death_recovery",
        player_id=player.plyrid,
        old_name=player.altnam,
        old_room=old_room,
        old_level=old_level,
        new_level=new_level,
        player_updates=player_updates,
        room_object_updates=room_object_updates,
        filtered_items=filtered_items,
        vanished_items=vanished_items,
        dropped_rooms=dropped_rooms,
        metadata=metadata,
    )


def apply_death_recovery_plan(
    player: Any,
    locations: dict[int, Any],
    plan: DeathRecoveryPlan,
) -> None:
    """Apply a DeathRecoveryPlan after it has been selected by the caller."""

    for field_name, value in plan.player_updates.items():
        _set(player, field_name, value)
    for update in plan.room_object_updates:
        location = locations.get(update.room_id)
        if location is None:
            continue
        object_ids = list(update.object_ids)
        locations[update.room_id] = location.model_copy(
            update={"objects": object_ids, "nlobjs": len(object_ids)}
        )


def _modern_death_filtered_items(old_room: int, carried_items: tuple[int, ...]) -> tuple[int, ...]:
    if not (
        constants.MODERN_DEATH_CASTLE_MIN_ROOM
        <= old_room
        <= constants.MODERN_DEATH_CASTLE_MAX_ROOM
    ):
        return ()
    return tuple(
        item
        for item in carried_items
        if item in {constants.SOULSTONE_OBJECT_ID, constants.KYRAGEM_OBJECT_ID}
    )


def _modern_death_flags_after_recovery(
    flags: int,
    *,
    new_level: int,
    filtered_items: tuple[int, ...],
) -> int:
    preserved_mask = int(
        constants.PlayerFlag.LOADED
        | constants.PlayerFlag.FEMALE
        | constants.PlayerFlag.BRFSTF
        | constants.PlayerFlag.MARRYD
        | constants.PlayerFlag.BLESSD
        | constants.PlayerFlag.GOTKYG
    )
    recovered_flags = flags & preserved_mask
    if new_level < constants.MODERN_DEATH_GOTKYG_MIN_LEVEL or filtered_items:
        recovered_flags &= ~int(constants.PlayerFlag.GOTKYG)
    return recovered_flags


def _place_modern_death_items(
    items: tuple[int, ...],
    *,
    old_room: int,
    locations: dict[int, Any],
    rng: Any,
) -> tuple[tuple[RoomObjectUpdate, ...], tuple[int, ...]]:
    room_objects = {room_id: list(location.objects) for room_id, location in locations.items()}
    dropped_by_room: dict[int, list[int]] = {}
    remaining = list(items)

    remaining = _fill_room(old_room, remaining, room_objects, dropped_by_room)
    for room_id in _modern_death_adjacent_rooms(old_room, locations, rng):
        remaining = _fill_room(room_id, remaining, room_objects, dropped_by_room)
        if not remaining:
            break

    vanished: list[int] = []
    for item in remaining:
        room_id = _pick_dark_forest_room_with_space(room_objects, locations, rng)
        if room_id is None:
            vanished.append(item)
            continue
        _append_dropped_item(room_id, item, room_objects, dropped_by_room)

    updates = tuple(
        RoomObjectUpdate(
            room_id=room_id,
            object_ids=tuple(room_objects[room_id]),
            dropped_items=tuple(dropped_items),
        )
        for room_id, dropped_items in dropped_by_room.items()
    )
    return updates, tuple(vanished)


def _modern_death_adjacent_rooms(
    old_room: int,
    locations: dict[int, Any],
    rng: Any,
) -> list[int]:
    location = locations.get(old_room)
    if location is None:
        return []
    adjacent = []
    for room_id in (
        location.gi_north,
        location.gi_south,
        location.gi_east,
        location.gi_west,
    ):
        if room_id >= 0 and room_id != old_room and room_id in locations:
            adjacent.append(room_id)
    _shuffle_with_rng(adjacent, rng)
    return adjacent


def _shuffle_with_rng(values: list[int], rng: Any) -> None:
    shuffle = getattr(rng, "shuffle", None)
    if shuffle is not None:
        shuffle(values)
        return
    for index in range(len(values) - 1, 0, -1):
        swap_index = rng.randrange(0, index + 1)
        values[index], values[swap_index] = values[swap_index], values[index]


def _fill_room(
    room_id: int,
    remaining: list[int],
    room_objects: dict[int, list[int]],
    dropped_by_room: dict[int, list[int]],
) -> list[int]:
    if room_id not in room_objects:
        return remaining
    while remaining and len(room_objects[room_id]) < constants.MXLOBS:
        _append_dropped_item(room_id, remaining.pop(0), room_objects, dropped_by_room)
    return remaining


def _append_dropped_item(
    room_id: int,
    item: int,
    room_objects: dict[int, list[int]],
    dropped_by_room: dict[int, list[int]],
) -> None:
    room_objects[room_id].append(item)
    dropped_by_room.setdefault(room_id, []).append(item)


def _pick_dark_forest_room_with_space(
    room_objects: dict[int, list[int]],
    locations: dict[int, Any],
    rng: Any,
) -> int | None:
    forest_rooms = [
        room_id
        for room_id in range(
            constants.MODERN_DEATH_DARK_FOREST_MIN_ROOM,
            constants.MODERN_DEATH_DARK_FOREST_MAX_ROOM + 1,
        )
        if room_id in locations
    ]
    if not any(len(room_objects[room_id]) < constants.MXLOBS for room_id in forest_rooms):
        return None

    for _ in range(max(1, len(forest_rooms) * 2)):
        room_id = rng.randrange(
            constants.MODERN_DEATH_DARK_FOREST_MIN_ROOM,
            constants.MODERN_DEATH_DARK_FOREST_MAX_ROOM + 1,
        )
        if room_id in room_objects and len(room_objects[room_id]) < constants.MXLOBS:
            return room_id
    for room_id in forest_rooms:
        if len(room_objects[room_id]) < constants.MXLOBS:
            return room_id
    return None


def _apply_initgp_defaults(
    player: Any,
    *,
    display_name: str,
    flags: int,
    room_id: int,
    birthstone_picker: Callable[[int, int], int],
) -> None:
    _set(player, "altnam", display_name)
    _set(player, "attnam", display_name)
    _set(player, "gamloc", room_id)
    _set(player, "pgploc", room_id)
    _set(player, "nmpdes", constants.level_to_nmpdes(1))
    _set(player, "level", 1)
    _set(player, "hitpts", 4)
    _set(player, "spts", 2)
    _set(player, "gold", 0)
    _set(player, "gpobjs", [])
    _set(player, "obvals", [])
    _set(player, "npobjs", 0)
    _set(player, "spells", [])
    _set(player, "nspells", 0)
    _set(player, "offspls", 0)
    _set(player, "defspls", 0)
    _set(player, "othspls", 0)
    _set(player, "charms", [0] * constants.NCHARM)
    _set(player, "gemidx", 0)
    _set(
        player,
        "stones",
        [
            birthstone_picker(
                constants.BIRTHSTONE_MIN,
                constants.BIRTHSTONE_MAX + 1,
            )
            for _ in range(constants.BIRTHSTONE_SLOTS)
        ],
    )
    _set(player, "macros", 0)
    _set(player, "stumpi", 0)
    _set(player, "spouse", "")
    _set(player, "flags", flags)


def _set(player: Any, field: str, value: Any) -> None:
    object.__setattr__(player, field, value)
