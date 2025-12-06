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
            on_command=_spring_on_command(messages),
        ),
        38: RoomRoutine(
            on_enter=_fountain_on_enter(messages),
            on_exit=_willow_on_exit,
            on_command=_fountain_on_command(messages),
        ),
        101: RoomRoutine(
            on_command=_heart_and_soul_on_command(messages),
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
    ) -> bool:
        verb = command.lower()
        
        # Legacy: PUT object handling for level-up donations
        if verb == "put" and args:
            obj_arg = args[0].lower()
            # Check if chant requirement is met (chantd == 5 in legacy)
            chant_ready = context.state.flags.get("chant_count", 0) >= 5
            
            if chant_ready:
                # Legacy: case 18 - requires level 9
                if obj_arg in {"amulet", "18"}:
                    level = player_level or 0
                    if level >= 9:
                        await context.direct(player_id, "room_message", 
                                           text=messages.messages.get("LVL9M0", "You have achieved level 9!"))
                        await context.broadcast("room_message", 
                                              text=messages.messages.get("LVL9M1", ""),
                                              player=player_id)
                        return True
                # Legacy: case 21 - requires level 10
                elif obj_arg in {"crystal", "21"}:
                    level = player_level or 0
                    if level >= 10:
                        await context.direct(player_id, "room_message",
                                           text=messages.messages.get("LV10M0", "You have achieved level 10!"))
                        await context.broadcast("room_message",
                                              text=messages.messages.get("LVL9M1", ""),
                                              player=player_id)
                        return True
                # Default offering response
                await context.direct(player_id, "room_message", 
                                   text=messages.messages.get("OFFER0", "The altar accepts your offering."))
                await context.broadcast("room_message",
                                      text=messages.messages.get("OFFER1", ""),
                                      player=player_id)
                return True
        
        # Legacy: CHANT TASHANNA command
        if verb == "chant" and args and args[0].lower() == "tashanna":
            chant_count = context.state.flags.get("chant_count", 0)
            chant_count += 1
            context.state.flags["chant_count"] = chant_count
            
            if chant_count == 1:
                await context.broadcast("ambient", 
                                      text="*** The altar begins to glow dimly.")
            else:
                await context.broadcast("ambient",
                                      text="*** The altar glows even brighter!")
            return True
        
        # Legacy: PRAY/MEDITATE commands
        if verb in {"pray", "meditate"}:
            text = messages.messages.get("PRAYER", "...You whisper a quiet prayer...")
            await context.direct(player_id, "room_message", text=text)
            await context.broadcast(
                "room_message", text=text, player=player_id, message_id="PRAYER"
            )
            return True

        return False

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


def _spring_on_command(messages: MessageBundleModel) -> RoomCommandCallback:
    async def _handler(
        context: RoomContext,
        player_id: str,
        command: str,
        args: list[str],
        player_level: Optional[int],
    ) -> bool:  # noqa: ARG001
        verb = command.lower()
        
        # Legacy: GET ROSE command gives player object 40
        if verb in {"get", "take", "pick"} and args and args[0].lower() == "rose":
            # Note: Legacy checks npobjs >= MXPOBS for inventory full
            # Simplified here without inventory check
            await context.direct(player_id, "room_message",
                               text=messages.messages.get("GROSE1", "You pick a beautiful rose."))
            await context.broadcast("room_message",
                                  text=messages.messages.get("GROSE2", "") % player_id,
                                  player=player_id)
            return True
        
        return False

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
        
        # Legacy: case 32 (pinecone) - requires 3 donations to spawn scroll
        if offering == "pinecone":
            scroll_count = state.flags.get("scroll_count", 0)
            # Note: Legacy checks BLESSD flag for bonus increment; simplified here
            scroll_count += 1
            
            if scroll_count >= 3:
                state.flags["scroll_count"] = 0
                # Legacy spawns scroll (object 35) at random location
                await context.direct(player_id, "room_message", text=messages.messages["MAGF00"])
                await context.broadcast(
                    "room_message",
                    text=messages.messages["MAGF01"] % player_id,
                    player=player_id,
                )
            else:
                state.flags["scroll_count"] = scroll_count
                await context.direct(player_id, "room_message", text=messages.messages["MAGF04"])
                await context.broadcast(
                    "room_message",
                    text=messages.messages["MAGF07"] % player_id,
                    player=player_id,
                )
            return True

        # Legacy: case 43 (shard) - requires 6 donations to grant object 16
        if offering == "shard":
            shard_count = state.flags.get("shard_count", 0)
            shard_count += 1
            
            if shard_count >= 6:
                state.flags["shard_count"] = 0
                # Legacy gives player object 16
                await context.direct(player_id, "room_message", text=messages.messages["MAGF05"])
                await context.broadcast(
                    "room_message",
                    text=messages.messages["MAGF03"] % player_id,
                    player=player_id,
                )
            else:
                state.flags["shard_count"] = shard_count
                await context.direct(player_id, "room_message", text=messages.messages["MAGF06"])
                await context.broadcast(
                    "room_message",
                    text=messages.messages["MAGF03"] % player_id,
                    player=player_id,
                )
            return True

        # Default case for other objects
        await context.direct(
            player_id, "room_message", text=messages.messages.get("MAGF02", "")
        )
        await context.broadcast(
            "room_message",
            text=messages.messages.get("MAGF03", "") % player_id,
            player=player_id,
        )
        return True

    return _handler


async def _broadcast_message(context: RoomContext, event: str, text: str):
    await context.broadcast(event, text=text)


def _heart_and_soul_on_command(messages: MessageBundleModel) -> RoomCommandCallback:
    async def _handler(
        context: RoomContext,
        player_id: str,
        command: str,
        args: list[str],
        player_level: Optional[int],
    ) -> bool:
        if command.lower() != "offer":
            return False

        words = [arg.lower() for arg in args]
        if len(words) < 5 or words[0] != "heart" or words[2] != "soul" or words[-1] != "tashanna":
            return False

        # Legacy: offering heart and soul to Tashanna grants the willowisp spell at level 7+.
        # Source: legacy/KYRROUS.C lines 821-837 (hnsrou).
        level = player_level or 0
        if level < 7:
            await context.direct(
                player_id,
                "room_message",
                text="...A whisper reminds you that true devotion requires greater strength.",
            )
            return True

        rewarded = context.state.flags.setdefault("hns_rewards", set())
        if player_id in rewarded:
            await context.direct(player_id, "room_message", text=messages.messages.get("HNSYOU", ""))
            return True

        rewarded.add(player_id)
        await context.direct(
            player_id,
            "room_message",
            text=messages.messages.get(
                "HNSYOU", "...As you offer your heart and soul, you feel newly empowered."
            ),
        )
        await context.broadcast(
            "room_message",
            text=messages.messages.get("HNSOTH", "%s is filled with new strength!") % player_id,
            player=player_id,
        )
        return True

    return _handler
