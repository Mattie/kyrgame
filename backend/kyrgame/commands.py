import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, List, Protocol, Set

from . import constants, fixtures, models, repositories, room_spoilers


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
            {
                **parsed.args,
                "command_id": parsed.command_id,
                "message_id": parsed.message_id,
                "verb": parsed.verb,
            },
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

_PICKUP_VERBS = {
    "get",
    "grab",
    "pickpocket",
    "pilfer",
    "snatch",
    "steal",
    "take",
}
# Pickup verbs mirror legacy getter aliases in KYRCMDS.C (gi_cmdarr).【F:legacy/KYRCMDS.C†L117-L174】


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
        occupants = await state.presence.players_in_room(location.id)
        target_player = None
        for occupant_id in occupants:
            if occupant_id == state.player.plyrid:
                continue
            candidate = state.player_lookup(occupant_id)
            if candidate and _matches_player_name(target, candidate):
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
                    ),
                ],
            )

    object_id = _find_object_in_location(location, objects, target)
    if object_id is None:
        raise CommandError(f"No {target} here", message_id=message_id)

    if len(state.player.gpobjs) >= constants.MXPOBS:
        raise CommandError("You cannot carry any more", message_id=message_id)

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
                _message_event("room", "GETLOC5", room_text, command_id),
            ],
        )

    remaining_objects = [oid for oid in location.objects if oid != object_id]
    location = location.model_copy(
        update={"objects": remaining_objects, "nlobjs": len(remaining_objects)}
    )
    state.locations[location.id] = location
    _persist_location_objects(state, location.id, remaining_objects)

    state.player.gpobjs.append(object_id)
    state.player.obvals.append(0)
    state.player.npobjs = len(state.player.gpobjs)

    return CommandResult(
        state=state,
        events=[
            _inventory_event(state, command_id, message_id),
            _room_objects_event(location, objects, command_id, message_id),
            _message_event(
                "room",
                "GETLOC7",
                _format_message(
                    state, "GETLOC7", state.player.altnam, obj.name, location.objlds
                ),
                command_id,
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
                ),
            ],
        )

    value = target_player.obvals.pop(inventory_index)
    target_player.gpobjs.pop(inventory_index)
    target_player.npobjs = len(target_player.gpobjs)
    state.player.gpobjs.append(obj_id)
    state.player.obvals.append(value)
    state.player.npobjs = len(state.player.gpobjs)

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
            ),
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
    _persist_location_objects(state, location.id, updated_objects)

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


def _matches_player_name(target: str, player: models.PlayerModel) -> bool:
    target_lower = target.lower()
    # Legacy: findgp matches against attnam only (KYRUTIL.C 472-484).
    return target_lower == player.attnam.lower()


def _can_see_player(viewer: models.PlayerModel, target: models.PlayerModel) -> bool:
    if target is viewer:
        return True
    if not (target.flags & constants.PlayerFlag.INVISF):
        return True
    return viewer.charms[constants.CharmSlot.INVISIBILITY] > 0


async def _find_player_in_room(
    state: GameState, target_name: str
) -> models.PlayerModel | None:
    if not state.presence or not state.player_lookup:
        return None
    occupants = await state.presence.players_in_room(state.player.gamloc)
    for occupant_id in occupants:
        candidate = state.player_lookup(occupant_id)
        if candidate and _matches_player_name(target_name, candidate):
            return candidate
    return None


def _message_event(
    scope: str,
    message_id: str | None,
    text: str | None,
    command_id: int | None,
    *,
    exclude_player: str | None = None,
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
    return event


def _handle_spellbook(state: GameState, args: dict) -> CommandResult:
    command_id = args.get("command_id")
    message_id = args.get("message_id") or _command_message_id(command_id)
    header_text = _format_message(state, "SBOOK1", state.player.plyrid, state.player.altnam)
    return CommandResult(
        state=state,
        events=[
            _message_event("player", "SBOOK1", header_text, command_id),
            _message_event("player", "SBOOK4", _format_message(state, "SBOOK4"), command_id),
            {
                "scope": "player",
                "event": "unimplemented",
                "type": "unimplemented",
                "detail": "Spellbook listing not yet implemented",
                "command_id": command_id,
                "message_id": message_id,
            },
        ],
    )


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
            events.append(_message_event("room", "LOOKER1", looker_text, command_id))
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
            events.append(_message_event("room", "LOOKER2", looker_text, command_id))
            return CommandResult(state=state, events=events)

        target_player = None
        if _matches_player_name(raw, state.player):
            target_player = state.player
        elif state.presence and state.player_lookup:
            occupants = await state.presence.players_in_room(state.player.gamloc)
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
                desc_id = "WILDES"
                desc_text = _format_message(state, desc_id)
            elif target_player.flags & constants.PlayerFlag.PEGASU:
                desc_id = "PEGDES"
                desc_text = _format_message(state, desc_id)
            elif target_player.flags & constants.PlayerFlag.PDRAGN:
                desc_id = "PDRDES"
                desc_text = _format_message(state, desc_id)
            else:
                desc_id = _player_description_message_id(target_player)
                base_text = _format_message(state, desc_id, target_player.plyrid)
                inventory_text = _inventory_summary_text(state, target_player, objects)
                desc_text = f"{base_text} {inventory_text}".strip() if base_text else inventory_text

            events.append(_message_event("player", desc_id, desc_text, command_id))

            looker3_text = _format_message(state, "LOOKER3", state.player.altnam)
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
                )
            )
            return CommandResult(state=state, events=events)

        if target == "brief":
            looker_text = _format_message(state, "LOOKER5", location.brfdes)
            events.append(_message_event("player", "LOOKER5", looker_text, command_id))
            events.append(
                _room_objects_event(location, objects, command_id, message_id)
            )
            occupants_event = await _room_occupants_event(state, location.id)
            if occupants_event:
                events.append(occupants_event)
            return CommandResult(state=state, events=events)

        if target == "spellbook":
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


def _persist_location_objects(state: GameState, location_id: int, object_ids: list[int]):
    """Persist location object changes to database so they survive server restarts."""
    if state.db_session:
        location_repo = repositories.LocationRepository(state.db_session)
        location_repo.update_objects(location_id, object_ids)
        state.db_session.commit()


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
        return f"{occupants[0]} {suffix}", message_id

    suffix = catalog.get("KUTM12", "are here.")
    message_id = "KUTM12" if "KUTM12" in catalog else None
    if len(occupants) == 2:
        names = f"{occupants[0]} and {occupants[1]}"
    else:
        names = ", ".join(occupants[:-1]) + f", and {occupants[-1]}"
    return f"{names} {suffix}", message_id


async def _room_occupants_event(state: GameState, room_id: int) -> dict | None:
    if not state.presence:
        return None
    occupants = await state.presence.players_in_room(room_id)
    others = sorted(occupant for occupant in occupants if occupant != state.player.plyrid)
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
    if player.charms[constants.CharmSlot.ALTERNATE_NAME] > 0:
        return "its"
    return "her" if player.flags & constants.PlayerFlag.FEMALE else "his"


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
        needs_an = "NEEDAN" in obj.flags
        article = "an" if needs_an else "a"
        item_names.append(f"{article} {obj.name}")

    catalog = state.messages.messages if state.messages else {}
    and_text = catalog.get("KUTM08", "and")
    spellbook_template = catalog.get("KUTM09", "%s spellbook.")
    spellbook_text = spellbook_template % _hisher(target)

    if item_names:
        return f"{', '.join(item_names)}, {and_text} {spellbook_text}"
    return spellbook_text


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
