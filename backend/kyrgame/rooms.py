from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, Iterable, Optional

from .gateway import RoomGateway
from .scheduler import ScheduledHandle, SchedulerService
from .models import MessageBundleModel


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
        messages: MessageBundleModel,
    ):
        self.gateway = gateway
        self.scheduler = scheduler
        self.locations = {location.id: location for location in locations}
        self.messages = messages
        self.routines: Dict[int, RoomRoutine] = build_default_routines(messages)
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
        self.routines = build_default_routines(self.messages)
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


def build_default_routines(messages: MessageBundleModel) -> Dict[int, RoomRoutine]:
    return {
        0: RoomRoutine(
            on_enter=_willow_on_enter,
            on_exit=_willow_on_exit,
            on_command=_willow_on_command,
        ),
        7: RoomRoutine(
            on_enter=_temple_on_enter(messages),
            on_exit=_willow_on_exit,
            on_command=_temple_on_command(messages),
        ),
        32: RoomRoutine(
            on_enter=_spring_on_enter(messages),
            on_exit=_willow_on_exit,
        ),
        38: RoomRoutine(
            on_enter=_fountain_on_enter(messages),
            on_exit=_willow_on_exit,
            on_command=_fountain_on_command(messages),
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


def _temple_on_enter(messages: MessageBundleModel) -> RoomCallback:
    async def _handler(context: RoomContext, player_id: str):  # noqa: ARG001
        if "prayer_prompt" not in context.state.timers:
            context.schedule(
                "prayer_prompt",
                0.05,
                lambda: _broadcast_message(
                    context, "ambient", messages.messages.get("TMPRAY", "")
                ),
                interval=30.0,
            )

    return _handler


def _temple_on_command(messages: MessageBundleModel) -> RoomCommandCallback:
    async def _handler(
        context: RoomContext,
        player_id: str,
        command: str,
        args: list[str],
        player_level: Optional[int],
    ) -> bool:  # noqa: ARG001
        if command.lower() != "pray":
            return False
        text = messages.messages.get("PRAYER", "...You whisper a quiet prayer...")
        await context.direct(player_id, "room_message", text=text)
        await context.broadcast(
            "room_message", text=text, player=player_id, message_id="PRAYER"
        )
        return True

    return _handler


def _spring_on_enter(messages: MessageBundleModel) -> RoomCallback:
    async def _handler(context: RoomContext, player_id: str):  # noqa: ARG001
        if "spring_ambience" not in context.state.timers:
            context.schedule(
                "spring_ambience",
                0.05,
                lambda: _broadcast_message(
                    context, "ambient", messages.messages.get("KRD032", "")
                ),
                interval=20.0,
            )

    return _handler


def _fountain_on_enter(messages: MessageBundleModel) -> RoomCallback:
    async def _handler(context: RoomContext, player_id: str):  # noqa: ARG001
        state = context.state
        state.flags.setdefault("fountain_donations", 0)
        if "fountain_ambience" not in state.timers:
            context.schedule(
                "fountain_ambience",
                0.05,
                lambda: _broadcast_message(
                    context, "ambient", messages.messages.get("KRD038", "")
                ),
                interval=25.0,
            )

    return _handler


def _fountain_on_command(messages: MessageBundleModel) -> RoomCommandCallback:
    async def _handler(
        context: RoomContext,
        player_id: str,
        command: str,
        args: list[str],
        player_level: Optional[int],
    ) -> bool:  # noqa: ARG001
        if command.lower() != "toss" or not args:
            return False

        offering = args[0].lower()
        state = context.state
        if offering == "pinecone":
            state.flags["fountain_donations"] = state.flags.get("fountain_donations", 0) + 1
            await context.direct(player_id, "room_message", text=messages.messages["MAGF00"])
            await context.broadcast(
                "room_message",
                text=messages.messages["MAGF01"] % player_id,
                player=player_id,
            )
            return True

        if offering == "shard":
            if state.flags.get("fountain_donations", 0):
                await context.direct(
                    player_id, "room_message", text=messages.messages["MAGF05"]
                )
            else:
                await context.direct(
                    player_id, "room_message", text=messages.messages["MAGF06"]
                )
            template = messages.messages.get("MAGF07")
            broadcast_text = (
                template % player_id if template and "%s" in template else template
            )
            await context.broadcast(
                "room_message",
                text=broadcast_text or messages.messages.get("MAGF06", ""),
                player=player_id,
            )
            return True

        await context.direct(
            player_id, "room_message", text=messages.messages.get("MAGF04", "")
        )
        return True

    return _handler


async def _broadcast_message(context: RoomContext, event: str, text: str):
    await context.broadcast(event, text=text)
