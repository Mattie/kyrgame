import json
import logging

import pytest

from kyrgame.telemetry import TelemetryEventSink


@pytest.mark.anyio
async def test_telemetry_records_system_events_to_dedicated_file(tmp_path):
    sink = TelemetryEventSink(tmp_path / "telemetry")

    await sink.record_system(
        event_type="animation.tick",
        payload={
            "routine": "browns",
            "authorization": "must-not-log",
            "admin_token": "must-not-log",
        },
    )

    log_file = tmp_path / "telemetry" / "system.jsonl"
    assert log_file.exists()
    line = json.loads(log_file.read_text(encoding="utf-8"))
    assert line["userid"] == "__system__"
    assert line["event_type"] == "animation.tick"
    assert line["payload"] == {"routine": "browns"}


@pytest.mark.anyio
async def test_telemetry_record_ignores_filesystem_failures(monkeypatch, tmp_path, caplog):
    sink = TelemetryEventSink(tmp_path / "telemetry")

    def fail_write_event(userid, event):  # noqa: ARG001
        raise OSError("telemetry volume is full")

    monkeypatch.setattr(sink, "_write_event", fail_write_event)
    caplog.set_level(logging.WARNING, logger="kyrgame.telemetry")

    await sink.record(userid="Hero", event_type="input", payload={"command": "look"})

    assert "Telemetry write failed" in caplog.text
