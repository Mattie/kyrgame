from __future__ import annotations

from dataclasses import dataclass, field
import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Dict, Mapping, MutableMapping, Protocol, Sequence

from sqlalchemy.exc import SQLAlchemyError

from .. import constants, models, modern_features
from ..honor_mode import HonorModePolicy
from ..player_lifecycle import (
    DeathRecoveryPlan,
    apply_death_recovery_plan,
    build_modern_death_recovery_plan,
    reset_player_after_death,
)


logger = logging.getLogger(__name__)


@dataclass(eq=True, frozen=True)
class AnimationTickEvent:
    """One-shot world event emitted by the animation timer."""

    flag: str
    room_id: int
    message_id: str | None = None
    message_text: str | None = None
    payload: Mapping[str, object] = field(default_factory=dict)


@dataclass
class AnimationTickResult:
    """Outputs produced by one animation-timer run."""

    routine_name: str
    routine_events: list[AnimationTickEvent] = field(default_factory=list)
    timed_events: list[AnimationTickEvent] = field(default_factory=list)


@dataclass
class AnimationTickState:
    """Coordinator-owned animation timer state for multiplayer runtime.

    Legacy parity note: this replaces KYRANIM.C static/global fields used by
    ``animat()`` and ``chkzar()`` (legacy/KYRANIM.C lines 67-85, 111-173).
    """

    routine_index: int = 0
    zar_counter: int = 0
    zar_location: int = 302
    zar_attack_index: int = 0
    timed_flags: MutableMapping[str, int] = field(
        default_factory=lambda: {"sesame": 0, "chantd": 0, "rockpr": 0}
    )
    gem_counter: int = 0
    gem_last_attempt_room_id: int | None = None
    gem_last_attempt_status: str | None = None
    gem_last_attempt_object_count: int | None = None
    gem_last_spawn_room_id: int | None = None
    gem_last_spawn_object_id: int | None = None
    gem_last_spawn_object_name: str | None = None
    dryad_location: int = 0
    brownie_location: int = 0
    brownie_path_index: int = 0
    elf_last_room: int | None = None
    elf_reward_next: int = 0
    elf_hint_index: int = 0


class AnimationTickStateStore(Protocol):
    """Persistence port for animation scheduler state.

    Multiplayer strategy: load a single shared snapshot on boot and store after
    each tick so reconnects/process restarts keep routine cadence + one-shot
    flags consistent for all connected players.
    """

    def load(self) -> Mapping[str, object] | None: ...

    def save(self, payload: Mapping[str, object]) -> None: ...


class InMemoryAnimationTickPersistence:
    """Process-local state store for isolated animation unit tests."""

    def __init__(self) -> None:
        self._payload: dict[str, object] | None = None

    def load(self) -> Mapping[str, object] | None:
        return dict(self._payload) if self._payload is not None else None

    def save(self, payload: Mapping[str, object]) -> None:
        self._payload = dict(payload)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


class SQLAlchemyAnimationTickPersistence:
    """Persist KYRANIM.C animation globals in the runtime_state table."""

    def __init__(self, session_factory: Callable[[], Any], *, key: str = "animation_tick") -> None:
        self._session_factory = session_factory
        self._key = key
        self._unavailable = False

    def load(self) -> Mapping[str, object] | None:
        if self._unavailable:
            return None
        try:
            with self._session_factory() as session:
                record = session.get(models.RuntimeState, self._key)
                if record is None:
                    return None
                return dict(record.payload)
        except SQLAlchemyError as exc:
            self._warn_unavailable("load", exc)
            return None

    def save(self, payload: Mapping[str, object]) -> None:
        if self._unavailable:
            return
        try:
            with self._session_factory() as session:
                record = session.get(models.RuntimeState, self._key)
                if record is None:
                    record = models.RuntimeState(key=self._key, payload=dict(payload))
                    session.add(record)
                else:
                    record.payload = dict(payload)
                session.commit()
        except SQLAlchemyError as exc:
            self._warn_unavailable("save", exc)
            return

    def _warn_unavailable(self, operation: str, exc: SQLAlchemyError) -> None:
        if self._unavailable:
            return
        self._unavailable = True
        logger.warning(
            "Animation tick persistence %s failed; continuing with process-local state.",
            operation,
            exc_info=exc,
        )


RoutineHandler = Callable[[AnimationTickState], Sequence[AnimationTickEvent] | None]
MobUpdateHandler = Callable[[AnimationTickState], Sequence[AnimationTickEvent] | None]
TimedFlagHandler = Callable[[AnimationTickState], AnimationTickEvent]
MessageLookup = Callable[[str], str | None]
RoomFlagGetter = Callable[[int, str], int]
RoomFlagSetter = Callable[[int, str, int], None]
EventDispatcher = Callable[[AnimationTickEvent], Awaitable[None] | None]
AuditRecorder = Callable[[str, Mapping[str, object]], Awaitable[None] | None]


def _noop_handler(_: AnimationTickState) -> Sequence[AnimationTickEvent] | None:
    return None


def _room_objects_payload(room_id: int, object_ids: Sequence[int]) -> dict[str, object]:
    return {
        "type": "room_objects",
        "event": "room_objects",
        "location": room_id,
        "objects": [{"id": object_id} for object_id in object_ids],
    }


# Legacy reference: KYRANIM.C bpath/bpidx/bloc globals at lines 69-80.
BROWNIE_PATH = (
    71, 144, 66, 29, 82, 96, 136, 31, 114, 134,
    67, 52, 103, 53, 43, 150, 137, 18, 0, 129,
    168, 77, 133, 92, 61, 101, 73, 99, 69, 111,
    45, 132, 3, 2, 55, 60, 160, 48, 70, 112,
)

