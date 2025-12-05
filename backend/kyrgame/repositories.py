from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import models


class PlayerSessionRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_session(self, player_id: int, session_token: str, room_id: int):
        player_session = models.PlayerSession(
            player_id=player_id,
            session_token=session_token,
            room_id=room_id,
            last_seen=datetime.now(timezone.utc),
        )
        self.session.add(player_session)
        return player_session

    def mark_seen(self, session_token: str, timestamp: Optional[datetime] = None):
        player_session = self.get_by_token(session_token, active_only=False)
        if player_session:
            player_session.last_seen = timestamp or datetime.now(timezone.utc)
        return player_session

    def deactivate(self, session_token: str, timestamp: Optional[datetime] = None):
        player_session = self.get_by_token(session_token, active_only=False)
        if player_session:
            player_session.is_active = False
            player_session.last_seen = timestamp or datetime.now(timezone.utc)
        return player_session

    def deactivate_all(self, player_id: int, timestamp: Optional[datetime] = None) -> List[str]:
        tokens: List[str] = []
        for session in self.session.scalars(
            select(models.PlayerSession).where(
                models.PlayerSession.player_id == player_id,
                models.PlayerSession.is_active.is_(True),
            )
        ).all():
            session.is_active = False
            session.last_seen = timestamp or datetime.now(timezone.utc)
            tokens.append(session.session_token)
        return tokens

    def list_active(self, player_id: int) -> List[models.PlayerSession]:
        return list(
            self.session.scalars(
                select(models.PlayerSession).where(
                    models.PlayerSession.player_id == player_id,
                    models.PlayerSession.is_active.is_(True),
                )
            ).all()
        )

    def get_by_token(self, session_token: str, active_only: bool = True):
        stmt = select(models.PlayerSession).where(models.PlayerSession.session_token == session_token)
        if active_only:
            stmt = stmt.where(models.PlayerSession.is_active.is_(True))
        return self.session.scalar(stmt)

    def set_room(self, session_token: str, room_id: int):
        player_session = self.get_by_token(session_token, active_only=False)
        if player_session:
            player_session.room_id = room_id
        return player_session


class InventoryRepository:
    def __init__(self, session: Session):
        self.session = session

    def set_slot(self, player_id: int, slot_index: int, object_id: int, object_value: int):
        inventory_slot = self.session.scalar(
            select(models.PlayerInventory).where(
                models.PlayerInventory.player_id == player_id,
                models.PlayerInventory.slot_index == slot_index,
            )
        )
        if inventory_slot:
            inventory_slot.object_id = object_id
            inventory_slot.object_value = object_value
        else:
            inventory_slot = models.PlayerInventory(
                player_id=player_id,
                slot_index=slot_index,
                object_id=object_id,
                object_value=object_value,
            )
            self.session.add(inventory_slot)
            self.session.flush([inventory_slot])
        return inventory_slot

    def list_for_player(self, player_id: int) -> List[models.PlayerInventory]:
        return list(
            self.session.scalars(
                select(models.PlayerInventory)
                .where(models.PlayerInventory.player_id == player_id)
                .order_by(models.PlayerInventory.slot_index)
            ).all()
        )

    def clear(self, player_id: int):
        self.session.execute(
            delete(models.PlayerInventory).where(models.PlayerInventory.player_id == player_id)
        )


class SpellTimerRepository:
    def __init__(self, session: Session):
        self.session = session

    def set_timer(self, player_id: int, spell_id: int, remaining_ticks: int):
        timer = self.session.scalar(
            select(models.SpellTimer).where(
                models.SpellTimer.player_id == player_id, models.SpellTimer.spell_id == spell_id
            )
        )
        if timer:
            timer.remaining_ticks = remaining_ticks
        else:
            timer = models.SpellTimer(
                player_id=player_id, spell_id=spell_id, remaining_ticks=remaining_ticks
            )
            self.session.add(timer)
            self.session.flush([timer])
        return timer

    def prune_expired(self, player_id: int):
        self.session.execute(
            delete(models.SpellTimer).where(
                models.SpellTimer.player_id == player_id, models.SpellTimer.remaining_ticks <= 0
            )
        )

    def list_active(self, player_id: int) -> List[models.SpellTimer]:
        return list(
            self.session.scalars(
                select(models.SpellTimer)
                .where(models.SpellTimer.player_id == player_id)
                .order_by(models.SpellTimer.spell_id)
            ).all()
        )


class RoomOccupantRepository:
    def __init__(self, session: Session):
        self.session = session

    def add_or_update(self, room_id: int, player_id: int):
        occupant = self.session.scalar(
            select(models.RoomOccupant).where(
                models.RoomOccupant.room_id == room_id,
                models.RoomOccupant.player_id == player_id,
            )
        )
        if occupant:
            occupant.entered_at = datetime.now(timezone.utc)
        else:
            occupant = models.RoomOccupant(room_id=room_id, player_id=player_id)
            self.session.add(occupant)
            self.session.flush([occupant])
        return occupant

    def remove(self, room_id: int, player_id: int):
        self.session.execute(
            delete(models.RoomOccupant).where(
                models.RoomOccupant.room_id == room_id,
                models.RoomOccupant.player_id == player_id,
            )
        )

    def list_room(self, room_id: int) -> List[models.RoomOccupant]:
        return list(
            self.session.scalars(
                select(models.RoomOccupant)
                .where(models.RoomOccupant.room_id == room_id)
                .order_by(models.RoomOccupant.player_id)
            ).all()
        )

    def clear(self, room_id: int):
        self.session.execute(
            delete(models.RoomOccupant).where(models.RoomOccupant.room_id == room_id)
        )
