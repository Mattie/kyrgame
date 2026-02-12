from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, ContextManager, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from kyrgame import constants, models


class SpellTickPlayerRepository(Protocol):
    def list_players_for_spell_tick(self) -> list[models.Player]: ...


class SpellTickMessagingAdapter(Protocol):
    def send_direct(self, *, player_id: str, message_id: str, text: str) -> None: ...

    def broadcast_room(
        self,
        *,
        room_id: int,
        exclude_player_id: str,
        message_id: str,
        text: str,
    ) -> None: ...


@dataclass(frozen=True)
class SpellTickConstants:
    alt_name_slot: int = constants.ALTNAM
    invisibility_flag: int = int(constants.PlayerFlag.INVISF)
    pegasus_flag: int = int(constants.PlayerFlag.PEGASU)
    willow_flag: int = int(constants.PlayerFlag.WILLOW)
    pseudo_dragon_flag: int = int(constants.PlayerFlag.PDRAGN)

    @property
    def alt_name_clear_mask(self) -> int:
        return (
            self.invisibility_flag
            | self.pegasus_flag
            | self.willow_flag
            | self.pseudo_dragon_flag
        )


class SQLAlchemySpellTickPlayerRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_players_for_spell_tick(self) -> list[models.Player]:
        return list(
            self.session.scalars(
                select(models.Player)
                .where(models.Player.gamloc != -1)
                .order_by(models.Player.modno)
            ).all()
        )


class NoopSpellTickMessaging:
    def send_direct(self, *, player_id: str, message_id: str, text: str) -> None:
        return None

    def broadcast_room(
        self,
        *,
        room_id: int,
        exclude_player_id: str,
        message_id: str,
        text: str,
    ) -> None:
        return None


class SpellTickSystem:
    """Port of KYRSPEL.C `splrtk()` timer behavior for scheduler-safe callbacks."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], ContextManager[Session]],
        player_repository_factory: Callable[[Session], SpellTickPlayerRepository],
        messaging: SpellTickMessagingAdapter,
        constants: SpellTickConstants,
        message_lookup: Callable[[str], str],
    ) -> None:
        self._session_factory = session_factory
        self._player_repository_factory = player_repository_factory
        self._messaging = messaging
        self._constants = constants
        self._message_lookup = message_lookup

    def __call__(self) -> None:
        self.tick()

    def tick(self) -> None:
        # Legacy parity: KYRSPEL.C splrtk() iterates players each rtkick window and
        # updates macros/spts/charm timers before re-scheduling in insrtk/splrtk.
        # Ref: legacy/KYRSPEL.C lines 216-263.
        with self._session_factory() as session:
            repo = self._player_repository_factory(session)
            players = repo.list_players_for_spell_tick()
            for player in players:
                self._tick_player(player)
            session.commit()

    def _tick_player(self, player: models.Player) -> None:
        player.macros = 0

        max_spell_points = 2 * player.level
        player.spts = min(player.spts + 2, max_spell_points)

        for index, timer in enumerate(player.charms):
            if timer <= 0:
                continue
            next_timer = timer - 1
            player.charms[index] = next_timer
            if next_timer != 0:
                continue

            message_id = _base_charm_message_id(index)
            self._messaging.send_direct(
                player_id=player.plyrid,
                message_id=message_id,
                text=self._message_lookup(message_id),
            )

            if index == self._constants.alt_name_slot:
                self._expire_alt_name(player)

    def _expire_alt_name(self, player: models.Player) -> None:
        # Legacy parity: ALTNAM expiration clears morph flags and reverts player
        # identity fields after broadcasting RET2NM to room occupants.
        # Ref: legacy/KYRSPEL.C lines 245-253, legacy/KYRANDIA.H lines 80, 90-96.
        original_alt_name = player.altnam
        player.flags &= ~self._constants.alt_name_clear_mask

        return_template = self._message_lookup("RET2NM")
        if "%" in return_template:
            return_message = return_template % (original_alt_name, player.plyrid)
        else:
            return_message = return_template
        self._messaging.broadcast_room(
            room_id=player.gamloc,
            exclude_player_id=player.plyrid,
            message_id="RET2NM",
            text=return_message,
        )

        player.altnam = player.plyrid
        player.attnam = player.plyrid


def _base_charm_message_id(index: int) -> str:
    return "BASMSG" if index == 0 else f"BASMSG{index}"
