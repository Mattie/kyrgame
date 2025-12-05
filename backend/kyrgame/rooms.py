from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, Iterable, Optional

from .gateway import RoomGateway
from .scheduler import ScheduledHandle, SchedulerService
from .models import MessageCatalogModel


RoomCallback = Callable[["RoomContext", str], Awaitable[None]]
RoomCommandCallback = Callable[["RoomContext", str, str, list[str], Optional[int]], Awaitable[bool]]


@dataclass
class RoomRoutine:
    on_enter: Optional[RoomCallback] = None
    on_exit: Optional[RoomCallback] = None
    on_command: Optional[RoomCommandCallback] = None


@dataclass
class RoomState:
    room_id: int
    occupants: set[str] = field(default_factory=set)
    flags: dict = field(default_factory=dict)
    timers: dict[str, ScheduledHandle] = field(default_factory=dict)


@dataclass
class RoomContext:
    engine: "RoomScriptEngine"
    room_id: int

    @property
    def state(self) -> RoomState:
        return self.engine.get_room_state(self.room_id)

    async def broadcast(self, event: str, **payload):
        await self.engine.gateway.broadcast(self.room_id, {"event": event, **payload})

    async def direct(self, player_id: str, event: str, **payload):
        if hasattr(self.engine.gateway, "direct"):
            await self.engine.gateway.direct(
                self.room_id, player_id, {"event": event, **payload}
            )
        else:
            await self.engine.gateway.broadcast(
                self.room_id, {"event": event, "player": player_id, **payload}
            )

    def schedule(self, name: str, delay: float, callback: Callable[[], Awaitable[None] | None], interval: float | None = None):
        handle = self.engine.scheduler.schedule(delay, callback, interval=interval)
        self.state.timers[name] = handle
        return handle

    def cancel_timer(self, name: str):
        handle = self.state.timers.pop(name, None)
        if handle:
            handle.cancel()


class RoomScriptEngine:
    def __init__(
        self,
        gateway: RoomGateway,
        scheduler: SchedulerService,
        locations: Iterable,
        messages: MessageCatalogModel,
    ):
        self.gateway = gateway
        self.scheduler = scheduler
        self.locations = {location.id: location for location in locations}
        self.messages = messages
        self.routines: Dict[int, RoomRoutine] = build_default_routines()
        self.states: Dict[int, RoomState] = {}
        self.reloads = 0

    def get_room_state(self, room_id: int) -> RoomState:
        if room_id not in self.states:
            self.states[room_id] = RoomState(room_id=room_id)
        return self.states[room_id]

    async def enter_room(self, player_id: str, room_id: int):
        state = self.get_room_state(room_id)
        state.occupants.add(player_id)
        state.flags["entries"] = state.flags.get("entries", 0) + 1
        await self.gateway.broadcast(room_id, {"event": "player_enter", "player": player_id})

        routine = self.routines.get(room_id)
        if routine and routine.on_enter:
            await routine.on_enter(RoomContext(self, room_id), player_id)

    async def exit_room(self, player_id: str, room_id: int):
        state = self.get_room_state(room_id)
        if player_id in state.occupants:
            state.occupants.remove(player_id)
        routine = self.routines.get(room_id)
        if routine and routine.on_exit:
            await routine.on_exit(RoomContext(self, room_id), player_id)
        if not state.occupants:
            for handle in list(state.timers.values()):
                handle.cancel()
            state.timers.clear()
            await self.gateway.broadcast(room_id, {"event": "room_empty"})

    def reload_scripts(self):
        self.routines = build_default_routines()
        self.reloads += 1

    async def handle_command(
        self,
        player_id: str,
        room_id: int,
        command: str,
        args: Optional[list[str]] = None,
        player_level: Optional[int] = None,
    ) -> bool:
        routine = self.routines.get(room_id)
        if routine and routine.on_command:
            return await routine.on_command(
                RoomContext(self, room_id), player_id, command, args or [], player_level
            )
        return False


def build_default_routines() -> Dict[int, RoomRoutine]:
    return {
        0: RoomRoutine(
            on_enter=_willow_on_enter,
            on_exit=_willow_on_exit,
            on_command=_willow_on_command,
        ),
    }


async def _willow_on_enter(context: RoomContext, player_id: str):
    await context.broadcast("player_enter", player=player_id)


async def _willow_on_exit(context: RoomContext, player_id: str):  # noqa: ARG001
    state = context.state
    if not state.occupants:
        for timer in list(state.timers.keys()):
            context.cancel_timer(timer)


async def _willow_on_command(
    context: RoomContext,
    player_id: str,
    command: str,
    args: list[str],
    player_level: Optional[int],
):
    catalog = context.engine.messages.messages
    verb = command.lower()
    arg0 = args[0].lower() if args else ""

    if verb in {"look", "examine", "see"} and arg0 in {"tree", "willow", "willow tree"}:
        await context.direct(player_id, "room_message", text=catalog["KID046"])
        return True

    kneel_word = catalog.get("WILCMD", "kneel").lower()
    if verb == kneel_word:
        level = player_level or 0
        if level < 2:
            await context.direct(
                player_id,
                "room_message",
                text="...Nothing happens. You sense the willow expects greater strength.",
            )
            return True

        blessed = context.state.flags.setdefault("willow_blessed", set())
        if player_id not in blessed:
            blessed.add(player_id)
        await context.direct(player_id, "room_message", text=catalog["LVL200"])
        await context.broadcast(
            "room_message",
            text=catalog["GETLVL"] % player_id,
            player=player_id,
        )
        return True

    return False
