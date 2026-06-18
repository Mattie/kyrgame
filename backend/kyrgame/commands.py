import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Protocol, Set

from sqlalchemy import select, update

from . import constants, fixtures, models, modern_features, repositories, room_spoilers
from .effects import EffectError, ObjectEffectEngine, SpellEffectEngine
from .honor_mode import HonorModePolicy
from .inventory import pop_inventory_index
from .player_lifecycle import (
    DeathRecoveryPlan,
    apply_death_recovery_plan,
    build_modern_death_recovery_plan,
    reset_player_after_death,
)
from .player_titles import legacy_title_for_level
from .spellbook import (
    add_spell_to_book,
    forget_all_memorized,
    forget_memorized_spell,
    has_spell_in_book,
    list_spellbook_spells,
    memorize_spell,
)
from .world.animation_tick_system import AnimationTickEvent


class CommandError(Exception):
    """Base exception for command dispatch problems."""

    def __init__(self, message: str, message_id: str | None = None):
        super().__init__(message)
        self.message_id = message_id


class UnknownCommandError(CommandError):
    def __init__(self, verb: str, message_id: str | None = None):
        super().__init__(verb)
        self.message_id = message_id or "HUH"


class LevelRequirementError(CommandError):
    def __init__(self, message: str, message_id: str | None = None):
        super().__init__(message)
        self.message_id = message_id


class FlagRequirementError(CommandError):
    def __init__(self, message: str, message_id: str | None = None):
        super().__init__(message)
        self.message_id = message_id


class BlockedExitError(CommandError):
    pass


class CooldownActiveError(CommandError):
    pass


class InvalidDirectionError(CommandError):
    pass


class CommandHandler(Protocol):
    def __call__(self, state: "GameState", args: dict) -> Awaitable["CommandResult"] | "CommandResult":
        ...


class PresenceAccessor(Protocol):
    async def players_in_room(self, room_id: int) -> Set[str]:
        ...


@dataclass
class CommandMetadata:
    verb: str
    command_id: int | None = None
    required_level: int = 0
    required_flags: int = 0
    cooldown_seconds: float = 0.0
    failure_message_id: str | None = None


@dataclass
class RegisteredCommand:
    metadata: CommandMetadata
    handler: CommandHandler


@dataclass
class ParsedCommand:
    verb: str
    args: dict
    command_id: int | None = None
    message_id: str | None = None
    pay_only: bool = False


@dataclass
class GameState:
    player: models.PlayerModel
    locations: Dict[int, models.LocationModel]
    objects: Dict[int, models.GameObjectModel] = field(default_factory=dict)
    messages: models.MessageBundleModel | None = None
    content_mappings: dict[str, dict[str, str]] | None = None
    cooldowns: Dict[str, float] = field(default_factory=dict)
    rng: random.Random = field(default_factory=random.Random)
    db_session: any = None  # SQLAlchemy session for persistence
    presence: PresenceAccessor | None = None
    player_lookup: Callable[[str], models.PlayerModel | None] | None = None
    global_player_lookup: Callable[[str], models.PlayerModel | None] | None = None
    zar_controller: Any | None = None
    zar_state: Any | None = None
    honor_mode_policy: HonorModePolicy = field(default_factory=HonorModePolicy)


@dataclass
class CommandResult:
    state: GameState
    events: List[dict] = field(default_factory=list)


FATIGUE_CHECKED_ARG = "_fatigue_checked"
FATIGUE_BYPASS_ARG = "_fatigue_bypass"
FATIGUE_BYPASS_META_KEY = "fatigue_bypass"
_PAY_ONLY_ARG = "_pay_only"

_FATIGUE_BYPASS_STATUS_VERBS = frozenset(
    {"?", "check", "count", "gold", "help", "hits", "inventory", "spells"}
)
_FATIGUE_BYPASS_LOOK_VERBS = frozenset({"examine", "look", "read", "see"})
_FATIGUE_BYPASS_LOOK_TARGETS = frozenset({"", "brief", "spellbook"})


class CommandRegistry:
    def __init__(self):
        self._commands: Dict[str, RegisteredCommand] = {}

    def register(self, metadata: CommandMetadata, handler: CommandHandler):
        self._commands[metadata.verb] = RegisteredCommand(metadata=metadata, handler=handler)

    def get(self, verb: str) -> RegisteredCommand | None:
        return self._commands.get(verb)

    def __getitem__(self, verb: str) -> RegisteredCommand:
        return self._commands[verb]

    def verbs(self) -> List[str]:
        return list(self._commands.keys())


class CommandDispatcher:
    def __init__(self, registry: CommandRegistry, clock: Callable[[], float] | None = None):
        self.registry = registry
        self.clock = clock or time.monotonic

    async def dispatch_parsed(self, parsed: "ParsedCommand", state: GameState) -> CommandResult:
        return await self.dispatch(
            parsed.verb,
            {
                **parsed.args,
                "command_id": parsed.command_id,
                "message_id": parsed.message_id,
                "verb": parsed.verb,
                _PAY_ONLY_ARG: parsed.pay_only,
            },
            state,
        )

    async def dispatch(self, verb: str, args: dict, state: GameState) -> CommandResult:
        entry = self.registry.get(verb)
        if entry is None:
            command_id = args.get("command_id")
            fatigue_checked = bool(args.get(FATIGUE_CHECKED_ARG))
            fatigue_bypass_requested = bool(args.get(FATIGUE_BYPASS_ARG))
            fatigue_bypassed = fatigue_bypass_requested and can_bypass_command_fatigue(
                verb, args
            )
            if not fatigue_checked and not fatigue_bypassed:
                fatigue_result = apply_command_fatigue_gate(state, command_id)
                if fatigue_result is not None:
                    return fatigue_result
            return _legacy_unknown_command_result(state, verb, args)

        metadata = entry.metadata
        command_id = args.get("command_id")
        fatigue_checked = bool(args.get(FATIGUE_CHECKED_ARG))
        fatigue_bypass_requested = bool(args.get(FATIGUE_BYPASS_ARG))
        fatigue_bypassed = fatigue_bypass_requested and can_bypass_command_fatigue(
            verb, args
        )
        pay_only = bool(args.get(_PAY_ONLY_ARG))
        handler_args = dict(args)
        handler_args.pop(FATIGUE_CHECKED_ARG, None)
        handler_args.pop(FATIGUE_BYPASS_ARG, None)
        handler_args.pop(_PAY_ONLY_ARG, None)

        if not fatigue_checked and not fatigue_bypassed:
            fatigue_result = apply_command_fatigue_gate(state, command_id)
            if fatigue_result is not None:
                return fatigue_result

        if pay_only and not state.player.flags & constants.PlayerFlag.LOADED:
            raise FlagRequirementError(
                "Command requires a live player", message_id="CMPCMD1"
            )
        self._validate_requirements(metadata, state)

        now = self.clock()
        if metadata.cooldown_seconds:
            self._validate_cooldown(verb, metadata, state, now)

        result = entry.handler(state, handler_args)
        if asyncio.iscoroutine(result):
            result = await result

        state.cooldowns[verb] = now
        return result

    @staticmethod
    def _validate_requirements(metadata: CommandMetadata, state: GameState):
        if state.player.level < metadata.required_level:
            raise LevelRequirementError(
                f"Command '{metadata.verb}' requires level {metadata.required_level}",
                message_id=metadata.failure_message_id,
            )
        if metadata.required_flags and (state.player.flags & metadata.required_flags) != metadata.required_flags:
            raise FlagRequirementError(
                f"Command '{metadata.verb}' requires flags {metadata.required_flags:#x}",
                message_id=metadata.failure_message_id,
            )

    @staticmethod
    def _validate_cooldown(verb: str, metadata: CommandMetadata, state: GameState, now: float):
        last_used = state.cooldowns.get(verb, -float("inf"))
        if now - last_used < metadata.cooldown_seconds:
            raise CooldownActiveError(
                f"Command '{verb}' on cooldown for {metadata.cooldown_seconds - (now - last_used):.2f}s"
            )


_DIRECTION_FIELDS = {
    "north": "gi_north",
    "south": "gi_south",
    "east": "gi_east",
    "west": "gi_west",
}

_PICKUP_VERBS = {
    "get",
    "grab",
    "pickpocket",
    "pilfer",
    "snatch",
    "steal",
    "take",
}

_SAY_VERBS = {"say", "comment", "note"}
_YELL_VERBS = {"scream", "shout", "shriek", "yell"}
_GIVE_VERBS = {"give", "hand", "pass", "toss"}

SIMPLE_EMOTES = {
    "blink": ("Blink!", "blinking %s eyes in disbelief!", False),
    "blush": ("Blush.", "blushing and turning bright red!", False),
    "boo": ("BOO!", "booing and yelling for the hook!", True),
    "bow": ("Bow.", "bowing rather modestly.", False),
    "burp": ("Urrrrp!", "belching rudely!", True),
    "cackle": ("Cackle, cackle!", "cackling frighteningly!", True),
    "cheer": ("Rah, rah, rah!", "cheering enthusiastically!", True),
    "chuckle": ("Heh, heh, heh.", "chuckling under %s breath.", True),
    "clap": ("Clap, clap.", "clapping in admiration.", False),
    "cough": ("Ahem.", "coughing loud and harshly.", True),
    "cry": ("Awwwww.", "crying %s little heart out.", True),
    "dance": ("How graceful!", "dancing with soaring spirits!", False),
    "fart": ("Yuck.", "emanating a horrible odor.", False),
    "frown": ("Frown.", "frowning unhappily.", False),
    "gasp": ("WOW!", "gasping in total amazement!", True),
    "giggle": ("Giggle, giggle!", "giggling like a hyena.", True),
    "grin": ("What a grin!", "grinning from ear to ear.", False),
    "groan": ("Groan!", "groaning with disgust.", True),
    "growl": ("Growl!", "growling like a rabid bear!", True),
    "hiss": ("Hisss!", "hissing like an angry snake!", True),
    "howl": ("Howl!", "howling like a dog in heat!", True),
    "laugh": ("What's so funny?", "laughing %s head off!", True),
    "lie": ("Comfortable?", "lying down comfortably.", True),
    "moan": ("Moan!", "moaning loudly.", True),
    "nod": ("Nod.", "nodding in agreement.", False),
    "piss": ("If you say so.", "lifting %s leg strangely.", False),
    "pout": ("Wasdamatta?", "pouting with tearful eyes.", True),
    "shit": ("Find a toilet!", "grunting on %s knees.", False),
    "shrug": ("Shrug.", "shrugging with indifference.", False),
    "sigh": ("Sigh.", "sighing wistfully.", True),
    "sing": ("Lalalala.", "singing a cheerful melody.", True),
    "sit": ("Ok, now what?", "sitting down for a bit.", False),
    "smile": ("Smile!", "smiling kindly.", False),
    "smirk": ("Smirk.", "smirking in disdain.", False),
    "sneeze": ("Waaacho!", "sneezing %s brains out!", False),
    "snicker": ("Snicker, snicker.", "snickering evily.", True),
    "sniff": ("Sniff.", "sniffling woefully.", False),
    "sob": ("Sob!", "sobbing pitifully.", True),
    "whistle": ("Whistle.", "whistling a faintly familiar tune.", True),
    "yawn": ("Aaarhh.", "yawning with boredom.", True),
}
# Pickup verbs mirror legacy getter aliases in KYRCMDS.C (gi_cmdarr).【F:legacy/KYRCMDS.C†L117-L174】

_NORMALIZE_ARTICLES = {"the", "a", "an"}
_NORMALIZE_PREPOSITIONS = {"at", "to", "into", "through", "in"}


def normalize_tokens(tokens: List[str]) -> List[str]:
    """Remove legacy stop-words while preserving the last argument token."""
    # Mirrors gi_bagthe/bagprep token stripping in legacy/GAMUTILS.C (lines 55-95).
    if len(tokens) <= 2:
        return tokens[:]

    normalized = [tokens[0]]
    last_index = len(tokens) - 1
    for index, token in enumerate(tokens[1:], start=1):
        if index >= last_index:
            normalized.append(token)
            continue
        lowered = token.lower()
        if lowered in _NORMALIZE_ARTICLES or lowered in _NORMALIZE_PREPOSITIONS:
            continue
        normalized.append(token)
    return normalized


def _command_message_id(command_id: int | None) -> str | None:
    if command_id is None:
        return None
    return f"CMD{command_id:03d}"


def can_bypass_command_fatigue(verb: str, args: dict | None = None) -> bool:
    """Return whether a UI refresh command may skip the legacy fatigue gate.

    This is intentionally a small allowlist for read-only satellite UI refreshes.
    The WebSocket contract is `meta.fatigue_bypass=true`, and direct callers may
    pass `FATIGUE_BYPASS_ARG`. Add entries here only when the command has no room
    routine dependency, no room/target fan-out, and no state mutation beyond the
    usual session bookkeeping. Mutating commands must keep paying the legacy
    `macros` cost from KYRANDIA.C:300-307.
    """

    normalized_verb = (verb or "").strip().lower()
    command_args = args or {}
    if normalized_verb in _FATIGUE_BYPASS_STATUS_VERBS:
        return True
    if normalized_verb not in _FATIGUE_BYPASS_LOOK_VERBS:
        return False

    target = str(command_args.get("raw") or command_args.get("target") or "")
    normalized_target = target.strip().lower()
    if normalized_verb == "read":
        # Legacy reader() delegates `read spellbook` back into looker()/seesbk().
        # Keep this bypass as narrow as that non-mutating alias. See legacy/KYRCMDS.C:1035-1057.
        return normalized_target == "spellbook"
    return normalized_target in _FATIGUE_BYPASS_LOOK_TARGETS


def apply_command_fatigue_gate(
    state: GameState, command_id: int | None = None
) -> CommandResult | None:
    """Apply the legacy command fatigue counter before command execution."""

    # Legacy kyrand() case 7 lets commands run until macros reaches 19; the
    # 20th accepted command emits TIRED and skips kyra(). See legacy/KYRANDIA.C:300-307.
    if not _increment_player_macros(state):
        return CommandResult(
            state=state,
            events=[
                _message_event(
                    "player",
                    "TIRED",
                    _format_message(state, "TIRED"),
                    command_id,
                )
            ],
        )
    return None


