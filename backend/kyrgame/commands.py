import asyncio
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, List, Mapping, Protocol

from . import constants, fixtures, models


class CommandError(Exception):
    """Base exception for command dispatch problems."""


class UnknownCommandError(CommandError):
    def __init__(self, verb: str, message_id: str | None = None):
        super().__init__(verb)
        self.message_id = message_id


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
    location_mappings: Mapping[int | str, str] | None = None
    cooldowns: Dict[str, float] = field(default_factory=dict)


@dataclass
class CommandResult:
    state: GameState
    events: List[dict] = field(default_factory=list)


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
        if parsed.pay_only and not state.player.flags & constants.PlayerFlag.LOADED:
            raise FlagRequirementError(
                "Command requires a live player", message_id="CMPCMD1"
            )
        return await self.dispatch(
            parsed.verb,
            {**parsed.args, "command_id": parsed.command_id, "message_id": parsed.message_id},
            state,
        )

    async def dispatch(self, verb: str, args: dict, state: GameState) -> CommandResult:
        entry = self.registry.get(verb)
        if entry is None:
            raise UnknownCommandError(verb)

        metadata = entry.metadata
        self._validate_requirements(metadata, state)

        now = self.clock()
        if metadata.cooldown_seconds:
            self._validate_cooldown(verb, metadata, state, now)

        result = entry.handler(state, args)
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


def _command_message_id(command_id: int | None) -> str | None:
    if command_id is None:
        return None
    return f"CMD{command_id:03d}"


def _location_message_key(state: GameState, location_id: int) -> str:
    if state.location_mappings:
        mapped = state.location_mappings.get(location_id) or state.location_mappings.get(
            str(location_id)
        )
        if mapped:
            return mapped
    return f"KRD{location_id:03d}"


def _location_description(state: GameState, location_id: int) -> str | None:
    if not state.messages:
        return None
    key = _location_message_key(state, location_id)
    return state.messages.messages.get(key)


def _article_for_object(obj: models.GameObjectModel) -> str:
    prefix = "an" if "NEEDAN" in obj.flags else "a"
    return f"{prefix} {obj.name}"


def _inventory_event(state: GameState, command_id: int | None, message_id: str | None) -> dict:
    objects = state.objects or {}
    items = []
    for obj_id in state.player.gpobjs:
        if obj := objects.get(obj_id):
            items.append(_article_for_object(obj))
        else:
            items.append(f"object {obj_id}")

    return {
        "scope": "player",
        "event": "inventory",
        "type": "inventory",
        # Legacy reference: KYRUTIL.C lines 323-356 format inventory with
        # indefinite articles and gold totals.
        "inventory": items,
        "gold": state.player.gold,
        "command_id": command_id,
        "message_id": message_id,
    }


def _handle_move(state: GameState, args: dict) -> CommandResult:
    direction = args.get("direction")
    if direction not in _DIRECTION_FIELDS:
        raise InvalidDirectionError(f"Unknown direction: {direction}")

    command_id = args.get("command_id")
    message_id = args.get("message_id") or _command_message_id(command_id)
    current = state.locations[state.player.gamloc]
    target_id = getattr(current, _DIRECTION_FIELDS[direction])
    if target_id < 0 or target_id not in state.locations:
        raise BlockedExitError(f"No exit {direction} from location {current.id}")

    state.player.pgploc = state.player.gamloc
    state.player.gamloc = target_id
    destination = state.locations[target_id]
    description = _location_description(state, destination.id) or destination.brfdes

    return CommandResult(
        state=state,
        events=[
            {
                "scope": "room",
                "event": "player_enter",
                "type": "player_moved",
                "player": state.player.plyrid,
                "from": current.id,
                "to": destination.id,
                "description": description,
                "command_id": command_id,
                "message_id": message_id,
            },
            {
                "scope": "player",
                "event": "location_update",
                "type": "location_update",
                "location": destination.id,
                "description": description,
                "brief_description": destination.brfdes,
                # Legacy reference: KYRUTIL.C lines 236-254 print the room's default
                # description (brief or long) when entering a location.
                "command_id": command_id,
                "message_id": message_id,
            }
        ],
    )


def _handle_chat(state: GameState, args: dict) -> CommandResult:
    text = args.get("text", "").strip()
    command_id = args.get("command_id")
    message_id = args.get("message_id") or _command_message_id(command_id)
    mode = args.get("mode", "say")
    return CommandResult(
        state=state,
        events=[
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
        ],
    )


def _handle_inventory(state: GameState, args: dict) -> CommandResult:  # noqa: ARG001
    command_id = args.get("command_id")
    message_id = args.get("message_id") or _command_message_id(command_id)

    return CommandResult(
        state=state,
        events=[_inventory_event(state, command_id, message_id)],
    )


