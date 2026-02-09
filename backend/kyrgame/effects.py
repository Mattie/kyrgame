from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, Optional

from . import constants, models
from .inventory import remove_inventory_item
from .spellbook import (
    forget_all_memorized,
    forget_one_random_memorized,
    wipe_spellbook_bits,
)


class EffectError(Exception):
    """Base class for effect failures."""


class ResourceCostError(EffectError):
    pass


class TargetingError(EffectError):
    pass


class CooldownActiveError(EffectError):
    pass


@dataclass
class EffectResult:
    success: bool
    message_id: str
    text: str
    animation: Optional[str] = None
    context: dict = field(default_factory=dict)


@dataclass
class SpellEffect:
    spell: models.SpellModel
    cost: int
    cooldown: float
    requires_target: bool
    animation: Optional[str] = None
    message_id: Optional[str] = None
    handler: Optional[
        Callable[
            [models.PlayerModel, Optional[str], Optional[models.PlayerModel], "SpellEffect"],
            EffectResult,
        ]
    ] = None


class SpellEffectEngine:
    def __init__(
        self,
        spells: Iterable[models.SpellModel],
        messages: models.MessageBundleModel,
        clock: Callable[[], float] | None = None,
        rng: random.Random | None = None,
        objects: Iterable[models.GameObjectModel] | None = None,
    ):
        self.spells = {spell.id: spell for spell in spells}
        self.messages = messages
        self.clock = clock or time.monotonic
        self.rng = rng or random.Random()
        self.objects = {obj.id: obj for obj in objects} if objects else {}
        self.cooldowns: Dict[str, Dict[int, float]] = {}
        self.effects: Dict[int, SpellEffect] = self._build_effects()

    def _build_effects(self) -> Dict[int, SpellEffect]:
        effects: Dict[int, SpellEffect] = {}
        for spell in self.spells.values():
            cost = spell.level  # Legacy: gmpptr->spts -= (SHORT)splptr->level
            cooldown = 2.5 if spell.sbkref == constants.OFFENS else 1.5
            requires_target = spell.sbkref == constants.OFFENS
            animation = spell.splrou
            effects[spell.id] = SpellEffect(
                spell=spell,
                cost=cost,
                cooldown=cooldown,
                requires_target=requires_target,
                animation=animation,
                message_id=f"SPL{spell.id:03d}",
            )

        if 15 in effects:
            # Legacy transformation: flyaway turns the caster into a pegasus (legacy/KYRSPEL.C lines 644-651).
            effects[15].message_id = "S16M00"
            effects[15].requires_target = False
            effects[15].handler = self._transformation_handler(
                flag=constants.PlayerFlag.PEGASU,
                direct_key="S16M00",
                broadcast_key="S16M01",
            )

        if 4 in effects:
            # Legacy spell: bookworm wipes target spellbook (legacy/KYRSPEL.C:490-513).
            effects[4].message_id = "S05M03"
            effects[4].requires_target = True
            effects[4].handler = self._bookworm_handler()

        if 12 in effects:
            # Legacy spell: dumdum forgets all memorized spells (legacy/KYRSPEL.C:606-616).
            effects[12].message_id = "S13M03"
            effects[12].requires_target = True
            effects[12].handler = self._forget_all_handler(
                failure_key="S13M00",
                failure_target_key="S13M01",
                failure_broadcast_key="S13M02",
                success_key="S13M03",
                success_target_key="S13M04",
                success_broadcast_key="S13M05",
            )

        if 33 in effects:
            # Legacy spell: howru reports target HP (legacy/KYRSPEL.C:815-824).
            effects[33].message_id = "S34M00"
            effects[33].requires_target = True
            effects[33].handler = self._howru_handler()

        if 50 in effects:
            # Legacy spell: saywhat forgets one memorized spell (legacy/KYRSPEL.C:1045-1055).
            effects[50].message_id = "S51M03"
            effects[50].requires_target = True
            effects[50].handler = self._forget_one_handler(
                failure_key="S51M00",
                failure_target_key="S51M01",
                failure_broadcast_key="S51M02",
                success_key="S51M03",
                success_target_key="S51M04",
                success_broadcast_key="S51M05",
            )

        if 49 in effects:
            # Legacy spell: sapspel drains spell points (legacy/KYRSPEL.C:1028-1040).
            effects[49].message_id = "S50M03"
            effects[49].requires_target = True
            effects[49].handler = self._sap_spell_points_handler(
                amount=16,
                failure_ids=("S50M00", "S50M01", "S50M02"),
                success_ids=("S50M03", "S50M04", "S50M05"),
            )

        if 56 in effects:
            # Legacy spell: takethat drains spell points (legacy/KYRSPEL.C:1093-1105).
            effects[56].message_id = "S57M03"
            effects[56].requires_target = True
            effects[56].handler = self._sap_spell_points_handler(
                amount=8,
                failure_ids=("S57M00", "S57M01", "S57M02"),
                success_ids=("S57M03", "S57M04", "S57M05"),
            )

        if 61 in effects:
            # Legacy transformation: weewillo grants willowisp wings (legacy/KYRSPEL.C lines 1188-1195).
            effects[61].message_id = "S62M00"
            effects[61].requires_target = False
            effects[61].handler = self._transformation_handler(
                flag=constants.PlayerFlag.WILLOW,
                direct_key="S62M00",
                broadcast_key="S62M01",
            )

        # Legacy direct damage spell behavior (striker/masshitr in legacy/KYRSPEL.C:339-429,
        # 520-1229).
        direct_damage = [
            (16, "S17M00", 4, constants.FIRPRO, 0),  # spl017 fpandl
            (18, "S19M00", 16, constants.ICEPRO, 1),  # spl019 frostie
            (20, "S21M00", 22, constants.FIRPRO, 1),  # spl021 frythes
            (21, "S22M00", 18, constants.LIGPRO, 2),  # spl022 gotcha
            (28, "S29M00", 24, constants.LIGPRO, 2),  # spl029 holyshe
            (31, "S32M00", 10, constants.FIRPRO, 1),  # spl032 hotkiss
            (39, "S40M00", 6, constants.ICEPRO, 0),  # spl040 koolit
            (47, "S48M00", 2, constants.OBJPRO, 0),  # spl048 pocus
            (53, "S54M00", 20, constants.ICEPRO, 2),  # spl054 snowjob
            (65, "S66M00", 8, constants.LIGPRO, 1),  # spl066 zapher
        ]
        for spell_id, base_id, damage, protection, mercy_level in direct_damage:
            if spell_id not in effects:
                continue
            effects[spell_id].requires_target = True
            effects[spell_id].message_id = base_id
            effects[spell_id].handler = self._direct_damage_handler(
                damage=damage,
                protection=protection,
                mercy_level=mercy_level,
                base_id=base_id,
            )

        area_damage = [
            (5, "S06M00", "S06M01", "S06M02", "S06M03", "S06M04", 10, constants.FIRPRO, False, 1),  # spl006 burnup
            (9, "S10M00", "S10M01", "S10M02", "S10M03", "S10M04", 30, constants.ICEPRO, True, 3),  # spl010 chillou
            (17, "S18M00", "S18M01", "S18M02", "S18M03", "S18M04", 26, constants.ICEPRO, False, 2),  # spl018 freezuu
            (19, "S20M00", "S20M01", "S20M02", "S20M03", "S20M04", 12, constants.ICEPRO, False, 1),  # spl020 frozenu
            (29, "S30M00", "S30M01", "S30M02", "S30M03", "S30M04", 16, constants.LIGPRO, False, 2),  # spl030 hotflas
            (30, "S31M00", "S31M01", "S31M02", "S31M03", "S31M04", 22, constants.FIRPRO, False, 2),  # spl031 hotfoot
            (36, "S37M00", "S37M01", "S37M02", "S37M03", "S37M04", 20, constants.ICEPRO, True, 2),  # spl037 icedtea
            (51, "S52M00", "S52M01", "S52M02", "S52M03", "S52M04", 26, constants.FIRPRO, True, 2),  # spl052 screwem
            (60, "S61M00", "S61M01", "S61M02", "S61M03", "S61M04", 32, constants.FIRPRO, False, 2),  # spl061 toastem
        ]
        for (
            spell_id,
            caster_id,
            broadcast_id,
            hit_id,
            other_id,
            protect_id,
            damage,
            protection,
            hits_self,
            mercy_level,
        ) in area_damage:
            if spell_id not in effects:
                continue
            effects[spell_id].requires_target = False
            effects[spell_id].message_id = caster_id
            effects[spell_id].handler = self._area_damage_handler(
                caster_id=caster_id,
                broadcast_id=broadcast_id,
                hit_id=hit_id,
                other_id=other_id,
                protect_id=protect_id,
                damage=damage,
                protection=protection,
                hits_self=hits_self,
                mercy_level=mercy_level,
            )
        return effects

    def cast_spell(
        self,
        player: models.PlayerModel,
        spell_id: int,
        target: Optional[str],
        target_player: Optional[models.PlayerModel],
        *,
        apply_cost: bool = True,
    ) -> EffectResult:
        if spell_id not in self.effects:
            raise EffectError(f"Unknown spell {spell_id}")
        effect = self.effects[spell_id]

        now = self.clock()
        player_cooldowns = self.cooldowns.setdefault(player.plyrid, {})
        last_used = player_cooldowns.get(spell_id, -float("inf"))
        if now - last_used < effect.cooldown:
            raise CooldownActiveError(
                f"Spell {spell_id} on cooldown for {effect.cooldown - (now - last_used):.2f}s"
            )

        if effect.requires_target and not target:
            raise TargetingError("This spell requires a target")
        if effect.handler and effect.requires_target and target_player is None:
            raise TargetingError("Target player is required for this spell")

        if apply_cost and player.spts < effect.cost:
            raise ResourceCostError("Not enough spell points to cast")

        if apply_cost:
            player.spts -= effect.cost
        player_cooldowns[spell_id] = now

        if effect.handler:
            return effect.handler(player, target, target_player, effect)

        text = self.messages.messages.get(
            effect.message_id or "", self.messages.messages.get("PRAYER", "")
        )
        return EffectResult(
            success=True,
            message_id=effect.message_id or "",
            text=text,
            animation=effect.animation,
            context={"target": target} if target else {},
        )

    def _transformation_handler(
        self,
        flag: constants.PlayerFlag,
        direct_key: str,
        broadcast_key: str,
    ) -> Callable[
        [models.PlayerModel, Optional[str], Optional[models.PlayerModel], SpellEffect],
        EffectResult,
    ]:
        def _handler(
            player: models.PlayerModel,
            target: Optional[str],
            target_player: Optional[models.PlayerModel],
            effect: SpellEffect,
        ) -> EffectResult:  # noqa: ARG001
            player.flags |= flag

            direct_text = self.messages.messages.get(direct_key, "")
            broadcast_text = self.messages.messages.get(broadcast_key, "")

            return EffectResult(
                success=True,
                message_id=direct_key,
                text=direct_text,
                animation=effect.animation,
                context={
                    "broadcast": broadcast_text % getattr(player, "plyrid", "")
                    if "%s" in broadcast_text
                    else broadcast_text,
                    "target": target,
                },
            )

        return _handler

    def _format_message(self, message_id: str, *args: object) -> str:
        template = self.messages.messages.get(message_id, "")
        if args:
            try:
                return template % args
            except TypeError:
                return template
        return template

    def _kheshe(self, player: models.PlayerModel) -> str:
        if player.charms[constants.CharmSlot.ALTERNATE_NAME] > 0:
            return "it"
        return "she" if player.flags & constants.PlayerFlag.FEMALE else "he"

    def _message_id_with_offset(self, base_id: str, offset: int) -> str:
        prefix, value = base_id[:-2], int(base_id[-2:])
        return f"{prefix}{value + offset:02d}"

    def _direct_damage_handler(
        self,
        *,
        damage: int,
        protection: int,
        mercy_level: int,
        base_id: str,
    ) -> Callable[
        [models.PlayerModel, Optional[str], Optional[models.PlayerModel], SpellEffect],
        EffectResult,
    ]:
        def _handler(
            player: models.PlayerModel,
            target: Optional[str],
            target_player: Optional[models.PlayerModel],
            effect: SpellEffect,
        ) -> EffectResult:
            if not target_player:
                raise TargetingError("Target player is required for this spell")

            if target_player.charms[protection]:
                caster_id = base_id
                target_id = self._message_id_with_offset(base_id, 1)
                broadcast_id = self._message_id_with_offset(base_id, 2)
                caster_text = self._format_message(caster_id, target_player.altnam)
                target_text = self._format_message(target_id, player.altnam)
                broadcast_text = self._format_message(
                    broadcast_id, player.altnam, target_player.altnam
                )
                return EffectResult(
                    success=False,
                    message_id=caster_id,
                    text=caster_text,
                    animation=effect.animation,
                    context={
                        "target_message_id": target_id,
                        "target_text": target_text,
                        "broadcast": broadcast_text,
                        "broadcast_message_id": broadcast_id,
                        "broadcast_exclude_player": target_player.plyrid,
                        "target": target,
                    },
                )

            if target_player.level <= mercy_level:
                caster_text = self._format_message("MERCYA", target_player.altnam)
                target_text = self._format_message("MERCYB", player.altnam)
                broadcast_text = self._format_message(
                    "MERCYC", player.altnam, target_player.altnam, self._kheshe(target_player)
                )
                return EffectResult(
                    success=False,
                    message_id="MERCYA",
                    text=caster_text,
                    animation=effect.animation,
                    context={
                        "target_message_id": "MERCYB",
                        "target_text": target_text,
                        "broadcast": broadcast_text,
                        "broadcast_message_id": "MERCYC",
                        "broadcast_exclude_player": target_player.plyrid,
                        "target": target,
                    },
                )

            caster_id = self._message_id_with_offset(base_id, 3)
            target_id = self._message_id_with_offset(base_id, 4)
            broadcast_id = self._message_id_with_offset(base_id, 5)
            target_player.hitpts = max(0, target_player.hitpts - damage)
            caster_text = self._format_message(caster_id, target_player.altnam)
            target_text = self._format_message(target_id, player.altnam, damage)
            broadcast_text = self._format_message(
                broadcast_id, player.altnam, target_player.altnam, self._kheshe(target_player)
            )
            return EffectResult(
                success=True,
                message_id=caster_id,
                text=caster_text,
                animation=effect.animation,
                context={
                    "target_message_id": target_id,
                    "target_text": target_text,
                    "broadcast": broadcast_text,
                    "broadcast_message_id": broadcast_id,
                    "broadcast_exclude_player": target_player.plyrid,
                    "target": target,
                },
            )

        return _handler

    def _area_damage_handler(
        self,
        *,
        caster_id: str,
        broadcast_id: str,
        hit_id: str,
        other_id: str,
        protect_id: str,
        damage: int,
        protection: int,
        hits_self: bool,
        mercy_level: int,
    ) -> Callable[
        [models.PlayerModel, Optional[str], Optional[models.PlayerModel], SpellEffect],
        EffectResult,
    ]:
        def _handler(
            player: models.PlayerModel,
            target: Optional[str],
            target_player: Optional[models.PlayerModel],
            effect: SpellEffect,
        ) -> EffectResult:  # noqa: ARG001
            result = self._msgutl2(
                player,
                caster_key=caster_id,
                broadcast_key=broadcast_id,
                target=target,
                success=True,
                effect=effect,
            )
            result.context["area_damage"] = {
                "hit_id": hit_id,
                "other_id": other_id,
                "protect_id": protect_id,
                "damage": damage,
                "protection": protection,
                "hits_self": hits_self,
                "mercy_level": mercy_level,
            }
            return result

        return _handler

    def _sap_spell_points_handler(
        self,
        *,
        amount: int,
        failure_ids: tuple[str, str, str],
        success_ids: tuple[str, str, str],
    ) -> Callable[
        [models.PlayerModel, Optional[str], Optional[models.PlayerModel], SpellEffect],
        EffectResult,
    ]:
        # Legacy sap spell points handling (legacy/KYRSPEL.C:1028-1040, 1093-1105).
        def _handler(
            player: models.PlayerModel,
            target: Optional[str],
            target_player: Optional[models.PlayerModel],
            effect: SpellEffect,
        ) -> EffectResult:
            if not target_player:
                raise TargetingError("Target player is required for this spell")
            if target_player.charms[constants.OBJPRO] or target_player.spts == 0:
                return self._msgutl3(
                    player,
                    target_player,
                    caster_key=failure_ids[0],
                    target_key=failure_ids[1],
                    broadcast_key=failure_ids[2],
                    target=target,
                    success=False,
                    effect=effect,
                )

            target_player.spts = max(0, target_player.spts - amount)
            return self._msgutl3(
                player,
                target_player,
                caster_key=success_ids[0],
                target_key=success_ids[1],
                broadcast_key=success_ids[2],
                target=target,
                success=True,
                effect=effect,
            )

        return _handler

    def _msgutl2(
        self,
        caster: models.PlayerModel,
        *,
        caster_key: str,
        broadcast_key: str,
        target: Optional[str],
        success: bool,
        effect: SpellEffect,
    ) -> EffectResult:
        caster_text = self._format_message(caster_key)
        broadcast_text = self._format_message(broadcast_key, caster.altnam)
        context = {
            "broadcast": broadcast_text,
            "broadcast_message_id": broadcast_key,
        }
        if target:
            context["target"] = target
        return EffectResult(
            success=success,
            message_id=caster_key,
            text=caster_text,
            animation=effect.animation,
            context=context,
        )

    def _msgutl3(
        self,
        caster: models.PlayerModel,
        target_player: models.PlayerModel,
        *,
        caster_key: str,
        target_key: str,
        broadcast_key: str,
        target: Optional[str],
        success: bool,
        effect: SpellEffect,
    ) -> EffectResult:
        caster_text = self._format_message(caster_key)
        target_text = self._format_message(target_key, caster.altnam)
        broadcast_text = self._format_message(
            broadcast_key, caster.altnam, target_player.altnam
        )
        context = {
            "target_message_id": target_key,
            "target_text": target_text,
            "broadcast": broadcast_text,
            "broadcast_message_id": broadcast_key,
            "broadcast_exclude_player": target_player.plyrid,
        }
        if target:
            context["target"] = target
        return EffectResult(
            success=success,
            message_id=caster_key,
            text=caster_text,
            animation=effect.animation,
            context=context,
        )

    def _bookworm_handler(
        self,
    ) -> Callable[
        [models.PlayerModel, Optional[str], Optional[models.PlayerModel], SpellEffect],
        EffectResult,
    ]:
        def _handler(
            player: models.PlayerModel,
            target: Optional[str],
            target_player: Optional[models.PlayerModel],
            effect: SpellEffect,
        ) -> EffectResult:
            if not target_player:
                raise TargetingError("Target player is required for bookworm")
            if target_player.charms[constants.OBJPRO]:
                return self._msgutl3(
                    player,
                    target_player,
                    caster_key="S05M00",
                    target_key="S05M01",
                    broadcast_key="S05M02",
                    target=target,
                    success=False,
                    effect=effect,
                )

            moonstone_id = None
            for obj in self.objects.values():
                if obj.name.lower() == "moonstone":
                    moonstone_id = obj.id
                    break
            if moonstone_id is None or not remove_inventory_item(player, moonstone_id):
                return self._msgutl2(
                    player,
                    caster_key="MISS00",
                    broadcast_key="MISS01",
                    target=target,
                    success=False,
                    effect=effect,
                )

            wipe_spellbook_bits(target_player)
            caster_text = self._format_message(
                "S05M03", target_player.altnam, target_player.altnam
            )
            target_text = self._format_message(
                "S05M04", player.altnam, player.altnam
            )
            broadcast_text = self._format_message(
                "S05M05", player.altnam, player.altnam, target_player.altnam
            )
            context = {
                "target_message_id": "S05M04",
                "target_text": target_text,
                "broadcast": broadcast_text,
                "broadcast_message_id": "S05M05",
                "broadcast_exclude_player": target_player.plyrid,
            }
            if target:
                context["target"] = target
            return EffectResult(
                success=True,
                message_id="S05M03",
                text=caster_text,
                animation=effect.animation,
                context=context,
            )

        return _handler

    def _forget_all_handler(
        self,
        *,
        failure_key: str,
        failure_target_key: str,
        failure_broadcast_key: str,
        success_key: str,
        success_target_key: str,
        success_broadcast_key: str,
    ) -> Callable[
        [models.PlayerModel, Optional[str], Optional[models.PlayerModel], SpellEffect],
        EffectResult,
    ]:
        def _handler(
            player: models.PlayerModel,
            target: Optional[str],
            target_player: Optional[models.PlayerModel],
            effect: SpellEffect,
        ) -> EffectResult:  # noqa: ARG001
            if not target_player:
                raise TargetingError("Target player is required for this spell")
            if target_player.charms[constants.OBJPRO] or target_player.nspells == 0:
                return self._msgutl3(
                    player,
                    target_player,
                    caster_key=failure_key,
                    target_key=failure_target_key,
                    broadcast_key=failure_broadcast_key,
                    target=target,
                    success=False,
                    effect=effect,
                )

            forget_all_memorized(target_player)
            return self._msgutl3(
                player,
                target_player,
                caster_key=success_key,
                target_key=success_target_key,
                broadcast_key=success_broadcast_key,
                target=target,
                success=True,
                effect=effect,
            )

        return _handler

    def _forget_one_handler(
        self,
        *,
        failure_key: str,
        failure_target_key: str,
        failure_broadcast_key: str,
        success_key: str,
        success_target_key: str,
        success_broadcast_key: str,
    ) -> Callable[
        [models.PlayerModel, Optional[str], Optional[models.PlayerModel], SpellEffect],
        EffectResult,
    ]:
        def _handler(
            player: models.PlayerModel,
            target: Optional[str],
            target_player: Optional[models.PlayerModel],
            effect: SpellEffect,
        ) -> EffectResult:  # noqa: ARG001
            if not target_player:
                raise TargetingError("Target player is required for this spell")
            if target_player.charms[constants.OBJPRO] or target_player.nspells == 0:
                return self._msgutl3(
                    player,
                    target_player,
                    caster_key=failure_key,
                    target_key=failure_target_key,
                    broadcast_key=failure_broadcast_key,
                    target=target,
                    success=False,
                    effect=effect,
                )

            forgotten = forget_one_random_memorized(target_player, self.rng)
            result = self._msgutl3(
                player,
                target_player,
                caster_key=success_key,
                target_key=success_target_key,
                broadcast_key=success_broadcast_key,
                target=target,
                success=True,
                effect=effect,
            )
            result.context["forgot_spell_id"] = forgotten
            return result

        return _handler

    def _howru_handler(
        self,
    ) -> Callable[
        [models.PlayerModel, Optional[str], Optional[models.PlayerModel], SpellEffect],
        EffectResult,
    ]:
        def _handler(
            player: models.PlayerModel,
            target: Optional[str],
            target_player: Optional[models.PlayerModel],
            effect: SpellEffect,
        ) -> EffectResult:
            if not target_player:
                raise TargetingError("Target player is required for howru")
            caster_text = self._format_message("S34M00", target_player.hitpts)
            target_text = self._format_message("S34M01", player.altnam)
            broadcast_text = self._format_message(
                "S34M02", player.altnam, target_player.altnam
            )
            context = {
                "target_message_id": "S34M01",
                "target_text": target_text,
                "broadcast": broadcast_text,
                "broadcast_message_id": "S34M02",
                "broadcast_exclude_player": target_player.plyrid,
            }
            if target:
                context["target"] = target
            return EffectResult(
                success=True,
                message_id="S34M00",
                text=caster_text,
                animation=effect.animation,
                context=context,
            )

        return _handler


