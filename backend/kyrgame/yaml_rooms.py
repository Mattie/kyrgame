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


class YamlRoomEngine:
    """Interpret YAML-defined room behaviors against a player state."""

    def __init__(
        self,
        definitions: dict,
        messages: models.MessageBundleModel,
        objects: Iterable[models.GameObjectModel],
        spells: Iterable[models.SpellModel],
        rng: random.Random | None = None,
    ):
        self.messages = messages
        self.rooms = {room["id"]: room for room in definitions.get("rooms", [])}
        self.objects_by_name = {obj.name.lower(): obj for obj in objects}
        self.spells_by_name = {spell.name.lower(): spell for spell in spells}
        self.rng = rng or random.Random()

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
        events: list[dict] = []

        for trigger in room.get("triggers", []):
            if not self._matches_trigger(trigger, command, args):
                continue
            self._execute_actions(trigger.get("actions", []), player, args, context, events)
            return RoomHandleResult(handled=True, events=events)

        return RoomHandleResult(handled=False, events=events)

    def _matches_trigger(self, trigger: dict, command: str, args: list[str]) -> bool:
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

        return True

    def _execute_actions(
        self,
        actions: list[dict],
        player: models.PlayerModel,
        args: list[str],
        context: dict[str, Any],
        events: list[dict],
    ):
        for action in actions:
            action_type = action.get("type")
            if action_type == "branch_by_item":
                self._action_branch_by_item(action, player, args, context, events)
            elif action_type == "remove_item":
                self._action_remove_item(action, player, context)
            elif action_type == "add_gold":
                self._action_add_gold(action, player, context)
            elif action_type == "grant_object":
                self._action_grant_object(action, player, context, events)
            elif action_type == "message":
                self._action_message(action, player, context, events)
            elif action_type == "heal":
                self._action_heal(action, player)
            elif action_type == "damage":
                self._action_damage(action, player)
            elif action_type == "random_chance":
                self._action_random_chance(action, player, args, context, events)
            elif action_type == "random_range":
                self._action_random_range(action, context)
            elif action_type == "conditional":
                self._action_conditional(action, player, args, context, events)
            elif action_type == "purchase_spell":
                self._action_purchase_spell(action, player, args, context, events)
            elif action_type == "level_gate":
                self._action_level_gate(action, player, context, events)

    def _action_branch_by_item(
        self,
        action: dict,
        player: models.PlayerModel,
        args: list[str],
        context: dict[str, Any],
        events: list[dict],
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
                self._execute_actions(action.get("missing_actions", []), player, args, context, events)
                return

        self._execute_actions(branch_actions or [], player, args, context, events)

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
    ):
        obj_name = action.get("object")
        obj = self.objects_by_name.get(obj_name.lower()) if obj_name else None
        if obj is None:
            return

        if len(player.gpobjs) >= constants.MXPOBS:
            self._execute_actions(action.get("on_full", []), player, [], context, events)
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
        amount = int(action.get("amount", 0))
        player.hitpts = max(0, player.hitpts - amount)

    def _action_random_chance(
        self,
        action: dict,
        player: models.PlayerModel,
        args: list[str],
        context: dict[str, Any],
        events: list[dict],
    ):
        probability = float(action.get("probability", 0))
        roll = self.rng.random()
        branch = action.get("on_success", []) if roll < probability else action.get("on_failure", [])
        self._execute_actions(branch, player, args, context, events)

    def _action_random_range(self, action: dict, context: dict[str, Any]):
        start = int(action.get("start", 0))
        stop = int(action.get("stop", 0))
        value = self.rng.randrange(start, stop)
        if "context_key" in action:
            context[action["context_key"]] = value

    def _action_conditional(
        self,
        action: dict,
        player: models.PlayerModel,
        args: list[str],
        context: dict[str, Any],
        events: list[dict],
    ):
        conditions = action.get("conditions", [])
        if all(self._evaluate_condition(cond, player, context) for cond in conditions):
            self._execute_actions(action.get("then", []), player, args, context, events)
        else:
            self._execute_actions(action.get("else", []), player, args, context, events)

    def _action_purchase_spell(
        self,
        action: dict,
        player: models.PlayerModel,
        args: list[str],
        context: dict[str, Any],
        events: list[dict],
    ):
        target_idx = action.get("target_arg", 0)
        requested = args[target_idx].lower() if len(args) > target_idx else None

        stock = {entry["name"].lower(): entry["price"] for entry in action.get("stock", [])}
        if not requested or requested not in stock or requested not in self.spells_by_name:
            self._execute_actions(action.get("missing", []), player, [], context, events)
            return

        price = stock[requested]
        spell = self.spells_by_name[requested]
        if player.gold < price:
            self._execute_actions(action.get("insufficient", []), player, [], context, events)
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
        self._execute_actions(action.get("success", []), player, [], context, events)

    def _action_level_gate(
        self,
        action: dict,
        player: models.PlayerModel,
        context: dict[str, Any],
        events: list[dict],
    ):
        target = int(action.get("target_level", 0))
        level_up = action.get("level_up", False)

        # Mirrors the chklvl/glvutl progression checks (legacy/KYRROUS.C lines 660-676).
        if player.level == target - 1:
            if level_up:
                self._level_up(player)
            self._execute_actions(action.get("on_success", []), player, [], context, events)
            return

        if player.level >= target:
            self._execute_actions(action.get("on_too_high", []), player, [], context, events)
        else:
            self._execute_actions(action.get("on_too_low", []), player, [], context, events)

    def _evaluate_condition(self, condition: dict, player: models.PlayerModel, context: dict[str, Any]) -> bool:
        if "gold_lt" in condition:
            return player.gold < int(condition["gold_lt"])
        if "context_lt" in condition:
            key = condition["context_lt"]["key"]
            value = condition["context_lt"]["value"]
            return context.get(key, 0) < value
        if "inventory_lt" in condition:
            return player.npobjs < int(condition["inventory_lt"])
        return False

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

    @staticmethod
    def _level_up(player: models.PlayerModel):
        player.level += 1
        player.nmpdes += 1
        player.hitpts += 4
        player.spts += 2


def load_yaml_room_definitions(path) -> dict:
    """Load YAML room configuration from disk."""

    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)
