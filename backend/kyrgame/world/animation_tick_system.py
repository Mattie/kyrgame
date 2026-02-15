from __future__ import annotations

from dataclasses import dataclass, field
import asyncio
from typing import Awaitable, Callable, Dict, Mapping, MutableMapping, Protocol


@dataclass(eq=True, frozen=True)
class AnimationTickEvent:
    """One-shot world event emitted by the animation timer."""

    flag: str
    room_id: int
    message_id: str | None = None
    message_text: str | None = None


@dataclass
class AnimationTickResult:
    """Outputs produced by one animation-timer run."""

    routine_name: str
    timed_events: list[AnimationTickEvent] = field(default_factory=list)


@dataclass
class AnimationTickState:
    """Coordinator-owned animation timer state for multiplayer runtime.

    Legacy parity note: this replaces KYRANIM.C static/global fields used by
    ``animat()`` and ``chkzar()`` (legacy/KYRANIM.C lines 67-85, 111-173).
    """

    routine_index: int = 0
    zar_counter: int = 0
    timed_flags: MutableMapping[str, int] = field(
        default_factory=lambda: {"sesame": 0, "chantd": 0, "rockpr": 0}
    )


class AnimationTickStateStore(Protocol):
    """Persistence port for animation scheduler state.

    Multiplayer strategy: load a single shared snapshot on boot and store after
    each tick so reconnects/process restarts keep routine cadence + one-shot
    flags consistent for all connected players.
    """

    def load(self) -> Mapping[str, object] | None: ...

    def save(self, payload: Mapping[str, object]) -> None: ...


class InMemoryAnimationTickPersistence:
    """Process-local state store used until DB-backed world-state tables exist."""

    def __init__(self) -> None:
        self._payload: dict[str, object] | None = None

    def load(self) -> Mapping[str, object] | None:
        return dict(self._payload) if self._payload is not None else None

    def save(self, payload: Mapping[str, object]) -> None:
        self._payload = dict(payload)


RoutineHandler = Callable[[AnimationTickState], None]
MobUpdateHandler = Callable[[AnimationTickState], None]
TimedFlagHandler = Callable[[AnimationTickState], AnimationTickEvent]
MessageLookup = Callable[[str], str | None]
RoomFlagGetter = Callable[[int, str], int]
RoomFlagSetter = Callable[[int, str, int], None]
EventDispatcher = Callable[[AnimationTickEvent], Awaitable[None] | None]


def _noop_handler(_: AnimationTickState) -> None:
    return None


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

    def set_timed_flag(self, name: str, value: int = 1) -> None:
        self.state.timed_flags[name] = value
        self._persist()

    def tick(self) -> AnimationTickResult:
        # Legacy reference: `animat()` starts with `chkzar()` before routine switch.
        # See legacy/KYRANIM.C lines 116-133.
        self._mob_updater(self.state)

        routine_name = self._ROUTINE_SEQUENCE[
            self.state.routine_index % len(self._ROUTINE_SEQUENCE)
        ]
        handler = self._routine_handlers[routine_name]
        handler(self.state)

        timed_events = self._consume_timed_flags()

        self.state.routine_index = (self.state.routine_index + 1) % len(
            self._ROUTINE_SEQUENCE
        )
        self._persist()
        return AnimationTickResult(routine_name=routine_name, timed_events=timed_events)

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
                "timed_flags": dict(self.state.timed_flags),
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
            timed_flags=normalized_flags,
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
    ) -> None:
        self._system = system
        self._room_flag_getter = room_flag_getter
        self._room_flag_setter = room_flag_setter
        self._message_lookup = message_lookup
        self._event_dispatcher = event_dispatcher

    async def __call__(self) -> None:
        self._sync_flags_from_rooms()
        result = self._system.tick()
        for event in result.timed_events:
            self._room_flag_setter(event.room_id, event.flag, 0)
            maybe_awaitable = self._event_dispatcher(event)
            if asyncio.iscoroutine(maybe_awaitable):
                await maybe_awaitable

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