def _handle_get(state: GameState, args: dict) -> CommandResult:
    target = (args.get("object") or args.get("raw") or "").strip().lower()
    if not target:
        raise CommandError("Specify an object to pick up")

    command_id = args.get("command_id")
    message_id = args.get("message_id") or _command_message_id(command_id)
    location = state.locations[state.player.gamloc]

    obj_id = next(
        (
            candidate
            for candidate in location.objects
            if (obj := state.objects.get(candidate))
            and obj.name.lower() == target
        ),
        None,
    )
    if obj_id is None:
        raise CommandError(f"No {target} available here")

    obj = state.objects[obj_id]
    if "PICKUP" not in obj.flags:
        raise CommandError(f"{obj.name} cannot be picked up")
    if len(state.player.gpobjs) >= constants.MXPOBS:
        raise CommandError("Inventory is full")

    if obj_id in location.objects:
        location.objects.remove(obj_id)
        location.nlobjs = len(location.objects)

    state.player.gpobjs.append(obj_id)
    state.player.obvals.append(0)
    state.player.npobjs = len(state.player.gpobjs)

    return CommandResult(
        state=state,
        events=[
            {
                "scope": "room",
                "event": "player_pickup",
                "type": "inventory_update",
                # Legacy reference: KYRCMDS.C lines 702-736 guard pickup rules
                # (visibility, pickup flag, capacity) before moving an object.
                "player": state.player.plyrid,
                "object": obj.name,
                "command_id": command_id,
                "message_id": message_id,
            },
            _inventory_event(state, command_id, message_id),
        ],
    )


def _handle_drop(state: GameState, args: dict) -> CommandResult:
    target = (args.get("object") or args.get("raw") or "").strip().lower()
    if not target:
        raise CommandError("Specify an object to drop")

    command_id = args.get("command_id")
    message_id = args.get("message_id") or _command_message_id(command_id)
    location = state.locations[state.player.gamloc]

    try:
        idx = next(
            i
            for i, obj_id in enumerate(state.player.gpobjs)
            if state.objects.get(obj_id) and state.objects[obj_id].name.lower() == target
        )
    except StopIteration as exc:
        raise CommandError(f"You are not carrying {target}") from exc

    if len(location.objects) >= constants.MXLOBS:
        raise CommandError("There is no room to drop that here")

    obj_id = state.player.gpobjs.pop(idx)
    state.player.obvals.pop(idx)
    state.player.npobjs = len(state.player.gpobjs)

    location.objects.append(obj_id)
    location.nlobjs = len(location.objects)

    obj = state.objects.get(obj_id)
    return CommandResult(
        state=state,
        events=[
            {
                "scope": "room",
                "event": "player_drop",
                "type": "inventory_update",
                # Legacy reference: KYRCMDS.C lines 862-892 enforce room capacity
                # when dropping items before updating shared state.
                "player": state.player.plyrid,
                "object": obj.name if obj else target,
                "command_id": command_id,
                "message_id": message_id,
            },
            _inventory_event(state, command_id, message_id),
        ],
    )


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


class CommandVocabulary:
    """Fixture-driven parser for mapping raw command text to dispatcher inputs."""

    chat_aliases = {
        "say",
        "comment",
        "note",
        "shout",
        "scream",
        "shriek",
        "yell",
        "whisper",
    }

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

    def parse_text(self, text: str) -> ParsedCommand:
        raw = (text or "").strip()
        if not raw:
            raise UnknownCommandError(text)

        tokens = raw.split()
        verb = tokens[0].lower()
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

        if verb in self.chat_aliases:
            command_id = command_id or self._lookup_command_id("say")
            message_id = message_id or self._message_for_command(command_id)
            return ParsedCommand(
                verb="chat",
                args={"text": remainder, "mode": verb},
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

        return ParsedCommand(
            verb=verb,
            args={"raw": remainder},
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
    registry.register(CommandMetadata(verb="move", required_level=1), _handle_move)
    registry.register(CommandMetadata(verb="chat", cooldown_seconds=1.5), _handle_chat)
    registry.register(CommandMetadata(verb="inventory"), _handle_inventory)

    get_entry = vocabulary.commands.get("get")
    drop_entry = vocabulary.commands.get("drop")

    if get_entry:
        registry.register(
            CommandMetadata(
                verb="get",
                command_id=get_entry.id,
                required_level=1 if get_entry.payonl else 0,
                required_flags=int(constants.PlayerFlag.LOADED)
                if get_entry.payonl
                else 0,
                failure_message_id="CMPCMD1" if get_entry.payonl else None,
            ),
            _handle_get,
        )

    if drop_entry:
        registry.register(
            CommandMetadata(
                verb="drop",
                command_id=drop_entry.id,
                required_level=1 if drop_entry.payonl else 0,
                required_flags=int(constants.PlayerFlag.LOADED)
                if drop_entry.payonl
                else 0,
                failure_message_id="CMPCMD1" if drop_entry.payonl else None,
            ),
            _handle_drop,
        )

    for command in vocabulary.iter_commands():
        verb = command.command.lower()
        if verb in registry.verbs():
            continue
        if vocabulary._direction_from_alias(verb) or verb in vocabulary.chat_aliases:
            continue
        if verb in {"inv", "inventory"}:
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