ZAR_HOME_ROOM = 302
ZAR_DRAGON_OBJECT_ID = 52
ZAR_DRYAD_OBJECT_ID = 45
ZAR_SPECIAL_ROOM_OBJECTS = {
    0: 46,
    7: 47,
    9: 48,
    42: 49,
    101: 50,
    186: 51,
    295: 53,
}
ZAR_ATTACKS = ("bite", "breath", "claw", "lightning")


class _ChancePickerRandom:
    def __init__(self, chance_picker: Callable[[int, int], int]) -> None:
        self._chance_picker = chance_picker

    def randrange(self, low: int, high: int) -> int:
        return self._chance_picker(low, high)


def _player_pronoun_possessive(player: models.PlayerModel) -> str:
    return "her" if player.flags & constants.PlayerFlag.FEMALE else "his"


def _modern_death_metadata(
    plan: DeathRecoveryPlan,
    *,
    recipient_scope: str,
) -> dict[str, object]:
    metadata = dict(plan.metadata)
    metadata["refresh_location"] = constants.WILLOW_ROOM_ID
    metadata["recipient_scope"] = recipient_scope
    return metadata


class ZarDragonRoutine:
    """Port Zar's legacy animation, movement, and attack routines.

    Legacy references:
    - `inianm`, `chkzar`: legacy/KYRANIM.C lines 88-173.
    - `zaritm`, `zarfood`, `rmvzar`, `pzinlc`, `dthbyz`: lines 176-322.
    - `zarapp`: lines 452-459.
    """

    def __init__(
        self,
        *,
        room_picker: Callable[[int, int], int],
        chance_picker: Callable[[int, int], int],
        room_objects_getter: Callable[[int], Sequence[int]],
        room_objects_setter: Callable[[int, Sequence[int]], None],
        players_getter: Callable[[int], Sequence[models.PlayerModel]],
        player_persister: Callable[[models.PlayerModel], None],
        message_formatter: Callable[..., str],
        object_name_lookup: Callable[[int], str] | None = None,
        zar_location_setter: Callable[[int], None] | None = None,
        locations_getter: Callable[[], dict[int, models.LocationModel]] | None = None,
        death_recovery_persister: Callable[
            [models.PlayerModel, DeathRecoveryPlan], None
        ]
        | None = None,
        honor_mode_policy: HonorModePolicy | None = None,
        home_room_id: int = ZAR_HOME_ROOM,
        dragon_object_id: int = ZAR_DRAGON_OBJECT_ID,
    ) -> None:
        self._room_picker = room_picker
        self._chance_picker = chance_picker
        self._room_objects_getter = room_objects_getter
        self._room_objects_setter = room_objects_setter
        self._players_getter = players_getter
        self._player_persister = player_persister
        self._message_formatter = message_formatter
        self._object_name_lookup = object_name_lookup or (lambda object_id: str(object_id))
        self._zar_location_setter = zar_location_setter
        self._locations_getter = locations_getter
        self._death_recovery_persister = death_recovery_persister
        self._honor_mode_policy = honor_mode_policy or HonorModePolicy()
        self.home_room_id = home_room_id
        self.dragon_object_id = dragon_object_id

    @staticmethod
    def attack_name(attack_index: int) -> str:
        return ZAR_ATTACKS[attack_index % len(ZAR_ATTACKS)]

    def initialize(self, state: AnimationTickState) -> None:
        if self.dragon_object_id not in self._room_objects_getter(state.zar_location):
            self._set_zar_room_objects(
                state.zar_location,
                self._placement_objects(state.zar_location),
            )
        self._sync_zar_location(state.zar_location)

    def chkzar(self, state: AnimationTickState) -> list[AnimationTickEvent]:
        events: list[AnimationTickEvent] = []

        if state.zar_counter > 24:
            events.extend(self.remove_zar(state, "ZMSG00"))
            events.extend(self.place_zar(state, self.home_room_id, "ZMSG01"))
            state.zar_counter = 0
        elif state.zar_counter < 5:
            _, attack_events = self.zarfood(state)
            events.extend(attack_events)
        else:
            found_food, attack_events = self.zarfood(state)
            events.extend(attack_events)
            if not found_food:
                events.extend(self.remove_zar(state, "ZMSG00"))
                events.extend(
                    self.place_zar(
                        state,
                        self._room_picker(219, 300),
                        "ZMSG01",
                    )
                )

        state.zar_counter += 1
        return events

    def should_attack_after_staff(self) -> bool:
        return self._chance_picker(0, 2) == 1

    def zarapp(self, _: AnimationTickState) -> list[AnimationTickEvent]:
        return [
            AnimationTickEvent(
                flag="zarapp",
                room_id=self._room_picker(0, 168),
                message_id="ZARABO",
            )
        ]

    def remove_zar(
        self, state: AnimationTickState, message_id: str
    ) -> list[AnimationTickEvent]:
        room_id = state.zar_location
        updated = [
            object_id
            for object_id in self._room_objects_getter(room_id)
            if object_id != self.dragon_object_id
        ]
        self._set_zar_room_objects(room_id, updated)
        return [
            AnimationTickEvent(
                flag="rmvzar",
                room_id=room_id,
                message_id=message_id,
            ),
            AnimationTickEvent(
                flag="rmvzar",
                room_id=room_id,
                payload=_room_objects_payload(room_id, updated),
            )
        ]

    def place_zar(
        self, state: AnimationTickState, room_id: int, message_id: str
    ) -> list[AnimationTickEvent]:
        objects = self._placement_objects(room_id)
        state.zar_location = room_id
        self._sync_zar_location(room_id)
        self._set_zar_room_objects(room_id, objects)
        return [
            AnimationTickEvent(
                flag="pzinlc",
                room_id=room_id,
                message_id=message_id,
            ),
            AnimationTickEvent(
                flag="pzinlc",
                room_id=room_id,
                payload=_room_objects_payload(room_id, objects),
            )
        ]

    def zarfood(
        self, state: AnimationTickState
    ) -> tuple[bool, list[AnimationTickEvent]]:
        players = list(self._players_getter(state.zar_location))
        if not players:
            return False, []

        events = [
            AnimationTickEvent(
                flag="zarfood",
                room_id=state.zar_location,
                message_id="ZMSG02",
            )
        ]
        for player in players:
            if state.zar_attack_index == len(ZAR_ATTACKS):
                state.zar_attack_index = 0
            attack_index = state.zar_attack_index
            if player.level < constants.MAX_PLAYER_LEVEL:
                events.extend(self._attack_player(state.zar_location, player, attack_index))
            state.zar_attack_index += 1
        return True, events

    def _attack_player(
        self, room_id: int, player: models.PlayerModel, attack_index: int
    ) -> list[AnimationTickEvent]:
        attack = self.attack_name(attack_index)
        message_id, damage = self._attack_message_and_damage(player, attack)

        events = [
            AnimationTickEvent(
                flag="zarfood",
                room_id=room_id,
                message_id="ZMSG07",
                message_text=self._message_formatter("ZMSG07", player.altnam),
                payload={"exclude_player": player.plyrid, "attack": attack},
            ),
            AnimationTickEvent(
                flag="zarfood",
                room_id=room_id,
                payload={
                    "target_only": True,
                    "target_player": player.plyrid,
                    "target_message_id": message_id,
                    "target_text": self._message_formatter(message_id),
                    "damage": damage,
                    "attack": attack,
                },
            ),
        ]

        remaining_hitpts = max(0, player.hitpts - damage)
        if remaining_hitpts <= 0 and self._honor_mode_policy.modern_feature_enabled(
            player, modern_features.MODERN_DEATH_RECOVERY
        ):
            # modern_death_recovery: Zar death recovery must commit before we
            # mutate live HP/location state. See docs/MODERN_FEATURES.md.
            locations = self._locations_getter() if self._locations_getter else {}
            plan = build_modern_death_recovery_plan(
                player,
                locations=locations,
                rng=_ChancePickerRandom(self._chance_picker),
            )
            if self._death_recovery_persister:
                self._death_recovery_persister(player, plan)
                apply_death_recovery_plan(player, locations, plan)
            else:
                apply_death_recovery_plan(player, locations, plan)
                for room_update in plan.room_object_updates:
                    self._room_objects_setter(
                        room_update.room_id, list(room_update.object_ids)
                    )
                self._player_persister(player)
            events.extend(self._modern_death_recovery_events(room_id, player, plan))
            return events

        player.hitpts = remaining_hitpts
        self._player_persister(player)
        if player.hitpts <= 0:

            reset = self._reset_dead_player(player)
            self._player_persister(player)
            events.extend(
                [
                    AnimationTickEvent(
                        flag="zarfood",
                        room_id=room_id,
                        payload={
                            "target_only": True,
                            "target_player": player.plyrid,
                            "target_message_id": "DIEMSG",
                            "target_text": self._message_formatter("DIEMSG"),
                            "death_reset": True,
                        },
                    ),
                    AnimationTickEvent(
                        flag="zarfood",
                        room_id=room_id,
                        message_id="KILLED",
                        message_text=self._message_formatter("KILLED", reset.old_name),
                        payload={"exclude_player": player.plyrid},
                    ),
                    AnimationTickEvent(
                        flag="zarfood",
                        room_id=0,
                        payload={
                            "target_only": True,
                            "target_player": player.plyrid,
                            "target_event": "location_update",
                            "target_type": "location_update",
                            "location": 0,
                            "move_player_to": 0,
                            "death_reset": True,
                        },
                    ),
                    # Legacy hitoth() reinitializes the player, then entrgp(0, ...)
                    # announces a holy-light arrival (legacy/KYRSPEL.C:312-320;
                    # legacy/KYRUTIL.C:236-256).
                    AnimationTickEvent(
                        flag="zarfood",
                        room_id=0,
                        message_text=(
                            f"*** {player.plyrid} has just appeared in a holy light!"
                        ),
                        payload={
                            "event": "room_message",
                            "type": "room_message",
                            "exclude_player": player.plyrid,
                            "player": player.plyrid,
                        },
                    ),
                ]
            )
        return events

    def _modern_death_recovery_events(
        self,
        room_id: int,
        player: models.PlayerModel,
        plan: DeathRecoveryPlan,
    ) -> list[AnimationTickEvent]:
        """Build Zar animation events for modern_death_recovery."""

        target_metadata = _modern_death_metadata(plan, recipient_scope="target")
        room_metadata = _modern_death_metadata(plan, recipient_scope="room")
        predeath_target_metadata = dict(target_metadata)
        predeath_target_metadata.pop("death_reset", None)
        predeath_target_metadata["pre_death_drop"] = True
        events: list[AnimationTickEvent] = []
        for room_update in plan.room_object_updates:
            events.append(
                AnimationTickEvent(
                    flag="zarfood",
                    room_id=room_update.room_id,
                    payload={
                        **_room_objects_payload(
                            room_update.room_id, room_update.object_ids
                        ),
                        # modern_death_recovery: victim-facing pre-death drop
                        # notices are target-only events; room broadcasts keep
                        # notifying the nearby witnesses. See
                        # docs/MODERN_FEATURES.md.
                        "exclude_player": player.plyrid,
                        **room_metadata,
                    },
                )
            )
            for object_id in room_update.dropped_items:
                drop_text = self._message_formatter(
                    "DROPIT3",
                    plan.old_name,
                    _player_pronoun_possessive(player),
                    self._object_name_lookup(object_id),
                )
                events.append(
                    AnimationTickEvent(
                        flag="zarfood",
                        room_id=room_update.room_id,
                        payload={
                            "target_only": True,
                            "target_player": player.plyrid,
                            "target_message_id": "DROPIT3",
                            "target_text": drop_text,
                            "object_id": object_id,
                            **predeath_target_metadata,
                        },
                    )
                )
                events.append(
                    AnimationTickEvent(
                        flag="zarfood",
                        room_id=room_update.room_id,
                        message_id="DROPIT3",
                        message_text=drop_text,
                        payload={
                            "event": "room_message",
                            "type": "room_message",
                            "exclude_player": player.plyrid,
                            "object_id": object_id,
                            **room_metadata,
                        },
                    )
                )
        events.extend(
            [
                AnimationTickEvent(
                    flag="zarfood",
                    room_id=room_id,
                    payload={
                        "target_only": True,
                        "target_player": player.plyrid,
                        "target_message_id": "DIEMSG",
                        "target_text": self._message_formatter("DIEMSG"),
                        **target_metadata,
                    },
                ),
                AnimationTickEvent(
                    flag="zarfood",
                    room_id=room_id,
                    message_id="KILLED",
                    message_text=self._message_formatter("KILLED", plan.old_name),
                    payload={"exclude_player": player.plyrid, **room_metadata},
                ),
                AnimationTickEvent(
                    flag="zarfood",
                    room_id=constants.WILLOW_ROOM_ID,
                    payload={
                        "target_only": True,
                        "target_player": player.plyrid,
                        "target_event": "location_update",
                        "target_type": "location_update",
                        "location": constants.WILLOW_ROOM_ID,
                        "move_player_to": constants.WILLOW_ROOM_ID,
                        **target_metadata,
                    },
                ),
                AnimationTickEvent(
                    flag="zarfood",
                    room_id=constants.WILLOW_ROOM_ID,
                    message_text=f"*** {player.plyrid} has just appeared in a holy light!",
                    payload={
                        "event": "room_message",
                        "type": "room_message",
                        "exclude_player": player.plyrid,
                        "player": player.plyrid,
                        **room_metadata,
                    },
                ),
            ]
        )
        return events

    def _reset_dead_player(self, player: models.PlayerModel):
        return reset_player_after_death(player, self._chance_picker)

    def _attack_message_and_damage(
        self, player: models.PlayerModel, attack: str
    ) -> tuple[str, int]:
        if attack == "bite":
            return "ZMSG03", 16
        if attack == "breath":
            return "ZMSG04", 28 if player.charms[constants.FIRPRO] else 48
        if attack == "claw":
            return "ZMSG05", 12
        return "ZMSG06", 16 if player.charms[constants.LIGPRO] else 32

    def _placement_objects(self, room_id: int) -> list[int]:
        existing = list(self._room_objects_getter(room_id))
        objects = [self.dragon_object_id]
        special_object = ZAR_SPECIAL_ROOM_OBJECTS.get(room_id)
        if special_object is not None:
            objects.append(special_object)
        if ZAR_DRYAD_OBJECT_ID in existing:
            objects.append(ZAR_DRYAD_OBJECT_ID)
        return objects

    def _set_zar_room_objects(self, room_id: int, objects: Sequence[int]) -> None:
        self._room_objects_setter(room_id, list(objects))

    def _sync_zar_location(self, room_id: int) -> None:
        if self._zar_location_setter:
            self._zar_location_setter(room_id)


