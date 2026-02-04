from sqlalchemy import select

from kyrgame import commands, fixtures, models
from kyrgame.database import create_session, get_engine, init_db_schema


def test_persist_player_state_updates_room_script_changes():
    engine = get_engine("sqlite+pysqlite:///:memory:")
    init_db_schema(engine)
    session = create_session(engine)

    base_player = fixtures.build_player()
    session.add(models.Player(**base_player.model_dump()))
    session.commit()

    updated_player = base_player.model_copy(
        update={
            "level": base_player.level + 1,
            "gold": base_player.gold + 10,
            "flags": base_player.flags | 0x80,
            "gpobjs": [29],
            "obvals": [0],
            "npobjs": 1,
            "gamloc": 219,
            "pgploc": base_player.gamloc,
        }
    )
    state = commands.GameState(player=updated_player, locations={}, db_session=session)

    commands._persist_player_state(state, updated_player)

    record = session.scalar(select(models.Player).where(models.Player.plyrid == base_player.plyrid))
    assert record is not None
    assert record.level == updated_player.level
    assert record.gold == updated_player.gold
    assert record.flags == updated_player.flags
    assert record.gpobjs == updated_player.gpobjs
    assert record.obvals == updated_player.obvals
    assert record.npobjs == updated_player.npobjs
    assert record.gamloc == updated_player.gamloc
    assert record.pgploc == updated_player.pgploc
