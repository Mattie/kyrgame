from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Any, Iterable, Optional

import yaml

from . import constants, models


@dataclass
class RoomHandleResult:
    handled: bool
    events: list[dict]


def extract_room_spoilers(definitions: dict) -> dict[int, dict[str, str | None]]:
    spoilers: dict[int, dict[str, str | None]] = {}
    for room in definitions.get("rooms", []):
        room_id = room.get("id")
        if room_id is None:
            continue
        summary = room.get("spoiler_summary")
        interaction = room.get("spoiler_interaction")
        legacy_ref = room.get("legacy_ref")
        if not (summary or interaction or legacy_ref):
            continue
        spoilers[int(room_id)] = {
            "summary": summary,
            "interaction": interaction,
            "legacy_ref": legacy_ref,
        }
    return spoilers


class YamlRoomEngine:
    """Interpret YAML-defined room behaviors against a player state."""

    def __init__(
        self,
        definitions: dict,
        messages: models.MessageBundleModel,
        objects: Iterable[models.GameObjectModel],
        spells: Iterable[models.SpellModel],
        rng: random.Random | None = None,
        locations: Iterable[models.LocationModel] | None = None,
    ):
        self.messages = messages
        self.rooms = {room["id"]: room for room in definitions.get("rooms", [])}
        self.objects_by_name = {obj.name.lower(): obj for obj in objects}
        self.spells_by_name = {spell.name.lower(): spell for spell in spells}
        self.rng = rng or random.Random()
        self.room_state_defaults: dict[int, dict] = {
            room_id: room.get("state", {})
            for room_id, room in ((room.get("id"), room) for room in self.rooms.values())
            if room_id is not None
        }
        self.room_states: dict[int, dict] = {}
        self.room_object_defaults: dict[int, list[int]] = {}
        self.room_objects: dict[int, list[int]] = {}

        for location in locations or []:
            if hasattr(location, "id"):
                room_id = location.id  # type: ignore[attr-defined]
                objects = list(getattr(location, "objects", []) or [])
            else:
                room_id = location.get("id") if isinstance(location, dict) else None
                objects = list(location.get("objects", [])) if isinstance(location, dict) else []

            if room_id is not None:
                self.room_object_defaults[room_id] = objects

    def handle(
        self,
        player: models.PlayerModel,
        room_id: int,
        command: str,
        args: Optional[list[str]] = None,
    ) -> RoomHandleResult:
        args = args or []
        room = self.rooms.get(room_id)
        if not room:
            return RoomHandleResult(handled=False, events=[])

        context: dict[str, Any] = self._base_context(player, args)
        context.update(
            {
                "room_id": room_id,
                "room_state": self._get_room_state(room_id),
                "room_objects": self._get_room_objects(room_id),
            }
        )
        events: list[dict] = []

        for trigger in room.get("triggers", []):
            if not self._matches_trigger(trigger, command, args, room_id):
                continue
            self._execute_actions(
                trigger.get("actions", []), player, args, context, events, room_id
            )
            return RoomHandleResult(handled=True, events=events)

        return RoomHandleResult(handled=False, events=events)

    def _matches_trigger(
        self, trigger: dict, command: str, args: list[str], room_id: int
    ) -> bool:
        verb = command.lower()
        verbs = {v.lower() for v in trigger.get("verbs", [])}
        if verbs and verb not in verbs:
            return False

        phrase_key = trigger.get("match_phrase_key")
        if phrase_key:
            target_phrase = self.messages.messages.get(phrase_key, "").lower()
            attempt = " ".join([command, *args]).lower()
            return attempt == target_phrase

        target_terms = {term.lower() for term in trigger.get("target_in", [])}
        if target_terms:
            return args and args[0].lower() in target_terms

        sequence = [arg.lower() for arg in trigger.get("arg_sequence", [])]
        if sequence:
            if len(args) < len(sequence):
                return False
            if any(args[idx].lower() != expected for idx, expected in enumerate(sequence)):
                return False

        arg_at = trigger.get("arg_at")
        if arg_at:
            index = int(arg_at.get("index", 0))
            value = str(arg_at.get("value", "")).lower()
            if len(args) <= index or args[index].lower() != value:
                return False

        required_state = trigger.get("room_state_at_least", {})
        if required_state:
            state = self._get_room_state(room_id)
            for key, value in required_state.items():
                if state.get(key, self.room_state_defaults.get(room_id, {}).get(key, 0)) < int(value):
                    return False

        return True

    def _execute_actions(
        self,
        actions: list[dict],
        player: models.PlayerModel,
        args: list[str],
        context: dict[str, Any],
        events: list[dict],
        room_id: int,
    ):
        for action in actions:
            action_type = action.get("type")
            if action_type == "branch_by_item":
                self._action_branch_by_item(action, player, args, context, events, room_id)
            elif action_type == "remove_item":
                self._action_remove_item(action, player, context)
            elif action_type == "add_gold":
                self._action_add_gold(action, player, context)
            elif action_type == "grant_object":
                self._action_grant_object(action, player, context, events, room_id)
            elif action_type == "message":
                self._action_message(action, player, context, events)
            elif action_type == "heal":
                self._action_heal(action, player)
            elif action_type == "damage":
                self._action_damage(action, player)
            elif action_type == "grant_spell":
                self._action_grant_spell(action, player, context)
            elif action_type == "random_chance":
                self._action_random_chance(action, player, args, context, events, room_id)
            elif action_type == "random_range":
                self._action_random_range(action, context)
            elif action_type == "random_choice":
                self._action_random_choice(action, player, args, context, events, room_id)
            elif action_type == "conditional":
                self._action_conditional(action, player, args, context, events, room_id)
            elif action_type == "purchase_spell":
                self._action_purchase_spell(action, player, args, context, events, room_id)
            elif action_type == "level_gate":
                self._action_level_gate(action, player, context, events, room_id)
            elif action_type == "add_room_object":
                self._action_add_room_object(action, player, context, events, room_id)
            elif action_type == "increment_room_state":
                self._action_increment_room_state(action, context, room_id)

    def _action_branch_by_item(
        self,
        action: dict,
        player: models.PlayerModel,
        args: list[str],
        context: dict[str, Any],
        events: list[dict],
        room_id: int,
    ):
        target_idx = action.get("target_arg", 0)
        target_name = args[target_idx].lower() if len(args) > target_idx else None

        branch_actions: list[dict] | None = None
        inventory_index: int | None = None
        if target_name:
            obj = self.objects_by_name.get(target_name)
            if obj is not None:
                inventory_index = self._find_inventory_index(player, obj.id)
                if inventory_index is not None:
                    context["target_item_id"] = obj.id
                    context["target_item_name"] = obj.name
                    context["item_article"] = self._article_for_object(obj)
                    branch_actions = action.get("cases", {}).get(target_name)
                else:
                    branch_actions = action.get("missing_actions")
            else:
                branch_actions = action.get("missing_actions")
        else:
            branch_actions = action.get("missing_actions")

        if branch_actions is None:
            branch_actions = action.get("default_actions", [])

        if isinstance(branch_actions, dict):
            branch_actions = branch_actions.get("actions", [])

        if branch_actions is action.get("default_actions") and action.get("default_requires_item", True):
            # If a default branch expects the item to be present, treat absence as missing.
            if target_name and target_name in self.objects_by_name and inventory_index is None:
                self._execute_actions(
                    action.get("missing_actions", []), player, args, context, events, room_id
                )
                return

        self._execute_actions(branch_actions or [], player, args, context, events, room_id)

    def _action_remove_item(self, action: dict, player: models.PlayerModel, context: dict[str, Any]):
        item_name = action.get("item")
        obj_id = None
        if item_name:
            obj = self.objects_by_name.get(item_name.lower())
            if obj:
                obj_id = obj.id
        else:
            obj_id = context.get("target_item_id")

        if obj_id is None:
            return

        idx = self._find_inventory_index(player, obj_id)
        if idx is not None:
            self._remove_inventory_index(player, idx)

    def _action_add_gold(self, action: dict, player: models.PlayerModel, context: dict[str, Any]):
        amount = action.get("amount", 0)
        if isinstance(amount, str):
            amount = context.get(amount, 0)
        player.gold += int(amount)
        if "context_key" in action:
            context[action["context_key"]] = int(amount)

    def _action_grant_object(
        self,
        action: dict,
        player: models.PlayerModel,
        context: dict[str, Any],
        events: list[dict],
        room_id: int | None,
    ):
        obj_name = action.get("object")
        obj = self.objects_by_name.get(obj_name.lower()) if obj_name else None
        if obj is None:
            return

        if len(player.gpobjs) >= constants.MXPOBS:
            target_room = room_id if room_id is not None else -1
            self._execute_actions(
                action.get("on_full", []), player, [], context, events, target_room
            )
            return

        player.gpobjs.append(obj.id)
        player.obvals.append(0)
        player.npobjs = len(player.gpobjs)
        context["granted_object_id"] = obj.id
        context["granted_object_name"] = obj.name

    def _action_message(
        self,
        action: dict,
        player: models.PlayerModel,
        context: dict[str, Any],
        events: list[dict],
    ):
        message_id = action.get("message_id")
        text = action.get("text")
        format_args = action.get("format", [])
        if text is None and message_id:
            text = self.messages.messages.get(message_id, "")

        if format_args and text:
            values = [context.get(arg, arg) for arg in format_args]
            try:
                text = text % tuple(values)
            except TypeError:
                text = text % tuple(str(val) for val in values)

        if text is None:
            return

        events.append(
            {
                "scope": action.get("scope", "direct"),
                "event": "room_message",
                "message_id": message_id,
                "text": text,
                "player": player.plyrid,
            }
        )

    def _action_heal(self, action: dict, player: models.PlayerModel):
        amount = int(action.get("amount", 0))
        cap_per_level = action.get("cap_per_level")
        player.hitpts += amount
        if cap_per_level:
            cap = player.level * int(cap_per_level)
            player.hitpts = min(player.hitpts, cap)

    def _action_damage(self, action: dict, player: models.PlayerModel):
        amount = max(0, int(action.get("amount", 0)))
        player.hitpts = max(0, player.hitpts - amount)

    def _action_grant_spell(
        self, action: dict, player: models.PlayerModel, context: dict[str, Any]
    ):
        """Grant a spell bit and optional memorization slot (e.g., druid orb routine in legacy/KYRROUS.C lines 620-639)."""
        spell_name = action.get("spell")
        spell = self.spells_by_name.get(spell_name.lower()) if spell_name else None
        if spell is None:
            return

        sbkref = spell.sbkref
        override = action.get("book")
        if isinstance(override, str):
            normalized = override.lower()
            if normalized in {"offense", "offensive"}:
                sbkref = constants.OFFENS
            elif normalized in {"defense", "defensive"}:
                sbkref = constants.DEFENS
            elif normalized in {"other", "others"}:
                sbkref = constants.OTHERS
        elif isinstance(override, int):
            sbkref = override

        if sbkref == constants.OFFENS:
            player.offspls |= spell.bitdef
        elif sbkref == constants.DEFENS:
            player.defspls |= spell.bitdef
        else:
            player.othspls |= spell.bitdef

        if spell.id not in player.spells and len(player.spells) < constants.MAXSPL:
            player.spells.append(spell.id)
            player.nspells = len(player.spells)

        context["granted_spell_id"] = spell.id
        context["granted_spell_name"] = spell.name

    def _action_random_chance(
        self,
        action: dict,
        player: models.PlayerModel,
        args: list[str],
        context: dict[str, Any],
        events: list[dict],
        room_id: int,
    ):
        probability = float(action.get("probability", 0))
        roll = self.rng.random()
        branch = action.get("on_success", []) if roll < probability else action.get("on_failure", [])
        self._execute_actions(branch, player, args, context, events, room_id)

    def _action_random_range(self, action: dict, context: dict[str, Any]):
        start = int(action.get("start", 0))
        stop = int(action.get("stop", 0))
        value = self.rng.randrange(start, stop)
        if "context_key" in action:
            context[action["context_key"]] = value

    def _action_random_choice(
        self,
        action: dict,
        player: models.PlayerModel,
        args: list[str],
        context: dict[str, Any],
        events: list[dict],
        room_id: int,
    ):
        """Randomly select a weighted branch (used for spell rolls like the druid orb interaction)."""
        choices = action.get("choices", [])
        if not choices:
            return

        weights = [float(choice.get("weight", 1)) for choice in choices]
        total_weight = sum(weights)
        if total_weight <= 0:
            return

        roll = self.rng.random() * total_weight
        cumulative = 0.0
        selected = choices[-1]
        for choice, weight in zip(choices, weights):
            cumulative += weight
            if roll < cumulative:
                selected = choice
                break

        if "context_key" in action and "value" in selected:
            context[action["context_key"]] = selected["value"]

        self._execute_actions(
            selected.get("actions", []), player, args, context, events, room_id
        )

    def _action_conditional(
        self,
        action: dict,
        player: models.PlayerModel,
        args: list[str],
        context: dict[str, Any],
        events: list[dict],
        room_id: int,
    ):
        conditions = action.get("conditions", [])
        if all(
            self._evaluate_condition(cond, player, context, room_id) for cond in conditions
        ):
            self._execute_actions(
                action.get("then", []), player, args, context, events, room_id
            )
        else:
            self._execute_actions(action.get("else", []), player, args, context, events, room_id)

    def _action_purchase_spell(
        self,
        action: dict,
        player: models.PlayerModel,
        args: list[str],
        context: dict[str, Any],
        events: list[dict],
        room_id: int,
    ):
        target_idx = action.get("target_arg", 0)
        requested = args[target_idx].lower() if len(args) > target_idx else None

        stock = {entry["name"].lower(): entry["price"] for entry in action.get("stock", [])}
        if not requested or requested not in stock or requested not in self.spells_by_name:
            self._execute_actions(action.get("missing", []), player, [], context, events, room_id)
            return

        price = stock[requested]
        spell = self.spells_by_name[requested]
        if player.gold < price:
            self._execute_actions(
                action.get("insufficient", []), player, [], context, events, room_id
            )
            return

        player.gold -= price
        if spell.sbkref == constants.OFFENS:
            player.offspls |= spell.bitdef
        elif spell.sbkref == constants.DEFENS:
            player.defspls |= spell.bitdef
        else:
            player.othspls |= spell.bitdef

        if spell.id not in player.spells and len(player.spells) < constants.MAXSPL:
            player.spells.append(spell.id)
            player.nspells = len(player.spells)

        context["spell_price"] = price
        context["spell_name"] = spell.name
        self._execute_actions(action.get("success", []), player, [], context, events, room_id)

    def _action_level_gate(
        self,
        action: dict,
        player: models.PlayerModel,
        context: dict[str, Any],
        events: list[dict],
        room_id: int,
    ):
        target = int(action.get("target_level", 0))
        level_up = action.get("level_up", False)

        # Mirrors the chklvl/glvutl progression checks (legacy/KYRROUS.C lines 660-676).
        if player.level == target - 1:
            if level_up:
                self._level_up(player)
            self._execute_actions(
                action.get("on_success", []), player, [], context, events, room_id
            )
            return

        if player.level >= target:
            self._execute_actions(
                action.get("on_too_high", []), player, [], context, events, room_id
            )
        else:
            self._execute_actions(action.get("on_too_low", []), player, [], context, events, room_id)

    def _evaluate_condition(
        self, condition: dict, player: models.PlayerModel, context: dict[str, Any], room_id: int | None
    ) -> bool:
        if "gold_lt" in condition:
            return player.gold < int(condition["gold_lt"])
        if "context_lt" in condition:
            key = condition["context_lt"]["key"]
            value = condition["context_lt"]["value"]
            return context.get(key, 0) < value
        if "inventory_lt" in condition:
            return player.npobjs < int(condition["inventory_lt"])
        if "room_objects_lt" in condition:
            limit = int(condition["room_objects_lt"])
            current = len(self._get_room_objects(room_id)) if room_id is not None else 0
            return current < limit
        if "room_state_gte" in condition and room_id is not None:
            key = condition["room_state_gte"].get("key")
            value = condition["room_state_gte"].get("value", 0)
            state = self._get_room_state(room_id)
            baseline = self.room_state_defaults.get(room_id, {}).get(key, 0)
            return state.get(key, baseline) >= int(value)
        if "has_item" in condition:
            obj_name = condition["has_item"]
            obj = self.objects_by_name.get(obj_name.lower()) if obj_name else None
            return obj is not None and obj.id in player.gpobjs
        return False

    def _action_add_room_object(
        self,
        action: dict,
        player: models.PlayerModel,
        context: dict[str, Any],
        events: list[dict],
        room_id: int,
    ):
        obj_name = action.get("object")
        obj = self.objects_by_name.get(obj_name.lower()) if obj_name else None
        if obj is None:
            return

        room_objects = self._get_room_objects(room_id)
        limit = int(action.get("limit", constants.MXLOBS))
        if len(room_objects) >= limit:
            self._execute_actions(action.get("on_full", []), player, [], context, events, room_id)
            return

        room_objects.append(obj.id)
        context["room_object_id"] = obj.id
        context["room_object_name"] = obj.name

    def _action_increment_room_state(self, action: dict, context: dict[str, Any], room_id: int):
        key = action.get("key")
        amount = int(action.get("amount", 1))
        if not key:
            return

        state = self._get_room_state(room_id)
        baseline = self.room_state_defaults.get(room_id, {}).get(key, 0)
        state[key] = state.get(key, baseline) + amount
        if "context_key" in action:
            context[action["context_key"]] = state[key]

    @staticmethod
    def _find_inventory_index(player: models.PlayerModel, object_id: int) -> int | None:
        try:
            return player.gpobjs.index(object_id)
        except ValueError:
            return None

    @staticmethod
    def _remove_inventory_index(player: models.PlayerModel, index: int):
        player.gpobjs.pop(index)
        player.obvals.pop(index)
        player.npobjs = len(player.gpobjs)

    def _article_for_object(self, obj: models.GameObjectModel) -> str:
        article = "an" if "NEEDAN" in obj.flags or obj.name[0].lower() in "aeiou" else "a"
        return f"{article} {obj.name}"

    def _base_context(self, player: models.PlayerModel, args: list[str]) -> dict[str, Any]:
        female = bool(player.flags & constants.PlayerFlag.FEMALE)
        return {
            "player_id": player.plyrid,
            "player_altnam": player.altnam,
            "player_pronoun_obj": "her" if female else "him",
            "player_pronoun_poss": "her" if female else "his",
            "args": args,
        }

    def _get_room_state(self, room_id: int) -> dict:
        if room_id not in self.room_states:
            self.room_states[room_id] = dict(self.room_state_defaults.get(room_id, {}))
        return self.room_states[room_id]

    def _get_room_objects(self, room_id: int) -> list[int]:
        if room_id not in self.room_objects:
            self.room_objects[room_id] = list(self.room_object_defaults.get(room_id, []))
        return self.room_objects[room_id]

    def get_room_state(self, room_id: int) -> dict:
        return self._get_room_state(room_id)

    def get_room_objects(self, room_id: int) -> list[int]:
        return self._get_room_objects(room_id)

    @staticmethod
    def _level_up(player: models.PlayerModel):
        player.level += 1
        # Legacy: glvutl increments level, nmpdes, hitpts, spts (KYRROUS.C 1455-1461).
        if player.nmpdes is None:
            player.nmpdes = constants.level_to_nmpdes(player.level)
        else:
            player.nmpdes += 1
        player.hitpts += 4
        player.spts += 2


def load_yaml_room_definitions(path) -> dict:
    """Load YAML room configuration from disk."""

    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)