class GemSpawnRoutine:
    """Port KYRANIM.C `gemakr()` gem placement into runtime-owned world state.

    Legacy reference: `gemakr()` in `legacy/KYRANIM.C` lines 429-449.
    """

    def __init__(
        self,
        *,
        room_picker: Callable[[int, int], int],
        gem_picker: Callable[[int, int], int],
        room_objects_getter: Callable[[int], Sequence[int]],
        room_objects_setter: Callable[[int, Sequence[int]], None],
        gem_name_lookup: Callable[[int], str],
        message_formatter: Callable[[str], str],
    ) -> None:
        self._room_picker = room_picker
        self._gem_picker = gem_picker
        self._room_objects_getter = room_objects_getter
        self._room_objects_setter = room_objects_setter
        self._gem_name_lookup = gem_name_lookup
        self._message_formatter = message_formatter

    def __call__(self, state: AnimationTickState) -> list[AnimationTickEvent]:
        # Legacy gemakr() uses genrdn(44,168), an exclusive upper bound, skips
        # rooms with 4+ objects, and advances gemctr only after successful puts.
        # Source: legacy/KYRANIM.C:429-449.
        room_id = self._room_picker(44, 168)
        room_objects = list(self._room_objects_getter(room_id))
        gem_counter_before = state.gem_counter
        state.gem_last_attempt_room_id = room_id
        state.gem_last_attempt_object_count = len(room_objects)

        if len(room_objects) >= 4:
            state.gem_last_attempt_status = "skipped_capacity"
            return [
                self._audit_event(
                    room_id,
                    {
                        "status": "skipped_capacity",
                        "room_object_count_before": len(room_objects),
                        "room_object_count_after": len(room_objects),
                        "gem_counter_before": gem_counter_before,
                        "gem_counter_after": state.gem_counter,
                    },
                )
            ]

        if state.gem_counter == 10:
            gem_id = self._gem_picker(0, 12)
            state.gem_counter = 0
        else:
            state.gem_counter += 1
            gem_id = 2
        gem_name = self._gem_name_lookup(gem_id)

        updated_objects = [*room_objects, gem_id]
        self._room_objects_setter(room_id, updated_objects)
        state.gem_last_attempt_status = "spawned"
        state.gem_last_spawn_room_id = room_id
        state.gem_last_spawn_object_id = gem_id
        state.gem_last_spawn_object_name = gem_name

        return [
            AnimationTickEvent(
                flag="gemakr",
                room_id=room_id,
                message_id="GEMAPP",
                message_text=self._message_formatter(gem_name),
                payload={
                    "type": "room_objects",
                    "location": room_id,
                    "objects": [{"id": object_id} for object_id in updated_objects],
                    "spawned_object_id": gem_id,
                    "spawned_object_name": gem_name,
                    "spawn_source": "gemakr",
                },
            ),
            self._audit_event(
                room_id,
                {
                    "status": "spawned",
                    "room_object_count_before": len(room_objects),
                    "room_object_count_after": len(updated_objects),
                    "gem_counter_before": gem_counter_before,
                    "gem_counter_after": state.gem_counter,
                    "spawned_object_id": gem_id,
                    "spawned_object_name": gem_name,
                },
            ),
        ]

    def _audit_event(self, room_id: int, payload: Mapping[str, object]) -> AnimationTickEvent:
        return AnimationTickEvent(
            flag="gemakr",
            room_id=room_id,
            payload={
                "audit_only": True,
                "audit": {
                    "event_type": "animation.gem_attempt",
                    "room_id": room_id,
                    **dict(payload),
                },
            },
        )


