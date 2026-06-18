from __future__ import annotations

from dataclasses import dataclass
import re
import random
from typing import Any, Callable, Iterable, Optional

import yaml

from . import constants, models, modern_features
from .honor_mode import HonorModePolicy
from .messaging import build_direct_and_others_events
from .inventory import pop_inventory_index
from .player_lifecycle import (
    DeathRecoveryPlan,
    RoomObjectUpdate,
    apply_death_recovery_plan,
    build_modern_death_recovery_plan,
    reset_player_after_death,
)
from .player_progression import level_up_player
from .spellbook import add_spell_to_book, memorize_spell


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
        honor_mode_policy: HonorModePolicy | None = None,
        defer_modern_death_recovery: bool = False,
        room_objects_getter: Callable[[int], list[int]] | None = None,
    ):
        object_list = list(objects)
        spell_list = list(spells)
        self.messages = messages
        self.rooms = {room["id"]: room for room in definitions.get("rooms", [])}
        self.objects_by_name = {obj.name.lower(): obj for obj in object_list}
        self.objects_by_id = {obj.id: obj for obj in object_list}
        self.spells_by_name = {spell.name.lower(): spell for spell in spell_list}
        self.rng = rng or random.Random()
        self.honor_mode_policy = honor_mode_policy or HonorModePolicy()
        self.defer_modern_death_recovery = defer_modern_death_recovery
        self.room_objects_getter = room_objects_getter
        self.room_state_defaults: dict[int, dict] = {
            room_id: room.get("state", {})
            for room_id, room in ((room.get("id"), room) for room in self.rooms.values())
            if room_id is not None
        }
        self.room_states: dict[int, dict] = {}
        self.room_object_defaults: dict[int, list[int]] = {}
        self.room_objects: dict[int, list[int]] = {}
        self.locations: dict[int, models.LocationModel] = {}
        self.last_room_object_updates: list[RoomObjectUpdate] = []
        self.last_death_recovery_plan: DeathRecoveryPlan | None = None

        for location in locations or []:
            if hasattr(location, "id"):
                room_id = location.id  # type: ignore[attr-defined]
                objects = list(getattr(location, "objects", []) or [])
                if hasattr(location, "model_copy"):
                    self.locations[room_id] = location
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

        self.last_room_object_updates = []
        self.last_death_recovery_plan = None
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
            if not self._matches_trigger(trigger, player, command, args, room_id):
                continue
            self._execute_actions(
                trigger.get("actions", []), player, args, context, events, room_id
            )
            return RoomHandleResult(handled=True, events=events)

        return RoomHandleResult(handled=False, events=events)

    def allows_normalized_retry(self, room_id: int) -> bool:
        # Strict legacy room routines use raw margv boundaries and GAMUTILS token
        # macros, so some rooms opt out of the modern normalized retry path.
        # See legacy/KYRCMDS.C:1251-1257 and legacy/GAMUTILS.C:55-106.
        room = self.rooms.get(room_id)
        if not room:
            return True
        return bool(room.get("allow_normalized_retry", True))

    def _matches_trigger(
        self,
        trigger: dict,
        player: models.PlayerModel,
        command: str,
        args: list[str],
        room_id: int,
    ) -> bool:
        verb = command.lower()
        verbs = {v.lower() for v in trigger.get("verbs", [])}
        if verbs and verb not in verbs:
            return False

        filtered_args = self._apply_legacy_arg_filters(trigger, args)
        strip_tokens = {token.lower() for token in trigger.get("arg_strip", [])}
        filtered_args = (
            [arg for arg in filtered_args if arg.lower() not in strip_tokens]
            if strip_tokens
            else filtered_args
        )

        def _normalize_phrase(text: str) -> str:
            lowered = text.lower()
            stripped = re.sub(r"[^a-z0-9\\s]", "", lowered)
            return " ".join(stripped.split())

        def _sameas_phrase(text: str) -> str:
            return " ".join(text.lower().split())

        phrase_match = str(trigger.get("phrase_match", "normalized")).lower()

        required_state_equal = trigger.get("room_state_equals", {})
        if required_state_equal:
            state = self._get_room_state(room_id)
            defaults = self.room_state_defaults.get(room_id, {})
            for key, value in required_state_equal.items():
                if state.get(key, defaults.get(key, 0)) != value:
                    return False

        phrase_key = trigger.get("match_phrase_key")
        if phrase_key:
            target_phrase = self.messages.messages.get(phrase_key, "")
            attempt = " ".join([command, *filtered_args])
            if phrase_match == "sameas":
                return _sameas_phrase(attempt) == _sameas_phrase(target_phrase)
            return _normalize_phrase(attempt) == _normalize_phrase(target_phrase)

        arg_phrase_key = trigger.get("arg_phrase_key")
        if arg_phrase_key:
            target_phrase = self.messages.messages.get(arg_phrase_key, "")
            attempt = " ".join(filtered_args)
            if phrase_match == "sameas":
                return _sameas_phrase(attempt) == _sameas_phrase(target_phrase)
            return _normalize_phrase(attempt) == _normalize_phrase(target_phrase)

        target_terms = {term.lower() for term in trigger.get("target_in", [])}
        if target_terms:
            return filtered_args and filtered_args[0].lower() in target_terms

        sequence = [arg.lower() for arg in trigger.get("arg_sequence", [])]
        if sequence:
            if len(filtered_args) < len(sequence):
                return False
            if any(
                filtered_args[idx].lower() != expected for idx, expected in enumerate(sequence)
            ):
                return False

        arg_at = trigger.get("arg_at")
        if arg_at:
            index = int(arg_at.get("index", 0))
            value = str(arg_at.get("value", "")).lower()
            if len(filtered_args) <= index or filtered_args[index].lower() != value:
                return False

        arg_count = trigger.get("arg_count")
        if arg_count is not None and len(filtered_args) != int(arg_count):
            return False

        arg_matches = trigger.get("arg_matches", [])
        if arg_matches:
            for match in arg_matches:
                index = int(match.get("index", 0))
                value = str(match.get("value", "")).lower()
                if len(filtered_args) <= index or filtered_args[index].lower() != value:
                    return False

        arg_equals_spouse = trigger.get("arg_equals_player_spouse")
        if arg_equals_spouse:
            # Legacy heartm compares the offered spouse name directly (legacy/KYRROUS.C:1216-1229).
            index = int(arg_equals_spouse.get("index", 0))
            spouse = (player.spouse or "").lower()
            if not spouse or len(filtered_args) <= index:
                return False
            if filtered_args[index].lower() != spouse:
                return False

        required_item = trigger.get("requires_item")
        if required_item:
            # Legacy room routines often check fgmpobj() before handling drops (e.g., KYRROUS.C:972-1027).
            obj = self.objects_by_name.get(str(required_item).lower())
            if obj is None or self._find_inventory_index(player, obj.id) is None:
                return False

        required_state = trigger.get("room_state_at_least", {})
        if required_state:
            state = self._get_room_state(room_id)
            for key, value in required_state.items():
                if state.get(key, self.room_state_defaults.get(room_id, {}).get(key, 0)) < int(value):
                    return False

        return True

    @staticmethod
    def _remove_legacy_tokens_except_last(args: list[str], tokens: set[str]) -> list[str]:
        # Mirrors the GAMUTILS.C bagging helpers: they scan before the final token,
        # delete a matching word, then advance the index. Consecutive removable
        # tokens can therefore leave the second token in place.
        # Source: legacy/GAMUTILS.C:55-106.
        filtered = args[:]
        index = 0
        while index < len(filtered) - 1:
            if filtered[index].lower() in tokens:
                del filtered[index]
            index += 1
        return filtered

    def _apply_legacy_arg_filters(self, trigger: dict, args: list[str]) -> list[str]:
        filtered = args[:]
        for rule in trigger.get("arg_filters", []):
            if isinstance(rule, str):
                key = rule.lower()
                if key == "gi_bagthe":
                    # Legacy gi_bagthe() removes articles before the final token.
                    # Source: legacy/GAMUTILS.C:55-68.
                    filtered = self._remove_legacy_tokens_except_last(
                        filtered, {"the", "a", "an"}
                    )
                elif key == "bagprep":
                    # Legacy bagprep() removes common prepositions before the final token.
                    # Source: legacy/GAMUTILS.C:72-90.
                    filtered = self._remove_legacy_tokens_except_last(
                        filtered, {"at", "to", "into", "through", "in"}
                    )
            elif isinstance(rule, dict) and "bag_word" in rule:
                # Legacy bagwrd(word) removes one configured word before the final token.
                # Source: legacy/GAMUTILS.C:94-106.
                filtered = self._remove_legacy_tokens_except_last(
                    filtered, {str(rule["bag_word"]).lower()}
                )
        return filtered

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
                self._action_damage(action, player, context, events)
            elif action_type == "nonlethal_damage":
                self._action_nonlethal_damage(action, player)
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
            elif action_type == "transfer_player":
                self._action_transfer_player(action, player, context, events)
            elif action_type == "set_player_flag":
                self._action_set_player_flag(action, player)
            elif action_type == "remove_inventory_index":
                self._action_remove_inventory_index(action, player)
            elif action_type == "level_up":
                self._action_level_up(player)
            else:
                raise ValueError(
                    f"Unknown YAML room action type: {action_type!r} (room_id={room_id})"
                )

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
            if action.get("strategy") == "legacy_takpobj":
                self._legacy_take_inventory_index(player, idx)
            else:
                pop_inventory_index(player, idx)

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
        # Legacy slot machine rewards use dobutl() to include articles (KYRROUS.C:976-981).
        context["granted_object_article"] = self._article_for_object(obj)

    def _action_message(
        self,
        action: dict,
        player: models.PlayerModel,
        context: dict[str, Any],
        events: list[dict],
    ):
        def _render_message(
            message_key: str | None,
            fallback_text: str | None,
            format_list: list[str] | None,
        ) -> str | None:
            resolved = fallback_text
            if resolved is None and message_key:
                resolved = self.messages.messages.get(message_key, "")
            if format_list and resolved:
                values = [context.get(arg, arg) for arg in format_list]
                try:
                    resolved = resolved % tuple(values)
                except TypeError:
                    resolved = resolved % tuple(str(val) for val in values)
            return resolved

        message_id = action.get("message_id")
        if isinstance(message_id, str) and "{" in message_id:
            message_id = message_id.format(**context)
        text = action.get("text")
        format_args = action.get("format", [])
        scope = action.get("scope")
        broadcast_message_id = action.get("broadcast_message_id")
        if isinstance(broadcast_message_id, str) and "{" in broadcast_message_id:
            broadcast_message_id = broadcast_message_id.format(**context)
        broadcast_text = action.get("broadcast_text")
        broadcast_format = action.get("broadcast_format", [])

        if scope in {"direct", "broadcast", "broadcast_others", "direct_and_others", "global"}:
            if scope == "direct_and_others":
                direct_text = _render_message(message_id, text, format_args)
                other_text = _render_message(
                    broadcast_message_id, broadcast_text, broadcast_format
                )
                events.extend(
                    build_direct_and_others_events(
                        player_id=player.plyrid,
                        event="room_message",
                        direct_text=direct_text,
                        others_text=other_text,
                        direct_message_id=message_id,
                        others_message_id=broadcast_message_id,
                    )
                )
                return

            direct_text = _render_message(message_id, text, format_args)
            if direct_text is None:
                return
            events.append(
                {
                    "scope": "broadcast" if scope == "broadcast_others" else scope,
                    "event": "room_message",
                    "message_id": message_id,
                    "text": direct_text,
                    "player": player.plyrid,
                    "exclude_player": player.plyrid if scope == "broadcast_others" else None,
                }
            )
            if "include_sender" in action:
                events[-1]["include_sender"] = bool(action["include_sender"])
            return

        has_direct = message_id is not None or text is not None
        has_broadcast = broadcast_message_id is not None or broadcast_text is not None
        direct_text = _render_message(message_id, text, format_args) if has_direct else None
        other_text = (
            _render_message(broadcast_message_id, broadcast_text, broadcast_format)
            if has_broadcast
            else None
        )

        events.extend(
            build_direct_and_others_events(
                player_id=player.plyrid,
                event="room_message",
                direct_text=direct_text,
                others_text=other_text,
                direct_message_id=message_id,
                others_message_id=broadcast_message_id,
            )
        )

    def _action_heal(self, action: dict, player: models.PlayerModel):
        amount = int(action.get("amount", 0))
        cap_per_level = action.get("cap_per_level")
        player.hitpts += amount
        if cap_per_level:
            cap = player.level * int(cap_per_level)
            player.hitpts = min(player.hitpts, cap)

    def _action_nonlethal_damage(self, action: dict, player: models.PlayerModel):
        amount = max(0, int(action.get("amount", 0)))
        player.hitpts = max(0, player.hitpts - amount)

    def _action_damage(
        self,
        action: dict,
        player: models.PlayerModel,
        context: dict[str, Any],
        events: list[dict],
    ):
        # Legacy hitoth() deducts hit points, then initgp()/entrgp() resets dead
        # players to room 0 with DIEMSG/KILLED fan-out. Source: legacy/KYRSPEL.C:303-321.
        amount = max(0, int(action.get("amount", 0)))
        remaining_hitpts = player.hitpts - amount
        if remaining_hitpts > 0:
            player.hitpts = remaining_hitpts
            return

        if self.honor_mode_policy.modern_feature_enabled(
            player, modern_features.MODERN_DEATH_RECOVERY
        ):
            # modern_death_recovery: YAML room damage can be deferred so the
            # WebSocket layer persists the player row and spill rooms atomically.
            # See docs/MODERN_FEATURES.md.
            self._refresh_modern_death_recovery_room_objects(player.gamloc)
            plan = build_modern_death_recovery_plan(
                player,
                locations=self.locations,
                rng=self.rng,
            )
            self.last_death_recovery_plan = plan
            context["death_old_room"] = plan.old_room
            context["death_old_name"] = plan.old_name
            self.last_room_object_updates = list(plan.room_object_updates)
            if not self.defer_modern_death_recovery:
                apply_death_recovery_plan(player, self.locations, plan)
                for room_update in plan.room_object_updates:
                    self.set_room_objects(room_update.room_id, list(room_update.object_ids))
            self._append_modern_death_recovery_events(player, events, plan)
            return

        player.hitpts = remaining_hitpts
        old_room = player.gamloc
        old_name = player.altnam
        # Honor-mode YAML deaths stay on the legacy hitoth()/initgp() reset
        # path. Source: legacy/KYRSPEL.C:303-321.
        reset_player_after_death(player, self.rng.randrange)
        context["death_old_room"] = old_room
        context["death_old_name"] = old_name

        events.append(
            {
                "scope": "direct",
                "event": "room_message",
                "message_id": "DIEMSG",
                "text": self.messages.messages.get("DIEMSG", ""),
                "player": player.plyrid,
                "room_id": old_room,
                "death_reset": True,
            }
        )
        killed = self.messages.messages.get("KILLED", "")
        if killed:
            killed = killed % old_name
        events.append(
            {
                "scope": "broadcast",
                "event": "room_message",
                "message_id": "KILLED",
                "text": killed,
                "player": player.plyrid,
                "room_id": old_room,
                "exclude_player": player.plyrid,
            }
        )
        events.append(
            {
                "scope": "system",
                "event": "room_transfer",
                "player": player.plyrid,
                "target_room": 0,
                "arrive_text": f"*** {player.plyrid} has just appeared in a holy light!",
                "death_reset": True,
            }
        )

    def _append_modern_death_recovery_events(
        self,
        player: models.PlayerModel,
        events: list[dict],
        plan: DeathRecoveryPlan,
    ) -> None:
        """Append YAML events for modern_death_recovery.

        When `defer_modern_death_recovery=True`, these events are emitted before the
        plan is applied so the caller can persist the staged player/room updates
        atomically.
        """
        target_metadata = _modern_death_metadata(plan, recipient_scope="target")
        room_metadata = _modern_death_metadata(plan, recipient_scope="room")
        events.append(
            {
                "scope": "direct",
                "event": "room_message",
                "message_id": "DIEMSG",
                "text": self.messages.messages.get("DIEMSG", ""),
                "player": player.plyrid,
                "room_id": plan.old_room,
                **target_metadata,
            }
        )
        killed = self.messages.messages.get("KILLED", "")
        if killed:
            killed = killed % plan.old_name
        events.append(
            {
                "scope": "broadcast",
                "event": "room_message",
                "message_id": "KILLED",
                "text": killed,
                "player": player.plyrid,
                "room_id": plan.old_room,
                "exclude_player": player.plyrid,
                **room_metadata,
            }
        )
        events.append(
            {
                "scope": "system",
                "event": "room_transfer",
                "player": player.plyrid,
                "target_room": constants.WILLOW_ROOM_ID,
                "arrive_text": f"*** {player.plyrid} has just appeared in a holy light!",
                **target_metadata,
            }
        )
        for room_update in plan.room_object_updates:
            events.append(
                {
                    "scope": "broadcast",
                    "event": "room_objects",
                    "type": "room_objects",
                    "room_id": room_update.room_id,
                    "location": room_update.room_id,
                    "objects": self._room_object_entries(room_update.object_ids),
                    "include_sender": True,
                    **room_metadata,
                }
            )
            for object_id in room_update.dropped_items:
                obj = self.objects_by_id.get(object_id)
                events.append(
                    {
                        "scope": "broadcast",
                        "event": "room_message",
                        "message_id": "DROPIT3",
                        "text": self._message(
                            "DROPIT3",
                            plan.old_name,
                            _player_pronoun_possessive(player),
                            obj.name if obj else str(object_id),
                        ),
                        "player": player.plyrid,
                        "room_id": room_update.room_id,
                        "include_sender": True,
                        "object_id": object_id,
                        **room_metadata,
                    }
                )

    def _action_grant_spell(
        self, action: dict, player: models.PlayerModel, context: dict[str, Any]
    ):
        """Grant a spellbook bit, with optional pre-memorization for scripted exceptions."""
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

        # Legacy parity: room grants set spellbook bits; memorization is separate unless
        # the room script explicitly opts in for special cases.
        # Sources: legacy/KYRROUS.C:632-634 (druids bit grant), legacy/KYRSPEL.C:1491-1497 (memutl).
        spell = spell.model_copy(update={"sbkref": sbkref})
        add_spell_to_book(player, spell)
        if bool(action.get("memorize", False)):
            memorize_spell(player, spell)

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
            self._evaluate_condition(cond, player, args, context, room_id)
            for cond in conditions
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

        stock_entries = action.get("stock", [])
        stock = {entry["name"].lower(): entry["price"] for entry in stock_entries}
        matched_name = (
            self._legacy_spell_purchase_key(requested, stock.keys()) if requested else None
        )
        if (
            not matched_name
            or matched_name not in stock
            or matched_name not in self.spells_by_name
        ):
            self._execute_actions(action.get("missing", []), player, [], context, events, room_id)
            return

        price = stock[matched_name]
        spell = self.spells_by_name[matched_name]
        if player.gold < price:
            self._execute_actions(
                action.get("insufficient", []), player, [], context, events, room_id
            )
            return

        player.gold -= price
        # Legacy buyspl awards spellbook ownership bits only (legacy/KYRROUS.C:265-273).
        add_spell_to_book(player, spell)

        context["spell_price"] = price
        context["spell_name"] = spell.name
        self._execute_actions(action.get("success", []), player, [], context, events, room_id)

    @staticmethod
    def _legacy_spell_purchase_key(input_text: str, keys: Iterable[str]) -> str | None:
        # Legacy buyspl calls sameto(stocked spell name, input). See legacy/KYRROUS.C:249-250.
        target = input_text.strip().lower()
        if not target:
            return None
        for key in keys:
            if target.startswith(key.lower()):
                return key
        return None

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

        # Mirrors the chklvl/glvutl progression checks (legacy/KYRROUS.C:1436-1462).
        if player.level == target - 1:
            required_item = action.get("requires_item")
            if required_item:
                obj = self.objects_by_name.get(str(required_item).lower())
                if obj is None or self._find_inventory_index(player, obj.id) is None:
                    self._execute_actions(
                        action.get("on_missing_item", []), player, [], context, events, room_id
                    )
                    return
            if level_up:
                level_up_player(player)
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
        self,
        condition: dict,
        player: models.PlayerModel,
        args: list[str],
        context: dict[str, Any],
        room_id: int | None,
    ) -> bool:
        if "arg_at" in condition:
            index = int(condition["arg_at"].get("index", 0))
            value = str(condition["arg_at"].get("value", "")).lower()
            return len(args) > index and args[index].lower() == value
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
        if "player_flag_set" in condition:
            flag_value = self._resolve_player_flag(condition["player_flag_set"])
            if flag_value is None:
                return False
            return bool(player.flags & flag_value)
        if "has_charm" in condition:
            slot = self._resolve_charm_slot(condition["has_charm"])
            if slot is None:
                return False
            if slot < 0 or slot >= len(player.charms):
                return False
            return player.charms[slot] > 0
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

    def _action_transfer_player(
        self,
        action: dict,
        player: models.PlayerModel,
        context: dict[str, Any],
        events: list[dict],
    ):
        """Teleport a player with legacy remvgp/entrgp messaging (KYRROUS.C:939-958)."""
        target_room = action.get("target_room")
        if target_room is None:
            return

        leave_text = action.get("leave_text")
        leave_format = action.get("leave_format", [])
        arrive_text = action.get("arrive_text")
        arrive_format = action.get("arrive_format", [])

        def _format_text(template: str | None, format_list: list[str]) -> str | None:
            if not template:
                return None
            values = [context.get(arg, arg) for arg in format_list]
            if not values:
                return template
            try:
                return template % tuple(values)
            except TypeError:
                return template % tuple(str(val) for val in values)

        player.pgploc = player.gamloc
        player.gamloc = int(target_room)

        events.append(
            {
                "scope": "system",
                "event": "room_transfer",
                "player": player.plyrid,
                "target_room": int(target_room),
                "leave_text": _format_text(leave_text, leave_format),
                "arrive_text": _format_text(arrive_text, arrive_format),
                "legacy_transfer_format": bool(action.get("legacy_transfer_format")),
            }
        )

    def _action_set_player_flag(self, action: dict, player: models.PlayerModel):
        """Toggle player flags for legacy routines such as rainbo (legacy/KYRROUS.C:1090-1103)."""
        flag_value = self._resolve_player_flag(action.get("flag"))
        if flag_value is None:
            return
        enabled = action.get("enabled", True)
        if enabled:
            player.flags |= flag_value
        else:
            player.flags &= ~flag_value

    def _action_remove_inventory_index(self, action: dict, player: models.PlayerModel):
        index = action.get("index")
        if index is None:
            return
        idx = int(index)
        if idx < 0 or idx >= len(player.gpobjs):
            return
        if action.get("strategy") == "legacy_takpobj":
            self._legacy_take_inventory_index(player, idx)
        else:
            pop_inventory_index(player, idx)

    def _action_level_up(self, player: models.PlayerModel):
        level_up_player(player)

    @staticmethod
    def _legacy_take_inventory_index(player: models.PlayerModel, index: int) -> tuple[int, int]:
        """Remove inventory with takpobj/tgmpobj last-slot replacement semantics.

        Source: legacy/KYRUTIL.C:550-565.
        """

        object_id = player.gpobjs[index]
        object_value = player.obvals[index] if index < len(player.obvals) else 0
        last_index = len(player.gpobjs) - 1
        if index != last_index:
            player.gpobjs[index] = player.gpobjs[last_index]
            if player.obvals:
                if len(player.obvals) <= last_index:
                    player.obvals.extend([0] * (last_index + 1 - len(player.obvals)))
                player.obvals[index] = player.obvals[last_index]
        player.gpobjs.pop()
        if player.obvals:
            player.obvals.pop()
        player.npobjs = len(player.gpobjs)
        return object_id, object_value

    @staticmethod
    def _resolve_player_flag(flag: Any) -> int | None:
        if isinstance(flag, int):
            return flag
        if isinstance(flag, str):
            key = flag.strip().upper()
            if key in constants.PlayerFlag.__members__:
                return int(constants.PlayerFlag[key])
            try:
                return int(flag, 0)
            except ValueError:
                return None
        return None

    @staticmethod
    def _resolve_charm_slot(slot: Any) -> int | None:
        if isinstance(slot, int):
            return slot
        if isinstance(slot, str):
            key = slot.strip().upper()
            if hasattr(constants, key):
                return int(getattr(constants, key))
            for name, member in constants.CharmSlot.__members__.items():
                if name.upper() == key:
                    return int(member)
            try:
                return int(slot, 0)
            except ValueError:
                return None
        return None

    @staticmethod
    def _find_inventory_index(player: models.PlayerModel, object_id: int) -> int | None:
        try:
            return player.gpobjs.index(object_id)
        except ValueError:
            return None


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
            "player_pronoun_subj": "she" if female else "he",
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

    def set_room_objects(self, room_id: int, object_ids: list[int]) -> None:
        self.room_objects[room_id] = list(object_ids)
        location = self.locations.get(room_id)
        if location is not None:
            self.locations[room_id] = location.model_copy(
                update={"objects": list(object_ids), "nlobjs": len(object_ids)}
            )

    def _refresh_modern_death_recovery_room_objects(self, old_room: int) -> None:
        if self.room_objects_getter is None:
            return
        room_ids = {old_room}
        location = self.locations.get(old_room)
        if location is not None:
            for room_id in (
                location.gi_north,
                location.gi_south,
                location.gi_east,
                location.gi_west,
            ):
                if room_id >= 0 and room_id in self.locations:
                    room_ids.add(room_id)
        room_ids.update(
            room_id
            for room_id in range(
                constants.MODERN_DEATH_DARK_FOREST_MIN_ROOM,
                constants.MODERN_DEATH_DARK_FOREST_MAX_ROOM + 1,
            )
            if room_id in self.locations
        )
        for room_id in room_ids:
            # modern_death_recovery placement must use current live room
            # objects, since adjacent/fallback rooms may have changed after
            # YAML fixtures loaded. See docs/MODERN_FEATURES.md.
            self.set_room_objects(room_id, self.room_objects_getter(room_id))

    def _message(self, message_id: str, *args: object) -> str:
        template = self.messages.messages.get(message_id, "")
        if not args:
            return template
        try:
            return template % args
        except TypeError:
            return template

    def _room_object_entries(self, object_ids: Iterable[int]) -> list[dict[str, object]]:
        entries: list[dict[str, object]] = []
        for object_id in object_ids:
            entry: dict[str, object] = {"id": object_id}
            obj = self.objects_by_id.get(object_id)
            if obj:
                entry["name"] = obj.name
            entries.append(entry)
        return entries


def _player_pronoun_possessive(player: models.PlayerModel) -> str:
    return "her" if player.flags & constants.PlayerFlag.FEMALE else "his"


def _modern_death_metadata(
    plan: DeathRecoveryPlan,
    *,
    recipient_scope: str,
) -> dict[str, object]:
    metadata = dict(plan.metadata)
    metadata["refresh_location"] = constants.WILLOW_ROOM_ID
    metadata["recipient_scope"] = recipient_scope
    return metadata


def load_yaml_room_definitions(path) -> dict:
    """Load YAML room configuration from disk."""

    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)
