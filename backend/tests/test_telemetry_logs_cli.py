import json
from types import SimpleNamespace

from kyrgame.scripts import telemetry_logs


def _write_jsonl(path, records):
    path.write_text(
        "".join(f"{json.dumps(record, sort_keys=True)}\n" for record in records),
        encoding="utf-8",
    )


def test_latest_filters_to_most_recent_matching_payload_field(tmp_path, capsys):
    log_file = tmp_path / "system.jsonl"
    _write_jsonl(
        log_file,
        [
            {
                "timestamp": "2026-06-12T20:09:01+00:00",
                "userid": "__system__",
                "event_type": "animation.tick",
                "payload": {"routine_name": "elves"},
            },
            {
                "timestamp": "2026-06-12T20:09:19+00:00",
                "userid": "__system__",
                "event_type": "animation.gem_attempt",
                "payload": {
                    "status": "spawned",
                    "room_id": 166,
                    "spawned_object_name": "emerald",
                },
            },
            {
                "timestamp": "2026-06-12T20:11:19+00:00",
                "userid": "__system__",
                "event_type": "animation.gem_attempt",
                "payload": {
                    "status": "spawned",
                    "room_id": 167,
                    "spawned_object_name": "bloodstone",
                },
            },
        ],
    )

    exit_code = telemetry_logs.main(
        [
            "--file",
            str(log_file),
            "latest",
            "--event",
            "animation.gem_attempt",
            "--where",
            "payload.room_id=167",
            "--limit",
            "1",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "bloodstone" in output
    assert "room 167" in output
    assert "emerald" not in output


def test_gems_shows_success_and_capacity_skip_status(tmp_path, capsys):
    log_file = tmp_path / "system.jsonl"
    _write_jsonl(
        log_file,
        [
            {
                "timestamp": "2026-06-12T20:09:19+00:00",
                "userid": "__system__",
                "event_type": "animation.gem_attempt",
                "payload": {
                    "status": "spawned",
                    "room_id": 166,
                    "room_object_count_before": 2,
                    "room_object_count_after": 3,
                    "gem_counter_before": 10,
                    "gem_counter_after": 0,
                    "spawned_object_name": "emerald",
                },
            },
            {
                "timestamp": "2026-06-12T20:10:49+00:00",
                "userid": "__system__",
                "event_type": "animation.gem_attempt",
                "payload": {
                    "status": "skipped_capacity",
                    "room_id": 51,
                    "room_object_count_before": 4,
                    "room_object_count_after": 4,
                    "gem_counter_before": 0,
                    "gem_counter_after": 0,
                },
            },
        ],
    )

    exit_code = telemetry_logs.main(["--file", str(log_file), "gems", "--limit", "2"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "skipped_capacity" in output
    assert "spawned" in output
    assert "emerald" in output
    assert "51" in output
    assert output.index("skipped_capacity") < output.index("spawned")


def test_types_counts_event_types(tmp_path, capsys):
    log_file = tmp_path / "system.jsonl"
    _write_jsonl(
        log_file,
        [
            {
                "timestamp": "2026-06-12T20:09:01+00:00",
                "userid": "__system__",
                "event_type": "animation.tick",
                "payload": {},
            },
            {
                "timestamp": "2026-06-12T20:09:19+00:00",
                "userid": "__system__",
                "event_type": "animation.gem_attempt",
                "payload": {"status": "spawned"},
            },
            {
                "timestamp": "2026-06-12T20:10:49+00:00",
                "userid": "__system__",
                "event_type": "animation.gem_attempt",
                "payload": {"status": "skipped_capacity"},
            },
        ],
    )

    exit_code = telemetry_logs.main(["--file", str(log_file), "types"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "animation.gem_attempt" in output
    assert "2" in output
    assert "animation.tick" in output


def test_types_can_emit_jsonl_for_piping(tmp_path, capsys):
    log_file = tmp_path / "system.jsonl"
    _write_jsonl(
        log_file,
        [
            {
                "timestamp": "2026-06-12T20:09:19+00:00",
                "userid": "__system__",
                "event_type": "animation.gem_attempt",
                "payload": {"status": "spawned"},
            },
        ],
    )

    exit_code = telemetry_logs.main(["--file", str(log_file), "types", "--format", "jsonl"])

    assert exit_code == 0
    [line] = capsys.readouterr().out.splitlines()
    payload = json.loads(line)
    assert payload == {
        "count": 1,
        "event_type": "animation.gem_attempt",
        "latest_timestamp": "2026-06-12T20:09:19+00:00",
    }


def test_docker_source_uses_container_posix_path(monkeypatch, capsys):
    calls = []

    def fake_run(command, capture_output, text, check):  # noqa: ARG001
        calls.append(command)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "timestamp": "2026-06-12T20:09:19+00:00",
                    "userid": "__system__",
                    "event_type": "animation.gem_attempt",
                    "payload": {
                        "status": "spawned",
                        "room_id": 166,
                        "spawned_object_name": "emerald",
                    },
                },
                sort_keys=True,
            )
            + "\n",
            stderr="",
        )

    monkeypatch.setattr(telemetry_logs.subprocess, "run", fake_run)

    exit_code = telemetry_logs.main(["--docker", "gems", "--limit", "1"])

    assert exit_code == 0
    assert calls[0][-1] == "/data/telemetry/system.jsonl"
    assert "emerald" in capsys.readouterr().out