class DryadWanderRoutine:
    """Port KYRANIM.C `dryads()` wandering dryad placement.

    Legacy reference: `dryads()` in `legacy/KYRANIM.C` lines 326-348.
    """

    def __init__(
        self,
        *,
        room_picker: Callable[[int, int], int],
        room_objects_getter: Callable[[int], Sequence[int]],
        room_objects_setter: Callable[[int, Sequence[int]], None],
        object_name_lookup: Callable[[int], str],
        location_phrase_lookup: Callable[[int], str],
        message_formatter: Callable[..., str],
        dryad_object_id: int = 45,
        max_room_objects: int = 6,
    ) -> None:
        self._room_picker = room_picker
        self._room_objects_getter = room_objects_getter
        self._room_objects_setter = room_objects_setter
        self._object_name_lookup = object_name_lookup
        self._location_phrase_lookup = location_phrase_lookup
        self._message_formatter = message_formatter
        self._dryad_object_id = dryad_object_id
        self._max_room_objects = max_room_objects

    def __call__(self, state: AnimationTickState) -> list[AnimationTickEvent]:
        destination = self._room_picker(12, 168)
        origin = state.dryad_location
        if destination == origin:
            return []

        events: list[AnimationTickEvent] = []
        origin_objects = list(self._room_objects_getter(origin))
        if self._dryad_object_id in origin_objects:
            origin_objects.remove(self._dryad_object_id)
            self._room_objects_setter(origin, origin_objects)
            events.append(AnimationTickEvent(flag="dryads", room_id=origin, message_id="DMSG00"))
            events.append(
                AnimationTickEvent(
                    flag="dryads",
                    room_id=origin,
                    payload=_room_objects_payload(origin, origin_objects),
                )
            )

        destination_objects = list(self._room_objects_getter(destination))
        if len(destination_objects) >= self._max_room_objects:
            evicted_object_id = destination_objects[-1]
            destination_objects = destination_objects[:-1]
            events.append(
                AnimationTickEvent(
                    flag="dryads",
                    room_id=destination,
                    message_id="DMSG01",
                    message_text=self._message_formatter(
                        "DMSG01",
                        self._object_name_lookup(evicted_object_id),
                        self._location_phrase_lookup(destination),
                    ),
                    payload={"evicted_object_id": evicted_object_id},
                )
            )

        destination_objects.append(self._dryad_object_id)
        self._room_objects_setter(destination, destination_objects)
        state.dryad_location = destination
        events.append(AnimationTickEvent(flag="dryads", room_id=destination, message_id="DMSG02"))
        events.append(
            AnimationTickEvent(
                flag="dryads",
                room_id=destination,
                payload=_room_objects_payload(destination, destination_objects),
            )
        )
        return events


