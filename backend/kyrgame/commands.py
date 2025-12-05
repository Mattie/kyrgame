import asyncio
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, List, Protocol

from . import models


class CommandError(Exception):
    """Base exception for command dispatch problems."""


class UnknownCommandError(CommandError):
    pass


class LevelRequirementError(CommandError):
    pass


class FlagRequirementError(CommandError):
    pass


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
    required_level: int = 0
    required_flags: int = 0
    cooldown_seconds: float = 0.0


@dataclass
class RegisteredCommand:
    metadata: CommandMetadata
    handler: CommandHandler


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
                f"Command '{metadata.verb}' requires level {metadata.required_level}"
            )
        if metadata.required_flags and (state.player.flags & metadata.required_flags) != metadata.required_flags:
            raise FlagRequirementError(
                f"Command '{metadata.verb}' requires flags {metadata.required_flags:#x}"
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


def _handle_move(state: GameState, args: dict) -> CommandResult:
    direction = args.get("direction")
    if direction not in _DIRECTION_FIELDS:
        raise InvalidDirectionError(f"Unknown direction: {direction}")

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
                "type": "player_moved",
                "from": current.id,
                "to": destination.id,
                "description": destination.brfdes,
            }
        ],
    )


def _handle_chat(state: GameState, args: dict) -> CommandResult:
    text = args.get("text", "").strip()
    return CommandResult(
        state=state,
        events=[{"type": "chat", "from": state.player.plyrid, "text": text, "location": state.player.gamloc}],
    )


def _handle_inventory(state: GameState, args: dict) -> CommandResult:  # noqa: ARG001
    objects = state.objects or {}
    items = []
    for obj_id in state.player.gpobjs:
        entry = {"id": obj_id}
        if obj_id in objects:
            entry["name"] = objects[obj_id].name
        items.append(entry)

    return CommandResult(state=state, events=[{"type": "inventory", "items": items}])


def build_default_registry() -> CommandRegistry:
    registry = CommandRegistry()
    registry.register(CommandMetadata(verb="move", required_level=1), _handle_move)
    registry.register(CommandMetadata(verb="chat", cooldown_seconds=1.5), _handle_chat)
    registry.register(CommandMetadata(verb="inventory"), _handle_inventory)
    return registry
