import json
import importlib.util
from pathlib import Path

import pytest

from kyrgame import database, models
from kyrgame.moving_mobs import (
    audit_moving_mobs,
    cleanup_confirmation_token,
    cleanup_moving_mobs,
)
from kyrgame.scripts import audit_moving_mobs as audit_cli


def _seed_location(session, room_id: int, objects: list[int]):
    session.add(
        models.Location(
            id=room_id,
            brfdes=f"room {room_id}",
            objlds="on the ground",
            nlobjs=len(objects),
            objects=list(objects),
            gi_north=room_id,
            gi_south=room_id,
            gi_east=room_id,
            gi_west=room_id,
        )
    )


def _seed_runtime_state(session, **payload):
    session.add(
        models.RuntimeState(
            key="animation_tick",
            payload={
                "dryad_location": payload.get("dryad_location", 18),
                "zar_location": payload.get("zar_location", 250),
                "brownie_location": payload.get("brownie_location", 77),
                "brownie_path_index": payload.get("brownie_path_index", 22),
                "elf_last_room": payload.get("elf_last_room", 35),
                "elf_reward_next": payload.get("elf_reward_next", 1),
            },
        )
    )


def _session_with_mob_drift(tmp_path):
    engine = database.get_engine(f"sqlite+pysqlite:///{tmp_path / 'mobs.db'}")
    database.init_db_schema(engine)
    session = database.create_session(engine)
    _seed_location(session, 5, [45])
    _seed_location(session, 18, [45, 45, 2])
    _seed_location(session, 250, [52])
    _seed_location(session, 302, [52, 47])
    _seed_runtime_state(session, dryad_location=18, zar_location=250)
    session.commit()
    return session


def test_audit_reports_singleton_duplicates_and_virtual_mobs(tmp_path):
    session = _session_with_mob_drift(tmp_path)

    audit = audit_moving_mobs(session)
    mobs = {mob["id"]: mob for mob in audit["mobs"]}

    assert mobs["dryad"]["copy_count"] == 3
    assert mobs["dryad"]["object_rooms"] == [5, 18, 18]
    assert mobs["dryad"]["duplicate_room_counts"] == {"18": 2}
    assert mobs["dryad"]["tracker_room_id"] == 18
    assert mobs["dryad"]["tracker_mismatch"] is True
    assert mobs["dryad"]["singleton_status"] == "duplicate"
    assert mobs["dryad"]["proposed_changes"] == [
        {"room_id": 5, "before": [45], "after": []},
        {"room_id": 18, "before": [45, 45, 2], "after": [2, 45]},
    ]

    assert mobs["dragon"]["copy_count"] == 2
    assert mobs["dragon"]["object_rooms"] == [250, 302]
    assert mobs["dragon"]["tracker_room_id"] == 250
    assert mobs["dragon"]["singleton_status"] == "duplicate"
    assert mobs["dragon"]["proposed_changes"] == [
        {"room_id": 250, "before": [52], "after": [52]},
        {"room_id": 302, "before": [52, 47], "after": [47]},
    ]

    assert mobs["brownie"]["kind"] == "virtual_tracker"
    assert mobs["brownie"]["tracker_room_id"] == 77
    assert mobs["brownie"]["copy_count"] == 0
    assert mobs["brownie"]["singleton_status"] == "tracker_only"
    assert mobs["elf"]["tracker_room_id"] == 35


def test_audit_caps_dryad_cleanup_to_room_capacity(tmp_path):
    engine = database.get_engine(f"sqlite+pysqlite:///{tmp_path / 'full-room.db'}")
    database.init_db_schema(engine)
    session = database.create_session(engine)
    _seed_location(session, 5, [45])
    _seed_location(session, 18, [1, 2, 3, 4, 5, 6])
    _seed_location(session, 250, [52])
    _seed_runtime_state(session, dryad_location=18, zar_location=250)
    session.commit()

    audit = audit_moving_mobs(session)
    dryad = {mob["id"]: mob for mob in audit["mobs"]}["dryad"]

    assert dryad["proposed_changes"] == [
        {"room_id": 5, "before": [45], "after": []},
        {"room_id": 18, "before": [1, 2, 3, 4, 5, 6], "after": [1, 2, 3, 4, 5, 45]},
    ]


