from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import constants, models


ANIMATION_STATE_KEY = "animation_tick"
DRYAD_OBJECT_ID = 45
ZAR_DRAGON_OBJECT_ID = 52
SINGLETON_MOVING_MOB_OBJECT_IDS = frozenset({DRYAD_OBJECT_ID, ZAR_DRAGON_OBJECT_ID})

ZAR_SPECIAL_ROOM_OBJECTS = {
    0: 46,
    7: 47,
    9: 48,
    42: 49,
    101: 50,
    186: 51,
    295: 53,
}


@dataclass(frozen=True)
class SingletonMobSpec:
    id: str
    name: str
    object_id: int
    tracker_field: str


SINGLETON_MOBS = (
    SingletonMobSpec("dryad", "Dryad", DRYAD_OBJECT_ID, "dryad_location"),
    SingletonMobSpec("dragon", "Zar", ZAR_DRAGON_OBJECT_ID, "zar_location"),
)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _room_brief(room_id: int | None, room_briefs: Mapping[int, str] | None) -> str | None:
    if room_id is None or room_briefs is None:
        return None
    return room_briefs.get(room_id)


def _dragon_placement_objects(room_id: int, before: Sequence[int]) -> list[int]:
    # Legacy pzinlc() reconstructs Zar rooms, but the cleanup tool is narrower:
    # preserve unrelated live objects while normalizing the singleton dragon.
    dragon_count = before.count(ZAR_DRAGON_OBJECT_ID)
    existing = [object_id for object_id in before if object_id != ZAR_DRAGON_OBJECT_ID]
    existing_without_dryad = [
        object_id for object_id in existing if object_id != DRYAD_OBJECT_ID
    ]
    objects = [ZAR_DRAGON_OBJECT_ID]
    special = ZAR_SPECIAL_ROOM_OBJECTS.get(room_id)
    if dragon_count != 1 and special is not None and special not in existing:
        objects.append(special)
    if DRYAD_OBJECT_ID in existing:
        objects.append(DRYAD_OBJECT_ID)
    objects.extend(existing_without_dryad)
    return objects[: constants.MXLOBS]


def _canonical_after_objects(spec: SingletonMobSpec, room_id: int, before: Sequence[int]) -> list[int]:
    if spec.object_id == ZAR_DRAGON_OBJECT_ID:
        return _dragon_placement_objects(room_id, before)

    without_mob = [object_id for object_id in before if object_id != spec.object_id]
    if len(without_mob) >= constants.MXLOBS:
        without_mob = without_mob[: constants.MXLOBS - 1]
    return [*without_mob, spec.object_id]


def _apply_singleton_cleanup(
    *, mob_id: str, room_id: int, tracker_room_id: int | None, objects: Sequence[int]
) -> list[int]:
    if mob_id == "dryad":
        without_dryad = [
            object_id for object_id in objects if object_id != DRYAD_OBJECT_ID
        ]
        if room_id != tracker_room_id:
            return without_dryad
        if len(without_dryad) >= constants.MXLOBS:
            without_dryad = without_dryad[: constants.MXLOBS - 1]
        return [*without_dryad, DRYAD_OBJECT_ID]

    if mob_id == "dragon":
        if room_id != tracker_room_id:
            return [
                object_id for object_id in objects if object_id != ZAR_DRAGON_OBJECT_ID
            ]
        return _dragon_placement_objects(room_id, objects)

    return list(objects)


def _proposed_changes(
    *,
    spec: SingletonMobSpec,
    tracker_room_id: int | None,
    location_objects: Mapping[int, Sequence[int]],
) -> list[dict[str, object]]:
    if tracker_room_id is None:
        return []

    rooms_with_object = {
        room_id for room_id, objects in location_objects.items() if spec.object_id in objects
    }
    candidate_rooms = set(rooms_with_object)
    if tracker_room_id is not None:
        candidate_rooms.add(tracker_room_id)

    changes: list[dict[str, object]] = []
    for room_id in sorted(candidate_rooms):
        before = list(location_objects.get(room_id, []))
        if room_id == tracker_room_id:
            after = _canonical_after_objects(spec, room_id, before)
        else:
            after = [object_id for object_id in before if object_id != spec.object_id]
        if before != after or room_id == tracker_room_id:
            changes.append({"room_id": room_id, "before": before, "after": after})
    return changes