class ElfEncounterRoutine:
    """Port KYRANIM.C `elves()` hint/reward encounters.

    Legacy reference: `elves()` in `legacy/KYRANIM.C` lines 352-389.
    """

    _HINT_IDS = tuple(f"EHINT{idx}" for idx in range(10))

    def __init__(
        self,
        *,
        room_picker: Callable[[int, int], int],
        gold_picker: Callable[[int, int], int],
        player_getter: Callable[[int], Any | None],
        player_persister: Callable[[Any], None],
        message_formatter: Callable[..., str],
    ) -> None:
        self._room_picker = room_picker
        self._gold_picker = gold_picker
        self._player_getter = player_getter
        self._player_persister = player_persister
        self._message_formatter = message_formatter

    def __call__(self, state: AnimationTickState) -> list[AnimationTickEvent]:
        room_id = self._room_picker(12, 168)
        return self.trigger_room(state, room_id)

    def trigger_room(self, state: AnimationTickState, room_id: int) -> list[AnimationTickEvent]:
        # Legacy reference: KYRANIM.C elves() chooses eloc via genrdn(12,168)
        # before using rndlgp(eloc) to find an active player (lines 363-389).
        player = self._player_getter(room_id)
        if player is None:
            return []
        state.elf_last_room = room_id

        events = [
            AnimationTickEvent(flag="elves", room_id=room_id, message_id="EMSG00")
        ]
        player_name = getattr(player, "altnam", getattr(player, "plyrid", "player"))
        player_id = getattr(player, "plyrid", player_name)

        if state.elf_reward_next:
            gold = self._gold_picker(2, 11)
            player.gold += gold
            self._player_persister(player)
            state.elf_reward_next = 0
            target_message_id = "EMSG01"
            target_text = self._message_formatter("EMSG01", gold)
            room_message_id = "EMSG02"
            room_text = self._message_formatter("EMSG02", player_name, gold)
        else:
            hint_id = self._HINT_IDS[state.elf_hint_index % len(self._HINT_IDS)]
            state.elf_hint_index = (state.elf_hint_index + 1) % len(self._HINT_IDS)
            state.elf_reward_next = 1
            target_message_id = hint_id
            target_text = self._message_formatter(hint_id)
            room_message_id = "EMSG03"
            room_text = self._message_formatter("EMSG03", player_name)

        events.append(
            AnimationTickEvent(
                flag="elves",
                room_id=room_id,
                message_id=room_message_id,
                message_text=room_text,
                payload={
                    "target_player": player_id,
                    "target_message_id": target_message_id,
                    "target_text": target_text,
                },
            )
        )
        events.append(AnimationTickEvent(flag="elves", room_id=room_id, message_id="EMSG04"))
        return events