def _increment_player_macros(state: GameState) -> bool:
    if not state.db_session:
        if state.player.macros >= 19:
            return False
        state.player.macros += 1
        return True

    result = state.db_session.execute(
        update(models.Player)
        .where(models.Player.plyrid == state.player.plyrid)
        .where(models.Player.macros < 19)
        .values(macros=models.Player.macros + 1)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount:
        state.db_session.commit()
        refreshed = _refresh_player_macros_from_record(state)
        if refreshed is None:
            state.player.macros += 1
        return True

    refreshed = _refresh_player_macros_from_record(state)
    if refreshed is None:
        if state.player.macros >= 19:
            return False
        state.player.macros += 1
        return True
    return False


def _refresh_player_macros_from_record(state: GameState) -> int | None:
    if not state.db_session:
        return None
    record = state.db_session.scalar(
        select(models.Player)
        .where(models.Player.plyrid == state.player.plyrid)
        .execution_options(populate_existing=True)
    )
    if record is not None:
        state.player.macros = record.macros
        return record.macros
    return None


def _arrival_text(direction: str) -> str:
    """Return the arrival phrase used when a player enters a room.

    Mirrors the "has just <enttxt>" formatting in ``entrgp`` when movement
    transitions are announced to the new room.【F:legacy/KYRCMDS.C†L330-L368】【F:legacy/KYRUTIL.C†L236-L260】
    """

    origin_map = {
        "north": "south",
        "south": "north",
        "east": "west",
        "west": "east",
    }
    source = origin_map.get(direction)
    if source:
        return f"appeared from the {source}"
    return "arrived"


def _departure_text(direction: str) -> str:
    """Return the legacy phrase used when a player leaves by walking."""

    if direction in _DIRECTION_FIELDS:
        return f"moved off to the {direction}"
    return "left"


def _room_departure_event(
    state: GameState,
    *,
    from_room: int,
    to_room: int | None,
    command_id: int | None,
    direction: str | None,
    departure_text: str,
) -> dict:
    # Mirrors remvgp() source-room fan-out before gamloc changes in legacy/KYRUTIL.C:225-233.
    return {
        "scope": "room",
        "room_id": from_room,
        "event": "room_message",
        "type": "room_message",
        "player": state.player.plyrid,
        "from": from_room,
        "to": to_room,
        "direction": direction,
        "text": f"*** {state.player.altnam} has just {departure_text}!",
        "message_id": None,
        "command_id": command_id,
        "exclude_player": state.player.plyrid,
    }


def _build_room_transition_events(
    state: GameState,
    *,
    from_room: int,
    to_room: int,
    command_id: int | None,
    message_id: str | None,
    direction: str | None,
    arrival_text: str,
) -> list[dict]:
    destination = state.locations[to_room]
    description_id, long_description = _location_description(state, destination)

    return [
        {
            "scope": "room",
            "event": "player_enter",
            "type": "player_moved",
            "player": state.player.plyrid,
            "from": from_room,
            "to": destination.id,
            "description": destination.brfdes,
            "command_id": command_id,
            "message_id": message_id,
        },
        {
            "scope": "room",
            "event": "room_message",
            "type": "room_message",
            "player": state.player.plyrid,
            "from": from_room,
            "to": destination.id,
            "direction": direction,
            "text": arrival_text,
            "message_id": None,
            "command_id": command_id,
        },
        {
            "scope": "player",
            "event": "location_update",
            "type": "location_update",
            "location": destination.id,
            "description": destination.brfdes,
            "description_id": description_id,
            "long_description": long_description,
            "command_id": command_id,
            "message_id": message_id,
        },
        {
            "scope": "player",
            "event": "location_description",
            "type": "location_description",
            "location": destination.id,
            "message_id": description_id,
            "text": long_description or destination.brfdes,
            "objects": room_object_entries(destination, state.objects or {}),
        },
        # Mirror locobjs call in legacy entrgp to describe visible room objects on entry.【F:legacy/KYRUTIL.C†L248-L266】
        _room_objects_event(
            destination,
            state.objects or {},
            command_id,
            message_id,
        ),
    ]


def _handle_move(state: GameState, args: dict) -> CommandResult:
    direction = args.get("direction")
    if direction not in _DIRECTION_FIELDS:
        raise InvalidDirectionError(f"Unknown direction: {direction}")

    command_id = args.get("command_id")
    message_id = args.get("message_id") or _command_message_id(command_id)
    current = state.locations[state.player.gamloc]
    target_id = getattr(current, _DIRECTION_FIELDS[direction])
    if target_id == -1 or target_id not in state.locations:
        raise BlockedExitError(
            f"No exit {direction} from location {current.id}", message_id="MOVUTL"
        )

    from_room = state.player.gamloc
    state.player.pgploc = from_room
    state.player.gamloc = target_id
    _persist_player_location(state, state.player)

    # Mirrors movutl/entrgp in legacy/KYRCMDS.C and KYRUTIL.C for movement flow.【F:legacy/KYRCMDS.C†L328-L366】【F:legacy/KYRUTIL.C†L236-L255】
    arrival_phrase = _arrival_text(direction)
    arrival_text = f"*** {state.player.altnam} has just {arrival_phrase}!"
    events = [
        _room_departure_event(
            state,
            from_room=from_room,
            to_room=target_id,
            command_id=command_id,
            direction=direction,
            departure_text=_departure_text(direction),
        )
    ]
    events.extend(
        _build_room_transition_events(
            state,
            from_room=current.id,
            to_room=target_id,
            command_id=command_id,
            message_id=message_id,
            direction=direction,
            arrival_text=arrival_text,
        )
    )

    return CommandResult(
        state=state,
        events=events,
    )


def _handle_exit(state: GameState, args: dict) -> CommandResult:
    command_id = args.get("command_id")
    from_room = state.player.gamloc
    events: list[dict] = []
    if from_room >= 0:
        events.append(
            _room_departure_event(
                state,
                from_room=from_room,
                to_room=None,
                command_id=command_id,
                direction=None,
                departure_text="vanished in sparkling light",
            )
        )

    # Legacy kyra() checks "x" before the command table and calls remvgp() before EXIKYR.
    # See legacy/KYRANDIA.C:192-196 and legacy/KYRUTIL.C:225-233.
    if from_room >= 0:
        state.player.pgploc = from_room
    state.player.gamloc = -1
    _persist_player_location(state, state.player)
    events.append(
        _message_event(
            "player",
            "EXIKYR",
            _format_message(state, "EXIKYR") or "...Exiting Kyrandia...",
            command_id,
        )
    )
    events.append(
        {
            "scope": "control",
            "event": "session_exit",
            "type": "session_exit",
            "from": from_room,
            "command_id": command_id,
            "message_id": "EXIKYR",
        }
    )
    return CommandResult(state=state, events=events)


def _adjacent_room_ids(state: GameState) -> List[int]:
    """Return room IDs reachable from the player's current location.

    Mirrors sndnear() which sends to the four cardinal exits.
    See legacy/KYRUTIL.C:193-208.
    """
    loc = state.locations.get(state.player.gamloc)
    if not loc:
        return []
    current = state.player.gamloc
    nearby = []
    for room_id in (loc.gi_north, loc.gi_south, loc.gi_east, loc.gi_west):
        if room_id >= 0 and room_id != current and room_id in state.locations:
            nearby.append(room_id)
    return nearby


def _handle_chat(state: GameState, args: dict) -> CommandResult:
    text = args.get("text", "").strip()
    command_id = args.get("command_id")
    message_id = args.get("message_id") or _command_message_id(command_id)
    mode = args.get("mode", "say")
    events: List[dict] = [
        {
            "scope": "room",
            "event": "chat",
            "type": "chat",
            "from": state.player.plyrid,
            "text": text,
            "args": {"text": text},
            "mode": mode,
            "location": state.player.gamloc,
            "command_id": command_id,
            "message_id": message_id,
        }
    ]
    # Legacy yeller() calls sndnear() to broadcast to adjacent rooms.
    # See legacy/KYRCMDS.C:298-326 and legacy/KYRUTIL.C:193-208.
    if mode in _YELL_VERBS:
        if text:
            uppercased_text = text.upper()
            nearby_text = _format_message(state, "YELLER6", uppercased_text)
            nearby_msg_id = "YELLER6"
        else:
            nearby_text = _format_message(state, "YELLER2", mode)
            nearby_msg_id = "YELLER2"
        for room_id in _adjacent_room_ids(state):
            events.append({
                "scope": "nearby_room",
                "room_id": room_id,
                "event": "room_message",
                "type": "room_message",
                "text": nearby_text,
                "message_id": nearby_msg_id,
                "command_id": command_id,
            })
    return CommandResult(state=state, events=events)


def _handle_inventory(state: GameState, args: dict) -> CommandResult:  # noqa: ARG001
    command_id = args.get("command_id")
    message_id = args.get("message_id") or _command_message_id(command_id)

    # Mirrors gi_invrou/gi_invutl from legacy/KYRUTIL.C for inventory listing output.【F:legacy/KYRUTIL.C†L311-L338】
    return CommandResult(
        state=state,
        events=[_inventory_event(state, command_id, message_id)],
    )


def _handle_spoiler(state: GameState, args: dict) -> CommandResult:
    command_id = args.get("command_id")
    message_id = args.get("message_id") or _command_message_id(command_id)
    room_id = state.player.gamloc
    spoiler = room_spoilers.load_room_spoilers().get(room_id)
    if not spoiler:
        return CommandResult(state=state, events=[])

    summary = _resolve_spoiler_phrases(spoiler.get("summary"), state.messages)
    interaction = _resolve_spoiler_phrases(spoiler.get("interaction"), state.messages)
    legacy_ref = spoiler.get("legacy_ref")
    text_parts = [part for part in (summary, interaction) if part]
    text = "\n".join(text_parts) if text_parts else None

    return CommandResult(
        state=state,
        events=[
            {
                "scope": "player",
                "event": "spoiler",
                "type": "spoiler",
                "location": room_id,
                "summary": summary,
                "interaction": interaction,
                "legacy_ref": legacy_ref,
                "text": text,
                "command_id": command_id,
                "message_id": message_id,
            }
        ],
    )


def _resolve_spoiler_phrases(
    text: str | None, messages: models.MessageBundleModel | None
) -> str | None:
    if not text or not messages:
        return text
    replacements = {
        "WILCMD": messages.messages.get("WILCMD"),
        "EGLADE": messages.messages.get("EGLADE"),
    }
    resolved = text
    for key, value in replacements.items():
        if value:
            resolved = resolved.replace(key, value)
    return resolved


async def _handle_get(state: GameState, args: dict) -> CommandResult:
    # Ported from getloc in legacy/KYRCMDS.C for pickup/broadcast parity.【F:legacy/KYRCMDS.C†L702-L729】
    command_id = args.get("command_id")
    message_id = args.get("message_id") or _command_message_id(command_id)
    verb = (args.get("verb") or "get").strip().lower()
    raw_target = (args.get("target") or "").strip()
    target = raw_target.lower()
    target_player_name = (args.get("target_player") or "").strip()

    if not target:
        raise CommandError("Specify an item to pick up", message_id=message_id)

    if target_player_name:
        return await _handle_get_from_player(
            state, target_player_name, raw_target, verb, command_id
        )

    location = state.locations[state.player.gamloc]
    objects = state.objects or {}
    if state.presence and state.player_lookup:
        occupants = await _ordered_players_in_room(state, location.id)
        target_player = None
        for occupant_id in occupants:
            candidate = state.player_lookup(occupant_id)
            if (
                candidate
                and _matches_player_name(target, candidate)
                and _can_see_player(state.player, candidate)
            ):
                target_player = candidate
                break
        if target_player:
            actor_text = _format_message(state, "GETLOC1", target_player.altnam)
            target_text = _format_message(state, "GETLOC2", state.player.altnam, verb)
            room_text = _format_message(
                state, "GETLOC3", state.player.altnam, verb, target_player.altnam
            )
            return CommandResult(
                state=state,
                events=[
                    _message_event("player", "GETLOC1", actor_text, command_id),
                    {
                        **_message_event("target", "GETLOC2", target_text, command_id),
                        "player": target_player.plyrid,
                    },
                    _message_event(
                        "room",
                        "GETLOC3",
                        room_text,
                        command_id,
                        exclude_player=target_player.plyrid,
                        exclude_players=_sndbt2_excluded_players(state, target_player),
                    ),
                ],
            )

    object_index = _find_object_slot_in_location(location, objects, target)
    if object_index is None:
        return CommandResult(
            state=state,
            events=[
                _message_event(
                    "player",
                    "GETLOC4",
                    _format_message(state, "GETLOC4", raw_target, location.objlds),
                    command_id,
                ),
                _message_event(
                    "room",
                    None,
                    _sndutl_text(state.player, "beyond all hope."),
                    command_id,
                    exclude_player=state.player.plyrid,
                ),
            ],
        )
    object_id = location.objects[object_index]

    obj = objects.get(object_id)
    if obj is None or "PICKUP" not in obj.flags:
        room_text = _format_message(
            state, "GETLOC5", state.player.altnam, verb, obj.name if obj else target
        )
        return CommandResult(
            state=state,
            events=[
                _message_event(
                    "player",
                    message_id,
                    _format_message(state, message_id) or "You cannot pick that up",
                    command_id,
                ),
                _message_event(
                    "room",
                    "GETLOC5",
                    room_text,
                    command_id,
                    exclude_player=state.player.plyrid,
                ),
            ],
        )

    if len(state.player.gpobjs) >= constants.MXPOBS:
        return CommandResult(
            state=state,
            events=[
                _message_event(
                    "player",
                    "GETLOC6",
                    _format_message(state, "GETLOC6"),
                    command_id,
                ),
                _message_event(
                    "room",
                    None,
                    _sndutl_text(state.player, "looking very greedy."),
                    command_id,
                    exclude_player=state.player.plyrid,
                ),
            ],
        )

    # Legacy fgmlobj records objno, then getloc calls tgmlobj(objno), which
    # removes one lcobjs slot via taklobj. See legacy/KYRCMDS.C:713-730 and
    # legacy/KYRUTIL.C:568-582.
    remaining_objects = list(location.objects)
    last_index = len(remaining_objects) - 1
    if object_index != last_index:
        remaining_objects[object_index] = remaining_objects[last_index]
    remaining_objects.pop()
    location = location.model_copy(
        update={"objects": remaining_objects, "nlobjs": len(remaining_objects)}
    )
    state.locations[location.id] = location

    state.player.gpobjs.append(object_id)
    state.player.obvals.append(0)
    state.player.npobjs = len(state.player.gpobjs)
    _persist_location_objects_and_player_inventories(
        state, location.id, remaining_objects, [state.player]
    )

    return CommandResult(
        state=state,
        events=[
            _inventory_event(state, command_id, message_id),
            _room_objects_event(location, objects, command_id, message_id),
            # Legacy sends the inline ITSYOURS CHAR_BUFFER before room fan-out.
            # Source: legacy/KYRCMDS.C:237,730-733.
            _message_event("player", "ITSYOURS", "...It's yours!", command_id),
            _message_event(
                "room",
                "GETLOC7",
                _format_message(
                    state, "GETLOC7", state.player.altnam, obj.name, location.objlds
                ),
                command_id,
                exclude_player=state.player.plyrid,
            ),
            {
                "scope": "player",
                "event": "pickup_result",
                "type": "pickup",
                "object_id": object_id,
                "object_name": obj.name if obj else str(object_id),
                "message_id": message_id,
                "command_id": command_id,
            },
        ],
    )


async def _handle_get_from_player(
    state: GameState,
    target_player_name: str,
    target_item: str,
    verb: str,
    command_id: int | None,
) -> CommandResult:
    """Handle player-targeted pickup attempts (legacy getgp)."""

    # Ported from getgp in legacy/KYRCMDS.C (player theft rules + messages).【F:legacy/KYRCMDS.C†L654-L699】
    target_player = await _find_player_in_room(state, target_player_name)
    if not target_player:
        return CommandResult(
            state=state,
            events=[
                _message_event(
                    "player",
                    "GETGP1",
                    _format_message(state, "GETGP1"),
                    command_id,
                )
            ],
        )

    if target_player.plyrid == state.player.plyrid:
        return CommandResult(
            state=state,
            events=[
                _message_event(
                    "player",
                    "GETGP2",
                    _format_message(state, "GETGP2"),
                    command_id,
                )
            ],
        )

    objects = state.objects or {}
    inventory_index = _find_inventory_index(
        target_player, target_item.lower(), objects
    )
    if inventory_index is None:
        return CommandResult(
            state=state,
            events=[
                _message_event(
                    "player",
                    "GETGP3",
                    _format_message(state, "GETGP3", target_player.altnam, target_item),
                    command_id,
                )
            ],
        )

    if len(state.player.gpobjs) >= constants.MXPOBS:
        return CommandResult(
            state=state,
            events=[
                _message_event(
                    "player",
                    "GETGP4",
                    _format_message(state, "GETGP4"),
                    command_id,
                )
            ],
        )

    obj_id = target_player.gpobjs[inventory_index]
    obj = objects.get(obj_id)
    obj_name = obj.name if obj else target_item
    theft_roll = state.rng.randrange(256)
    if (theft_roll & 0x0E) != 0:
        actor_text = _format_message(state, "GETGP5")
        target_text = _format_message(state, "GETGP6", state.player.altnam, verb, obj_name)
        room_text = _format_message(
            state, "GETGP7", state.player.altnam, verb, target_player.altnam, obj_name
        )
        return CommandResult(
            state=state,
            events=[
                _message_event("player", "GETGP5", actor_text, command_id),
                {
                    **_message_event("target", "GETGP6", target_text, command_id),
                    "player": target_player.plyrid,
                },
                _message_event(
                    "room",
                    "GETGP7",
                    room_text,
                    command_id,
                    exclude_player=target_player.plyrid,
                    exclude_players=_sndbt2_excluded_players(state, target_player),
                ),
            ],
        )

    _, value = pop_inventory_index(target_player, inventory_index)
    state.player.gpobjs.append(obj_id)
    state.player.obvals.append(value)
    state.player.npobjs = len(state.player.gpobjs)
    _persist_player_inventories(state, [target_player, state.player])

    actor_text = _format_message(state, "GETGP8")
    target_text = _format_message(state, "GETGP9", state.player.altnam, obj_name)
    room_text = _format_message(
        state, "GETGP10", state.player.altnam, target_player.altnam, obj_name
    )
    return CommandResult(
        state=state,
        events=[
            _message_event("player", "GETGP8", actor_text, command_id),
            {
                **_message_event("target", "GETGP9", target_text, command_id),
                "player": target_player.plyrid,
            },
            _message_event(
                "room",
                "GETGP10",
                room_text,
                command_id,
                exclude_player=target_player.plyrid,
                exclude_players=_sndbt2_excluded_players(state, target_player),
            ),
        ],
    )


def _handle_drop(state: GameState, args: dict) -> CommandResult:
    # Ported from dropit in legacy/KYRCMDS.C when moving items back to the room.【F:legacy/KYRCMDS.C†L862-L892】
    command_id = args.get("command_id")
    message_id = args.get("message_id") or _command_message_id(command_id)
    target = (args.get("target") or "").strip().lower()

    if not target:
        return CommandResult(
            state=state,
            events=[
                _message_event(
                    "player",
                    "DROPIT5",
                    _format_message(state, "DROPIT5"),
                    command_id,
                ),
                _message_event(
                    "room",
                    None,
                    _sndutl_text(state.player, "looking a little queer!"),
                    command_id,
                    exclude_player=state.player.plyrid,
                ),
            ],
        )

    objects = state.objects or {}
    location = state.locations[state.player.gamloc]
    inventory_index = _find_inventory_index(state.player, target, objects)
    if inventory_index is None:
        return CommandResult(
            state=state,
            events=[
                _message_event(
                    "player",
                    "DROPIT4",
                    _format_message(state, "DROPIT4"),
                    command_id,
                ),
                _message_event(
                    "room",
                    None,
                    _sndutl_text(state.player, "acting very oddly."),
                    command_id,
                    exclude_player=state.player.plyrid,
                ),
            ],
        )

    if len(location.objects) >= constants.MXLOBS:
        return CommandResult(
            state=state,
            events=[
                _message_event(
                    "player",
                    "DROPIT1",
                    _format_message(state, "DROPIT1"),
                    command_id,
                ),
                _message_event(
                    "room",
                    None,
                    _sndutl_text(state.player, "struggling with the air!"),
                    command_id,
                    exclude_player=state.player.plyrid,
                ),
            ],
        )

    object_id, _ = pop_inventory_index(state.player, inventory_index)

    updated_objects = list(location.objects) + [object_id]
    location = location.model_copy(
        update={"objects": updated_objects, "nlobjs": len(updated_objects)}
    )
    state.locations[location.id] = location
    _persist_location_objects_and_player_inventories(
        state, location.id, updated_objects, [state.player]
    )

    obj = objects.get(object_id)

    return CommandResult(
        state=state,
        events=[
            _inventory_event(state, command_id, message_id),
            _room_objects_event(location, objects, command_id, message_id),
            _message_event(
                "player",
                "DROPIT2",
                _format_message(state, "DROPIT2"),
                command_id,
            ),
            _message_event(
                "room",
                "DROPIT3",
                # Legacy passes altnam, hisher, object name, and objlds; DROPIT3
                # consumes the first three placeholders.
                # Source: legacy/KYRCMDS.C:875-877; legacy/Dist/ELWKYRM.MSG:4684.
                _format_message(
                    state,
                    "DROPIT3",
                    state.player.altnam,
                    _hisher(state.player),
                    obj.name if obj else target,
                ),
                command_id,
                exclude_player=state.player.plyrid,
            ),
            {
                "scope": "room",
                "event": "drop",
                "type": "drop",
                "player": state.player.plyrid,
                "object_id": object_id,
                "object_name": obj.name if obj else str(object_id),
                "location": location.id,
                "message_id": message_id,
                "command_id": command_id,
            },
        ],
    )


def _matches_player_name(target: str, player: models.PlayerModel) -> bool:
    target_lower = target.strip().lower()
    # Legacy: findgp matches against attnam only (KYRUTIL.C 472-484).
    return _legacy_prefix_match(target_lower, player.attnam)


def _can_see_player(viewer: models.PlayerModel, target: models.PlayerModel) -> bool:
    if target is viewer:
        return True
    if not (target.flags & constants.PlayerFlag.INVISF):
        return True
    # Legacy ckinvs() gate: invisible targets are only targetable while CINVIS is active.
    # CINVIS is set by see-invisibility spells cadabra/iseeyou/icutwo in KYRSPEL.C.
    # Source trace: legacy/KYRUTIL.C:90-98, legacy/KYRSPEL.C:862-873.
    return viewer.charms[constants.CharmSlot.INVISIBILITY] > 0


async def _ordered_players_in_room(state: GameState, room_id: int) -> list[str]:
    if not state.presence:
        return []
    # Legacy findgp scans a stable gmparr; the port's presence layer exposes a set,
    # so sort ids before first-hit prefix matching. See legacy/KYRUTIL.C:472-484.
    return sorted(await state.presence.players_in_room(room_id))


async def _find_player_by_name(
    state: GameState, target_name: str, *, include_self: bool = True
) -> models.PlayerModel | None:
    if not state.presence or not state.player_lookup:
        return None
    occupants = await _ordered_players_in_room(state, state.player.gamloc)
    for occupant_id in occupants:
        candidate = state.player_lookup(occupant_id)
        if not candidate:
            continue
        if not include_self and candidate.plyrid == state.player.plyrid:
            continue
        if _matches_player_name(target_name, candidate) and _can_see_player(
            state.player, candidate
        ):
            return candidate
    return None


def _find_player_globally_by_true_id(
    state: GameState, target_name: str
) -> models.PlayerModel | None:
    if not state.global_player_lookup:
        return None
    candidate = state.global_player_lookup(target_name)
    if candidate is None or candidate.gamloc == -1:
        return None
    # Legacy fgamgp searches the full active game by true plyrid, bypassing
    # current-room attnam matching used by findgp (legacy/KYRUTIL.C:486-494).
    if candidate.plyrid.lower() != target_name.lower():
        return None
    return candidate


async def _find_player_in_room(
    state: GameState, target_name: str
) -> models.PlayerModel | None:
    if not state.presence or not state.player_lookup:
        return None
    occupants = await _ordered_players_in_room(state, state.player.gamloc)
    for occupant_id in occupants:
        candidate = state.player_lookup(occupant_id)
        # Legacy findgp() only returns attnam matches that pass ckinvs() visibility checks.
        # (legacy/KYRUTIL.C:472-478)
        if (
            candidate
            and _matches_player_name(target_name, candidate)
            and _can_see_player(state.player, candidate)
        ):
            return candidate
    return None


def _message_event(
    scope: str,
    message_id: str | None,
    text: str | None,
    command_id: int | None,
    *,
    exclude_player: str | None = None,
    exclude_players: list[str] | None = None,
) -> dict:
    event = {
        "scope": scope,
        "event": "room_message",
        "type": "room_message",
        "text": text,
        "message_id": message_id,
        "command_id": command_id,
    }
    if exclude_player:
        event["exclude_player"] = exclude_player
    if exclude_players:
        event["exclude_players"] = list(dict.fromkeys(exclude_players))
    return event


def _sndbt2_excluded_players(
    state: GameState, target_player: models.PlayerModel
) -> list[str]:
    return [state.player.plyrid, target_player.plyrid]


def _give_actor_prefix(state: GameState, verb: str) -> str:
    """Mirror gmsgutl() actor preface used before giveru target text."""
    # Legacy gmsgutl() concatenates GMSGUTL1 + (GMSGUTL2|GMSGUTL3) before GIVERU10.
    # (legacy/KYRCMDS.C:612-629)
    prefix = _format_message(state, "GMSGUTL1", state.player.altnam)
    if verb == "give":
        return f"{prefix}{_format_message(state, 'GMSGUTL2')}"
    return f"{prefix}{_format_message(state, 'GMSGUTL3', verb)}"


def _give_prefixed_message(
    state: GameState, verb: str, message_id: str, *args: object
) -> str:
    body = _format_message(state, message_id, *args) or ""
    return f"{_give_actor_prefix(state, verb)}{body}"


def _sndutl_text(player: models.PlayerModel, template: str) -> str:
    """Format a sndutl-style broadcast line for the room."""
    # Legacy sndutl formats "*** <altnam> is <template % hisher>" for room broadcasts.
    # (legacy/KYRUTIL.C:119-138)
    if "%s" in template:
        template = template % _hisher(player)
    return f"*** {player.altnam} is {template}"


def _legacy_unknown_command_result(
    state: GameState, verb: str, args: dict
) -> CommandResult:
    command_id = args.get("command_id")
    raw = str(args.get("fallback_raw") or args.get("raw") or "").strip()
    phrase = " ".join(part for part in (verb, raw) if part).strip()
    phrase_parts = phrase.split()
    argc = len(phrase_parts)
    first_word = phrase_parts[0].lower() if phrase_parts else verb.lower()
    # Legacy kyra() checks "i..." and "because" before the argc-based
    # KYRA5-KYRA9 replies, then broadcasts sndutl("mumbling under %s breath.").
    # Source: legacy/KYRCMDS.C:1259-1303.
    if first_word.startswith("i"):
        message_id = "KYRA2"
        text = _format_message(state, message_id)
    elif first_word == "because":
        message_id = "KYRA3"
        text = _format_message(state, message_id)
    elif argc == 1:
        message_id = "KYRA5"
        text = _format_message(state, message_id, phrase)
    elif argc == 2:
        message_id = "KYRA6"
        text = _format_message(state, message_id, phrase)
    elif argc == 3:
        message_id = "KYRA7"
        text = _format_message(state, message_id, phrase)
    elif argc == 4:
        message_id = "KYRA8"
        text = _format_message(state, message_id, phrase)
    else:
        message_id = "KYRA9"
        text = _format_message(state, message_id)

    return CommandResult(
        state=state,
        events=[
            _message_event("player", message_id, text, command_id),
            _message_event(
                "room",
                None,
                _sndutl_text(state.player, "mumbling under %s breath."),
                command_id,
                exclude_player=state.player.plyrid,
            ),
        ],
    )


def _player_and_room_message_events(
    state: GameState,
    command_id: int | None,
    message_id: str | None,
    text: str | None,
    *,
    room_template: str | None = None,
) -> list[dict]:
    events = [_message_event("player", message_id, text, command_id)]
    if room_template:
        events.append(
            _message_event(
                "room",
                None,
                _sndutl_text(state.player, room_template),
                command_id,
                exclude_player=state.player.plyrid,
            )
        )
    return events


def _msgutl2_events(
    state: GameState,
    command_id: int | None,
    actor_message_id: str,
    room_message_id: str,
    *actor_args: object,
) -> list[dict]:
    """Build legacy msgutl2 actor+room fan-out."""
    # Legacy msgutl2() sends yourmsg to usrnum and othmsg(altnam) to sndoth()
    # (legacy/KYRSPEL.C:389-396).
    return [
        _message_event(
            "player",
            actor_message_id,
            _format_message(state, actor_message_id, *actor_args),
            command_id,
        ),
        _message_event(
            "room",
            room_message_id,
            _format_message(state, room_message_id, state.player.altnam),
            command_id,
            exclude_player=state.player.plyrid,
        ),
    ]


def _find_location_object(
    state: GameState, target: str
) -> tuple[int, models.GameObjectModel] | tuple[None, None]:
    location = state.locations[state.player.gamloc]
    objects = state.objects or {}
    object_id = _find_object_in_location(location, objects, target)
    if object_id is None:
        return None, None
    obj = objects.get(object_id)
    if obj is None:
        return None, None
    return object_id, obj


async def _handle_kiss_mode(state: GameState, args: dict, mode: int) -> CommandResult:
    command_id = args.get("command_id")
    verb = str(args.get("verb") or "").lower()
    target_name = (args.get("raw") or "").strip().lower()
    objects = state.objects or {}

    # Ported from kisutl() target branching in legacy/KYRCMDS.C:390-466.
    if not target_name:
        return CommandResult(
            state=state,
            events=_player_and_room_message_events(
                state,
                command_id,
                "KISUTL1",
                _format_message(state, "KISUTL1", _upperc(verb)),
                room_template="making strange motions.",
            ),
        )

    inventory_index = _find_inventory_index(state.player, target_name, objects)
    if inventory_index is not None:
        obj = objects[state.player.gpobjs[inventory_index]]
        actor_text = _format_message(state, "KISUTL2", verb, _object_with_article(obj))
        room_prefix = _format_message(state, "KISUTL3", state.player.altnam) or ""
        if mode:
            room_body = _format_message(state, "KISUTL4", _hisher(state.player), obj.name, verb)
            room_id = "KISUTL4"
        else:
            room_body = _format_message(state, "KISUTL5", verb, _hisher(state.player), obj.name)
            room_id = "KISUTL5"
        return CommandResult(
            state=state,
            events=[
                _message_event("player", "KISUTL2", actor_text, command_id),
                _message_event(
                    "room",
                    room_id,
                    f"{room_prefix}{room_body or ''}",
                    command_id,
                    exclude_player=state.player.plyrid,
                ),
            ],
        )

    _, location_obj = _find_location_object(state, target_name)
    if location_obj is not None:
        if location_obj.name.lower() == "dryad" and mode:
            return CommandResult(
                state=state,
                events=[
                    _message_event(
                        "player",
                        "UKISSD",
                        _format_message(state, "UKISSD", verb),
                        command_id,
                    ),
                    _message_event(
                        "room",
                        "OKISSD",
                        _format_message(
                            state,
                            "OKISSD",
                            state.player.altnam,
                            verb,
                            _himher(state.player),
                            verb,
                        ),
                        command_id,
                        exclude_player=state.player.plyrid,
                    ),
                ],
            )

        actor_text = _format_message(
            state, "KISUTL6", verb, _object_with_article(location_obj)
        )
        room_prefix = _format_message(state, "KISUTL7", state.player.altnam) or ""
        location = state.locations[state.player.gamloc]
        if mode:
            room_body = _format_message(
                state, "KISUTL8", location_obj.name, location.objlds, verb
            )
            room_id = "KISUTL8"
        else:
            room_body = _format_message(
                state, "KISUTL9", verb, location_obj.name, location.objlds
            )
            room_id = "KISUTL9"
        return CommandResult(
            state=state,
            events=[
                _message_event("player", "KISUTL6", actor_text, command_id),
                _message_event(
                    "room",
                    room_id,
                    f"{room_prefix}{room_body or ''}",
                    command_id,
                    exclude_player=state.player.plyrid,
                ),
            ],
        )

    target_player = await _find_player_in_room(state, target_name)
    if target_player:
        if mode:
            if target_player.plyrid == state.player.spouse and verb == "kiss":
                return CommandResult(
                    state=state,
                    events=[
                        _message_event(
                            "player",
                            "SKISSR",
                            _format_message(
                                state, "SKISSR", target_player.plyrid, _himher(target_player)
                            ),
                            command_id,
                        ),
                        {
                            **_message_event(
                                "target",
                                "SKISSU",
                                _format_message(
                                    state,
                                    "SKISSU",
                                    state.player.altnam,
                                    _hisher(state.player),
                                ),
                                command_id,
                            ),
                            "player": target_player.plyrid,
                        },
                        _message_event(
                            "room",
                            "SKISSO",
                            _format_message(
                                state,
                                "SKISSO",
                                state.player.altnam,
                                target_player.altnam,
                                _hisher(state.player),
                                _himher(target_player),
                            ),
                            command_id,
                            exclude_player=target_player.plyrid,
                            exclude_players=_sndbt2_excluded_players(state, target_player),
                        ),
                    ],
                )
            return CommandResult(
                state=state,
                events=[
                    _message_event("player", "DONE", _format_message(state, "DONE"), command_id),
                    {
                        **_message_event(
                            "target",
                            "KISUTL10",
                            _format_message(state, "KISUTL10", state.player.altnam, verb),
                            command_id,
                        ),
                        "player": target_player.plyrid,
                    },
                    _message_event(
                        "room",
                        "KISUTL11",
                        _format_message(
                            state, "KISUTL11", state.player.altnam, target_player.altnam, verb
                        ),
                        command_id,
                        exclude_player=target_player.plyrid,
                        exclude_players=_sndbt2_excluded_players(state, target_player),
                    ),
                ],
            )

        return CommandResult(
            state=state,
            events=[
                _message_event("player", "BEST", _format_message(state, "BEST"), command_id),
                {
                    **_message_event(
                        "target",
                        "KISUTL12",
                        _format_message(
                            state, "KISUTL12", state.player.altnam, _hisher(state.player), verb
                        ),
                        command_id,
                    ),
                    "player": target_player.plyrid,
                },
                _message_event(
                    "room",
                    "KISUTL13",
                    _format_message(
                        state,
                        "KISUTL13",
                        state.player.altnam,
                        _hisher(state.player),
                        verb,
                        target_player.altnam,
                    ),
                    command_id,
                    exclude_player=target_player.plyrid,
                    exclude_players=_sndbt2_excluded_players(state, target_player),
                ),
            ],
        )

    return CommandResult(
        state=state,
        events=_player_and_room_message_events(
            state,
            command_id,
            "KISUTL14",
            _format_message(state, "KISUTL14"),
            room_template="seeing things!",
        ),
    )


async def _handle_kissr1(state: GameState, args: dict) -> CommandResult:
    return await _handle_kiss_mode(state, args, 0)


async def _handle_kissr2(state: GameState, args: dict) -> CommandResult:
    return await _handle_kiss_mode(state, args, 1)


async def _handle_think(state: GameState, args: dict) -> CommandResult:
    command_id = args.get("command_id")
    raw = (args.get("raw") or "").strip()
    tokens = raw.split(maxsplit=1)
    objects = state.objects or {}

    # Ported from thinkr() in legacy/KYROBJR.C:91-119.
    if len(tokens) == 2 and _find_inventory_index(state.player, "amulet", objects) is not None:
        target = _find_player_globally_by_true_id(state, tokens[0])
        if target:
            return CommandResult(
                state=state,
                events=[
                    _message_event(
                        "player",
                        "OBJM02",
                        _format_message(state, "OBJM02"),
                        command_id,
                    ),
                    {
                        **_message_event(
                            "target",
                            None,
                            f"A voice in your mind says: {_unquote_text(tokens[1])}",
                            command_id,
                        ),
                        "player": target.plyrid,
                        "room_id": target.gamloc,
                    },
                ],
            )

    if not raw:
        return CommandResult(
            state=state,
            events=_player_and_room_message_events(
                state,
                command_id,
                "OBJM03",
                _format_message(state, "OBJM03"),
                room_template="thinking about life.",
            ),
        )

    item_name = tokens[0].lower()
    inventory_index = _find_inventory_index(state.player, item_name, objects)
    if inventory_index is None:
        return CommandResult(
            state=state,
            events=_player_and_room_message_events(
                state,
                command_id,
                "OBJM09",
                _format_message(state, "OBJM09"),
                room_template="having wild dreams.",
            ),
        )

    object_id = state.player.gpobjs[inventory_index]
    obj = objects.get(object_id)
    if obj is None or "THIABL" not in obj.flags:
        return CommandResult(
            state=state,
            events=_player_and_room_message_events(
                state,
                command_id,
                "OBJM04",
                _format_message(state, "OBJM04"),
                room_template="thinking of %s possesions.",
            ),
        )

    try:
        effect = _build_object_engine(state).use_object(
            player_id=state.player.plyrid,
            object_id=object_id,
            room_id=state.player.gamloc,
            action="think",
            player=state.player,
        )
    except EffectError:
        return CommandResult(
            state=state,
            events=_player_and_room_message_events(
                state,
                command_id,
                "OBJM04",
                _format_message(state, "OBJM04"),
                room_template="thinking of %s possesions.",
            ),
        )
    return CommandResult(
        state=state,
        events=[_message_event("player", effect.message_id, effect.text, command_id)],
    )


def _flight_events(
    state: GameState,
    command_id: int | None,
    *,
    destination: int,
    player_message_id: str,
    departure_text: str,
    arrival_text: str,
) -> list[dict]:
    from_room = state.player.gamloc
    state.player.pgploc = from_room
    state.player.gamloc = destination
    # Ported from willof()/pegasf() remvgp+entrgp flow in legacy/KYRCMDS.C:953-969.
    events = [
        _message_event(
            "player",
            player_message_id,
            _format_message(state, player_message_id),
            command_id,
        ),
        {
            "scope": "nearby_room",
            "room_id": from_room,
            "event": "room_message",
            "type": "room_message",
            "player": state.player.plyrid,
            "from": from_room,
            "to": destination,
            "text": f"*** {state.player.altnam} has just {departure_text}!",
            "message_id": None,
            "command_id": command_id,
            "exclude_player": state.player.plyrid,
        },
    ]
    events.extend(
        _build_room_transition_events(
            state,
            from_room=from_room,
            to_room=destination,
            command_id=command_id,
            message_id=_command_message_id(command_id),
            direction=None,
            arrival_text=f"*** {state.player.altnam} has just {arrival_text}!",
        )
    )
    _persist_player_state(state, state.player)
    return events


def _handle_fly(state: GameState, args: dict) -> CommandResult:
    command_id = args.get("command_id")
    flags = constants.PlayerFlag(state.player.flags)
    # Ported from flyrou() in legacy/KYRCMDS.C:919-950.
    if flags & constants.PlayerFlag.WILLOW:
        if state.player.gamloc == 179:
            events = _flight_events(
                state,
                command_id,
                destination=180,
                player_message_id="WILFLY",
                departure_text="gracefully flown across the chasm",
                arrival_text="gracefully flown from across the chasm",
            )
            return CommandResult(state=state, events=events)
        if state.player.gamloc == 180:
            events = _flight_events(
                state,
                command_id,
                destination=179,
                player_message_id="WILFLY",
                departure_text="gracefully flown across the chasm",
                arrival_text="gracefully flown from across the chasm",
            )
            return CommandResult(state=state, events=events)
        return CommandResult(state=state, events=_msgutl2_events(state, command_id, "UNOFLY", "ATFLY1"))

    if flags & constants.PlayerFlag.PEGASU:
        if state.player.gamloc == 22:
            events = _flight_events(
                state,
                command_id,
                destination=189,
                player_message_id="PEGFLY",
                departure_text="majestically flown across the sea",
                arrival_text="majestically flown from across the sea",
            )
            return CommandResult(state=state, events=events)
        if state.player.gamloc == 189:
            events = _flight_events(
                state,
                command_id,
                destination=22,
                player_message_id="PEGFLY",
                departure_text="majestically flown across the sea",
                arrival_text="majestically flown from across the sea",
            )
            return CommandResult(state=state, events=events)
        return CommandResult(state=state, events=_msgutl2_events(state, command_id, "UNOFLY", "ATFLY1"))

    if flags & constants.PlayerFlag.PDRAGN:
        return CommandResult(state=state, events=_msgutl2_events(state, command_id, "UNOFLY", "ATFLY1"))
    return CommandResult(state=state, events=_msgutl2_events(state, command_id, "HUNFLY", "ATFLY1"))


async def _set_presence_location_for_player(
    state: GameState, player_id: str, room_id: int
) -> None:
    presence = state.presence
    if presence is None:
        return
    set_location = getattr(presence, "set_location", None)
    if set_location is None:
        return
    sessions_for_player = getattr(presence, "sessions_for_player", None)
    if sessions_for_player is None:
        await set_location(player_id, room_id)
        return
    for token in await sessions_for_player(player_id):
        await set_location(player_id, room_id, token)


def _target_location_events(
    state: GameState,
    target: models.PlayerModel,
    command_id: int | None,
) -> list[dict]:
    return _location_refresh_events(state, target, command_id, scope="target")


def _location_refresh_events(
    state: GameState,
    player: models.PlayerModel,
    command_id: int | None,
    *,
    scope: str,
    death_reset: bool = False,
    metadata: dict[str, Any] | None = None,
) -> list[dict]:
    destination = state.locations[player.gamloc]
    description_id, long_description = _location_description(
        state, destination, player=player
    )
    location_update = {
        "scope": scope,
        "event": "location_update",
        "type": "location_update",
        "location": destination.id,
        "description": destination.brfdes,
        "description_id": description_id,
        "long_description": long_description,
        "command_id": command_id,
        "message_id": _command_message_id(command_id),
    }
    description_event = {
        "scope": scope,
        "event": "location_description",
        "type": "location_description",
        "location": destination.id,
        "message_id": description_id,
        "text": long_description or destination.brfdes,
        "objects": room_object_entries(destination, state.objects or {}),
    }
    objects_event = {
        **_room_objects_event(
            destination,
            state.objects or {},
            command_id,
            _command_message_id(command_id),
        ),
        "scope": scope,
    }
    if death_reset:
        location_update["death_reset"] = True
        description_event["death_reset"] = True
        objects_event["death_reset"] = True
    if metadata:
        location_update.update(metadata)
        description_event.update(metadata)
        objects_event.update(metadata)
    if scope == "target":
        location_update.update({"player": player.plyrid, "room_id": destination.id})
        description_event.update({"player": player.plyrid, "room_id": destination.id})
        objects_event.update({"player": player.plyrid, "room_id": destination.id})
    return [location_update, description_event, objects_event]


def _append_hitoth_death_events(
    state: GameState,
    dead_player: models.PlayerModel,
    command_id: int | None,
    events: list[dict],
) -> None:
    if state.honor_mode_policy.modern_feature_enabled(
        dead_player, modern_features.MODERN_DEATH_RECOVERY
    ):
        # modern_death_recovery: non-honor deaths use the documented recovery
        # contract instead of legacy initgp(). See docs/MODERN_FEATURES.md.
        plan = build_modern_death_recovery_plan(
            dead_player,
            locations=state.locations,
            rng=state.rng,
        )
        _persist_death_recovery_plan(state, dead_player, plan)
        apply_death_recovery_plan(dead_player, state.locations, plan)
        if dead_player.plyrid == state.player.plyrid:
            for event in events:
                if event.get("scope") == "room":
                    event["scope"] = "nearby_room"
                    event.setdefault("room_id", plan.old_room)
        _append_modern_death_recovery_events(state, dead_player, command_id, events, plan)
        return

    # Legacy hitoth() sends the death text, runs initgp(), tells the old room,
    # and re-enters room 0 in holy light. (legacy/KYRSPEL.C:303-321)
    reset = reset_player_after_death(dead_player, state.rng.randrange)
    _persist_player_state(state, dead_player)
    if dead_player.plyrid == state.player.plyrid:
        for event in events:
            if event.get("scope") == "room":
                event["scope"] = "nearby_room"
                event.setdefault("room_id", reset.old_room)

    death_event = _message_event(
        "target",
        "DIEMSG",
        _format_message(state, "DIEMSG"),
        command_id,
    )
    death_event.update(
        {
            "player": dead_player.plyrid,
            "room_id": reset.old_room,
            "death_reset": True,
        }
    )
    events.append(death_event)

    events.append(
        {
            "scope": "nearby_room",
            "room_id": reset.old_room,
            "event": "room_message",
            "type": "room_message",
            "player": dead_player.plyrid,
            "text": _format_message(state, "KILLED", reset.old_name),
            "message_id": "KILLED",
            "command_id": command_id,
            "exclude_player": dead_player.plyrid,
        },
    )
    events.extend(
        _location_refresh_events(
            state, dead_player, command_id, scope="target", death_reset=True
        )
    )
    events.append(
        {
            "scope": "nearby_room",
            "room_id": constants.WILLOW_ROOM_ID,
            "event": "room_message",
            "type": "room_message",
            "player": dead_player.plyrid,
            "text": f"*** {dead_player.plyrid} has just appeared in a holy light!",
            "message_id": None,
            "command_id": command_id,
            "exclude_player": dead_player.plyrid,
        },
    )


def _append_modern_death_recovery_events(
    state: GameState,
    dead_player: models.PlayerModel,
    command_id: int | None,
    events: list[dict],
    plan: DeathRecoveryPlan,
) -> None:
    """Append command events after modern_death_recovery persistence succeeds."""

    target_metadata = _modern_death_event_metadata(plan, recipient_scope="target")
    death_event = _message_event(
        "target",
        "DIEMSG",
        _format_message(state, "DIEMSG"),
        command_id,
    )
    death_event.update(
        {
            "player": dead_player.plyrid,
            "room_id": plan.old_room,
            **target_metadata,
        }
    )
    events.append(death_event)

    nearby_metadata = _modern_death_event_metadata(
        plan, recipient_scope="nearby_room"
    )
    events.append(
        {
            "scope": "nearby_room",
            "room_id": plan.old_room,
            "event": "room_message",
            "type": "room_message",
            "player": dead_player.plyrid,
            "text": _format_message(state, "KILLED", plan.old_name),
            "message_id": "KILLED",
            "command_id": command_id,
            "exclude_player": dead_player.plyrid,
            **nearby_metadata,
        },
    )

    events.extend(
        _location_refresh_events(
            state,
            dead_player,
            command_id,
            scope="target",
            death_reset=True,
            metadata=target_metadata,
        )
    )
    events.append(
        {
            "scope": "nearby_room",
            "room_id": constants.WILLOW_ROOM_ID,
            "event": "room_message",
            "type": "room_message",
            "player": dead_player.plyrid,
            "text": f"*** {dead_player.plyrid} has just appeared in a holy light!",
            "message_id": None,
            "command_id": command_id,
            "exclude_player": dead_player.plyrid,
            **nearby_metadata,
        },
    )
    _append_modern_death_drop_events(state, dead_player, command_id, events, plan)


def _append_modern_death_drop_events(
    state: GameState,
    dead_player: models.PlayerModel,
    command_id: int | None,
    events: list[dict],
    plan: DeathRecoveryPlan,
) -> None:
    """Broadcast modern_death_recovery inventory drops room by room."""

    metadata = _modern_death_event_metadata(plan, recipient_scope="room")
    for room_update in plan.room_object_updates:
        location = state.locations.get(room_update.room_id)
        if location is None:
            continue
        objects_event = _room_objects_event(
            location,
            state.objects or {},
            command_id,
            "room_objects",
            scope="room",
            include_sender=True,
        )
        objects_event.update({"room_id": room_update.room_id, **metadata})
        events.append(objects_event)
        for object_id in room_update.dropped_items:
            obj = state.objects.get(object_id) if state.objects else None
            events.append(
                {
                    "scope": "room",
                    "room_id": room_update.room_id,
                    "event": "room_message",
                    "type": "room_message",
                    "player": plan.player_id,
                    "text": _format_message(
                        state,
                        "DROPIT3",
                        plan.old_name,
                        _hisher(dead_player),
                        obj.name if obj else str(object_id),
                    ),
                    "message_id": "DROPIT3",
                    "command_id": command_id,
                    "include_sender": True,
                    "object_id": object_id,
                    **metadata,
                }
            )


def _modern_death_event_metadata(
    plan: DeathRecoveryPlan,
    *,
    recipient_scope: str,
) -> dict[str, Any]:
    metadata = dict(plan.metadata)
    metadata["refresh_location"] = constants.WILLOW_ROOM_ID
    metadata["recipient_scope"] = recipient_scope
    return metadata


async def _handle_shove(state: GameState, args: dict) -> CommandResult:
    command_id = args.get("command_id")
    raw = (args.get("raw") or "").strip()
    tokens = raw.split()
    # Ported from shover()/gi_shvutl() in legacy/KYRCMDS.C:800-856.
    if len(tokens) == 1:
        return await _handle_kiss_mode(state, {**args, "raw": tokens[0]}, 1)
    if len(tokens) != 2:
        return CommandResult(
            state=state,
            events=_player_and_room_message_events(
                state,
                command_id,
                "SHOVER3",
                _format_message(state, "SHOVER3"),
                room_template="having a medical emergency!",
            ),
        )

    target_name, direction = tokens[0], tokens[1].lower()
    target = await _find_player_in_room(state, target_name)
    if target is None:
        return CommandResult(
            state=state,
            events=_player_and_room_message_events(
                state,
                command_id,
                "SHOVER2",
                _format_message(state, "SHOVER2", target_name),
                room_template="seeing things.",
            ),
        )

    field = _DIRECTION_FIELDS.get(direction)
    current = state.locations[state.player.gamloc]
    destination = getattr(current, field) if field else -1
    if destination == -1 or destination not in state.locations:
        return CommandResult(
            state=state,
            events=_player_and_room_message_events(
                state,
                command_id,
                "SHOVER1",
                _format_message(state, "SHOVER1", direction),
                room_template="having hallucinations.",
            ),
        )

    from_room = target.gamloc
    from_direction = {
        "north": "south",
        "south": "north",
        "east": "west",
        "west": "east",
    }[direction]
    target.pgploc = from_room
    target.gamloc = destination
    await _set_presence_location_for_player(state, target.plyrid, destination)
    _persist_player_state(state, target)

    events: list[dict] = [
        _message_event(
            "player",
            "SHVUTL1",
            _format_message(state, "SHVUTL1", target.plyrid),
            command_id,
        ),
        _message_event(
            "room",
            None,
            f"*** {target.altnam} has just been shoved {direction} by {state.player.altnam}!",
            command_id,
            exclude_player=target.plyrid,
            exclude_players=_sndbt2_excluded_players(state, target),
        ),
        {
            **_message_event(
                "target",
                "SHVUTL2",
                _format_message(state, "SHVUTL2", state.player.altnam, direction),
                command_id,
            ),
            "player": target.plyrid,
            "room_id": destination,
        },
    ]
    events.extend(_target_location_events(state, target, command_id))
    events.append(
        {
            "scope": "nearby_room",
            "room_id": destination,
            "event": "player_enter",
            "type": "player_moved",
            "player": target.plyrid,
            "from": from_room,
            "to": destination,
            "description": state.locations[destination].brfdes,
            "command_id": command_id,
            "message_id": _command_message_id(command_id),
            "exclude_player": target.plyrid,
        }
    )
    events.append(
        {
            "scope": "nearby_room",
            "room_id": destination,
            "event": "room_message",
            "type": "room_message",
            "player": target.plyrid,
            "from": from_room,
            "to": destination,
            "text": f"*** {target.altnam} has just been shoved from the {from_direction}!",
            "message_id": None,
            "command_id": command_id,
            "exclude_player": target.plyrid,
        }
    )
    return CommandResult(state=state, events=events)


def _handle_simple_emote(state: GameState, args: dict) -> CommandResult:
    command_id = args.get("command_id")
    verb = str(args.get("verb") or "").lower()
    raw = (args.get("raw") or "").strip()
    you, them, speak = SIMPLE_EMOTES[verb]
    # Ported from cmpsmp()/smputl() in legacy/KYRCMDS.C:1332-1351.
    if speak and raw:
        return _handle_say(state, {**args, "text": raw, "verb": verb})
    them_text = them % _hisher(state.player) if "%s" in them else them
    return CommandResult(
        state=state,
        events=[
            _message_event(
                "player",
                "SMPUTL1",
                _format_message(state, "SMPUTL1", you),
                command_id,
            ),
            _message_event(
                "room",
                "SMPUTL2",
                _format_message(state, "SMPUTL2", state.player.altnam, them_text),
                command_id,
                exclude_player=state.player.plyrid,
            ),
        ],
    )


def _zar_animation_events_to_command_events(
    state: GameState,
    animation_events: list[AnimationTickEvent],
    command_id: int | None,
) -> list[dict]:
    events: list[dict] = []
    for animation_event in animation_events:
        payload = dict(animation_event.payload)
        target_only = bool(payload.pop("target_only", False))
        target_player = payload.pop("target_player", None)
        target_message_id = payload.pop("target_message_id", None)
        target_text = payload.pop("target_text", None)
        exclude_player = payload.pop("exclude_player", None)

        if target_only:
            event = _message_event(
                "target",
                target_message_id,
                target_text,
                command_id,
            )
            if target_player:
                event["player"] = target_player
            event["animation_flag"] = animation_event.flag
            event.update(payload)
            events.append(event)
            continue

        text = animation_event.message_text or _format_message(
            state, animation_event.message_id
        )
        scope = (
            "room"
            if animation_event.room_id == state.player.gamloc
            else "nearby_room"
        )
        event = _message_event(
            scope,
            animation_event.message_id,
            text,
            command_id,
            exclude_player=exclude_player if isinstance(exclude_player, str) else None,
        )
        event["animation_flag"] = animation_event.flag
        if scope == "nearby_room":
            event["room_id"] = animation_event.room_id
        event.update(payload)
        events.append(event)
    return events


def _handle_dragonstaff_rub(
    state: GameState,
    command_id: int | None,
    inventory_index: int,
) -> CommandResult:
    # Legacy zaritm() is reached from dragonstaff's rub routine and consumes
    # the staff before summoning/attacking with Zar. (legacy/KYRANIM.C:176-198)
    controller = state.zar_controller
    zar_state = state.zar_state
    if controller is None or zar_state is None:
        return CommandResult(state=state, events=[])

    pop_inventory_index(state.player, inventory_index)
    _persist_player_state(state, state.player)

    events = [
        _message_event(
            "room",
            None,
            _sndutl_text(state.player, "rubbing %s dragonstaff!"),
            command_id,
            exclude_player=state.player.plyrid,
        )
    ]

    if getattr(zar_state, "zar_location") == state.player.gamloc:
        events.append(
            _message_event(
                "player",
                "ZMSG12",
                _format_message(state, "ZMSG12"),
                command_id,
            )
        )
        events.append(
            _message_event(
                "player",
                "ZMSG14",
                _format_message(state, "ZMSG14"),
                command_id,
            )
        )
        _, attack_events = controller.zarfood(zar_state)
        events.extend(
            _zar_animation_events_to_command_events(state, attack_events, command_id)
        )
        return CommandResult(state=state, events=events)

    events.append(
        _message_event(
            "player",
            "ZMSG13",
            _format_message(state, "ZMSG13"),
            command_id,
        )
    )
    movement_events = [
        *controller.remove_zar(zar_state, "ZMSG10"),
        *controller.place_zar(zar_state, state.player.gamloc, "ZMSG11"),
    ]
    events.extend(
        _zar_animation_events_to_command_events(state, movement_events, command_id)
    )
    events.append(
        _message_event(
            "player",
            "ZMSG14",
            _format_message(state, "ZMSG14"),
            command_id,
        )
    )
    if controller.should_attack_after_staff():
        _, attack_events = controller.zarfood(zar_state)
        events.extend(
            _zar_animation_events_to_command_events(state, attack_events, command_id)
        )
    return CommandResult(state=state, events=events)



def _find_spell_by_name(raw_name: str, spells_catalog: list[models.SpellModel]) -> models.SpellModel | None:
    target = raw_name.strip().lower()
    if not target:
        return None
    for spell in spells_catalog:
        if spell.name.lower() == target:
            return spell
    return None


def _legacy_memorized_spells_text(memorized_names: list[str]) -> str:
    # Ported from shwsutl in legacy/KYRSPEL.C (lines 1372-1387):
    # 0=no spells, 1="x", 2="x" and "y", n=comma list with final and.
    count = len(memorized_names)
    if count == 0:
        return "no spells"
    if count == 1:
        return f'"{memorized_names[0]}"'
    if count == 2:
        return f'"{memorized_names[0]}" and "{memorized_names[1]}"'
    leading = ", ".join(f'"{name}"' for name in memorized_names[:-1])
    return f"{leading}, and \"{memorized_names[-1]}\""


def _handle_spells(state: GameState, args: dict) -> CommandResult:
    command_id = args.get("command_id")
    spells_catalog = fixtures.load_spells()
    spells_by_id = {spell.id: spell for spell in spells_catalog}
    memorized_spell_ids = list(state.player.spells[: state.player.nspells])
    memorized_spell_names = [
        spells_by_id[spell_id].name if spell_id in spells_by_id else str(spell_id)
        for spell_id in memorized_spell_ids
    ]
    memorized_text = _legacy_memorized_spells_text(memorized_spell_names)
    title = legacy_title_for_level(state.player.level)
    text = (
        f"{memorized_text} memorized, and {state.player.spts} spell points of energy.  "
        f"You are at level {state.player.level}, titled \"{title}\"."
    )

    return CommandResult(
        state=state,
        events=[
            {
                **_message_event("player", None, text, command_id),
                "memorized_spell_ids": memorized_spell_ids,
                "memorized_spell_names": memorized_spell_names,
                "spts": state.player.spts,
                "level": state.player.level,
                "title": title,
            }
        ],
    )


def _handle_memorize(state: GameState, args: dict) -> CommandResult:
    command_id = args.get("command_id")
    raw_target = (args.get("raw") or args.get("target") or "").strip()
    spells_catalog = fixtures.load_spells()
    # Ported from memori in legacy/KYRSPEL.C (lines 1448-1486): resolve spell name,
    # verify spellbook ownership bits, or emit KSPM09 on failure.
    spell = _find_spell_by_name(raw_target, spells_catalog)
    if spell is None or not has_spell_in_book(state.player, spell):
        return CommandResult(
            state=state,
            events=[
                _message_event(
                    "player",
                    "KSPM09",
                    _format_message(state, "KSPM09"),
                    command_id,
                )
            ],
        )

    at_capacity = state.player.nspells >= constants.MAXSPL and bool(state.player.spells)
    evicted_spell_name: str | None = None
    if at_capacity:
        evicted_spell_id = state.player.spells[constants.MAXSPL - 1]
        by_id = {entry.id: entry for entry in spells_catalog}
        evicted = by_id.get(evicted_spell_id)
        evicted_spell_name = evicted.name if evicted else str(evicted_spell_id)

    # Ported from memutl in legacy/KYRSPEL.C (lines 1491-1504): MAXSPL overflow
    # drops the last memorized slot before appending the newly memorized spell.
    memorize_spell(state.player, spell)
    _persist_player_state(state, state.player)

    actor_message_id = "LOSSPL" if at_capacity else "GAISPL"
    actor_text = (
        _format_message(state, actor_message_id, spell.name, evicted_spell_name)
        if at_capacity
        else _format_message(state, actor_message_id, spell.name)
    )

    return CommandResult(
        state=state,
        events=[
            _message_event("player", actor_message_id, actor_text, command_id),
            _message_event(
                "room",
                "MEMSPL",
                _format_message(state, "MEMSPL", state.player.altnam, _hisher(state.player)),
                command_id,
                exclude_player=state.player.plyrid,
            ),
        ],
    )


async def _handle_cast(state: GameState, args: dict) -> CommandResult:
    command_id = args.get("command_id")
    raw_target = (args.get("raw") or args.get("target") or "").strip()
    # Legacy caster(): arg checks, memorized gating, level/spts gates, rmvspl + spts decrement,
    # then splrou execution (legacy/KYRSPEL.C:1512-1533).
    if not raw_target:
        return CommandResult(
            state=state,
            events=[
                _message_event(
                    "player",
                    "OBJM07",
                    _format_message(state, "OBJM07"),
                    command_id,
                )
            ],
        )

    tokens = raw_target.split(maxsplit=1)
    spell_name = tokens[0]
    target = tokens[1].strip() if len(tokens) > 1 else None

    spells_catalog = fixtures.load_spells()
    spell = _find_spell_by_name(spell_name, spells_catalog)
    if spell is None or spell.id not in state.player.spells:
        return CommandResult(
            state=state,
            events=[
                _message_event(
                    "player",
                    "NOTMEM",
                    _format_message(state, "NOTMEM"),
                    command_id,
                ),
                _message_event(
                    "room",
                    "SPFAIL",
                    _format_message(state, "SPFAIL", state.player.altnam),
                    command_id,
                    exclude_player=state.player.plyrid,
                ),
            ],
        )

    if spell.level > state.player.level:
        return CommandResult(
            state=state,
            events=[
                _message_event(
                    "player",
                    "KSPM10",
                    _format_message(state, "KSPM10"),
                    command_id,
                ),
                _message_event(
                    "room",
                    None,
                    _sndutl_text(state.player, "mouthing off."),
                    command_id,
                    exclude_player=state.player.plyrid,
                ),
            ],
        )

    if spell.level > state.player.spts:
        return CommandResult(
            state=state,
            events=[
                _message_event(
                    "player",
                    "KSPM10",
                    _format_message(state, "KSPM10"),
                    command_id,
                ),
                _message_event(
                    "room",
                    None,
                    _sndutl_text(state.player, "waving %s arms."),
                    command_id,
                    exclude_player=state.player.plyrid,
                ),
            ],
        )

    # Legacy rmvspl: remove spell from memorized list before effect execution.
    # (legacy/KYRSPEL.C:1529-1532)
    forget_memorized_spell(state.player, spell.id)
    state.player.spts -= spell.level
    _persist_player_state(state, state.player)

    messages = state.messages or fixtures.load_messages()
    effect_engine = SpellEffectEngine(
        spells=spells_catalog,
        messages=messages,
        rng=state.rng,
        objects=state.objects.values() if state.objects else None,
        locations=state.locations.values(),
    )
    effect = effect_engine.effects.get(spell.id)

    if effect and effect.requires_target and not target:
        # Legacy chkstf() reports missing targets for player-directed spells
        # (legacy/KYRSPEL.C:266-295).
        return CommandResult(
            state=state,
            events=[
                _message_event(
                    "player",
                    None,
                    "...Something is missing and the spell fails!",
                    command_id,
                ),
                _message_event(
                    "room",
                    None,
                    _sndutl_text(state.player, "trying to cast a spell, without success."),
                    command_id,
                    exclude_player=state.player.plyrid,
                ),
            ],
        )

    target_player = None
    requires_target_player = False
    if effect:
        requires_target_player = (
            effect.requires_target
            if effect.requires_target_player is None
            else effect.requires_target_player
        )
    if effect and requires_target_player and target:
        if effect.global_target_player:
            target_player = _find_player_globally_by_true_id(state, target)
        else:
            target_player = await _find_player_by_name(state, target)
        if not target_player and not effect.allow_missing_target_player:
            return CommandResult(
                state=state,
                events=_spell_target_failure_events(state, target, command_id),
            )

    result = effect_engine.cast_spell(
        state.player, spell.id, target, target_player, apply_cost=False
    )

    context = dict(result.context)
    broadcast_text = context.pop("broadcast", None)
    broadcast_message_id = context.pop("broadcast_message_id", None)
    broadcast_exclude_player = context.pop("broadcast_exclude_player", None)
    target_text = context.pop("target_text", None)
    target_message_id = context.pop("target_message_id", None)
    target_message_after_room_events = bool(
        context.pop("target_message_after_room_events", False)
    )
    target_room_message_id = context.pop("target_room_message_id", None)
    target_room_message = context.pop("target_room_message", None)
    target_room_result_message_id = context.pop("target_room_result_message_id", None)
    target_room_result_text = context.pop("target_room_result_text", None)
    area_damage = context.pop("area_damage", None)
    hitoth_target = context.pop("hitoth_target", None)
    extra_events = context.pop("extra_events", [])
    room_messages = context.pop("room_messages", [])
    global_broadcast_message_id = context.pop("global_broadcast_message_id", None)
    room_broadcast_message_id = context.pop("room_broadcast_message_id", None)
    room_broadcast_include_sender = bool(
        context.pop("room_broadcast_include_sender", False)
    )
    move_to_room = context.pop("move_to_room", None)
    move_from_room = context.pop("move_from_room", None)
    departure_broadcast = context.pop("departure_broadcast", None)
    departure_broadcast_message_id = context.pop("departure_broadcast_message_id", None)
    departure_emote = context.pop("departure_emote", None)
    arrival_text = context.pop("arrival_text", None)
    room_objects_update = context.pop("room_objects_update", None)
    dropped_messages = context.pop("dropped_messages", [])

    event = _message_event(
        "player",
        result.message_id,
        result.text,
        command_id,
    )
    event.update(
        {
            "spell_id": spell.id,
            "spell_name": spell.name,
            **context,
        }
    )
    if result.animation:
        event["animation"] = result.animation

    events = [event]
    target_event = None
    if target_message_id and target_player:
        target_event = _message_event(
            "target",
            target_message_id,
            target_text,
            command_id,
        )
        target_event["player"] = target_player.plyrid
        target_event["room_id"] = target_player.gamloc
        if not target_message_after_room_events:
            events.append(target_event)
    if broadcast_text:
        events.append(
            _message_event(
                "room",
                broadcast_message_id,
                broadcast_text,
                command_id,
                exclude_player=broadcast_exclude_player or state.player.plyrid,
            )
        )
    if global_broadcast_message_id:
        events.append(
            _message_event(
                "global",
                global_broadcast_message_id,
                _format_message(state, global_broadcast_message_id),
                command_id,
            )
        )
    if room_broadcast_message_id:
        room_event = _message_event(
            "room",
            room_broadcast_message_id,
            _format_message(state, room_broadcast_message_id),
            command_id,
            exclude_player=state.player.plyrid
            if not room_broadcast_include_sender
            else None,
        )
        if room_broadcast_include_sender:
            room_event["include_sender"] = True
        events.append(room_event)
    for room_message in room_messages:
        if not isinstance(room_message, dict):
            continue
        message_id = room_message.get("message_id")
        text = room_message.get("text")
        if not isinstance(text, str):
            continue
        # Legacy inline spell room text uses prf()+sndloc(), which includes the caster
        # when they are still in the source room (legacy/KYRUTIL.C:184-193).
        room_event = _message_event(
            "room",
            message_id if isinstance(message_id, str) else None,
            text,
            command_id,
        )
        room_event["include_sender"] = True
        events.append(room_event)
    if target_room_message_id and target_player:
        events.append(
            {
                "scope": "nearby_room",
                "room_id": target_player.gamloc,
                "event": "room_message",
                "type": "room_message",
                "player": state.player.plyrid,
                "text": target_room_message
                or _format_message(state, target_room_message_id),
                "message_id": target_room_message_id,
                "command_id": command_id,
            }
        )
    if target_event and target_message_after_room_events:
        events.append(target_event)
    if target_room_result_message_id and target_player:
        events.append(
            {
                "scope": "nearby_room",
                "room_id": target_player.gamloc,
                "event": "room_message",
                "type": "room_message",
                "player": target_player.plyrid,
                "text": target_room_result_text
                or _format_message(state, target_room_result_message_id),
                "message_id": target_room_result_message_id,
                "command_id": command_id,
                "exclude_player": target_player.plyrid,
            }
        )
    if hitoth_target == "target" and target_player and target_player.hitpts <= 0:
        _append_hitoth_death_events(state, target_player, command_id, events)
    elif hitoth_target == "caster" and state.player.hitpts <= 0:
        _append_hitoth_death_events(state, state.player, command_id, events)
    if extra_events:
        for extra_event in extra_events:
            event_payload = dict(extra_event)
            event_payload.setdefault("command_id", command_id)
            events.append(event_payload)
    if area_damage:
        await _apply_area_damage(state, command_id, area_damage, events)

    if room_objects_update:
        location_id = room_objects_update["location"]
        object_ids = list(room_objects_update["objects"])
        location = state.locations.get(location_id)
        if location:
            object.__setattr__(location, "objects", object_ids)
            object.__setattr__(location, "nlobjs", len(object_ids))
            _persist_location_objects(state, location_id, object_ids)
        if location and state.player.gamloc == location_id:
            events.append(
                _room_objects_event(
                    location,
                    state.objects,
                    command_id,
                    result.message_id,
                )
            )

    for dropped in dropped_messages:
        if target_player:
            target_drop = _message_event(
                "target",
                dropped.get("target_message_id"),
                dropped.get("target_text"),
                command_id,
            )
            target_drop["player"] = target_player.plyrid
            events.append(target_drop)
        if dropped.get("broadcast"):
            # Legacy reference: clutzopho prints each S11M06 drop line to the
            # caster before sndbt2() broadcasts it to other room occupants
            # (legacy/KYRSPEL.C:584-586).
            events.append(
                _message_event(
                    "player",
                    dropped.get("broadcast_message_id"),
                    dropped.get("broadcast"),
                    command_id,
                )
            )
            events.append(
                _message_event(
                    "room",
                    dropped.get("broadcast_message_id"),
                    dropped.get("broadcast"),
                    command_id,
                    exclude_player=target_player.plyrid if target_player else state.player.plyrid,
                    exclude_players=_sndbt2_excluded_players(state, target_player)
                    if target_player
                    else [state.player.plyrid],
                )
            )

    if move_to_room is not None and move_from_room is not None:
        # Legacy goto teleports through remvgp/entrgp so movement side effects
        # follow the standard room transition pipeline (legacy/KYRSPEL.C:709-711).
        if departure_broadcast:
            events.append(
                {
                    "scope": "nearby_room",
                    "room_id": move_from_room,
                    "event": "room_message",
                    "type": "room_message",
                    "player": state.player.plyrid,
                    "from": move_from_room,
                    "to": move_to_room,
                    "direction": None,
                    "text": departure_broadcast,
                    "message_id": departure_broadcast_message_id,
                    "command_id": command_id,
                }
            )
        if departure_emote:
            # Mirror remvgp(gmpptr, "vanished in a red cloud") which announces
            # departure to origin-room occupants (legacy/KYRSPEL.C:712).
            # message_id is None: emote text is hardcoded (not a message-bank ID).
            events.append(
                {
                    "scope": "nearby_room",
                    "room_id": move_from_room,
                    "event": "room_message",
                    "type": "room_message",
                    "player": state.player.plyrid,
                    "from": move_from_room,
                    "to": move_to_room,
                    "direction": None,
                    "text": departure_emote,
                    "message_id": None,
                    "command_id": command_id,
                    "exclude_player": state.player.plyrid,
                }
            )
        transition_events = _build_room_transition_events(
            state,
            from_room=move_from_room,
            to_room=move_to_room,
            command_id=command_id,
            message_id=_command_message_id(command_id),
            direction=None,
            arrival_text=arrival_text
            or f"*** {state.player.plyrid} has just appeared in a red cloud!",
        )
        events.extend(transition_events)

    _persist_player_state(state, state.player)
    if target_player and target_player is not state.player:
        _persist_player_state(state, target_player)
    return CommandResult(state=state, events=events)


def _spell_target_failure_events(
    state: GameState, target_name: str, command_id: int | None
) -> list[dict]:
    """Emit legacy chkstf failure messaging for missing player targets."""
    # Legacy chkstf: object resistance (KSPM00/KSPM01) or phantom targets (KSPM02).
    # Source: legacy/KYRSPEL.C:266-295.
    objects = state.objects or {}
    location = state.locations[state.player.gamloc]
    obj_id = _find_object_in_location(location, objects, target_name)
    obj = objects.get(obj_id) if obj_id is not None else None
    if obj is None:
        inventory_index = _find_inventory_index(state.player, target_name, objects)
        if inventory_index is not None:
            obj = objects.get(state.player.gpobjs[inventory_index])

    if obj:
        if obj.id == 52:
            # Legacy chkstf backlash for targeting the dragon (legacy/KYRSPEL.C:277-285).
            damage = state.rng.randint(20, 46)
            state.player.hitpts = max(0, state.player.hitpts - damage)
            events = [
                _message_event(
                    "player",
                    "ZMSG08",
                    _format_message(state, "ZMSG08"),
                    command_id,
                ),
                _message_event(
                    "room",
                    "ZMSG09",
                    _format_message(state, "ZMSG09", state.player.altnam, _hisher(state.player)),
                    command_id,
                    exclude_player=state.player.plyrid,
                ),
            ]
            if state.player.hitpts <= 0:
                _append_hitoth_death_events(state, state.player, command_id, events)
            else:
                _persist_player_state(state, state.player)
            return events

        caster_text = _format_message(state, "KSPM00", obj.name)
        room_text = _format_message(
            state, "KSPM01", state.player.altnam, _object_with_article(obj)
        )
        return [
            _message_event("player", "KSPM00", caster_text, command_id),
            _message_event(
                "room",
                "KSPM01",
                room_text,
                command_id,
                exclude_player=state.player.plyrid,
            ),
        ]

    caster_text = _format_message(state, "KSPM02")
    room_text = _sndutl_text(state.player, "casting at phantoms!")
    return [
        _message_event("player", "KSPM02", caster_text, command_id),
        _message_event(
            "room",
            None,
            room_text,
            command_id,
            exclude_player=state.player.plyrid,
        ),
    ]


async def _apply_area_damage(
    state: GameState,
    command_id: int | None,
    area_damage: dict,
    events: list[dict],
) -> None:
    # Legacy masshitr handling (legacy/KYRSPEL.C:400-429).
    if not state.presence or not state.player_lookup:
        return
    origin_room = state.player.gamloc
    occupants = list(await state.presence.players_in_room(origin_room))
    if area_damage.get("hits_self") and state.player.plyrid in occupants:
        occupants = [
            state.player.plyrid,
            *sorted(
                occupant_id
                for occupant_id in occupants
                if occupant_id != state.player.plyrid
            ),
        ]

    def _origin_room_message(
        message_id: str,
        text: str,
        *,
        exclude_player: str | None = None,
    ) -> dict:
        event = _message_event(
            "nearby_room",
            message_id,
            text,
            command_id,
            exclude_player=exclude_player,
        )
        event["room_id"] = origin_room
        return event

    for occupant_id in occupants:
        # Legacy masshitr() compares the caster room with each candidate while
        # iterating; if hitoth() resets a self-killing caster to room 0, later
        # old-room occupants no longer match. (legacy/KYRSPEL.C:411-429)
        if state.player.gamloc != origin_room:
            break
        if not area_damage.get("hits_self") and occupant_id == state.player.plyrid:
            continue
        target = state.player_lookup(occupant_id)
        if not target:
            continue
        if target.gamloc != state.player.gamloc:
            continue

        protection = area_damage["protection"]
        if protection is not None and target.charms[protection]:
            caster_text = _format_message(
                state, area_damage["protect_id"], target.altnam
            )
            events.append(
                _message_event(
                    "player", area_damage["protect_id"], caster_text, command_id
                )
            )
            continue

        if target.level <= area_damage["mercy_level"]:
            target_text = _format_message(state, "MERCYU")
            target_event = _message_event("target", "MERCYU", target_text, command_id)
            target_event["player"] = target.plyrid
            target_event["room_id"] = origin_room
            events.append(target_event)

            broadcast_text = _format_message(state, "MERCYO", target.altnam)
            events.append(
                _origin_room_message(
                    "MERCYO",
                    broadcast_text,
                    exclude_player=target.plyrid,
                )
            )
            continue

        target.hitpts = max(0, target.hitpts - area_damage["damage"])

        target_text = _format_message(state, area_damage["hit_id"])
        target_event = _message_event(
            "target", area_damage["hit_id"], target_text, command_id
        )
        target_event["player"] = target.plyrid
        target_event["room_id"] = origin_room
        events.append(target_event)

        broadcast_text = _format_message(
            state, area_damage["other_id"], target.altnam
        )
        events.append(
            _origin_room_message(
                area_damage["other_id"],
                broadcast_text,
                exclude_player=target.plyrid,
            )
        )
        if target.hitpts <= 0:
            _append_hitoth_death_events(state, target, command_id, events)
        else:
            _persist_player_state(state, target)


def _handle_spellbook(state: GameState, args: dict) -> CommandResult:
    command_id = args.get("command_id")
    spells_catalog = fixtures.load_spells()
    owned_spells = list_spellbook_spells(state.player, spells_catalog)
    # Legacy seesbk chooses SBOOK* vs ASBOOK* by terminal type (legacy/KYRSPEL.C:1427).
    spellbook_prefix = "ASBOOK" if args.get("terminal_mode") == "at" else "SBOOK"
    title = "Lady" if state.player.flags & constants.PlayerFlag.FEMALE else "Lord"
    header_id = f"{spellbook_prefix}1"
    row_id = f"{spellbook_prefix}2"
    empty_id = f"{spellbook_prefix}3"
    footer_id = f"{spellbook_prefix}4"

    return CommandResult(
        state=state,
        events=_spellbook_events(
            state,
            command_id,
            owned_spells,
            header_id=header_id,
            row_id=row_id,
            empty_id=empty_id,
            footer_id=footer_id,
            title=title,
        ),
    )


def _spellbook_events(
    state: GameState,
    command_id: int | None,
    owned_spells: list[models.SpellModel],
    *,
    header_id: str,
    row_id: str,
    empty_id: str,
    footer_id: str,
    title: str,
) -> list[dict]:
    events = [
        _message_event(
            "player",
            header_id,
            _format_message(state, header_id, title, state.player.plyrid),
            command_id,
        )
    ]

    if owned_spells:
        spell_names = [spell.name for spell in owned_spells]
        # Legacy seesbk prints spell names in 3-column rows via SBOOK2/ASBOOK2 (legacy/KYRSPEL.C:1430-1437).
        for index in range(0, len(spell_names), 3):
            chunk = spell_names[index : index + 3]
            chunk.extend([""] * (3 - len(chunk)))
            events.append(
                _message_event(
                    "player",
                    row_id,
                    _format_message(state, row_id, chunk[0], chunk[1], chunk[2]),
                    command_id,
                )
            )
    else:
        events.append(
            _message_event("player", empty_id, _format_message(state, empty_id), command_id)
        )

    events.append(
        _message_event("player", footer_id, _format_message(state, footer_id), command_id)
    )
    return events


async def _handle_look(state: GameState, args: dict) -> CommandResult:
    # Ported from legacy looker/ckinvs logic in KYRCMDS.C and KYRUTIL.C.【F:legacy/KYRCMDS.C†L739-L784】【F:legacy/KYRUTIL.C†L91-L120】
    command_id = args.get("command_id")
    message_id = args.get("message_id") or _command_message_id(command_id)
    raw = (args.get("raw") or args.get("target") or "").strip()
    target = raw.lower()
    objects = state.objects or {}
    location = state.locations[state.player.gamloc]
    events: list[dict] = []

    if raw:
        obj_id = _find_object_in_location(location, objects, target)
        if obj_id is not None:
            obj = objects[obj_id]
            obj_message_id = _object_description_message_id(objects, obj)
            obj_text = _format_message(state, obj_message_id)
            events.append(_message_event("player", obj_message_id, obj_text, command_id))
            looker_text = _format_message(
                state,
                "LOOKER1",
                state.player.altnam,
                obj.name,
                location.objlds,
            )
            events.append(
                _message_event(
                    "room",
                    "LOOKER1",
                    looker_text,
                    command_id,
                    exclude_player=state.player.plyrid,
                )
            )
            return CommandResult(state=state, events=events)

        inventory_index = _find_inventory_index(state.player, target, objects)
        if inventory_index is not None:
            obj_id = state.player.gpobjs[inventory_index]
            obj = objects[obj_id]
            obj_message_id = _object_description_message_id(objects, obj)
            obj_text = _format_message(state, obj_message_id)
            events.append(_message_event("player", obj_message_id, obj_text, command_id))
            looker_text = _format_message(
                state,
                "LOOKER2",
                state.player.altnam,
                _hisher(state.player),
                obj.name,
            )
            events.append(
                _message_event(
                    "room",
                    "LOOKER2",
                    looker_text,
                    command_id,
                    exclude_player=state.player.plyrid,
                )
            )
            return CommandResult(state=state, events=events)

        target_player = None
        if _matches_player_name(raw, state.player):
            target_player = state.player
        elif state.presence and state.player_lookup:
            occupants = await _ordered_players_in_room(state, state.player.gamloc)
            for occupant_id in occupants:
                if occupant_id == state.player.plyrid:
                    continue
                if target_player:
                    break
                other = state.player_lookup(occupant_id)
                if other and _matches_player_name(raw, other):
                    if _can_see_player(state.player, other):
                        target_player = other

        if target_player:
            if target_player.flags & constants.PlayerFlag.INVISF:
                desc_id = "INVDES"
                desc_text = _format_message(state, desc_id)
            elif target_player.flags & constants.PlayerFlag.WILLOW:
                # Legacy looker picks transform descriptions by target flags only.
                # See legacy/KYRCMDS.C:755-767.
                desc_id = "WILDES"
                desc_text = _format_message(state, desc_id)
            elif target_player.flags & constants.PlayerFlag.PEGASU:
                # Legacy looker picks transform descriptions by target flags only.
                # See legacy/KYRCMDS.C:755-767.
                desc_id = "PEGDES"
                desc_text = _format_message(state, desc_id)
            elif target_player.flags & constants.PlayerFlag.PDRAGN:
                # Legacy looker picks transform descriptions by target flags only.
                # See legacy/KYRCMDS.C:755-767.
                desc_id = "PDRDES"
                desc_text = _format_message(state, desc_id)
            else:
                desc_id = _player_description_message_id(target_player)
                base_text = _format_message(state, desc_id, target_player.plyrid)
                inventory_text = _inventory_summary_text(state, target_player, objects)
                desc_text = f"{base_text} {inventory_text}".strip() if base_text else inventory_text

            events.append(_message_event("player", desc_id, desc_text, command_id))

            looker3_text = _compact_system_prefix(
                _format_message(state, "LOOKER3", state.player.altnam)
            )
            events.append(
                {
                    **_message_event("target", "LOOKER3", looker3_text, command_id),
                    "player": target_player.plyrid,
                }
            )
            looker4_text = _format_message(
                state, "LOOKER4", state.player.altnam, target_player.altnam
            )
            # Legacy sndbt2() excludes the target from LOOKER4 broadcasts.【F:legacy/KYRCMDS.C†L748-L775】
            events.append(
                _message_event(
                    "room",
                    "LOOKER4",
                    looker4_text,
                    command_id,
                    exclude_player=target_player.plyrid,
                    exclude_players=_sndbt2_excluded_players(state, target_player),
                )
            )
            return CommandResult(state=state, events=events)

        if _legacy_prefix_match(target, "brief"):
            looker_text = _format_message(state, "LOOKER5", location.brfdes)
            events.append(_message_event("player", "LOOKER5", looker_text, command_id))
            events.append(
                _room_objects_event(location, objects, command_id, message_id)
            )
            occupants_event = await _room_occupants_event(state, location.id)
            if occupants_event:
                events.append(occupants_event)
            return CommandResult(state=state, events=events)

        if _legacy_prefix_match(target, "spellbook"):
            return _handle_spellbook(state, args)

    description_id, long_description = _location_description(state, location)
    description_text = long_description or location.brfdes
    events.append(
        {
            "scope": "player",
            "event": "location_description",
            "type": "location_description",
            "location": location.id,
            "message_id": description_id,
            "text": description_text,
            "objects": room_object_entries(location, objects),
        }
    )
    events.append(_room_objects_event(location, objects, command_id, message_id))
    occupants_event = await _room_occupants_event(state, location.id)
    if occupants_event:
        events.append(occupants_event)
    return CommandResult(state=state, events=events)


def _location_message_id(location_id: int, content_mappings: dict[str, dict[str, str]] | None) -> str:
    if content_mappings and "locations" in content_mappings:
        mapping = content_mappings["locations"]
        if str(location_id) in mapping:
            return mapping[str(location_id)]
    return f"KRD{location_id:03d}"


def _location_description(
    state: GameState,
    location: models.LocationModel,
    *,
    player: models.PlayerModel | None = None,
) -> tuple[str, str | None]:
    viewer = player or state.player
    if viewer.flags & constants.PlayerFlag.BRFSTF:
        # Ported from entrgp in legacy/KYRUTIL.C, which printed the brief description when BRFSTF is set.【F:legacy/KYRUTIL.C†L236-L255】
        return None, None

    message_id = _location_message_id(location.id, state.content_mappings)
    text = None
    if state.messages:
        text = state.messages.messages.get(message_id)
    # Ported from entrgp in legacy/KYRUTIL.C, which printed either the brief description
    # or the full lcrous text when entering a room.【F:legacy/KYRUTIL.C†L236-L255】
    return message_id, text


def _inventory_items(state: GameState) -> list[dict]:
    objects = state.objects or {}
    items: list[dict] = []
    for idx, obj_id in enumerate(state.player.gpobjs):
        obj = objects.get(obj_id)
        value = state.player.obvals[idx] if idx < len(state.player.obvals) else 0
        needs_an = bool(obj and "NEEDAN" in obj.flags)
        name = obj.name if obj else str(obj_id)
        entry = {
            "id": obj_id,
            "value": value,
            "name": name,
            "display_name": f"{'an' if needs_an else 'a'} {name}",
        }
        items.append(entry)
    return items


def _inventory_event(state: GameState, command_id: int | None, message_id: str | None) -> dict:
    items = _inventory_items(state)
    text, text_message_id = _inventory_text(state, items)

    return {
        "scope": "player",
        "event": "inventory",
        "type": "inventory",
        "items": items,
        "inventory": [item["display_name"] for item in items],
        "gold": state.player.gold,
        "text": text,
        "text_message_id": text_message_id,
        "command_id": command_id,
        "message_id": message_id,
    }


def _inventory_text(state: GameState, items: list[dict]) -> tuple[str, str | None]:
    gold = state.player.gold
    plural = "" if gold == 1 else "s"
    if state.messages and "KUTM07" in state.messages.messages:
        suffix = state.messages.messages["KUTM07"] % (gold, plural)
        message_id = "KUTM07"
    else:
        suffix = f"your spellbook and {gold} piece{plural} of gold."
        message_id = None

    prefix = "...You have "
    item_names = [
        item.get("display_name") or item.get("name") or "" for item in items if item
    ]
    if item_names:
        prefix = prefix + ", ".join(item_names) + ", "
    return prefix + suffix, message_id


def _persist_location_objects(state: GameState, location_id: int, object_ids: list[int]):
    """Persist location object changes to database so they survive server restarts."""
    if state.db_session:
        location_repo = repositories.LocationRepository(state.db_session)
        location_repo.update_objects(location_id, object_ids)
        state.db_session.commit()


def _persist_location_objects_and_player_inventories(
    state: GameState,
    location_id: int,
    object_ids: list[int],
    players: list[models.PlayerModel],
):
    """Persist an item move between room objects and inventories in one commit."""
    if not state.db_session:
        return
    location_repo = repositories.LocationRepository(state.db_session)
    location_repo.update_objects(location_id, object_ids)
    _stage_player_inventory_records(state, players)
    state.db_session.commit()


def _persist_player_inventories(state: GameState, players: list[models.PlayerModel]):
    """Persist inventory changes for related players in one commit."""
    if not state.db_session:
        return
    _stage_player_inventory_records(state, players)
    state.db_session.commit()


def _persist_player_inventory(state: GameState, player: models.PlayerModel):
    """Persist player inventory changes so multiplayer sessions stay consistent."""
    if not state.db_session:
        return
    _stage_player_inventory_records(state, [player])
    state.db_session.commit()


def _stage_player_inventory_records(
    state: GameState, players: list[models.PlayerModel]
):
    seen: set[str] = set()
    if not state.db_session:
        return
    for player in players:
        if player.plyrid in seen:
            continue
        seen.add(player.plyrid)
        record = state.db_session.scalar(
            select(models.Player).where(models.Player.plyrid == player.plyrid)
        )
        if not record:
            continue
        record.gpobjs = list(player.gpobjs)
        record.obvals = list(player.obvals)
        record.npobjs = player.npobjs


def _persist_player_location(state: GameState, player: models.PlayerModel):
    """Persist player location changes without overwriting unrelated state."""
    if not state.db_session:
        return
    record = state.db_session.scalar(
        select(models.Player).where(models.Player.plyrid == player.plyrid)
    )
    if not record:
        return
    record.gamloc = player.gamloc
    record.pgploc = player.pgploc
    state.db_session.commit()


def _persist_player_state(state: GameState, player: models.PlayerModel):
    """Persist player state changes triggered by room scripts or commands."""
    if not state.db_session:
        return
    if _stage_player_state_record(state, player):
        state.db_session.commit()


def _persist_death_recovery_plan(
    state: GameState,
    player: models.PlayerModel,
    plan: DeathRecoveryPlan,
) -> None:
    """Persist modern_death_recovery player and room-object rows atomically."""
    if not state.db_session:
        return
    try:
        if not _stage_death_recovery_player_record(state, player, plan):
            raise RuntimeError(
                f"Cannot persist modern_death_recovery for missing player {player.plyrid}"
            )
        location_repo = repositories.LocationRepository(state.db_session)
        for room_update in plan.room_object_updates:
            location_repo.update_objects(room_update.room_id, list(room_update.object_ids))
        state.db_session.commit()
    except Exception:
        state.db_session.rollback()
        raise


def _stage_player_state_record(state: GameState, player: models.PlayerModel) -> bool:
    record = state.db_session.scalar(
        select(models.Player).where(models.Player.plyrid == player.plyrid)
    )
    if not record:
        return False
    record.altnam = player.altnam
    record.attnam = player.attnam
    record.level = player.level
    record.nmpdes = player.nmpdes
    record.hitpts = player.hitpts
    record.spts = player.spts
    record.flags = player.flags
    record.gold = player.gold
    record.gpobjs = list(player.gpobjs)
    record.obvals = list(player.obvals)
    record.npobjs = player.npobjs
    record.nspells = player.nspells
    record.offspls = player.offspls
    record.defspls = player.defspls
    record.othspls = player.othspls
    record.spells = list(player.spells)
    record.charms = list(player.charms)
    record.gamloc = player.gamloc
    record.pgploc = player.pgploc
    record.gemidx = player.gemidx
    record.stones = list(player.stones)
    record.macros = player.macros
    record.stumpi = player.stumpi
    record.spouse = player.spouse
    record.honor_mode = player.honor_mode
    return True


def _stage_death_recovery_player_record(
    state: GameState,
    player: models.PlayerModel,
    plan: DeathRecoveryPlan,
) -> bool:
    record = state.db_session.scalar(
        select(models.Player).where(models.Player.plyrid == player.plyrid)
    )
    if not record:
        return False

    def value(field_name: str):
        return plan.player_updates.get(field_name, getattr(player, field_name))

    record.altnam = value("altnam")
    record.attnam = value("attnam")
    record.level = value("level")
    record.nmpdes = value("nmpdes")
    record.hitpts = value("hitpts")
    record.spts = value("spts")
    record.flags = value("flags")
    record.gold = value("gold")
    record.gpobjs = list(value("gpobjs"))
    record.obvals = list(value("obvals"))
    record.npobjs = value("npobjs")
    record.nspells = value("nspells")
    record.offspls = value("offspls")
    record.defspls = value("defspls")
    record.othspls = value("othspls")
    record.spells = list(value("spells"))
    record.charms = list(value("charms"))
    record.gamloc = value("gamloc")
    record.pgploc = value("pgploc")
    record.gemidx = value("gemidx")
    record.stones = list(value("stones"))
    record.macros = value("macros")
    record.stumpi = value("stumpi")
    record.spouse = value("spouse")
    record.honor_mode = value("honor_mode")
    return True


def room_object_entries(
    location: models.LocationModel,
    objects: dict[int, models.GameObjectModel],
) -> list[dict]:
    visible = []
    for obj_id in location.objects:
        entry = {"id": obj_id}
        obj = objects.get(obj_id)
        if obj:
            entry["name"] = obj.name
        visible.append(entry)
    return visible


def _room_objects_event(
    location: models.LocationModel,
    objects: dict[int, models.GameObjectModel],
    command_id: int | None,
    message_id: str | None,
    *,
    scope: str = "player",
    include_sender: bool | None = None,
) -> dict:
    event = {
        "scope": scope,
        "event": "room_objects",
        "type": "room_objects",
        "objects": room_object_entries(location, objects),
        "location": location.id,
        "command_id": command_id,
        "message_id": message_id,
    }
    if include_sender is not None:
        event["include_sender"] = include_sender
    return event


def _format_room_occupants(
    occupants: list[str], messages: models.MessageBundleModel | None
) -> tuple[str | None, str | None]:
    """Format the occupant list shown when inspecting a room."""

    if not occupants:
        return None, None

    catalog = messages.messages if messages else {}
    message_id = None

    if len(occupants) == 1:
        suffix = catalog.get("KUTM11", "is here.")
        message_id = "KUTM11" if "KUTM11" in catalog else None
        return _join_room_occupant_suffix(occupants[0], suffix), message_id

    suffix = catalog.get("KUTM12", "are here.")
    message_id = "KUTM12" if "KUTM12" in catalog else None
    if len(occupants) == 2:
        names = f"{occupants[0]} and {occupants[1]}"
    else:
        names = ", ".join(occupants[:-1]) + f", and {occupants[-1]}"
    return _join_room_occupant_suffix(names, suffix), message_id


def _join_room_occupant_suffix(names: str, suffix: str) -> str:
    # Legacy locogps() prints names, then appends KUTM11/KUTM12 directly.
    # The catalog strings include their own leading space. (legacy/KYRUTIL.C:403-419)
    separator = "" if suffix[:1].isspace() else " "
    return f"{names}{separator}{suffix}"


def _dedupe_room_occupants(occupants: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for occupant in occupants:
        display = str(occupant or "").strip()
        if not display:
            continue
        key = display.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(display)
    return unique


async def _room_occupants_event(state: GameState, room_id: int) -> dict | None:
    if not state.presence:
        return None
    occupants = await state.presence.players_in_room(room_id)
    self_key = state.player.plyrid.strip().casefold()
    others = _dedupe_room_occupants(
        sorted(
            occupant
            for occupant in occupants
            if str(occupant or "").strip().casefold() != self_key
        )
    )
    text, message_id = _format_room_occupants(others, state.messages)
    if not text:
        return None
    return {
        "scope": "player",
        "event": "room_occupants",
        "type": "room_occupants",
        "location": room_id,
        "occupants": others,
        "text": text,
        "message_id": message_id,
    }


def _hisher(player: models.PlayerModel) -> str:
    return models.possessive_pronoun(player)


def _himher(player: models.PlayerModel) -> str:
    return models.object_pronoun(player)


def _upperc(text: str) -> str:
    return text[:1].upper() + text[1:].lower()


def _compact_system_prefix(text: str | None) -> str | None:
    if text and text.startswith("***\r\n"):
        return text.replace("***\r\n", "*** ", 1)
    return text


def _format_message(
    state: GameState, message_id: str | None, *args: object
) -> str | None:
    if not message_id or not state.messages:
        return None
    template = state.messages.messages.get(message_id)
    if template is None:
        return None
    if args:
        try:
            return template % args
        except TypeError:
            return template
    return template


def _object_description_message_id(
    objects: dict[int, models.GameObjectModel], obj: models.GameObjectModel
) -> str | None:
    objdes_values = sorted({entry.objdes for entry in objects.values()})
    if not objdes_values:
        return None
    try:
        index = objdes_values.index(obj.objdes)
    except ValueError:
        return None
    return f"KID{index:03d}"


def _player_description_message_id(player: models.PlayerModel) -> str | None:
    if player.nmpdes is None:
        nmpdes = constants.level_to_nmpdes(player.level)
    else:
        nmpdes = player.nmpdes
    # Legacy: initgp/EDT002 select FDES/MDES based on FEMALE (KYRANDIA.C 345-351,
    # KYRSYSP.C 138-144).
    prefix = "FDES" if player.flags & constants.PlayerFlag.FEMALE else "MDES"
    return f"{prefix}{nmpdes:02d}"


def _inventory_summary_text(
    state: GameState, target: models.PlayerModel, objects: dict[int, models.GameObjectModel]
) -> str:
    item_names = []
    for obj_id in target.gpobjs:
        obj = objects.get(obj_id)
        if not obj:
            continue
        item_names.append(_object_with_article(obj))

    catalog = state.messages.messages if state.messages else {}
    and_text = catalog.get("KUTM08", "and")
    spellbook_template = catalog.get("KUTM09", "%s spellbook.")
    spellbook_text = spellbook_template % _hisher(target)

    if item_names:
        return f"{', '.join(item_names)}, {and_text} {spellbook_text}"
    return spellbook_text


def _object_with_article(obj: models.GameObjectModel) -> str:
    needs_an = "NEEDAN" in obj.flags
    article = "an" if needs_an else "a"
    return f"{article} {obj.name}"


def _find_object_slot_in_location(
    location: models.LocationModel, objects: dict[int, models.GameObjectModel], target: str
) -> int | None:
    for index, obj_id in enumerate(location.objects):
        obj = objects.get(obj_id)
        if obj and _legacy_prefix_match(target, obj.name):
            return index
    return None


def _find_object_in_location(
    location: models.LocationModel, objects: dict[int, models.GameObjectModel], target: str
) -> int | None:
    index = _find_object_slot_in_location(location, objects, target)
    if index is None:
        return None
    return location.objects[index]


def _find_inventory_index(
    player: models.PlayerModel, target: str, objects: dict[int, models.GameObjectModel]
) -> int | None:
    for idx, obj_id in enumerate(player.gpobjs):
        obj = objects.get(obj_id)
        if obj and _legacy_prefix_match(target, obj.name):
            return idx
    return None


def _legacy_prefix_match(shorts: str, longs: str) -> bool:
    # MajorBBS sameto(shorts, longs): case-insensitive prefix matching.
    target = shorts.strip().lower()
    return bool(target) and longs.lower().startswith(target)


def _handle_stub(state: GameState, args: dict) -> CommandResult:  # noqa: ARG001
    command_id = args.get("command_id")
    message_id = args.get("message_id") or _command_message_id(command_id)
    return CommandResult(
        state=state,
        events=[
            {
                "scope": "player",
                "event": "unimplemented",
                "type": "unimplemented",
                "detail": "Command acknowledged",
                "command_id": command_id,
                "message_id": message_id,
            }
        ],
    )


def _build_object_engine(state: GameState) -> ObjectEffectEngine:
    return ObjectEffectEngine(
        objects=state.objects.values() if state.objects else [],
        messages=state.messages or fixtures.load_messages(),
    )


def _handle_drink(state: GameState, args: dict) -> CommandResult:
    command_id = args.get("command_id")
    raw = (args.get("raw") or "").strip().lower()
    if not raw:
        # Legacy drinkr() with no args => OBJM07 (legacy/KYROBJR.C:162-165).
        return CommandResult(
            state=state,
            events=_player_and_room_message_events(
                state,
                command_id,
                "OBJM07",
                _format_message(state, "OBJM07"),
                room_template="having a drinking problem.",
            ),
        )

    objects = state.objects or {}
    inventory_index = _find_inventory_index(state.player, raw, objects)
    if inventory_index is None:
        # Legacy nohutl() path for missing held item (legacy/KYROBJR.C:166-168,185-189).
        return CommandResult(
            state=state,
            events=_player_and_room_message_events(
                state,
                command_id,
                "OBJM09",
                _format_message(state, "OBJM09"),
                room_template="having wild dreams.",
            ),
        )

    object_id = state.player.gpobjs[inventory_index]
    obj = objects.get(object_id)
    if obj is None or "DRIABL" not in obj.flags:
        return CommandResult(
            state=state,
            events=_player_and_room_message_events(
                state,
                command_id,
                "OBJM07",
                _format_message(state, "OBJM07"),
                room_template="looking thirsty!",
            ),
        )

    effect = _build_object_engine(state).use_object(
        player_id=state.player.plyrid,
        object_id=object_id,
        room_id=state.player.gamloc,
        action="drink",
        player=state.player,
    )
    _persist_player_state(state, state.player)
    return CommandResult(
        state=state,
        events=_player_and_room_message_events(
            state,
            command_id,
            effect.message_id,
            effect.text,
            room_template="drinking something quickly.",
        ),
    )


def _handle_rub(state: GameState, args: dict) -> CommandResult:
    command_id = args.get("command_id")
    raw = (args.get("raw") or "").strip().lower()
    if not raw:
        # Legacy rubber() with no args => OBJM00 (legacy/KYROBJR.C:72-75).
        return CommandResult(
            state=state,
            events=_player_and_room_message_events(
                state,
                command_id,
                "OBJM00",
                _format_message(state, "OBJM00"),
                room_template="acting silly.",
            ),
        )

    objects = state.objects or {}
    inventory_index = _find_inventory_index(state.player, raw, objects)
    if inventory_index is None:
        return CommandResult(
            state=state,
            events=_player_and_room_message_events(
                state,
                command_id,
                "OBJM09",
                _format_message(state, "OBJM09"),
                room_template="having wild dreams.",
            ),
        )

    object_id = state.player.gpobjs[inventory_index]
    obj = objects.get(object_id)
    if obj is None or "RUBABL" not in obj.flags:
        return CommandResult(
            state=state,
            events=_player_and_room_message_events(
                state,
                command_id,
                "OBJM01",
                _format_message(state, "OBJM01"),
                room_template="rubbing something.",
            ),
        )

    if object_id == 30 and state.zar_controller is not None and state.zar_state is not None:
        return _handle_dragonstaff_rub(state, command_id, inventory_index)

    effect = _build_object_engine(state).use_object(
        player_id=state.player.plyrid,
        object_id=object_id,
        room_id=state.player.gamloc,
        action="rub",
        player=state.player,
    )
    _persist_player_state(state, state.player)
    room_template = None
    if object_id == 30:
        # Legacy zaritm() opens dragonstaff use with sndutl("rubbing %s dragonstaff!").
        # (legacy/KYRANIM.C:177-180)
        room_template = "rubbing %s dragonstaff!"
    return CommandResult(
        state=state,
        events=_player_and_room_message_events(
            state,
            command_id,
            effect.message_id,
            effect.text,
            room_template=room_template,
        ),
    )


async def _handle_aim(state: GameState, args: dict) -> CommandResult:
    command_id = args.get("command_id")
    raw = (args.get("raw") or "").strip().lower()
    if not raw:
        # Legacy aimer() no-arg path (legacy/KYROBJR.C:122-124).
        return CommandResult(
            state=state,
            events=_player_and_room_message_events(
                state,
                command_id,
                "OBJM03",
                _format_message(state, "OBJM03"),
                room_template="pointing wildly.",
            ),
        )

    item_name = raw
    target_name = ""
    if " at " in raw:
        item_name, target_name = [part.strip() for part in raw.split(" at ", 1)]
    else:
        tokens = raw.split()
        if len(tokens) >= 2:
            item_name = tokens[0]
            target_name = tokens[-1]

    objects = state.objects or {}
    inventory_index = _find_inventory_index(state.player, item_name, objects)
    if inventory_index is None:
        return CommandResult(
            state=state,
            events=_player_and_room_message_events(
                state,
                command_id,
                "OBJM09",
                _format_message(state, "OBJM09"),
                room_template="having wild dreams.",
            ),
        )

    if not target_name:
        return CommandResult(
            state=state,
            events=_player_and_room_message_events(
                state,
                command_id,
                "OBJM05",
                _format_message(state, "OBJM05"),
                room_template="waving %s arms.",
            ),
        )

    target_player = await _find_player_in_room(state, target_name)
    if target_player is None:
        return CommandResult(
            state=state,
            events=_player_and_room_message_events(
                state,
                command_id,
                "OBJM06",
                _format_message(state, "OBJM06"),
                room_template="seeing ghosts!",
            ),
        )

    object_id = state.player.gpobjs[inventory_index]
    obj = objects.get(object_id)
    # Legacy aimer() only allows AIMABL objects through this branch (legacy/KYROBJR.C:147-153).
    if obj is None or "AIMABL" not in obj.flags:
        return CommandResult(
            state=state,
            events=_player_and_room_message_events(
                state,
                command_id,
                "OBJM04",
                _format_message(state, "OBJM04"),
                room_template="waving obscenely!",
            ),
        )

    try:
        effect = _build_object_engine(state).use_object(
            player_id=state.player.plyrid,
            object_id=object_id,
            room_id=state.player.gamloc,
            target=target_player.attnam,
            action="aim",
            player=state.player,
        )
    except EffectError:
        return CommandResult(
            state=state,
            events=_player_and_room_message_events(
                state,
                command_id,
                "OBJM04",
                _format_message(state, "OBJM04"),
                room_template="waving obscenely!",
            ),
        )

    return CommandResult(
        state=state,
        events=[_message_event("player", effect.message_id, effect.text, command_id)],
    )


def _unquote_text(text: str) -> str:
    stripped = text.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"\"", "'"}:
        return stripped[1:-1]
    return stripped


def _handle_help(state: GameState, args: dict) -> CommandResult:
    """Port of legacy helper() topic routing.

    Legacy behavior chooses a help screen by the first letter of the optional
    topic token and falls back to NOHELP when unknown.
    See legacy/KYRCMDS.C:973-1008.
    """
    command_id = args.get("command_id")
    topic = (args.get("raw") or "").strip()

    if topic:
        # Legacy helper() topic switch in KYRCMDS.C:973-1008.
        topic_map = {
            "c": "HLPCOM",
            "f": "HLPFAN",
            "g": "HLPGOL",
            "h": "HLPHIT",
            "l": "HLPLEV",
            "s": "HLPSPE",
            "w": "HLPWIN",
        }
        message_id = topic_map.get(topic[0].lower(), "NOHELP")
        text = (
            _format_message(state, "NOHELP", topic)
            if message_id == "NOHELP"
            else _format_message(state, message_id)
        )
    else:
        message_id = "HLPMSG"
        text = _format_message(state, message_id)

    return CommandResult(state=state, events=[_message_event("player", message_id, text, command_id)])


def _handle_brief(state: GameState, args: dict) -> CommandResult:
    """Port of briefr() with optional on/off toggles.

    In legacy Kyrandia, `brief` (or `brief on`) enables BRFSTF while
    `brief off` delegates to unbrief behavior.
    See legacy/KYRCMDS.C:1010-1025.
    """
    command_id = args.get("command_id")
    raw = (args.get("raw") or "").strip().lower()
    if not raw or raw == "on":
        state.player.flags |= int(constants.PlayerFlag.BRFSTF)
        message_id = "BRIEFR1"
    elif raw == "off":
        state.player.flags &= ~int(constants.PlayerFlag.BRFSTF)
        message_id = "UNBRIEF"
    else:
        message_id = "BRIEFR2"
    return CommandResult(
        state=state,
        events=[_message_event("player", message_id, _format_message(state, message_id), command_id)],
    )


def _handle_unbrief(state: GameState, args: dict) -> CommandResult:
    """Port of ubrief() to disable brief room descriptions.

    Clears BRFSTF and emits UNBRIEF.
    See legacy/KYRCMDS.C:1027-1031.
    """
    command_id = args.get("command_id")
    state.player.flags &= ~int(constants.PlayerFlag.BRFSTF)
    return CommandResult(
        state=state,
        events=[_message_event("player", "UNBRIEF", _format_message(state, "UNBRIEF"), command_id)],
    )


def _handle_count(state: GameState, args: dict) -> CommandResult:
    """Port of countr() generic counting flow.

    Supports bare `count`, `count gold` (delegates to gold counter), and the
    generic failure response for unsupported targets.
    See legacy/KYRCMDS.C:469-483.
    """
    raw = (args.get("raw") or "").strip().lower()
    if not raw:
        return CommandResult(state=state, events=[_message_event("player", "COUNTR1", _format_message(state, "COUNTR1"), args.get("command_id"))])
    if raw == "gold":
        return _handle_gold(state, args)
    return CommandResult(state=state, events=[_message_event("player", "COUNTR2", _format_message(state, "COUNTR2"), args.get("command_id"))])


def _handle_gold(state: GameState, args: dict) -> CommandResult:
    """Port of gldcnt() with singular/plural suffix handling.

    Emits GLDCNT formatted with player's current gold amount.
    See legacy/KYRCMDS.C:485-491.
    """
    command_id = args.get("command_id")
    text = _format_message(state, "GLDCNT", state.player.gold, "" if state.player.gold == 1 else "s")
    return CommandResult(state=state, events=[_message_event("player", "GLDCNT", text, command_id)])


def _handle_hits(state: GameState, args: dict) -> CommandResult:
    """Port of hitctr() health-status output.

    Legacy displays current HP against the level-based cap (4 * level).
    See legacy/KYRCMDS.C:1159-1164.
    """
    command_id = args.get("command_id")
    text = _format_message(state, "HITCTR", state.player.hitpts, 4 * state.player.level)
    return CommandResult(state=state, events=[_message_event("player", "HITCTR", text, command_id)])


def _handle_ponder(state: GameState, args: dict) -> CommandResult:
    """Port of ponder() rhetorical response command.

    Uses the invoked verb uppercased as the display token (what?/where?/etc.).
    See legacy/KYRCMDS.C:369-376.
    """
    command_id = args.get("command_id")
    verb = (args.get("verb") or "what?").upper()
    text = _format_message(state, "PONDER1", verb)
    return CommandResult(state=state, events=[_message_event("player", "PONDER1", text, command_id)])


def _handle_pray(state: GameState, args: dict) -> CommandResult:
    """Port of prayer() canned prayer messaging.

    Emits PRAYER to the actor and follows legacy room flavor semantics in the
    surrounding event pipeline.
    See legacy/KYRCMDS.C:1151-1157.
    """
    return CommandResult(
        state=state,
        events=[_message_event("player", "PRAYER", _format_message(state, "PRAYER"), args.get("command_id"))],
    )


async def _handle_whisper(state: GameState, args: dict) -> CommandResult:
    """Port of whispr() targeted private speech.

    Validates minimum argument shape, then sends WHISPR1 to target, WHISPR2 to
    actor, and WHISPR3 to the room excluding the target (legacy sndbt2-style
    fan-out).
    See legacy/KYRCMDS.C:266-296.
    """
    command_id = args.get("command_id")
    target_name = (args.get("target_player") or "").strip()
    text = _unquote_text((args.get("text") or "").strip())
    if not target_name or not text:
        return CommandResult(state=state, events=[_message_event("player", "WHAT", _format_message(state, "WHAT"), command_id)])

    target_player = await _find_player_in_room(state, target_name)
    if not target_player:
        return CommandResult(state=state, events=[_message_event("player", "NOSUCHP", _format_message(state, "NOSUCHP"), command_id)])

    return CommandResult(
        state=state,
        events=[
            {
                **_message_event("target", "WHISPR1", _format_message(state, "WHISPR1", state.player.altnam, text), command_id),
                "player": target_player.plyrid,
            },
            _message_event("player", "WHISPR2", _format_message(state, "WHISPR2", target_player.plyrid), command_id),
            _message_event(
                "room",
                "WHISPR3",
                _format_message(state, "WHISPR3", state.player.altnam, target_player.altnam),
                command_id,
                exclude_player=target_player.plyrid,
                exclude_players=_sndbt2_excluded_players(state, target_player),
            ),
        ],
    )


def _handle_say(state: GameState, args: dict) -> CommandResult:
    """Port of speakr() normal speech mode for say/comment/note.

    This handler models the direct speech branch with legacy message IDs.
    See legacy/KYRCMDS.C:241-264.
    """
    command_id = args.get("command_id")
    verb = args.get("verb", "say")
    text = _unquote_text((args.get("text") or "").strip())
    if not text:
        return CommandResult(state=state, events=[_message_event("player", "HUH", _format_message(state, "HUH"), command_id)])
    # Legacy speakr(): SPEAK1 (actor context) and SPEAK2 (text) are sent together
    # via sndoth() to the room, and SPEAK3 via sndnear() to adjacent rooms.
    # See legacy/KYRCMDS.C:254-261.
    speak1 = _format_message(state, "SPEAK1", state.player.altnam, verb) or ""
    speak2 = _format_message(state, "SPEAK2", text)
    room_text = f"{speak1}{speak2 if speak2 is not None else text}"
    events: List[dict] = [
        _message_event("player", "SAIDIT", _format_message(state, "SAIDIT"), command_id),
        _message_event(
            "room",
            _command_message_id(command_id) or "SPEAK2",
            room_text,
            command_id,
            exclude_player=state.player.plyrid,
        ),
    ]
    nearby_text = _format_message(state, "SPEAK3")
    for room_id in _adjacent_room_ids(state):
        events.append({
            "scope": "nearby_room",
            "room_id": room_id,
            "event": "room_message",
            "type": "room_message",
            "text": nearby_text,
            "message_id": "SPEAK3",
            "command_id": command_id,
        })
    return CommandResult(state=state, events=events)


def _handle_yell(state: GameState, args: dict) -> CommandResult:
    """Port of yeller() loud speech variant.

    Emits VOICE for missing text and uppercases the spoken payload for the
    successful branch, matching the legacy all-caps yell presentation.
    Also calls sndnear() equivalent to broadcast to adjacent rooms.
    See legacy/KYRCMDS.C:298-326.
    """
    command_id = args.get("command_id")
    text = _unquote_text((args.get("text") or "").strip())
    verb = args.get("verb", "yell")
    if not text:
        # Legacy yeller(): VOICE to player, YELLER1 to room, YELLER2 to nearby via sndnear().
        # See legacy/KYRCMDS.C:303-308.
        yeller1_text = _format_message(state, "YELLER1", state.player.altnam, verb, _hisher(state.player))
        events: List[dict] = [
            _message_event("player", "VOICE", _format_message(state, "VOICE"), command_id),
            _message_event("room", "YELLER1", yeller1_text, command_id, exclude_player=state.player.plyrid),
        ]
        nearby_text = _format_message(state, "YELLER2", verb)
        for room_id in _adjacent_room_ids(state):
            events.append({
                "scope": "nearby_room",
                "room_id": room_id,
                "event": "room_message",
                "type": "room_message",
                "text": nearby_text,
                "message_id": "YELLER2",
                "command_id": command_id,
            })
        return CommandResult(state=state, events=events)
    # Legacy yeller(): YELLER3 to player, YELLER4+YELLER5 to room, YELLER6 to nearby.
    # See legacy/KYRCMDS.C:311-322.
    events = [_message_event("player", "YELLER3", _format_message(state, "YELLER3"), command_id)]
    up = text.upper()
    yeller4 = _format_message(state, "YELLER4", state.player.altnam, verb) or ""
    yeller5 = _format_message(state, "YELLER5", up)
    room_text = f"{yeller4}{yeller5 if yeller5 is not None else up}"
    events.append(_message_event("room", "YELLER5", room_text, command_id, exclude_player=state.player.plyrid))
    # Legacy yeller(): sndnear() broadcasts YELLER6 to adjacent rooms.
    nearby_text = _format_message(state, "YELLER6", up)
    for room_id in _adjacent_room_ids(state):
        events.append({
            "scope": "nearby_room",
            "room_id": room_id,
            "event": "room_message",
            "type": "room_message",
            "text": nearby_text,
            "message_id": "YELLER6",
            "command_id": command_id,
        })
    return CommandResult(state=state, events=events)


def _parse_give_args(raw: str) -> dict:
    """Parse give-family argument layouts used by giveit().

    Supports:
    - `<amount> gold to <target>` (legacy givcrd, margc==5, KYRCMDS.C:497-498)
    - `<target> <amount> gold` (legacy givcrd, margc==4, KYRCMDS.C:500-501)
    - `<item> to <target>` (legacy giveru, margc==4 with "to", KYRCMDS.C:506-507)
    - `<target> <item>` (legacy giveru, margc==3, KYRCMDS.C:503-504)
    See legacy/KYRCMDS.C:493-515.
    """
    tokens = raw.split()
    if not tokens:
        return {}
    if len(tokens) == 4 and tokens[1].lower() == "gold" and tokens[2].lower() == "to":
        return {"gold_amount": tokens[0], "target_player": tokens[3]}
    if len(tokens) == 3 and tokens[2].lower() == "gold":
        # Legacy: give <target> <amount> gold -> givcrd(2,1) (KYRCMDS.C:500-501)
        return {"target_player": tokens[0], "gold_amount": tokens[1]}
    if len(tokens) == 3 and tokens[1].lower() == "to":
        return {"target_item": tokens[0], "target_player": tokens[2]}
    if len(tokens) == 2:
        # Legacy: give <target> <item> -> giveru(margv[1], margv[2]) (KYRCMDS.C:503-504)
        return {"target_player": tokens[0], "target_item": tokens[1]}
    return {}


async def _handle_give(state: GameState, args: dict) -> CommandResult:
    """Port of giveit()/givcrd()/giveru() player-to-player transfers.

    Handles both gold transfers and inventory item handoffs with legacy-style
    target resolution and messaging IDs.
    See legacy/KYRCMDS.C:493-625.
    """
    command_id = args.get("command_id")
    message_id = args.get("message_id") or _command_message_id(command_id)
    verb = str(args.get("verb") or "give").lower()
    target_name = (args.get("target_player") or "").strip()
    if not target_name:
        return CommandResult(
            state=state,
            events=_player_and_room_message_events(
                state,
                command_id,
                "GIVIT1",
                _format_message(state, "GIVIT1"),
                room_template="fumbling around foolishly.",
            ),
        )

    gold_amount = args.get("gold_amount")
    if gold_amount is not None:
        # Validate gold amount before resolving target; mirrors legacy givcrd() (KYRCMDS.C:523-537).
        try:
            amount = int(gold_amount)
        except ValueError:
            amount = -1
        if amount < 0:
            return CommandResult(
                state=state,
                events=_player_and_room_message_events(
                    state,
                    command_id,
                    "GIVCRD1",
                    _format_message(state, "GIVCRD1"),
                    room_template="concentrating with difficulty.",
                ),
            )
        if amount > state.player.gold:
            return CommandResult(
                state=state,
                events=_player_and_room_message_events(
                    state,
                    command_id,
                    "GIVCRD2",
                    _format_message(state, "GIVCRD2"),
                    room_template="dreaming of great wealth.",
                ),
            )
        target_player = await _find_player_in_room(state, target_name)
        if not target_player:
            return CommandResult(
                state=state,
                events=_player_and_room_message_events(
                    state,
                    command_id,
                    "GIVCRD3",
                    _format_message(state, "GIVCRD3"),
                    room_template="looking rather puzzled",
                ),
            )
        state.player.gold -= amount
        target_player.gold += amount
        # Legacy giveit()/givcrd() updates both players immediately (KYRCMDS.C:537-550).
        _persist_player_state(state, state.player)
        _persist_player_state(state, target_player)
        return CommandResult(
            state=state,
            events=[
                _message_event("player", "GIVCRD4", _format_message(state, "GIVCRD4"), command_id),
                {
                    **_message_event("target", "GIVCRD5", _format_message(state, "GIVCRD5", state.player.altnam, amount, "" if amount == 1 else "s"), command_id),
                    "player": target_player.plyrid,
                },
                _message_event(
                    "room",
                    "GIVCRD6",
                    _format_message(
                        state,
                        "GIVCRD6",
                        state.player.altnam,
                        target_player.altnam,
                        amount,
                        "" if amount == 1 else "s",
                    ),
                    command_id,
                    exclude_player=target_player.plyrid,
                    exclude_players=_sndbt2_excluded_players(state, target_player),
                ),
            ],
        )

    target_player = await _find_player_in_room(state, target_name)
    if not target_player:
        return CommandResult(
            state=state,
            events=_player_and_room_message_events(
                state,
                command_id,
                "GIVERU1",
                _format_message(state, "GIVERU1", _upperc(target_name)),
                room_template="having hallucinations.",
            ),
        )

    item_name = (args.get("target_item") or "").strip().lower()
    if not item_name:
        return CommandResult(
            state=state,
            events=_player_and_room_message_events(
                state,
                command_id,
                "GIVIT1",
                _format_message(state, "GIVIT1"),
                room_template="fumbling around foolishly.",
            ),
        )
    if target_player.plyrid == state.player.plyrid:
        return CommandResult(
            state=state,
            events=_player_and_room_message_events(
                state,
                command_id,
                "GIVERU2",
                _format_message(state, "GIVERU2"),
                room_template="scratching %s rear end.",
            ),
        )

    objects = state.objects or {}
    inventory_index = _find_inventory_index(state.player, item_name, objects)
    if inventory_index is None:
        return CommandResult(
            state=state,
            events=_player_and_room_message_events(
                state,
                command_id,
                "GIVERU3",
                _format_message(state, "GIVERU3"),
                room_template="searching %s pockets frantically!",
            ),
        )

    location = state.locations[state.player.gamloc]
    obj_id = state.player.gpobjs[inventory_index]
    obj = objects[obj_id]
    obj_display = _object_with_article(obj)

    # Legacy giveru() handles a full recipient before removing the giver item
    # (legacy/KYRCMDS.C:573-603).
    if len(target_player.gpobjs) >= constants.MXPOBS:
        if len(location.objects) >= constants.MXLOBS:
            return CommandResult(
                state=state,
                events=_player_and_room_message_events(
                    state,
                    command_id,
                    "GIVERU4",
                    _format_message(state, "GIVERU4"),
                    room_template="wrestling with supernatural powers!",
                ),
            )

        if (state.rng.randrange(256) & 0x01) == 0:
            obj_id, _ = pop_inventory_index(state.player, inventory_index)
            updated_objects = list(location.objects) + [obj_id]
            location = location.model_copy(
                update={"objects": updated_objects, "nlobjs": len(updated_objects)}
            )
            state.locations[location.id] = location
            _persist_location_objects_and_player_inventories(
                state, location.id, updated_objects, [state.player]
            )
            return CommandResult(
                state=state,
                events=[
                    _message_event(
                        "player",
                        "GIVERU5",
                        _format_message(state, "GIVERU5"),
                        command_id,
                    ),
                    _room_objects_event(
                        location,
                        objects,
                        command_id,
                        message_id,
                        scope="room",
                        include_sender=True,
                    ),
                    _message_event(
                        "room",
                        "GIVERU6",
                        _format_message(
                            state,
                            "GIVERU6",
                            state.player.altnam,
                            _hisher(state.player),
                            obj.name,
                        ),
                        command_id,
                        exclude_player=state.player.plyrid,
                    ),
                ],
            )

        value = state.player.obvals[inventory_index] if inventory_index < len(state.player.obvals) else 0
        dropped_obj_id, _ = pop_inventory_index(target_player, 0)
        dropped_obj = objects[dropped_obj_id]
        pop_inventory_index(state.player, inventory_index)
        target_player.gpobjs.append(obj_id)
        target_player.obvals.append(value)
        target_player.npobjs = len(target_player.gpobjs)
        updated_objects = list(location.objects) + [dropped_obj_id]
        location = location.model_copy(
            update={"objects": updated_objects, "nlobjs": len(updated_objects)}
        )
        state.locations[location.id] = location
        _persist_location_objects_and_player_inventories(
            state, location.id, updated_objects, [target_player, state.player]
        )
        return CommandResult(
            state=state,
            events=[
                _message_event(
                    "player",
                    "GIVERU7",
                    _format_message(
                        state,
                        "GIVERU7",
                        _himher(target_player),
                        _hisher(target_player),
                        dropped_obj.name,
                    ),
                    command_id,
                ),
                _room_objects_event(
                    location,
                    objects,
                    command_id,
                    message_id,
                    scope="room",
                    include_sender=True,
                ),
                {
                    **_message_event(
                        "target",
                        "GIVERU8",
                        _give_prefixed_message(
                            state, verb, "GIVERU8", obj_display, dropped_obj.name
                        ),
                        command_id,
                    ),
                    "player": target_player.plyrid,
                },
                _message_event(
                    "room",
                    "GIVERU9",
                    _give_prefixed_message(
                        state,
                        verb,
                        "GIVERU9",
                        target_player.altnam,
                        obj_display,
                        _himher(target_player),
                        _hisher(target_player),
                        dropped_obj.name,
                    ),
                    command_id,
                    exclude_player=target_player.plyrid,
                    exclude_players=_sndbt2_excluded_players(state, target_player),
                ),
            ],
        )

    obj_id, value = pop_inventory_index(state.player, inventory_index)
    target_player.gpobjs.append(obj_id)
    target_player.obvals.append(value)
    target_player.npobjs = len(target_player.gpobjs)
    # Legacy giveru() mutates the giver and recipient inventory atomically (KYRCMDS.C:597-614).
    _persist_player_inventories(state, [state.player, target_player])
    return CommandResult(
        state=state,
        events=[
            _message_event("player", "DONE", _format_message(state, "DONE"), command_id),
            {
                **_message_event(
                    "target",
                    "GIVERU10",
                    _give_prefixed_message(
                        state, verb, "GIVERU10", _object_with_article(objects[obj_id])
                    ),
                    command_id,
                ),
                "player": target_player.plyrid,
            },
            _message_event(
                "room",
                "GIVERU11",
                _give_prefixed_message(
                    state,
                    verb,
                    "GIVERU11",
                    target_player.altnam,
                    _object_with_article(objects[obj_id]),
                ),
                command_id,
                exclude_player=target_player.plyrid,
                exclude_players=_sndbt2_excluded_players(state, target_player),
            ),
        ],
    )


async def _handle_wink(state: GameState, args: dict) -> CommandResult:
    """Port of winker() emote flow.

    Supports no-target wink text, targeted wink fan-out, and NOSUCHP-style
    failure branch for absent targets.
    See legacy/KYRCMDS.C:895-917.
    """
    command_id = args.get("command_id")
    target_name = (args.get("raw") or "").strip()
    if not target_name:
        return CommandResult(state=state, events=[_message_event("player", "WINKER1", _format_message(state, "WINKER1"), command_id)])
    target_player = await _find_player_in_room(state, target_name)
    if not target_player:
        return CommandResult(state=state, events=[_message_event("player", "WINKER5", _format_message(state, "WINKER5"), command_id)])
    return CommandResult(
        state=state,
        events=[
            _message_event("player", "WINKER2", _format_message(state, "WINKER2"), command_id),
            {**_message_event("target", "WINKER3", _format_message(state, "WINKER3", state.player.altnam), command_id), "player": target_player.plyrid},
            _message_event(
                "room",
                "WINKER4",
                _format_message(state, "WINKER4", state.player.altnam, target_player.altnam),
                command_id,
                exclude_player=target_player.plyrid,
                exclude_players=_sndbt2_excluded_players(state, target_player),
            ),
        ],
    )


class CommandVocabulary:
    """Fixture-driven parser for mapping raw command text to dispatcher inputs."""

    chat_aliases = _SAY_VERBS | _YELL_VERBS | {"whisper"}

    def __init__(self, commands: List[models.CommandModel], messages: models.MessageBundleModel):
        self.commands = {command.command.lower(): command for command in commands}
        self.messages = messages

    def _direction_from_alias(self, verb: str) -> str | None:
        if verb in {"n", "north"}:
            return "north"
        if verb in {"s", "south"}:
            return "south"
        if verb in {"e", "east"}:
            return "east"
        if verb in {"w", "west"}:
            return "west"
        return None

    def _lookup_command_id(self, command: str) -> int | None:
        entry = self.commands.get(command)
        return entry.id if entry else None

    def _message_for_command(self, command_id: int | None) -> str | None:
        if command_id is None:
            return None
        key = _command_message_id(command_id)
        if key and key in self.messages.messages:
            return key
        return key

    @staticmethod
    def _parse_pickup_target(remainder: str) -> tuple[str | None, str]:
        trimmed = remainder.strip()
        if not trimmed:
            return None, ""

        lowered = trimmed.lower()
        if " from " in lowered:
            idx = lowered.rfind(" from ")
            item = trimmed[:idx].strip()
            player = trimmed[idx + len(" from ") :].strip()
            if item and player:
                return player, item

        if "'s " in lowered:
            idx = lowered.find("'s ")
            player = trimmed[:idx].strip()
            item = trimmed[idx + len("'s ") :].strip()
            if player and item:
                return player, item

        return None, trimmed

    def parse_text(self, text: str) -> ParsedCommand:
        raw = (text or "").strip()
        if not raw:
            raise UnknownCommandError(text)

        tokens = raw.split()
        verb = tokens[0].lower()
        raw_remainder = " ".join(tokens[1:]).strip()
        remainder = raw_remainder
        # Legacy cmpsmp()/smputl() delegates speaking emotes directly to speakr()
        # without gi_bagthe()/bagprep(), so preserve post-verb text for smparr verbs.
        # (legacy/KYRCMDS.C:1329-1353)
        if verb not in self.chat_aliases and verb not in SIMPLE_EMOTES:
            tokens = normalize_tokens(tokens)
            remainder = " ".join(tokens[1:]).strip()

        command_entry = self.commands.get(verb)
        command_id = command_entry.id if command_entry else None
        pay_only = bool(command_entry and command_entry.payonl)
        message_id = self._message_for_command(command_id)

        direction = self._direction_from_alias(verb)
        if direction:
            command_id = command_id or self._lookup_command_id(direction)
            message_id = message_id or self._message_for_command(command_id)
            return ParsedCommand(
                verb="move",
                args={"direction": direction},
                command_id=command_id,
                message_id=message_id,
                pay_only=pay_only,
            )

        if verb in _SAY_VERBS | _YELL_VERBS:
            command_id = command_id or self._lookup_command_id(verb)
            message_id = message_id or self._message_for_command(command_id)
            return ParsedCommand(
                verb=verb,
                args={"text": remainder},
                command_id=command_id,
                message_id=message_id,
                pay_only=pay_only,
            )

        if verb == "whisper":
            command_id = command_id or self._lookup_command_id("whisper")
            message_id = message_id or self._message_for_command(command_id)
            whisper_target = ""
            whisper_text = ""
            whisper_tokens = remainder.split(maxsplit=2)
            if whisper_tokens:
                # Legacy whispr() expects the full text payload as margv[2], not just one token.
                # Reference: legacy/KYRCMDS.C lines 266-289.
                if whisper_tokens[0].lower() == "to" and len(whisper_tokens) >= 2:
                    whisper_target = whisper_tokens[1]
                    whisper_text = whisper_tokens[2] if len(whisper_tokens) == 3 else ""
                else:
                    whisper_target = whisper_tokens[0]
                    whisper_text = whisper_tokens[1] if len(whisper_tokens) >= 2 else ""
                    if len(whisper_tokens) == 3:
                        whisper_text = f"{whisper_text} {whisper_tokens[2]}"
            return ParsedCommand(
                verb="whisper",
                args={"target_player": whisper_target, "text": whisper_text},
                command_id=command_id,
                message_id=message_id,
                pay_only=pay_only,
            )

        if verb in _GIVE_VERBS:
            command_id = command_id or self._lookup_command_id(verb)
            message_id = message_id or self._message_for_command(command_id)
            # Legacy giveit() only strips articles via gi_bagthe(), NOT prepositions via
            # bagprep() (KYRCMDS.C:495-496). Bypass the normalized remainder so that "to"
            # is preserved for `give <item> to <target>` detection in _parse_give_args.
            give_tokens = [t for t in raw.split()[1:] if t.lower() not in _NORMALIZE_ARTICLES]
            give_remainder = " ".join(give_tokens)
            return ParsedCommand(
                verb=verb,
                args={"raw": give_remainder, **_parse_give_args(give_remainder)},
                command_id=command_id,
                message_id=message_id,
                pay_only=pay_only,
            )

        if verb in {"inv", "inventory"}:
            return ParsedCommand(
                verb="inventory",
                args={},
                command_id=command_id,
                message_id=message_id,
                pay_only=pay_only,
            )

        if verb in _PICKUP_VERBS | {"drop"}:
            command_id = command_id or self._lookup_command_id(verb)
            message_id = message_id or self._message_for_command(command_id)
            target_player = None
            target = remainder
            if verb in _PICKUP_VERBS:
                target_player, target = self._parse_pickup_target(remainder)
            return ParsedCommand(
                verb=verb,
                args={
                    "target": target,
                    **({"target_player": target_player} if target_player else {}),
                },
                command_id=command_id,
                message_id=message_id,
                pay_only=pay_only,
            )

        return ParsedCommand(
            verb=verb,
            # Legacy kyra() fallback restores the original command string for
            # KYRA5-KYRA9, even when generic command parsing would strip words.
            # Source: legacy/KYRCMDS.C:1278-1303.
            args={
                "raw": remainder,
                **({"fallback_raw": raw_remainder} if command_entry is None else {}),
            },
            command_id=command_id,
            message_id=message_id,
            pay_only=pay_only,
        )

    def iter_commands(self):
        return self.commands.values()


def build_default_registry(vocabulary: CommandVocabulary | None = None) -> CommandRegistry:
    vocabulary = vocabulary or CommandVocabulary(
        fixtures.load_commands(), fixtures.load_messages()
    )

    registry = CommandRegistry()
    registry.register(
        CommandMetadata(
            verb="move",
            required_level=1,
            required_flags=int(constants.PlayerFlag.LOADED),
            failure_message_id="CMPCMD1",
        ),
        _handle_move,
    )
    registry.register(CommandMetadata(verb="x"), _handle_exit)
    registry.register(CommandMetadata(verb="chat", cooldown_seconds=1.5), _handle_chat)
    for verb in sorted(_SAY_VERBS):
        registry.register(
            CommandMetadata(verb=verb, command_id=vocabulary._lookup_command_id(verb)),
            _handle_say,
        )
    for verb in sorted(_YELL_VERBS):
        registry.register(
            CommandMetadata(verb=verb, command_id=vocabulary._lookup_command_id(verb)),
            _handle_yell,
        )
    registry.register(
        CommandMetadata(verb="whisper", command_id=vocabulary._lookup_command_id("whisper")),
        _handle_whisper,
    )
    registry.register(CommandMetadata(verb="inventory"), _handle_inventory)
    registry.register(
        CommandMetadata(
            verb="spoiler",
            command_id=vocabulary._lookup_command_id("spoiler"),
        ),
        _handle_spoiler,
    )
    for verb in sorted(_PICKUP_VERBS):
        registry.register(
            CommandMetadata(
                verb=verb,
                command_id=vocabulary._lookup_command_id(verb),
                required_level=1,
                required_flags=int(constants.PlayerFlag.LOADED),
                failure_message_id="CMPCMD1",
            ),
            _handle_get,
        )
    registry.register(
        CommandMetadata(
            verb="drop",
            command_id=vocabulary._lookup_command_id("drop"),
            required_level=1,
            required_flags=int(constants.PlayerFlag.LOADED),
            failure_message_id="CMPCMD1",
        ),
        _handle_drop,
    )
    for verb in sorted(_GIVE_VERBS):
        registry.register(
            CommandMetadata(
                verb=verb,
                command_id=vocabulary._lookup_command_id(verb),
                required_level=1,
                required_flags=int(constants.PlayerFlag.LOADED),
                failure_message_id="CMPCMD1",
            ),
            _handle_give,
        )
    registry.register(
        CommandMetadata(verb="help", command_id=vocabulary._lookup_command_id("help")),
        _handle_help,
    )
    registry.register(
        CommandMetadata(verb="?", command_id=vocabulary._lookup_command_id("?")),
        _handle_help,
    )
    registry.register(
        CommandMetadata(verb="brief", command_id=vocabulary._lookup_command_id("brief")),
        _handle_brief,
    )
    registry.register(
        CommandMetadata(verb="unbrief", command_id=vocabulary._lookup_command_id("unbrief")),
        _handle_unbrief,
    )
    for verb, handler in (
        ("check", _handle_count),
        ("count", _handle_count),
        ("gold", _handle_gold),
        ("hits", _handle_hits),
        ("pray", _handle_pray),
        ("wink", _handle_wink),
        ("what?", _handle_ponder),
        ("where?", _handle_ponder),
        ("why?", _handle_ponder),
        ("how?", _handle_ponder),
    ):
        registry.register(
            CommandMetadata(verb=verb, command_id=vocabulary._lookup_command_id(verb)),
            handler,
        )
    registry.register(
        CommandMetadata(
            verb="look",
            command_id=vocabulary._lookup_command_id("look"),
        ),
        _handle_look,
    )
    registry.register(
        CommandMetadata(
            verb="examine",
            command_id=vocabulary._lookup_command_id("examine"),
        ),
        _handle_look,
    )
    registry.register(
        CommandMetadata(
            verb="see",
            command_id=vocabulary._lookup_command_id("see"),
        ),
        _handle_look,
    )
    registry.register(
        CommandMetadata(
            verb="read",
            command_id=vocabulary._lookup_command_id("read"),
            required_level=1,
            required_flags=int(constants.PlayerFlag.LOADED),
            failure_message_id="CMPCMD1",
        ),
        _handle_read,
    )
    for verb, handler in (("drink", _handle_drink), ("swallow", _handle_drink), ("rub", _handle_rub)):
        registry.register(
            CommandMetadata(
                verb=verb,
                command_id=vocabulary._lookup_command_id(verb),
                required_level=1,
                required_flags=int(constants.PlayerFlag.LOADED),
                failure_message_id="CMPCMD1",
            ),
            handler,
        )
    for verb in ("aim", "point"):
        registry.register(
            CommandMetadata(
                verb=verb,
                command_id=vocabulary._lookup_command_id(verb),
                required_level=1,
                required_flags=int(constants.PlayerFlag.LOADED),
                failure_message_id="CMPCMD1",
            ),
            _handle_aim,
        )

    for verb in ("learn", "memorize"):
        registry.register(
            CommandMetadata(
                verb=verb,
                command_id=vocabulary._lookup_command_id(verb),
                required_level=1,
                required_flags=int(constants.PlayerFlag.LOADED),
                failure_message_id="CMPCMD1",
            ),
            _handle_memorize,
        )
    for verb in ("cast", "chant"):
        registry.register(
            CommandMetadata(
                verb=verb,
                command_id=vocabulary._lookup_command_id(verb),
                required_level=1,
                required_flags=int(constants.PlayerFlag.LOADED),
                failure_message_id="CMPCMD1",
            ),
            _handle_cast,
        )
    registry.register(
        CommandMetadata(
            verb="spells",
            command_id=vocabulary._lookup_command_id("spells"),
        ),
        _handle_spells,
    )
    for verb in (
        "comfort",
        "cuddle",
        "embrace",
        "french",
        "hold",
        "love",
        "rape",
        "romance",
        "squeeze",
        "tickle",
    ):
        registry.register(
            CommandMetadata(
                verb=verb,
                command_id=vocabulary._lookup_command_id(verb),
                required_level=1 if vocabulary.commands[verb].payonl else 0,
                required_flags=int(constants.PlayerFlag.LOADED)
                if vocabulary.commands[verb].payonl
                else 0,
                failure_message_id="CMPCMD1" if vocabulary.commands[verb].payonl else None,
            ),
            _handle_kissr1,
        )
    for verb in ("hug", "kick", "kiss", "pinch", "punch", "slap", "smack", "smooch"):
        registry.register(
            CommandMetadata(
                verb=verb,
                command_id=vocabulary._lookup_command_id(verb),
                required_level=1 if vocabulary.commands[verb].payonl else 0,
                required_flags=int(constants.PlayerFlag.LOADED)
                if vocabulary.commands[verb].payonl
                else 0,
                failure_message_id="CMPCMD1" if vocabulary.commands[verb].payonl else None,
            ),
            _handle_kissr2,
        )
    for verb in ("concentrate", "meditate", "think"):
        registry.register(
            CommandMetadata(
                verb=verb,
                command_id=vocabulary._lookup_command_id(verb),
                required_level=1,
                required_flags=int(constants.PlayerFlag.LOADED),
                failure_message_id="CMPCMD1",
            ),
            _handle_think,
        )
    registry.register(
        CommandMetadata(
            verb="fly",
            command_id=vocabulary._lookup_command_id("fly"),
            required_level=1,
            required_flags=int(constants.PlayerFlag.LOADED),
            failure_message_id="CMPCMD1",
        ),
        _handle_fly,
    )
    for verb in ("push", "shove"):
        registry.register(
            CommandMetadata(
                verb=verb,
                command_id=vocabulary._lookup_command_id(verb),
                required_level=1,
                required_flags=int(constants.PlayerFlag.LOADED),
                failure_message_id="CMPCMD1",
            ),
            _handle_shove,
        )
    for verb in sorted(SIMPLE_EMOTES):
        registry.register(CommandMetadata(verb=verb), _handle_simple_emote)

    for command in vocabulary.iter_commands():
        verb = command.command.lower()
        if verb in registry.verbs():
            continue
        if vocabulary._direction_from_alias(verb) or verb in vocabulary.chat_aliases:
            continue
        if verb in {"inv", "inventory"}:
            continue
        if verb in _PICKUP_VERBS | {"drop"}:
            continue

        registry.register(
            CommandMetadata(
                verb=verb,
                command_id=command.id,
                required_level=1 if command.payonl else 0,
                required_flags=int(constants.PlayerFlag.LOADED)
                if command.payonl
                else 0,
                failure_message_id="CMPCMD1" if command.payonl else None,
            ),
            _handle_stub,
        )

    return registry


def _handle_read(state: GameState, args: dict) -> CommandResult:
    command_id = args.get("command_id")
    raw = (args.get("raw") or "").strip().lower()
    if raw == "spellbook":
        # Legacy reader() delegates `read spellbook` to looker()/seesbk() (legacy/KYRCMDS.C:1035-1056).
        return _handle_spellbook(state, args)

    objects = state.objects or {}
    inventory_index = _find_inventory_index(state.player, raw, objects)
    if inventory_index is None:
        return CommandResult(
            state=state,
            events=[
                _message_event(
                    "player",
                    "READER2",
                    _format_message(state, "READER2"),
                    command_id,
                )
            ],
        )

    object_id = state.player.gpobjs[inventory_index]
    obj = objects.get(object_id)
    if obj is None or "REDABL" not in obj.flags:
        return CommandResult(
            state=state,
            events=[
                _message_event(
                    "player",
                    "READER1",
                    _format_message(state, "READER1", obj.name if obj else raw),
                    command_id,
                )
            ],
        )

    # Ported from reader()/scroll() in legacy/KYRCMDS.C:1033-1145.
    pop_inventory_index(state.player, inventory_index)
    read_item = obj.name
    room_text = _format_message(
        state,
        "SCROLL1",
        state.player.altnam,
        _hisher(state.player),
        read_item,
    )
    events = [
        _message_event("room", None, room_text, command_id, exclude_player=state.player.plyrid),
    ]
    events[0]["room_id"] = state.player.gamloc

    spell_roll = state.rng.randrange(0, 111)
    if spell_roll < 67:
        spell = fixtures.load_spells()[spell_roll]
        events.append(
            _message_event(
                "player",
                "URSCRL",
                _format_message(state, "URSCRL", read_item, spell.name),
                command_id,
            )
        )
        add_spell_to_book(state.player, spell)
    else:
        failure = state.rng.randrange(0, 8)
        if failure == 0:
            forget_all_memorized(state.player)
            events.append(_message_event("player", "SCRLM0", _format_message(state, "SCRLM0", read_item), command_id))
        elif failure == 1:
            state.player.gpobjs.clear()
            state.player.obvals.clear()
            state.player.npobjs = 0
            events.append(_message_event("player", "SCRLM1", _format_message(state, "SCRLM1", read_item), command_id))
        elif failure == 2:
            state.player.gold = 0
            events.append(_message_event("player", "SCRLM2", _format_message(state, "SCRLM2", read_item), command_id))
        elif failure == 3:
            state.player.spts = 0
            events.append(_message_event("player", "SCRLM3", _format_message(state, "SCRLM3", read_item), command_id))
        elif failure == 4:
            target_room = state.rng.randrange(0, 169)
            from_room = state.player.gamloc
            events.append(_message_event("player", "SCRLM4", _format_message(state, "SCRLM4", read_item), command_id))
            events.append(
                _room_departure_event(
                    state,
                    from_room=from_room,
                    to_room=target_room,
                    command_id=command_id,
                    direction=None,
                    departure_text="vanished with a look of surprise",
                )
            )
            state.player.gamloc = target_room
            state.player.pgploc = target_room
            events.extend(
                _build_room_transition_events(
                    state,
                    from_room=from_room,
                    to_room=target_room,
                    command_id=command_id,
                    message_id=_command_message_id(command_id),
                    direction=None,
                    arrival_text=f"*** {state.player.altnam} has just appeared with a look of surprise!",
                )
            )
            events.append(_message_event("player", "SCRLM42", _format_message(state, "SCRLM42"), command_id))
        elif failure == 5:
            if len(state.player.gpobjs) < constants.MXPOBS:
                state.player.gpobjs.append(30)
                state.player.obvals.append(0)
                state.player.npobjs = len(state.player.gpobjs)
            events.append(_message_event("player", "SCRLM5", _format_message(state, "SCRLM5", read_item), command_id))
        elif failure == 6:
            surprise_item = state.rng.randrange(36, 38)
            label = "codex" if surprise_item == 36 else "tome"
            if len(state.player.gpobjs) < constants.MXPOBS:
                state.player.gpobjs.append(surprise_item)
                state.player.obvals.append(0)
                state.player.npobjs = len(state.player.gpobjs)
            events.append(_message_event("player", "SCRLM6", _format_message(state, "SCRLM6", read_item, label), command_id))
        else:
            damage = state.rng.randrange(2, 11)
            state.player.hitpts = max(0, state.player.hitpts - damage)
            events.append(_message_event("player", "SCRLM7", _format_message(state, "SCRLM7", read_item, damage), command_id))
            if state.player.hitpts <= 0:
                _append_hitoth_death_events(state, state.player, command_id, events)
                return CommandResult(state=state, events=events)

    _persist_player_state(state, state.player)
    return CommandResult(state=state, events=events)