def _singleton_status(
    *, copy_count: int, object_rooms: list[int], tracker_room_id: int | None
) -> str:
    if tracker_room_id is None:
        return "tracker_missing"
    if copy_count == 0:
        return "missing"
    if copy_count > 1:
        return "duplicate"
    if tracker_room_id is not None and object_rooms != [tracker_room_id]:
        return "tracker_mismatch"
    return "ok"


def build_moving_mob_audit(
    location_objects: Mapping[int, Sequence[int]],
    runtime_payload: Mapping[str, object],
    *,
    room_briefs: Mapping[int, str] | None = None,
) -> dict[str, object]:
    mobs: list[dict[str, object]] = []

    for spec in SINGLETON_MOBS:
        object_rooms = [
            room_id
            for room_id, objects in sorted(location_objects.items())
            for object_id in objects
            if object_id == spec.object_id
        ]
        unique_object_rooms = sorted(set(object_rooms))
        room_counts = Counter(object_rooms)
        duplicate_room_counts = {
            str(room_id): count for room_id, count in sorted(room_counts.items()) if count > 1
        }
        tracker_room_id = _optional_int(runtime_payload.get(spec.tracker_field))
        status = _singleton_status(
            copy_count=len(object_rooms),
            object_rooms=object_rooms,
            tracker_room_id=tracker_room_id,
        )
        tracker_mismatch = status != "ok"
        primary_room_id = tracker_room_id if tracker_room_id is not None else (
            unique_object_rooms[0] if unique_object_rooms else None
        )
        proposed_changes = _proposed_changes(
            spec=spec,
            tracker_room_id=tracker_room_id,
            location_objects=location_objects,
        )
        mobs.append(
            {
                "id": spec.id,
                "name": spec.name,
                "kind": "persistent_room_object",
                "object_id": spec.object_id,
                "room_id": primary_room_id,
                "tracker_room_id": tracker_room_id,
                "state_room_id": tracker_room_id,
                "object_room_id": unique_object_rooms[0] if unique_object_rooms else None,
                "object_rooms": object_rooms,
                "unique_object_rooms": unique_object_rooms,
                "copy_count": len(object_rooms),
                "duplicate_room_counts": duplicate_room_counts,
                "tracker_mismatch": tracker_mismatch,
                "singleton_status": status,
                "proposed_changes": proposed_changes,
                "room_brief": _room_brief(primary_room_id, room_briefs),
            }
        )

    brownie_room_id = _optional_int(runtime_payload.get("brownie_location"))
    mobs.append(
        {
            "id": "brownie",
            "name": "Brownie",
            "kind": "virtual_tracker",
            "object_id": None,
            "room_id": brownie_room_id,
            "tracker_room_id": brownie_room_id,
            "copy_count": 0,
            "object_rooms": [],
            "duplicate_room_counts": {},
            "tracker_mismatch": False,
            "singleton_status": "tracker_only",
            "path_index": _optional_int(runtime_payload.get("brownie_path_index")),
            "room_brief": _room_brief(brownie_room_id, room_briefs),
        }
    )

    elf_room_id = _optional_int(runtime_payload.get("elf_last_room"))
    mobs.append(
        {
            "id": "elf",
            "name": "Elf",
            "kind": "virtual_tracker",
            "object_id": None,
            "room_id": elf_room_id,
            "tracker_room_id": elf_room_id,
            "copy_count": 0,
            "object_rooms": [],
            "duplicate_room_counts": {},
            "tracker_mismatch": False,
            "singleton_status": "tracker_only",
            "room_brief": _room_brief(elf_room_id, room_briefs),
        }
    )

    return {"mobs": mobs}


def _location_objects_from_session(session: Session) -> tuple[dict[int, list[int]], dict[int, str]]:
    records = session.scalars(select(models.Location).order_by(models.Location.id)).all()
    return (
        {int(record.id): list(record.objects or []) for record in records},
        {int(record.id): str(record.brfdes) for record in records},
    )


