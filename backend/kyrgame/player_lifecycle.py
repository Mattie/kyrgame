from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from . import constants


@dataclass(frozen=True)
class DeathResetResult:
    player_id: str
    old_name: str
    old_room: int


def reset_player_after_death(
    player: Any,
    birthstone_picker: Callable[[int, int], int],
) -> DeathResetResult:
    """Reset a killed player to legacy initgp()/hitoth() room-0 state."""

    result = DeathResetResult(
        player_id=player.plyrid,
        old_name=player.altnam,
        old_room=player.gamloc,
    )
    old_flags = int(player.flags)

    # Legacy initgp() zeroes the gmplyr record, preserves true identity and sex,
    # rerolls birthstones, then hitoth()/entrgp() place the player at room 0.
    # (legacy/KYRANDIA.C:325-356; legacy/KYRSPEL.C:303-321)
    _set(player, "altnam", player.plyrid)
    _set(player, "attnam", player.plyrid)
    _set(player, "gamloc", 0)
    _set(player, "pgploc", 0)
    _set(player, "nmpdes", constants.level_to_nmpdes(1))
    _set(player, "level", 1)
    _set(player, "hitpts", 4)
    _set(player, "spts", 2)
    _set(player, "gold", 0)
    _set(player, "gpobjs", [])
    _set(player, "obvals", [])
    _set(player, "npobjs", 0)
    _set(player, "spells", [])
    _set(player, "nspells", 0)
    _set(player, "offspls", 0)
    _set(player, "defspls", 0)
    _set(player, "othspls", 0)
    _set(player, "charms", [0] * constants.NCHARM)
    _set(player, "gemidx", 0)
    _set(
        player,
        "stones",
        [
            birthstone_picker(
                constants.BIRTHSTONE_MIN,
                constants.BIRTHSTONE_MAX + 1,
            )
            for _ in range(constants.BIRTHSTONE_SLOTS)
        ],
    )
    _set(player, "macros", 0)
    _set(player, "stumpi", 0)
    _set(player, "spouse", "")
    _set(
        player,
        "flags",
        int(constants.PlayerFlag.LOADED)
        | (old_flags & int(constants.PlayerFlag.FEMALE)),
    )
    return result


def _set(player: Any, field: str, value: Any) -> None:
    object.__setattr__(player, field, value)
