import asyncio
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, List, Protocol

from . import constants, fixtures, models


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


def _handle_move(state: GameState, args: dict) -> CommandResult:
    direction = args.get("direction")
    if direction not in _DIRECTION_FIELDS:
        raise InvalidDirectionError(f"Unknown direction: {direction}")

    command_id = args.get("command_id")
    message_id = args.get("message_id") or _command_message_id(command_id)
    objects = state.objects or {}
    current = state.locations[state.player.gamloc]
    target_id = getattr(current, _DIRECTION_FIELDS[direction])
    if target_id == -1 or target_id not in state.locations:
        raise BlockedExitError(
            f"No exit {direction} from location {current.id}", message_id="MOVUTL"
        )

    state.player.pgploc = state.player.gamloc
    state.player.gamloc = target_id
    destination = state.locations[target_id]

    # Mirrors movutl/entrgp in legacy/KYRCMDS.C and KYRUTIL.C for movement flow.【F:legacy/KYRCMDS.C†L328-L366】【F:legacy/KYRUTIL.C†L236-L255】
    description_id, long_description = _location_description(state, destination)
    arrival_phrase = _arrival_text(direction)
    arrival_text = f"*** {state.player.plyrid} has just {arrival_phrase}!"

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
                "scope": "room",
                "event": "room_message",
                "type": "room_message",
                "player": state.player.plyrid,
                "from": current.id,
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
            },
            # Mirror locobjs call in legacy entrgp to describe visible room objects on entry.【F:legacy/KYRUTIL.C†L248-L266】
            _room_objects_event(
                destination,
                objects,
                command_id,
                message_id,
            ),
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

    # Mirrors gi_invrou/gi_invutl from legacy/KYRUTIL.C for inventory listing output.【F:legacy/KYRUTIL.C†L311-L338】
    return CommandResult(
        state=state,
        events=[_inventory_event(state, command_id, message_id)],
    )