def _runtime_payload_from_session(session: Session) -> dict[str, object]:
    record = session.get(models.RuntimeState, ANIMATION_STATE_KEY)
    return dict(record.payload or {}) if record is not None else {}


def audit_moving_mobs(session: Session) -> dict[str, object]:
    location_objects, room_briefs = _location_objects_from_session(session)
    return build_moving_mob_audit(
        location_objects,
        _runtime_payload_from_session(session),
        room_briefs=room_briefs,
    )


def cleanup_confirmation_token(audit: Mapping[str, object]) -> str:
    token_payload = {
        "mobs": [
            {
                "id": mob["id"],
                "tracker_room_id": mob.get("tracker_room_id"),
                "copy_count": mob.get("copy_count"),
                "object_rooms": mob.get("object_rooms"),
                "proposed_changes": mob.get("proposed_changes", []),
            }
            for mob in audit.get("mobs", [])
            if mob.get("id") in {"dryad", "dragon"}
        ]
    }
    encoded = json.dumps(token_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"moving-mobs:{hashlib.sha256(encoded).hexdigest()[:16]}"


def _cleanup_changes(audit: Mapping[str, object]) -> list[dict[str, object]]:
    room_changes: dict[int, dict[str, object]] = {}
    mob_changes_by_room: dict[int, list[tuple[str, int | None]]] = {}

    for mob in audit.get("mobs", []):
        if mob.get("id") not in {"dryad", "dragon"}:
            continue
        mob_id = str(mob["id"])
        tracker_room_id = _optional_int(mob.get("tracker_room_id"))
        for change in mob.get("proposed_changes", []):
            if change["before"] == change["after"]:
                continue
            room_id = int(change["room_id"])
            room_changes.setdefault(
                room_id,
                {"room_id": room_id, "before": list(change["before"])},
            )
            mob_changes_by_room.setdefault(room_id, []).append((mob_id, tracker_room_id))

    changes: list[dict[str, object]] = []
    for room_id in sorted(room_changes):
        before = list(room_changes[room_id]["before"])
        after = list(before)
        mob_ids: list[str] = []

        def operation_order(operation: tuple[str, int | None]) -> tuple[int, int]:
            mob_id, tracker_room_id = operation
            # Remove off-tracker singleton copies before adding tracked mobs; that
            # lets capacity checks see slots freed by stale Zar and dryad objects.
            placement_phase = int(room_id == tracker_room_id)
            mob_order = 0 if mob_id == "dryad" else 1
            return (placement_phase, mob_order)

        for mob_id, tracker_room_id in sorted(
            mob_changes_by_room[room_id], key=operation_order
        ):
            after = _apply_singleton_cleanup(
                mob_id=mob_id,
                room_id=room_id,
                tracker_room_id=tracker_room_id,
                objects=after,
            )
            mob_ids.append(mob_id)
        if before == after:
            continue
        changes.append(
            {
                "mob_id": "+".join(mob_ids),
                "mob_ids": mob_ids,
                "room_id": room_id,
                "before": before,
                "after": after,
            }
        )
    return changes


def cleanup_moving_mobs(
    session: Session,
    *,
    dry_run: bool = True,
    apply: bool = False,
    confirm: str | None = None,
) -> dict[str, object]:
    audit = audit_moving_mobs(session)
    token = cleanup_confirmation_token(audit)
    changes = _cleanup_changes(audit)

    if not dry_run and not apply:
        raise ValueError("cleanup writes require apply=True and a matching confirmation token")

    if apply:
        dry_run = False
        if confirm != token:
            raise ValueError(f"cleanup requires confirmation token {token}")

    if apply:
        for change in changes:
            location = session.get(models.Location, int(change["room_id"]))
            if location is None:
                continue
            location.objects = list(change["after"])
            location.nlobjs = len(location.objects)
            session.flush([location])

    return {
        "applied": bool(apply),
        "dry_run": bool(dry_run),
        "confirmation_token": token,
        "changes": changes,
        "audit": audit,
    }
