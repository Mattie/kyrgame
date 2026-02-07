from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, Optional

from . import constants, models
from .spellbook import forget_all_memorized, forget_one_random_memorized


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
    handler: Optional[Callable[[models.PlayerModel, Optional[str], "SpellEffect"], EffectResult]] = None


class SpellEffectEngine:
    def __init__(
        self,
        spells: Iterable[models.SpellModel],
        messages: models.MessageBundleModel,
        clock: Callable[[], float] | None = None,
        rng: random.Random | None = None,
    ):
        self.spells = {spell.id: spell for spell in spells}
        self.messages = messages
        self.clock = clock or time.monotonic
        self.rng = rng or random.Random()
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

        if 16 in effects:
            # Legacy transformation: flyaway turns the caster into a pegasus (legacy/KYRSPEL.C lines 644-651).
            effects[16].message_id = "S16M00"
            effects[16].requires_target = False
            effects[16].handler = self._transformation_handler(
                flag=constants.PlayerFlag.PEGASU,
                direct_key="S16M00",
                broadcast_key="S16M01",
            )

        if 12 in effects:
            # Legacy spell: dumdum forgets all memorized spells (legacy/KYRSPEL.C lines 607-615).
            effects[12].message_id = "S13M03"
            effects[12].handler = self._forget_all_handler(
                failure_key="S13M00",
                success_key="S13M03",
            )

        if 50 in effects:
            # Legacy spell: saywhat forgets one memorized spell (legacy/KYRSPEL.C lines 1047-1055).
            effects[50].message_id = "S51M03"
            effects[50].handler = self._forget_one_handler(
                failure_key="S51M00",
                success_key="S51M03",
            )

        if 62 in effects:
            # Legacy transformation: weewillo grants willowisp wings (legacy/KYRSPEL.C lines 1188-1195).
            effects[62].message_id = "S62M00"
            effects[62].requires_target = False
            effects[62].handler = self._transformation_handler(
                flag=constants.PlayerFlag.WILLOW,
                direct_key="S62M00",
                broadcast_key="S62M01",
            )
        return effects

    def cast_spell(
        self, player: models.PlayerModel, spell_id: int, target: Optional[str]
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

        if player.spts < effect.cost:
            raise ResourceCostError("Not enough spell points to cast")

        player.spts -= effect.cost
        player_cooldowns[spell_id] = now

        if effect.handler:
            return effect.handler(player, target, effect)

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
    ) -> Callable[[models.PlayerModel, Optional[str], SpellEffect], EffectResult]:
        def _handler(player: models.PlayerModel, target: Optional[str], effect: SpellEffect) -> EffectResult:  # noqa: ARG001
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

    def _forget_all_handler(
        self,
        *,
        failure_key: str,
        success_key: str,
    ) -> Callable[[models.PlayerModel, Optional[str], SpellEffect], EffectResult]:
        def _handler(player: models.PlayerModel, target: Optional[str], effect: SpellEffect) -> EffectResult:  # noqa: ARG001
            if player.charms[constants.OBJPRO] or player.nspells == 0:
                text = self.messages.messages.get(failure_key, "")
                return EffectResult(
                    success=False,
                    message_id=failure_key,
                    text=text,
                    animation=effect.animation,
                    context={"target": target} if target else {},
                )

            forget_all_memorized(player)
            text = self.messages.messages.get(success_key, "")
            return EffectResult(
                success=True,
                message_id=success_key,
                text=text,
                animation=effect.animation,
                context={"target": target} if target else {},
            )

        return _handler

    def _forget_one_handler(
        self,
        *,
        failure_key: str,
        success_key: str,
    ) -> Callable[[models.PlayerModel, Optional[str], SpellEffect], EffectResult]:
        def _handler(player: models.PlayerModel, target: Optional[str], effect: SpellEffect) -> EffectResult:  # noqa: ARG001
            if player.charms[constants.OBJPRO] or player.nspells == 0:
                text = self.messages.messages.get(failure_key, "")
                return EffectResult(
                    success=False,
                    message_id=failure_key,
                    text=text,
                    animation=effect.animation,
                    context={"target": target} if target else {},
                )

            forgotten = forget_one_random_memorized(player, self.rng)
            text = self.messages.messages.get(success_key, "")
            context = {"target": target} if target else {}
            context["forgot_spell_id"] = forgotten
            return EffectResult(
                success=True,
                message_id=success_key,
                text=text,
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