@dataclass
class ObjectEffect:
    obj: models.GameObjectModel
    message_id: str
    cooldown: float
    requires_target: bool = False
    animation: Optional[str] = None


class ObjectEffectEngine:
    def __init__(
        self,
        objects: Iterable[models.GameObjectModel],
        messages: models.MessageBundleModel,
        clock: Callable[[], float] | None = None,
    ):
        self.objects = {obj.id: obj for obj in objects}
        self.messages = messages
        self.clock = clock or time.monotonic
        self.cooldowns: Dict[str, Dict[int, float]] = {}
        self.effects: Dict[int, ObjectEffect] = self._build_effects()

    def _build_effects(self) -> Dict[int, ObjectEffect]:
        effects: Dict[int, ObjectEffect] = {}
        for obj in self.objects.values():
            if obj.id == 32:  # pinecone
                effects[obj.id] = ObjectEffect(
                    obj=obj,
                    message_id="MAGF02",
                    cooldown=1.0,
                    animation=f"obj{obj.id}",
                )
            elif obj.id == 33:  # dagger
                effects[obj.id] = ObjectEffect(
                    obj=obj,
                    message_id="OBJM05",
                    cooldown=1.5,
                    requires_target=True,
                    animation=f"obj{obj.id}",
                )
        return effects

    def use_object(
        self, player_id: str, object_id: int, room_id: int, target: Optional[str] = None
    ) -> EffectResult:
        if object_id not in self.effects:
            raise EffectError(f"Unknown object {object_id}")
        effect = self.effects[object_id]

        now = self.clock()
        player_cooldowns = self.cooldowns.setdefault(player_id, {})
        last_used = player_cooldowns.get(object_id, -float("inf"))
        if now - last_used < effect.cooldown:
            raise CooldownActiveError(
                f"Object {object_id} on cooldown for {effect.cooldown - (now - last_used):.2f}s"
            )

        if effect.requires_target and not target:
            raise TargetingError("This object requires a target")

        player_cooldowns[object_id] = now
        text = self.messages.messages.get(effect.message_id, effect.obj.name)
        context = {"room": room_id}
        if target:
            context["target"] = target

        return EffectResult(
            success=True,
            message_id=effect.message_id,
            text=text,
            animation=effect.animation,
            context=context,
        )
