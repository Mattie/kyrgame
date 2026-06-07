from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from . import models

# Default session expiration: 24 hours
DEFAULT_SESSION_EXPIRATION_HOURS = 24


class PlayerSessionRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_session(
        self,
        player_id: int,
        session_token: str,
        room_id: int,
        expiration_hours: int = DEFAULT_SESSION_EXPIRATION_HOURS,
        lifecycle_state: str | None = None,
        lifecycle_step: int | None = None,
        account_id: int | None = None,
        session_kind: str = "game",
        hidden_from_activity: bool = False,
    ):
        now = datetime.now(timezone.utc)
        player_session = models.PlayerSession(
            player_id=player_id,
            account_id=account_id,
            session_token=session_token,
            room_id=room_id,
            session_kind=session_kind,
            hidden_from_activity=hidden_from_activity,
            lifecycle_state=lifecycle_state,
            lifecycle_step=lifecycle_step,
            last_seen=now,
            expires_at=now + timedelta(hours=expiration_hours),
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

    def deactivate_all(
        self,
        player_id: int,
        timestamp: Optional[datetime] = None,
        session_kind: str | None = None,
    ) -> List[str]:
        # First, get all active session tokens
        conditions = [
            models.PlayerSession.player_id == player_id,
            models.PlayerSession.is_active.is_(True),
        ]
        if session_kind is not None:
            conditions.append(models.PlayerSession.session_kind == session_kind)
        tokens = [
            row[0] for row in self.session.execute(
                select(models.PlayerSession.session_token).where(*conditions)
            )
        ]
        
        # Then bulk update all matching sessions
        if tokens:
            self.session.execute(
                update(models.PlayerSession)
                .where(*conditions)
                .values(
                    is_active=False,
                    last_seen=timestamp or datetime.now(timezone.utc)
                )
            )
        
        return tokens

    def list_active(
        self, player_id: int, session_kind: str | None = None
    ) -> List[models.PlayerSession]:
        conditions = [
            models.PlayerSession.player_id == player_id,
            models.PlayerSession.is_active.is_(True),
        ]
        if session_kind is not None:
            conditions.append(models.PlayerSession.session_kind == session_kind)
        return list(
            self.session.scalars(
                select(models.PlayerSession).where(*conditions)
            ).all()
        )

    def get_by_token(self, session_token: str, active_only: bool = True):
        stmt = select(models.PlayerSession).where(models.PlayerSession.session_token == session_token)
        if active_only:
            stmt = stmt.where(
                models.PlayerSession.is_active.is_(True),
                models.PlayerSession.expires_at > datetime.now(timezone.utc)
            )
        return self.session.scalar(stmt)

    def set_room(self, session_token: str, room_id: int):
        player_session = self.get_by_token(session_token, active_only=False)
        if player_session:
            player_session.room_id = room_id
        return player_session

    def set_lifecycle(
        self,
        session_token: str,
        lifecycle_state: str | None,
        lifecycle_step: int | None,
    ):
        player_session = self.get_by_token(session_token, active_only=False)
        if player_session:
            player_session.lifecycle_state = lifecycle_state
            player_session.lifecycle_step = lifecycle_step
        return player_session


class AccountRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_userid_norm(self, userid_norm: str) -> models.Account | None:
        return self.session.scalar(
            select(models.Account).where(models.Account.userid_norm == userid_norm)
        )

    def create_account(
        self,
        *,
        userid: str,
        userid_norm: str,
        password_hash: str,
        player_id: int,
    ) -> models.Account:
        account = models.Account(
            userid=userid,
            userid_norm=userid_norm,
            password_hash=password_hash,
            player_id=player_id,
        )
        self.session.add(account)
        return account


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


class LocationRepository:
    def __init__(self, session: Session):
        self.session = session

    def update_objects(self, location_id: int, object_ids: List[int]):
        """Update the objects list for a location in the database."""
        location = self.session.scalar(
            select(models.Location).where(models.Location.id == location_id)
        )
        if not location:
            raise ValueError(f"Location {location_id} not found in database")
        location.objects = object_ids
        location.nlobjs = len(object_ids)
        self.session.flush([location])
        return location

    def get(self, location_id: int) -> Optional[models.Location]:
        """Get a location record from the database."""
        return self.session.scalar(
            select(models.Location).where(models.Location.id == location_id)
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
