from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, Iterable, Optional

from . import constants
from . import fixtures
from .gateway import RoomGateway
from .scheduler import ScheduledHandle, SchedulerService
from .models import (
    GameObjectModel,
    MessageBundleModel,
    PlayerModel,
    SpellModel,
)
from . import yaml_rooms
from .messaging import build_direct_and_others_events
from .player_progression import level_up_player
from .spellbook import add_spell_to_book
from .inventory import remove_inventory_item


RoomCallback = Callable[["RoomContext", str], Awaitable[None]]
RoomCommandCallback = Callable[
    ["RoomContext", str, str, list[str], Optional[int], Optional[PlayerModel]],
    Awaitable[bool],
]


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
        await self.engine.gateway.broadcast(
            self.room_id,
            self.engine.room_broadcast_envelope(
                self.room_id, {"event": event, "scope": "broadcast", **payload}
            ),
        )

    async def direct(self, player_id: str, event: str, **payload):
        await self.engine.gateway.broadcast(
            self.room_id,
            self.engine.room_broadcast_envelope(
                self.room_id,
                {"event": event, "scope": "direct", "player": player_id, **payload},
            ),
        )

    async def direct_and_others(
        self,
        player_id: str,
        event: str,
        *,
        direct_text: str | None,
        others_text: str | None,
        direct_message_id: str | None = None,
        others_message_id: str | None = None,
        **payload,
    ):
        for message in build_direct_and_others_events(
            player_id=player_id,
            event=event,
            direct_text=direct_text,
            others_text=others_text,
            direct_message_id=direct_message_id,
            others_message_id=others_message_id,
            extra_payload=payload,
        ):
            await self.engine.gateway.broadcast(
                self.room_id,
                self.engine.room_broadcast_envelope(self.room_id, message),
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
        players: Iterable[PlayerModel] | None = None,
        room_scripts: dict | None = None,
        objects: Iterable[GameObjectModel] | None = None,
        spells: Iterable[SpellModel] | None = None,
    ):
        self.gateway = gateway
        self.scheduler = scheduler
        self.locations = {location.id: location for location in locations}
        self.messages = messages
        self.routines: Dict[int, RoomRoutine] = build_default_routines(messages)
        self.states: Dict[int, RoomState] = {}
        self.players: Dict[str, PlayerModel] = {
            player.plyrid: player for player in (players or [])
        }
        self.reloads = 0
        self.pending_events: list[dict] = []  # Events to be processed by webapp
        self.yaml_engine = (
            yaml_rooms.YamlRoomEngine(
                definitions=room_scripts,
                messages=messages,
                objects=objects or [],
                spells=spells or [],
                locations=self.locations.values(),
            )
            if room_scripts
            else None
        )

    def get_room_state(self, room_id: int) -> RoomState:
        if room_id not in self.states:
            self.states[room_id] = RoomState(room_id=room_id)
        return self.states[room_id]

    async def enter_room(self, player_id: str, room_id: int):
        state = self.get_room_state(room_id)
        state.occupants.add(player_id)
        state.flags["entries"] = state.flags.get("entries", 0) + 1
        await self.gateway.broadcast(
            room_id,
            self.room_broadcast_envelope(
                room_id,
                {"event": "player_enter", "scope": "broadcast", "player": player_id},
            ),
        )

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
            await self.gateway.broadcast(
                room_id,
                self.room_broadcast_envelope(
                    room_id, {"event": "room_empty", "scope": "broadcast"}
                ),
            )

    def reload_scripts(self):
        self.routines = build_default_routines(self.messages)
        self.reloads += 1

    def get_and_clear_pending_events(self) -> list[dict]:
        """Retrieve and clear pending events for webapp processing."""
        events = self.pending_events
        self.pending_events = []
        return events

    def room_broadcast_envelope(self, room_id: int, payload: dict) -> dict:
        return {"type": "room_broadcast", "room": room_id, "payload": payload}

    async def handle_command(
        self,
        player_id: str,
        room_id: int,
        command: str,
        args: Optional[list[str]] = None,
        player_level: Optional[int] = None,
        player: Optional[PlayerModel] = None,
    ) -> bool:
        # Try YAML engine first if available
        if self.yaml_engine:
            player_obj = self.players.get(player_id) or player
            if player_obj:
                result = self.yaml_engine.handle(
                    player=player_obj,
                    room_id=room_id,
                    command=command,
                    args=args or [],
                )
                # Process events from YAML engine
                # Store events for webapp to process with proper filtering
                for event in result.events:
                    # Map YAML scopes to webapp-compatible scopes
                    scope = event.get("scope", "broadcast")
                    if scope == "direct":
                        # Direct messages should use "target" scope for webapp filtering
                        event = {**event, "scope": "target"}
                    elif scope == "broadcast":
                        # Broadcast messages should use "room" scope
                        event = {**event, "scope": "room"}
                    self.pending_events.append(event)
                if result.handled:
                    return True
        
        # Fall back to Python routines
        routine = self.routines.get(room_id)
        if routine and routine.on_command:
            return await routine.on_command(
                RoomContext(self, room_id), player_id, command, args or [], player_level, player
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
        18: RoomRoutine(
            on_command=_stump_on_command(messages),
        ),
        24: RoomRoutine(
            on_command=_silver_on_command(messages),
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
    player: Optional[PlayerModel],
):
    catalog = context.engine.messages.messages
    verb = command.lower()
    arg0 = args[0].lower() if args else ""

    if verb in {"look", "examine", "see"} and arg0 in {"tree", "willow", "willow tree"}:
        await context.direct(player_id, "room_message", text=catalog["KID046"])
        return True

    kneel_word = catalog.get("WILCMD", "kneel").lower()
    if verb == kneel_word:
        level = player_level if player_level is not None else (player.level if player else 0)
        display_name = player.altnam if player is not None else player_id
        if player is not None and level == 1:
            # Legacy willow calls chklvl(2), grants SBD053, then glvutl.
            # Source: legacy/KYRROUS.C:184-191.
            level_up_player(player)
            _grant_def_spell(player, 52, constants.SBD053_FIREPROT1)
        elif level >= 2:
            await context.direct_and_others(
                player_id,
                "room_message",
                direct_text=catalog.get("LVLM00", ""),
                others_text=catalog.get("LVLM01", "") % display_name,
                direct_message_id="LVLM00",
                others_message_id="LVLM01",
            )
            return True
        elif level < 2:
            await context.direct(
                player_id,
                "room_message",
                text=catalog.get("LVLM02", ""),
                message_id="LVLM02",
            )
            return True

        blessed = context.state.flags.setdefault("willow_blessed", set())
        if player_id not in blessed:
            blessed.add(player_id)
        await context.direct_and_others(
            player_id,
            "room_message",
            direct_text=catalog["LVL200"],
            others_text=catalog["GETLVL"] % display_name,
            direct_message_id="LVL200",
            others_message_id="GETLVL",
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


_TEMPLE_ARTICLES = {"the", "a", "an"}


def _temple_remainder_after_gi_bagthe(args: list[str]) -> str:
    # Legacy temple() calls gi_bagthe(), then rstrin(), before comparing margv[1]
    # with TEMPLE. Source: legacy/KYRROUS.C:294-340 and legacy/GAMUTILS.C:55-68.
    normalized = [arg.lower() for arg in args]
    index = 0
    while index < len(normalized) - 1:
        if normalized[index] in _TEMPLE_ARTICLES:
            del normalized[index]
        index += 1
    return " ".join(normalized)


def _temple_on_command(messages: MessageBundleModel) -> RoomCommandCallback:
    objects_by_name = {obj.name.lower(): obj.id for obj in fixtures.load_objects()}

    async def _handler(
        context: RoomContext,
        player_id: str,
        command: str,
        args: list[str],
        player_level: Optional[int],
        player: Optional[PlayerModel],
    ) -> bool:
        verb = command.lower()

        effective_level = (
            player_level if player_level is not None else (player.level if player is not None else 0)
        )
        display_name = player.altnam if player is not None else player_id

        async def level_gate(target_level: int, direct_id: str, broadcast_id: str) -> bool:
            if player is None:
                return False
            if effective_level == target_level - 1:
                level_up_player(player)
                await context.direct_and_others(
                    player_id,
                    "room_message",
                    direct_text=messages.messages.get(direct_id, ""),
                    others_text=messages.messages.get(broadcast_id, "") % display_name,
                    direct_message_id=direct_id,
                    others_message_id=broadcast_id,
                )
                return True
            if effective_level >= target_level:
                await context.direct_and_others(
                    player_id,
                    "room_message",
                    direct_text=messages.messages.get("LVLM00", ""),
                    others_text=messages.messages.get("LVLM01", "") % display_name,
                    direct_message_id="LVLM00",
                    others_message_id="LVLM01",
                )
                return True
            await context.direct_and_others(
                player_id,
                "room_message",
                direct_text=messages.messages.get("LVLM02", ""),
                others_text=messages.messages.get("LVLM03", "") % display_name,
                direct_message_id="LVLM02",
                others_message_id="LVLM03",
            )
            return True

        # Legacy: PUT object handling for level-up donations
        if verb == "put" and args:
            obj_arg = args[0].lower()
            # Legacy temple only accepts an offering when chantd is exactly 5.
            # Source: legacy/KYRROUS.C:295-314.
            chant_ready = context.state.flags.get("chantd", 0) == 5

            if chant_ready and player is not None:
                offered = _resolve_offering(obj_arg, objects_by_name)
                if offered is None or offered not in player.gpobjs:
                    return False
                # Legacy tgmpobj happens before the switch/chklvl call, so even
                # failed level gates consume the offering.
                # Source: legacy/KYRROUS.C:296-303.
                remove_inventory_item(player, offered)
                if offered == 18:
                    return await level_gate(9, "LVL9M0", "LVL9M1")
                if offered == 21:
                    return await level_gate(10, "LV10M0", "LVL9M1")
                await context.direct_and_others(
                    player_id,
                    "room_message",
                    direct_text=messages.messages.get("OFFER0", ""),
                    others_text=messages.messages.get("OFFER1", "") % display_name,
                    direct_message_id="OFFER0",
                    others_message_id="OFFER1",
                )
                return True

        # Legacy: CHANT TASHANNA command
        if verb == "chant" and args and args[0].lower() == "tashanna":
            chant_count = context.state.flags.get("chantd", 0)
            chant_count += 1
            context.state.flags["chantd"] = chant_count

            if chant_count == 1:
                await context.broadcast("ambient",
                                      text="*** The altar begins to glow dimly.")
            else:
                await context.broadcast("ambient",
                                      text="*** The altar glows even brighter!")
            return True

        temple_phrase = messages.messages.get("TEMPLE", "glory be to tashanna").lower()
        if _temple_remainder_after_gi_bagthe(args) == temple_phrase:
            # Legacy temple phrase calls chklvl(3), then glvutl and msgutl2(LVL300, GETLVL).
            # kyra() gives room routines first chance before caster handles chant as a spell.
            # Source: legacy/KYRROUS.C:319-340 and legacy/KYRCMDS.C:1248-1257.
            return await level_gate(3, "LVL300", "GETLVL")

        # Legacy: PRAY/MEDITATE commands
        if verb in {"pray", "meditate"}:
            await context.direct_and_others(
                player_id,
                "room_message",
                direct_text=messages.messages.get("TMPRAY", ""),
                others_text=f"*** {display_name} is praying to the Goddess Tashanna.",
                direct_message_id="TMPRAY",
                others_message_id=None,
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
        player: Optional[PlayerModel],
    ) -> bool:  # noqa: ARG001
        verb = command.lower()

        if (
            verb in {"get", "grab", "pick", "take"}
            and args
            and args[0].lower() == "rose"
        ):
            player_obj = player or context.engine.players.get(player_id)
            if player_obj is None:
                return False

            display_name = player_obj.altnam
            # Legacy rosutl checks pack size before pgmpobj(&gmobjs[40],0).
            # Source: legacy/KYRROUS.C:742-753.
            if player_obj.npobjs >= constants.MXPOBS:
                await context.direct_and_others(
                    player_id,
                    "room_message",
                    direct_text=messages.messages.get("GROSE3", ""),
                    others_text=messages.messages.get("GROSE4", "") % display_name,
                    direct_message_id="GROSE3",
                    others_message_id="GROSE4",
                )
                return True

            player_obj.gpobjs.append(40)
            player_obj.obvals.append(0)
            player_obj.npobjs = len(player_obj.gpobjs)
            await context.direct_and_others(
                player_id,
                "room_message",
                direct_text=messages.messages.get("GROSE1", ""),
                others_text=messages.messages.get("GROSE2", "") % display_name,
                direct_message_id="GROSE1",
                others_message_id="GROSE2",
            )
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
        player: Optional[PlayerModel],
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
                await context.direct_and_others(
                    player_id,
                    "room_message",
                    direct_text=messages.messages["MAGF00"],
                    others_text=messages.messages["MAGF01"] % player_id,
                    direct_message_id="MAGF00",
                    others_message_id="MAGF01",
                )
            else:
                state.flags["scroll_count"] = scroll_count
                await context.direct_and_others(
                    player_id,
                    "room_message",
                    direct_text=messages.messages["MAGF04"],
                    others_text=messages.messages["MAGF07"] % player_id,
                    direct_message_id="MAGF04",
                    others_message_id="MAGF07",
                )
            return True

        # Legacy: case 43 (shard) - requires 6 donations to grant object 16
        if offering == "shard":
            shard_count = state.flags.get("shard_count", 0)
            shard_count += 1
            
            if shard_count >= 6:
                state.flags["shard_count"] = 0
                # Legacy gives player object 16
                await context.direct_and_others(
                    player_id,
                    "room_message",
                    direct_text=messages.messages["MAGF05"],
                    others_text=messages.messages["MAGF03"] % player_id,
                    direct_message_id="MAGF05",
                    others_message_id="MAGF03",
                )
            else:
                state.flags["shard_count"] = shard_count
                await context.direct_and_others(
                    player_id,
                    "room_message",
                    direct_text=messages.messages["MAGF06"],
                    others_text=messages.messages["MAGF03"] % player_id,
                    direct_message_id="MAGF06",
                    others_message_id="MAGF03",
                )
            return True

        # Default case for other objects
        await context.direct_and_others(
            player_id,
            "room_message",
            direct_text=messages.messages.get("MAGF02", ""),
            others_text=messages.messages.get("MAGF03", "") % player_id,
            direct_message_id="MAGF02",
            others_message_id="MAGF03",
        )
        return True

    return _handler


def _stump_on_command(messages: MessageBundleModel) -> RoomCommandCallback:
    """Mirror the legacy ``stumpr`` routine (legacy/KYRROUS.C lines 512-538)."""

    gem_sequence = list(range(12))
    objects_by_name = {obj.name.lower(): obj.id for obj in fixtures.load_objects()}
    spells_by_name = {spell.name.lower(): spell for spell in fixtures.load_spells()}
    hotkiss = spells_by_name.get("hotkiss")

    async def _handler(
        context: RoomContext,
        player_id: str,
        command: str,
        args: list[str],
        player_level: Optional[int],
        player: Optional[PlayerModel],
    ) -> bool:
        verb = command.lower()

        if verb not in {"drop", "offer"}:
            return False

        if player is None or hotkiss is None or not args:
            return False

        display_name = player.altnam
        offered = _resolve_offering(args[0], objects_by_name)
        level = player_level if player_level is not None else (player.level or 0)
        progress = player.stumpi or 0
        expected = gem_sequence[progress] if progress < len(gem_sequence) else None

        if offered is None or offered not in player.gpobjs:
            await context.direct_and_others(
                player_id,
                "room_message",
                direct_text=messages.messages.get("BGEM05", ""),
                others_text=messages.messages.get("BGEM06", "") % display_name,
                direct_message_id="BGEM05",
                others_message_id="BGEM06",
            )
            return True

        # Legacy stumpr consumes the offered inventory object before validating
        # level or sequence, and only resets stumpi on final chklvl failure.
        # Source: legacy/KYRROUS.C:518-543.
        remove_inventory_item(player, offered)

        if level != 5:
            await context.direct_and_others(
                player_id,
                "room_message",
                direct_text=messages.messages.get("BGEM04", ""),
                others_text=messages.messages.get("BGEM03", "") % display_name,
                direct_message_id="BGEM04",
                others_message_id="BGEM03",
            )
            return True

        if expected is None or offered != expected:
            await context.direct_and_others(
                player_id,
                "room_message",
                direct_text=messages.messages.get("BGEM04", ""),
                others_text=messages.messages.get("BGEM03", "") % display_name,
                direct_message_id="BGEM04",
                others_message_id="BGEM03",
            )
            return True

        player.stumpi = progress + 1
        if player.stumpi == len(gem_sequence):
            if level == 5:
                # Legacy stumpr rewards the final gem with chklvl(6)+glvutl (legacy/KYRROUS.C:534-537).
                level_up_player(player)
                _grant_off_spell(player, hotkiss)
                await context.direct_and_others(
                    player_id,
                    "room_message",
                    direct_text=messages.messages.get("BGEM00", ""),
                    others_text=messages.messages.get("BGEM01", "") % display_name,
                    direct_message_id="BGEM00",
                    others_message_id="BGEM01",
                )
            return True

        await context.direct_and_others(
            player_id,
            "room_message",
            direct_text=messages.messages.get("BGEM02", ""),
            others_text=messages.messages.get("BGEM03", "") % display_name,
            direct_message_id="BGEM02",
            others_message_id="BGEM03",
        )
        return True

    return _handler


def _silver_on_command(messages: MessageBundleModel) -> RoomCommandCallback:
    """Mirror the legacy ``silver`` routine (legacy/KYRROUS.C lines 555-589)."""

    hotseat_spell_id = 32  # SBD033 / hotseat (ice protection I)
    hotseat_bit = constants.SBD033_ICEPROT1
    objects_by_name = {obj.name.lower(): obj.id for obj in fixtures.load_objects()}

    async def _handler(
        context: RoomContext,
        player_id: str,
        command: str,
        args: list[str],
        player_level: Optional[int],
        player: Optional[PlayerModel],
    ) -> bool:
        verb = command.lower()

        if verb == "offer":
            if player is None or not args:
                return False

            display_name = player.altnam
            offered = _resolve_offering(args[0], objects_by_name)
            if offered is None or offered not in player.gpobjs:
                await context.direct_and_others(
                    player_id,
                    "room_message",
                    direct_text=messages.messages.get("TRDM05", ""),
                    others_text=messages.messages.get("SILVM5", "") % display_name,
                    direct_message_id="TRDM05",
                    others_message_id="SILVM5",
                )
                return True

            remove_inventory_item(player, offered)
            progress = player.gemidx or 0
            expected = player.stones[progress] if progress < len(player.stones) else None

            if expected is not None and offered == expected:
                player.gemidx = progress + 1
                if player.gemidx == len(player.stones):
                    effective_level = (
                        player_level
                        if player_level is not None
                        else (player.level if player is not None else 0)
                    )
                    if effective_level == 3:
                        # Legacy silver uses chklvl(4) + glvutl before granting the spell (legacy/KYRROUS.C:568-573).
                        level_up_player(player)
                        _grant_def_spell(player, hotseat_spell_id, hotseat_bit)
                        await context.direct_and_others(
                            player_id,
                            "room_message",
                            direct_text=messages.messages.get("SILVM0", ""),
                            others_text=messages.messages.get("SILVM1", "") % display_name,
                            direct_message_id="SILVM0",
                            others_message_id="SILVM1",
                        )
                    else:
                        player.gemidx = 0
                        message_id = "LVLM00" if effective_level >= 4 else "LVLM02"
                        broadcast_id = "LVLM01" if effective_level >= 4 else "LVLM03"
                        await context.direct_and_others(
                            player_id,
                            "room_message",
                            direct_text=messages.messages.get(message_id, ""),
                            others_text=messages.messages.get(broadcast_id, "") % display_name,
                            direct_message_id=message_id,
                            others_message_id=broadcast_id,
                        )
                    return True

                await context.direct_and_others(
                    player_id,
                    "room_message",
                    direct_text=messages.messages.get("SILVM2", ""),
                    others_text=messages.messages.get("SILVM3", "") % display_name,
                    direct_message_id="SILVM2",
                    others_message_id="SILVM3",
                )
                return True

            # Legacy silver leaves gemidx unchanged for wrong birthstones; the
            # reset happens only after the fourth correct stone fails chklvl(4).
            # Source: legacy/KYRROUS.C:564-583.
            await context.direct_and_others(
                player_id,
                "room_message",
                direct_text=messages.messages.get("SILVM4", ""),
                others_text=messages.messages.get("SILVM3", "") % display_name,
                direct_message_id="SILVM4",
                others_message_id="SILVM3",
            )
            return True

        if verb in {"pray", "meditate"}:
            # Legacy behavior: deliver SAPRAY to the player and a sndutl-style
            # emote to the rest of the room (legacy/KYRROUS.C lines 555-589).
            prayer_text = messages.messages.get("SAPRAY", "")
            attnam = player.attnam if player else None
            broadcast_text = f"*** {attnam or player_id} is praying to the Goddess Tashanna."
            await context.direct_and_others(
                player_id,
                "room_message",
                direct_text=prayer_text,
                others_text=broadcast_text,
                direct_message_id="SAPRAY",
                others_message_id="SAPRAY",
            )
            return True

        return False

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
        player: Optional[PlayerModel],
    ) -> bool:
        if command.lower() != "offer":
            return False

        words = [arg.lower() for arg in args]
        if len(words) < 5 or words[0] != "heart" or words[2] != "soul" or words[-1] != "tashanna":
            return False

        # Legacy: offering heart and soul to Tashanna grants the willowisp spell at level 7.
        # Source: legacy/KYRROUS.C lines 821-837 (hnsrou).
        level = player_level if player_level is not None else (player.level if player else 0)
        display_name = player.altnam if player is not None else player_id
        if player is not None and level == 6:
            level_up_player(player)
            add_spell_to_book(
                player,
                SpellModel(
                    id=61,
                    name="weewillo",
                    sbkref=constants.OTHERS,
                    bitdef=constants.SBD062_WILLOWISP,
                    level=7,
                ),
            )
            await context.direct_and_others(
                player_id,
                "room_message",
                direct_text=messages.messages.get("HNSYOU", ""),
                others_text=messages.messages.get("HNSOTH", "") % display_name,
                direct_message_id="HNSYOU",
                others_message_id="HNSOTH",
            )
            return True
        if level >= 7:
            await context.direct_and_others(
                player_id,
                "room_message",
                direct_text=messages.messages.get("LVLM00", ""),
                others_text=messages.messages.get("LVLM01", "") % display_name,
                direct_message_id="LVLM00",
                others_message_id="LVLM01",
            )
            return True

        await context.direct_and_others(
            player_id,
            "room_message",
            direct_text=messages.messages.get("LVLM02", ""),
            others_text=messages.messages.get("LVLM03", "") % display_name,
            direct_message_id="LVLM02",
            others_message_id="LVLM03",
        )
        return True

    return _handler


def _resolve_offering(candidate: str, mapping: dict[str, int]) -> int | None:
    try:
        return int(candidate)
    except ValueError:
        return mapping.get(candidate.lower())


def _grant_def_spell(player: PlayerModel, spell_id: int, bitmask: int):
    # Legacy rewards set spellbook bit ownership only (legacy/KYRROUS.C:189,570).
    add_spell_to_book(
        player,
        SpellModel(id=spell_id, name=f"spell-{spell_id}", sbkref=constants.DEFENS, bitdef=bitmask, level=0),
    )


def _grant_off_spell(player: PlayerModel, spell: SpellModel):
    # Legacy rewards set spellbook bit ownership only (legacy/KYRROUS.C:634).
    add_spell_to_book(player, spell)
