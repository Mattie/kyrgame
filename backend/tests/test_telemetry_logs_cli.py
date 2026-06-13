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


def test_docker_recent_commands_tail_container_log_by_default(monkeypatch, capsys):
    calls = []

    def fake_run(command, timeout):  # noqa: ARG001
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

    monkeypatch.setattr(telemetry_logs, "_run_docker_command", fake_run)

    exit_code = telemetry_logs.main(["--docker", "gems", "--limit", "1"])

    assert exit_code == 0
    assert calls[0][:3] == ["docker", "exec", "kyrgame-local-backend-1"]
    assert calls[0][-4:-1] == ["tail", "-n", "5000"]
    assert calls[0][-1] == "/data/telemetry/system.jsonl"
    assert "emerald" in capsys.readouterr().out


def test_docker_full_scan_uses_cat_for_recent_commands(monkeypatch, capsys):
    calls = []

    def fake_run(command, timeout):  # noqa: ARG001
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

    monkeypatch.setattr(telemetry_logs, "_run_docker_command", fake_run)

    exit_code = telemetry_logs.main(["--docker", "--full-scan", "gems", "--limit", "1"])

    assert exit_code == 0
    assert calls[0][:3] == ["docker", "exec", "kyrgame-local-backend-1"]
    assert calls[0][-2:] == ["cat", "/data/telemetry/system.jsonl"]
    assert "emerald" in capsys.readouterr().out


def test_docker_scan_lines_overrides_default_tail(monkeypatch, capsys):
    calls = []

    def fake_run(command, timeout):  # noqa: ARG001
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

    monkeypatch.setattr(telemetry_logs, "_run_docker_command", fake_run)

    exit_code = telemetry_logs.main(["--docker", "--scan-lines", "20000", "gems", "--limit", "1"])

    assert exit_code == 0
    assert calls[0][-4:-1] == ["tail", "-n", "20000"]
    assert "emerald" in capsys.readouterr().out


def test_docker_source_times_out_with_clear_message(monkeypatch):
    def fake_run(command, timeout):  # noqa: ARG001
        raise telemetry_logs.subprocess.TimeoutExpired(command, timeout)

    monkeypatch.setattr(telemetry_logs, "_run_docker_command", fake_run)

    try:
        telemetry_logs.main(["--docker", "--docker-timeout", "3", "gems", "--limit", "1"])
    except SystemExit as exc:
        assert "Docker telemetry read timed out after 3.0s" in str(exc)
    else:
        raise AssertionError("expected SystemExit")


def test_docker_timeout_must_be_positive(capsys):
    try:
        telemetry_logs.main(["--docker", "--docker-timeout", "0", "gems", "--limit", "1"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected SystemExit")

    assert "must be greater than 0" in capsys.readouterr().err


def test_run_docker_command_terminates_process_tree_on_timeout(monkeypatch):
    calls = []

    class FakeProcess:
        pid = 1234
        returncode = None
        stdout = None
        stderr = None

        def communicate(self, timeout):
            calls.append(("communicate", timeout))
            raise telemetry_logs.subprocess.TimeoutExpired(["docker"], timeout)

    fake_process = FakeProcess()
    monkeypatch.setattr(telemetry_logs.subprocess, "Popen", lambda *args, **kwargs: fake_process)
    monkeypatch.setattr(
        telemetry_logs,
        "_terminate_process_tree",
        lambda process: calls.append(("terminate", process.pid)),
    )

    try:
        telemetry_logs._run_docker_command(["docker", "exec", "container", "tail"], 3)
    except telemetry_logs.subprocess.TimeoutExpired:
        pass
    else:
        raise AssertionError("expected TimeoutExpired")

    assert ("terminate", 1234) in calls


def test_posix_timeout_termination_kills_process_group(monkeypatch):
    calls = []

    class FakeProcess:
        pid = 4321

        def kill(self):
            calls.append(("kill", self.pid))

    monkeypatch.setattr(telemetry_logs.os, "name", "posix")
    monkeypatch.setattr(
        telemetry_logs.os,
        "killpg",
        lambda pid, signal_number: calls.append(("killpg", pid, signal_number)),
        raising=False,
    )
    monkeypatch.setattr(telemetry_logs.os, "getpgid", lambda pid: pid + 10, raising=False)
    monkeypatch.setattr(telemetry_logs.signal, "SIGKILL", 9, raising=False)

    telemetry_logs._terminate_process_tree(FakeProcess())

    assert calls == [("killpg", 4331, telemetry_logs.signal.SIGKILL)]
