from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, Optional

from . import constants, models


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


class SpellEffectEngine:
    def __init__(
        self,
        spells: Iterable[models.SpellModel],
        messages: models.MessageBundleModel,
        clock: Callable[[], float] | None = None,
    ):
        self.spells = {spell.id: spell for spell in spells}
        self.messages = messages
        self.clock = clock or time.monotonic
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
