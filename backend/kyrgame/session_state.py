import copy
from typing import Any

from sqlalchemy import select

from . import models


def player_model_from_record(record: models.Player) -> models.PlayerModel:
    return models.PlayerModel(
        uidnam=record.uidnam,
        plyrid=record.plyrid,
        altnam=record.altnam,
        attnam=record.attnam,
        gpobjs=record.gpobjs,
        nmpdes=record.nmpdes,
        modno=record.modno,
        level=record.level,
        gamloc=record.gamloc,
        pgploc=record.pgploc,
        flags=record.flags,
        gold=record.gold,
        npobjs=record.npobjs,
        obvals=record.obvals,
        nspells=record.nspells,
        spts=record.spts,
        hitpts=record.hitpts,
        offspls=record.offspls,
        defspls=record.defspls,
        othspls=record.othspls,
        charms=record.charms,
        spells=record.spells,
        gemidx=record.gemidx,
        stones=record.stones,
        macros=record.macros,
        stumpi=record.stumpi,
        spouse=record.spouse,
    )


def copy_player_model_state(
    destination: models.PlayerModel, source: models.PlayerModel
) -> None:
    for field_name in models.PlayerModel.model_fields:
        object.__setattr__(
            destination,
            field_name,
            copy.deepcopy(getattr(source, field_name)),
        )


def sync_active_player_state_from_record(
    app: Any, record: models.Player
) -> models.PlayerModel:
    fresh = player_model_from_record(record)
    active_sessions = getattr(app.state, "active_player_sessions", {})
    active_players = getattr(app.state, "active_players", {})
    synced: models.PlayerModel | None = None

    for player_state in active_sessions.values():
        if player_state.plyrid != fresh.plyrid:
            continue
        copy_player_model_state(player_state, fresh)
        synced = player_state

    active_player = active_players.get(fresh.plyrid)
    if active_player is not None:
        copy_player_model_state(active_player, fresh)
        synced = active_player

    if synced is not None:
        active_players[fresh.plyrid] = synced
    return fresh


def sync_active_player_state_from_db(
    app: Any, player_id: str
) -> models.PlayerModel | None:
    session_factory = getattr(app.state, "session_factory", None)
    if session_factory is None:
        return None
    with session_factory() as db:
        record = db.scalar(select(models.Player).where(models.Player.plyrid == player_id))
        if record is None:
            return None
        return sync_active_player_state_from_record(app, record)