class BrownieRoutine:
    """Port KYRANIM.C `browns()` gold/inventory theft encounters.

    Legacy reference: `browns()` in `legacy/KYRANIM.C` lines 393-426.
    """

    _PATH = BROWNIE_PATH

    def __init__(
        self,
        *,
        player_getter: Callable[[int], Any | None],
        player_ids_getter: Callable[[int], Sequence[str]] | None = None,
        player_persister: Callable[[Any], None],
        message_formatter: Callable[..., str],
        pronoun_lookup: Callable[[Any], str],
    ) -> None:
        self._player_getter = player_getter
        self._player_ids_getter = player_ids_getter
        self._player_persister = player_persister
        self._message_formatter = message_formatter
        self._pronoun_lookup = pronoun_lookup

    @classmethod
    def path(cls) -> tuple[int, ...]:
        return cls._PATH

    @classmethod
    def path_room(cls, index: int) -> int:
        return cls._PATH[index % len(cls._PATH)]

    def __call__(self, state: AnimationTickState) -> list[AnimationTickEvent]:
        if state.brownie_path_index >= len(self._PATH):
            state.brownie_path_index = 0
        path_index_before = state.brownie_path_index
        room_id = self._PATH[state.brownie_path_index]
        state.brownie_location = room_id
        state.brownie_path_index += 1
        path_index_after = state.brownie_path_index

        player = self._player_getter(room_id)
        if player is None:
            return [
                self._audit_event(
                    room_id,
                    {
                        "branch": "none",
                        "path_index_before": path_index_before,
                        "path_index_after": path_index_after,
                        "active_player_ids": self._player_ids(room_id),
                        "target_player": None,
                        "message_ids": [],
                    },
                )
            ]

        events = [
            AnimationTickEvent(flag="browns", room_id=room_id, message_id="BMSG00")
        ]
        player_name = getattr(player, "altnam", getattr(player, "plyrid", "player"))
        player_id = getattr(player, "plyrid", player_name)
        gold_before = int(getattr(player, "gold", 0))
        inventory_before = list(getattr(player, "gpobjs", []))
        inventory_count_before = int(getattr(player, "npobjs", len(inventory_before)))

        if getattr(player, "gold", 0) > 0:
            player.gold = 0
            branch = "gold"
            target_message_id = "BMSG01"
            room_message_id = "BMSG02"
            target_text = self._message_formatter(target_message_id)
            room_text = self._message_formatter(
                room_message_id, player_name, self._pronoun_lookup(player)
            )
        elif getattr(player, "npobjs", 0) > 0:
            object.__setattr__(player, "gpobjs", [])
            object.__setattr__(player, "obvals", [])
            object.__setattr__(player, "npobjs", 0)
            branch = "inventory"
            target_message_id = "BMSG03"
            room_message_id = "BMSG04"
            target_text = self._message_formatter(target_message_id)
            room_text = self._message_formatter(room_message_id, player_name)
        else:
            branch = "taunt"
            target_message_id = "BMSG05"
            room_message_id = "BMSG06"
            target_text = self._message_formatter(target_message_id)
            room_text = self._message_formatter(room_message_id, player_name)

        self._player_persister(player)
        events.append(
            AnimationTickEvent(
                flag="browns",
                room_id=room_id,
                message_id=room_message_id,
                message_text=room_text,
                payload={
                    "target_player": player_id,
                    "target_message_id": target_message_id,
                    "target_text": target_text,
                },
            )
        )
        events.append(AnimationTickEvent(flag="browns", room_id=room_id, message_id="BMSG07"))
        events.append(
            self._audit_event(
                room_id,
                {
                    "branch": branch,
                    "path_index_before": path_index_before,
                    "path_index_after": path_index_after,
                    "active_player_ids": self._player_ids(room_id, fallback=[player_id]),
                    "target_player": player_id,
                    "gold_before": gold_before,
                    "gold_after": int(getattr(player, "gold", 0)),
                    "inventory_before": inventory_before,
                    "inventory_after": list(getattr(player, "gpobjs", [])),
                    "inventory_count_before": inventory_count_before,
                    "inventory_count_after": int(
                        getattr(player, "npobjs", len(getattr(player, "gpobjs", [])))
                    ),
                    "message_ids": ["BMSG00", room_message_id, "BMSG07"],
                    "target_message_id": target_message_id,
                },
            )
        )
        return events

    def _player_ids(self, room_id: int, *, fallback: Sequence[str] = ()) -> list[str]:
        if self._player_ids_getter is None:
            return list(fallback)
        return list(self._player_ids_getter(room_id))

    def _audit_event(self, room_id: int, payload: Mapping[str, object]) -> AnimationTickEvent:
        return AnimationTickEvent(
            flag="browns",
            room_id=room_id,
            payload={
                "audit_only": True,
                "audit": {
                    "room_id": room_id,
                    **dict(payload),
                },
            },
        )


def _sesame_event(_: AnimationTickState) -> AnimationTickEvent:
    return AnimationTickEvent(flag="sesame", room_id=185, message_id="WALM05")


def _chantd_event(_: AnimationTickState) -> AnimationTickEvent:
    return AnimationTickEvent(
        flag="chantd",
        room_id=7,
        message_text="***\rThe altar stops glowing.\r",
    )


