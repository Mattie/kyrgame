import asyncio
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, List, Protocol

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
                "description": destination.brfdes,
                "command_id": command_id,
                "message_id": message_id,
            },
            {
                "scope": "player",
                "event": "location_update",
                "type": "location_update",
                "location": destination.id,
                "description": destination.brfdes,
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
    objects = state.objects or {}
    command_id = args.get("command_id")
    message_id = args.get("message_id") or _command_message_id(command_id)
    items = []
    for obj_id in state.player.gpobjs:
        entry = {"id": obj_id}
        if obj_id in objects:
            entry["name"] = objects[obj_id].name
        items.append(entry)

    return CommandResult(
        state=state,
        events=[
            {
                "scope": "player",
                "event": "inventory",
                "type": "inventory",
                "items": items,
                "command_id": command_id,
                "message_id": message_id,
            }
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