def _handle_get(state: GameState, args: dict) -> CommandResult:
    # Ported from getter in legacy/KYRCMDS.C for picking up room objects.【F:legacy/KYRCMDS.C†L633-L651】
    command_id = args.get("command_id")
    message_id = args.get("message_id") or _command_message_id(command_id)
    target = (args.get("target") or "").strip().lower()

    if not target:
        raise CommandError("Specify an item to pick up", message_id=message_id)

    location = state.locations[state.player.gamloc]
    objects = state.objects or {}
    object_id = _find_object_in_location(location, objects, target)
    if object_id is None:
        raise CommandError(f"No {target} here", message_id=message_id)

    if len(state.player.gpobjs) >= constants.MXPOBS:
        raise CommandError("You cannot carry any more", message_id=message_id)

    obj = objects.get(object_id)
    if obj is None or "PICKUP" not in obj.flags:
        raise CommandError("You cannot pick that up", message_id=message_id)

    remaining_objects = [oid for oid in location.objects if oid != object_id]
    location = location.model_copy(
        update={"objects": remaining_objects, "nlobjs": len(remaining_objects)}
    )
    state.locations[location.id] = location

    state.player.gpobjs.append(object_id)
    state.player.obvals.append(0)
    state.player.npobjs = len(state.player.gpobjs)

    return CommandResult(
        state=state,
        events=[
            _inventory_event(state, command_id, message_id),
            _room_objects_event(location, objects, command_id, message_id),
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


def _handle_drop(state: GameState, args: dict) -> CommandResult:
    # Ported from dropit in legacy/KYRCMDS.C when moving items back to the room.【F:legacy/KYRCMDS.C†L862-L892】
    command_id = args.get("command_id")
    message_id = args.get("message_id") or _command_message_id(command_id)
    target = (args.get("target") or "").strip().lower()

    if not target:
        raise CommandError("Specify an item to drop", message_id=message_id)

    objects = state.objects or {}
    location = state.locations[state.player.gamloc]
    if len(location.objects) >= constants.MXLOBS:
        raise CommandError("There is no room to drop that here", message_id=message_id)

    inventory_index = _find_inventory_index(state.player, target, objects)
    if inventory_index is None:
        raise CommandError("You are not carrying that", message_id=message_id)

    object_id = state.player.gpobjs.pop(inventory_index)
    if len(state.player.obvals) > inventory_index:
        state.player.obvals.pop(inventory_index)
    state.player.npobjs = len(state.player.gpobjs)

    updated_objects = list(location.objects) + [object_id]
    location = location.model_copy(
        update={"objects": updated_objects, "nlobjs": len(updated_objects)}
    )
    state.locations[location.id] = location

    obj = objects.get(object_id)

    return CommandResult(
        state=state,
        events=[
            _inventory_event(state, command_id, message_id),
            _room_objects_event(location, objects, command_id, message_id),
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


def _location_message_id(location_id: int, content_mappings: dict[str, dict[str, str]] | None) -> str:
    if content_mappings and "locations" in content_mappings:
        mapping = content_mappings["locations"]
        if str(location_id) in mapping:
            return mapping[str(location_id)]
    return f"KRD{location_id:03d}"


def _location_description(state: GameState, location: models.LocationModel) -> tuple[str, str | None]:
    if state.player.flags & constants.PlayerFlag.BRFSTF:
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


def _room_objects_event(
    location: models.LocationModel,
    objects: dict[int, models.GameObjectModel],
    command_id: int | None,
    message_id: str | None,
) -> dict:
    visible = []
    for obj_id in location.objects:
        entry = {"id": obj_id}
        obj = objects.get(obj_id)
        if obj:
            entry["name"] = obj.name
        visible.append(entry)
    return {
        "scope": "player",
        "event": "room_objects",
        "type": "room_objects",
        "objects": visible,
        "location": location.id,
        "command_id": command_id,
        "message_id": message_id,
    }


def _find_object_in_location(
    location: models.LocationModel, objects: dict[int, models.GameObjectModel], target: str
) -> int | None:
    target_lower = target.lower()
    for obj_id in location.objects:
        obj = objects.get(obj_id)
        if obj and obj.name.lower() == target_lower:
            return obj_id
    return None


def _find_inventory_index(
    player: models.PlayerModel, target: str, objects: dict[int, models.GameObjectModel]
) -> int | None:
    target_lower = target.lower()
    for idx, obj_id in enumerate(player.gpobjs):
        obj = objects.get(obj_id)
        if obj and obj.name.lower() == target_lower:
            return idx
    return None


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

        if verb in {"get", "grab", "drop"}:
            command_id = command_id or self._lookup_command_id(verb)
            message_id = message_id or self._message_for_command(command_id)
            return ParsedCommand(
                verb=verb,
                args={"target": remainder},
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
    registry.register(
        CommandMetadata(
            verb="move",
            required_level=1,
            required_flags=int(constants.PlayerFlag.LOADED),
            failure_message_id="CMPCMD1",
        ),
        _handle_move,
    )
    registry.register(CommandMetadata(verb="chat", cooldown_seconds=1.5), _handle_chat)
    registry.register(CommandMetadata(verb="inventory"), _handle_inventory)
    registry.register(
        CommandMetadata(
            verb="get",
            command_id=vocabulary._lookup_command_id("get"),
            required_level=1,
            required_flags=int(constants.PlayerFlag.LOADED),
            failure_message_id="CMPCMD1",
        ),
        _handle_get,
    )
    registry.register(
        CommandMetadata(
            verb="grab",
            command_id=vocabulary._lookup_command_id("grab"),
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

    for command in vocabulary.iter_commands():
        verb = command.command.lower()
        if verb in registry.verbs():
            continue
        if vocabulary._direction_from_alias(verb) or verb in vocabulary.chat_aliases:
            continue
        if verb in {"inv", "inventory"}:
            continue
        if verb in {"get", "grab", "drop"}:
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