def _rockpr_event(_: AnimationTickState) -> AnimationTickEvent:
    return AnimationTickEvent(
        flag="rockpr",
        room_id=27,
        message_text="***\rThe mists settle down.\r",
    )


class AnimationTickSystem:
    """Model KYRANIM.C `animat()` cadence as coordinator-owned runtime state.

    Routine order mirrors `switch (var)` in legacy/KYRANIM.C lines 117-133:
    dryads -> elves -> gemakr -> gemakr -> zarapp -> browns -> repeat.
    """

    _ROUTINE_SEQUENCE = (
        "dryads",
        "elves",
        "gemakr",
        "gemakr",
        "zarapp",
        "browns",
    )

    def __init__(
        self,
        *,
        persistence: AnimationTickStateStore,
        routine_handlers: Dict[str, RoutineHandler] | None = None,
        mob_updater: MobUpdateHandler | None = None,
        timed_flag_handlers: Dict[str, TimedFlagHandler] | None = None,
    ) -> None:
        self._persistence = persistence
        self.state = self._load_state(persistence)
        base_routines = {
            "dryads": _noop_handler,
            "elves": _noop_handler,
            "gemakr": _noop_handler,
            "zarapp": _noop_handler,
            "browns": _noop_handler,
        }
        if routine_handlers:
            base_routines.update(routine_handlers)
        self._routine_handlers = base_routines
        self._mob_updater = mob_updater or _noop_handler
        self._timed_flag_handlers = {
            "sesame": _sesame_event,
            "chantd": _chantd_event,
            "rockpr": _rockpr_event,
        }
        if timed_flag_handlers:
            self._timed_flag_handlers.update(timed_flag_handlers)

    @classmethod
    def routine_sequence(cls) -> tuple[str, ...]:
        return cls._ROUTINE_SEQUENCE

    def next_routine_name(self) -> str:
        return self._ROUTINE_SEQUENCE[
            self.state.routine_index % len(self._ROUTINE_SEQUENCE)
        ]

    def set_timed_flag(self, name: str, value: int = 1) -> None:
        self.state.timed_flags[name] = value
        self._persist()

    def persist_state(self) -> None:
        self._persist()

    def tick(self) -> AnimationTickResult:
        # Legacy reference: `animat()` starts with `chkzar()` before routine switch.
        # See legacy/KYRANIM.C lines 116-133.
        mob_events = list(self._mob_updater(self.state) or [])

        routine_name = self.next_routine_name()
        handler = self._routine_handlers[routine_name]
        routine_events = [*mob_events, *list(handler(self.state) or [])]

        timed_events = self._consume_timed_flags()

        self.state.routine_index = (self.state.routine_index + 1) % len(
            self._ROUTINE_SEQUENCE
        )
        self._persist()
        return AnimationTickResult(
            routine_name=routine_name,
            routine_events=routine_events,
            timed_events=timed_events,
        )

    def _consume_timed_flags(self) -> list[AnimationTickEvent]:
        events: list[AnimationTickEvent] = []
        for flag_name, handler in self._timed_flag_handlers.items():
            if self.state.timed_flags.get(flag_name, 0):
                events.append(handler(self.state))
                self.state.timed_flags[flag_name] = 0
        return events

    def _persist(self) -> None:
        self._persistence.save(
            {
                "routine_index": self.state.routine_index,
                "zar_counter": self.state.zar_counter,
                "zar_location": self.state.zar_location,
                "zar_attack_index": self.state.zar_attack_index,
                "timed_flags": dict(self.state.timed_flags),
                "gem_counter": self.state.gem_counter,
                "gem_last_attempt_room_id": self.state.gem_last_attempt_room_id,
                "gem_last_attempt_status": self.state.gem_last_attempt_status,
                "gem_last_attempt_object_count": self.state.gem_last_attempt_object_count,
                "gem_last_spawn_room_id": self.state.gem_last_spawn_room_id,
                "gem_last_spawn_object_id": self.state.gem_last_spawn_object_id,
                "gem_last_spawn_object_name": self.state.gem_last_spawn_object_name,
                "dryad_location": self.state.dryad_location,
                "brownie_location": self.state.brownie_location,
                "brownie_path_index": self.state.brownie_path_index,
                "elf_last_room": self.state.elf_last_room,
                "elf_reward_next": self.state.elf_reward_next,
                "elf_hint_index": self.state.elf_hint_index,
            }
        )

    @staticmethod
    def _load_state(persistence: AnimationTickStateStore) -> AnimationTickState:
        payload = persistence.load()
        if not payload:
            return AnimationTickState()

        timed_flags = payload.get("timed_flags")
        normalized_flags: dict[str, int] = {"sesame": 0, "chantd": 0, "rockpr": 0}
        if isinstance(timed_flags, Mapping):
            for key, value in timed_flags.items():
                if isinstance(key, str):
                    normalized_flags[key] = int(value)

        return AnimationTickState(
            routine_index=int(payload.get("routine_index", 0)),
            zar_counter=int(payload.get("zar_counter", 0)),
            zar_location=int(payload.get("zar_location", ZAR_HOME_ROOM)),
            zar_attack_index=int(payload.get("zar_attack_index", 0)),
            timed_flags=normalized_flags,
            gem_counter=int(payload.get("gem_counter", 0)),
            gem_last_attempt_room_id=_optional_int(payload.get("gem_last_attempt_room_id")),
            gem_last_attempt_status=_optional_str(payload.get("gem_last_attempt_status")),
            gem_last_attempt_object_count=_optional_int(
                payload.get("gem_last_attempt_object_count")
            ),
            gem_last_spawn_room_id=_optional_int(payload.get("gem_last_spawn_room_id")),
            gem_last_spawn_object_id=_optional_int(payload.get("gem_last_spawn_object_id")),
            gem_last_spawn_object_name=_optional_str(payload.get("gem_last_spawn_object_name")),
            dryad_location=int(payload.get("dryad_location", 0)),
            brownie_location=int(payload.get("brownie_location", 0)),
            brownie_path_index=int(payload.get("brownie_path_index", 0)),
            elf_last_room=(
                int(payload["elf_last_room"]) if payload.get("elf_last_room") is not None else None
            ),
            elf_reward_next=int(payload.get("elf_reward_next", 0)),
            elf_hint_index=int(payload.get("elf_hint_index", 0)),
        )