def test_audit_preserves_non_mob_objects_in_zar_tracker_room(tmp_path):
    engine = database.get_engine(f"sqlite+pysqlite:///{tmp_path / 'zar-objects.db'}")
    database.init_db_schema(engine)
    session = database.create_session(engine)
    _seed_location(session, 18, [45])
    _seed_location(session, 7, [52, 1])
    _seed_runtime_state(session, dryad_location=18, zar_location=7)
    session.commit()

    audit = audit_moving_mobs(session)
    dragon = {mob["id"]: mob for mob in audit["mobs"]}["dragon"]
    dry_run = cleanup_moving_mobs(session, dry_run=True)

    assert dragon["singleton_status"] == "ok"
    assert dragon["proposed_changes"] == [
        {"room_id": 7, "before": [52, 1], "after": [52, 1]}
    ]
    assert dry_run["changes"] == []
    assert session.get(models.Location, 7).objects == [52, 1]


def test_cleanup_dry_run_and_confirmed_apply(tmp_path):
    session = _session_with_mob_drift(tmp_path)

    dry_run = cleanup_moving_mobs(session, dry_run=True)

    assert dry_run["applied"] is False
    assert session.get(models.Location, 5).objects == [45]
    assert session.get(models.Location, 18).objects == [45, 45, 2]

    with pytest.raises(ValueError, match="confirmation token"):
        cleanup_moving_mobs(session, apply=True)
    with pytest.raises(ValueError, match="apply=True"):
        cleanup_moving_mobs(session, dry_run=False)

    token = cleanup_confirmation_token(audit_moving_mobs(session))
    applied = cleanup_moving_mobs(session, apply=True, confirm=token)

    assert applied["applied"] is True
    assert session.get(models.Location, 5).objects == []
    assert session.get(models.Location, 18).objects == [2, 45]
    assert session.get(models.Location, 250).objects == [52]
    assert session.get(models.Location, 302).objects == [47]


def test_cleanup_does_not_remove_mobs_without_tracker_state(tmp_path):
    engine = database.get_engine(f"sqlite+pysqlite:///{tmp_path / 'missing-tracker.db'}")
    database.init_db_schema(engine)
    session = database.create_session(engine)
    _seed_location(session, 5, [45])
    _seed_location(session, 18, [45, 2])
    _seed_location(session, 250, [52])
    session.commit()

    audit = audit_moving_mobs(session)
    mobs = {mob["id"]: mob for mob in audit["mobs"]}
    dry_run = cleanup_moving_mobs(session, dry_run=True)

    assert mobs["dryad"]["singleton_status"] == "tracker_missing"
    assert mobs["dryad"]["copy_count"] == 2
    assert mobs["dryad"]["proposed_changes"] == []
    assert mobs["dragon"]["singleton_status"] == "tracker_missing"
    assert mobs["dragon"]["proposed_changes"] == []
    assert dry_run["changes"] == []
    assert session.get(models.Location, 5).objects == [45]
    assert session.get(models.Location, 18).objects == [45, 2]
    assert session.get(models.Location, 250).objects == [52]


def test_cli_cleanup_apply_requires_confirmation_token(tmp_path, capsys):
    session = _session_with_mob_drift(tmp_path)
    session.close()
    db_path = tmp_path / "mobs.db"

    code = audit_cli.main(
        [
            "--database-url",
            f"sqlite+pysqlite:///{db_path}",
            "cleanup",
            "--apply",
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    assert code == 2
    assert "confirmation token" in captured.err

    engine = database.get_engine(f"sqlite+pysqlite:///{db_path}")
    with database.create_session(engine) as verify_session:
        assert verify_session.get(models.Location, 5).objects == [45]
        assert verify_session.get(models.Location, 18).objects == [45, 45, 2]


def test_cli_cleanup_dry_run_flag_previews_without_writing(tmp_path, capsys):
    session = _session_with_mob_drift(tmp_path)
    session.close()
    db_path = tmp_path / "mobs.db"

    code = audit_cli.main(
        [
            "--database-url",
            f"sqlite+pysqlite:///{db_path}",
            "cleanup",
            "--dry-run",
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert code == 0
    assert result["applied"] is False
    assert result["dry_run"] is True
    assert result["changes"]

    engine = database.get_engine(f"sqlite+pysqlite:///{db_path}")
    with database.create_session(engine) as verify_session:
        assert verify_session.get(models.Location, 5).objects == [45]
        assert verify_session.get(models.Location, 18).objects == [45, 45, 2]


def test_root_wrapper_imports_backend_cli():
    wrapper_path = Path(__file__).resolve().parents[2] / "tools" / "mob_audit.py"
    spec = importlib.util.spec_from_file_location("mob_audit_wrapper", wrapper_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader

    spec.loader.exec_module(module)

    from kyrgame.scripts import audit_moving_mobs as backend_cli

    assert module.main is backend_cli.main