class AnimationTickRuntimeBridge:
    """Bridge animation ticks into room-state flags + room broadcasts.

    Legacy reference: KYRANIM.C `animat()` checks global one-shot flags after the
    rotating routine and emits room-wide text before clearing the globals (lines
    135-149). This bridge syncs those one-shot flags from room script state and
    broadcasts equivalent room events on each scheduled animation tick.
    """

    _ROOM_FLAG_BINDINGS: dict[str, tuple[int, str]] = {
        "sesame": (185, "sesame"),
        "chantd": (7, "chantd"),
        "rockpr": (27, "rockpr"),
    }

    def __init__(
        self,
        *,
        system: AnimationTickSystem,
        room_flag_getter: RoomFlagGetter,
        room_flag_setter: RoomFlagSetter,
        message_lookup: MessageLookup,
        event_dispatcher: EventDispatcher,
        audit_recorder: AuditRecorder | None = None,
        expected_interval_seconds: float = 15.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._system = system
        self._room_flag_getter = room_flag_getter
        self._room_flag_setter = room_flag_setter
        self._message_lookup = message_lookup
        self._event_dispatcher = event_dispatcher
        self._audit_recorder = audit_recorder
        self._expected_interval_seconds = expected_interval_seconds
        self._clock = clock or time.monotonic
        self._last_tick_at: float | None = None

    async def __call__(self, trigger_source: str = "scheduled") -> None:
        tick_started_at = self._clock()
        observed_elapsed_seconds = (
            None
            if self._last_tick_at is None
            else max(0.0, tick_started_at - self._last_tick_at)
        )
        self._last_tick_at = tick_started_at
        routine_index_before = self._system.state.routine_index
        routine_name_before = self._system.next_routine_name()
        timed_flags_before = dict(self._system.state.timed_flags)
        brownie_path_index_before = self._system.state.brownie_path_index

        self._sync_flags_from_rooms()
        timed_flags_after_sync = dict(self._system.state.timed_flags)
        result = self._system.tick()
        dispatch_failures: list[dict[str, object]] = []
        audit_events = [
            dict(event.payload.get("audit") or {})
            for event in result.routine_events
            if self._is_audit_only_event(event)
        ]
        dispatched_event_count = 0
        raised: BaseException | None = None

        try:
            for event in result.routine_events:
                if self._is_audit_only_event(event):
                    continue
                await self._dispatch_event(event)
                dispatched_event_count += 1
            for event in result.timed_events:
                self._room_flag_setter(event.room_id, event.flag, 0)
                await self._dispatch_event(event)
                dispatched_event_count += 1
        except Exception as exc:
            raised = exc
            dispatch_failures.append(
                {
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )

        routine_event_count = sum(
            1 for event in result.routine_events if not self._is_audit_only_event(event)
        )
        await self._record_audit(
            "animation.tick",
            {
                "trigger_source": trigger_source,
                "routine_name": result.routine_name,
                "routine_index_before": routine_index_before,
                "routine_index_after": self._system.state.routine_index,
                "routine_name_before": routine_name_before,
                "expected_interval_seconds": self._expected_interval_seconds,
                "observed_elapsed_seconds": observed_elapsed_seconds,
                "timed_flags_before": timed_flags_before,
                "timed_flags_after_sync": timed_flags_after_sync,
                "timed_flags_consumed": [event.flag for event in result.timed_events],
                "routine_event_count": routine_event_count,
                "timed_event_count": len(result.timed_events),
                "dispatched_event_count": dispatched_event_count,
                "dispatch_failure_count": len(dispatch_failures),
                "dispatch_failures": dispatch_failures,
                "brownie_path_index_before": brownie_path_index_before,
                "brownie_path_index_after": self._system.state.brownie_path_index,
            },
        )
        dispatch_status = "failure" if dispatch_failures else "success"
        for audit_event in audit_events:
            event_type = str(
                audit_event.pop("event_type", None) or "animation.brownie_step"
            )
            audit_event.setdefault("trigger_source", trigger_source)
            audit_event["dispatch_status"] = dispatch_status
            audit_event["dispatch_failure_count"] = len(dispatch_failures)
            await self._record_audit(event_type, audit_event)

        if raised is not None:
            raise raised

    async def _dispatch_event(self, event: AnimationTickEvent) -> None:
        maybe_awaitable = self._event_dispatcher(event)
        if asyncio.iscoroutine(maybe_awaitable):
            await maybe_awaitable

    @staticmethod
    def _is_audit_only_event(event: AnimationTickEvent) -> bool:
        return bool(event.payload.get("audit_only"))

    async def _record_audit(self, event_type: str, payload: Mapping[str, object]) -> None:
        if self._audit_recorder is None:
            return
        try:
            maybe_awaitable = self._audit_recorder(event_type, payload)
            if asyncio.iscoroutine(maybe_awaitable):
                await maybe_awaitable
        except Exception:
            return

    def _sync_flags_from_rooms(self) -> None:
        for flag, (room_id, room_key) in self._ROOM_FLAG_BINDINGS.items():
            if self._room_flag_getter(room_id, room_key) > 0:
                self._system.state.timed_flags[flag] = 1

    def resolve_event_text(self, event: AnimationTickEvent) -> str:
        if event.message_text:
            return event.message_text
        if event.message_id:
            return self._message_lookup(event.message_id) or ""
        return ""
