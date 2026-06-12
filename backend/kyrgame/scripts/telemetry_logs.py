"""Small command-line helpers for Kyrgame telemetry JSONL logs."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, TextIO


DEFAULT_COMPOSE_PROJECT = "kyrgame-local"
DEFAULT_COMPOSE_SERVICE = "backend"
DEFAULT_TELEMETRY_DIR = Path("/data/telemetry")
DEFAULT_CONTAINER_TELEMETRY_DIR = "/data/telemetry"

Record = dict[str, Any]


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _parse_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _get_path(record: Record, dotted_path: str) -> Any:
    current: Any = record
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _parse_expected_value(value: str) -> Any:
    lowered = value.lower()
    if lowered == "null":
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _matches_where(record: Record, expression: str) -> bool:
    if "=" not in expression:
        raise SystemExit(f"--where must use FIELD=VALUE, got {expression!r}")
    field, expected_text = expression.split("=", 1)
    actual = _get_path(record, field.strip())
    expected = _parse_expected_value(expected_text.strip())
    if isinstance(actual, (dict, list)):
        return json.dumps(actual, sort_keys=True) == str(expected)
    return actual == expected or str(actual) == str(expected)


def _source_lines(args: argparse.Namespace) -> Iterable[str]:
    if args.docker:
        container_file = args.container_file or f"{DEFAULT_CONTAINER_TELEMETRY_DIR}/{args.log}.jsonl"
        command = [
            "docker",
            "compose",
            "-p",
            args.compose_project,
            "exec",
            "-T",
            args.compose_service,
            "cat",
            container_file,
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise SystemExit(f"Unable to read Docker telemetry log: {detail}")
        yield from completed.stdout.splitlines()
        return

    log_file = _resolve_log_file(args)
    with log_file.open("r", encoding="utf-8") as handle:
        yield from handle

def _resolve_log_file(args: argparse.Namespace) -> Path:
    if args.file is not None:
        log_file = args.file
    else:
        root = args.dir or os.getenv("KYRGAME_TELEMETRY_DIR")
        log_file = (Path(root) if root else DEFAULT_TELEMETRY_DIR) / f"{args.log}.jsonl"
    if not log_file.exists():
        raise SystemExit(
            f"Telemetry log not found at {log_file}. Pass --file, --dir, or --docker."
        )
    return log_file


def _iter_records(lines: Iterable[str], stderr: TextIO) -> Iterable[Record]:
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            print(f"Skipping malformed JSONL line {line_number}: {exc}", file=stderr)
            continue
        if isinstance(parsed, dict):
            yield parsed
        else:
            print(f"Skipping non-object JSONL line {line_number}", file=stderr)


def _matches_record(
    record: Record, args: argparse.Namespace, forced_events: set[str] | None = None
) -> bool:
    events = set(getattr(args, "event", None) or [])
    if forced_events:
        events.update(forced_events)
    if events and record.get("event_type") not in events:
        return False
    userid = getattr(args, "userid", None)
    if userid and record.get("userid") != userid:
        return False
    since = getattr(args, "since", None)
    if since:
        timestamp = record.get("timestamp")
        if not isinstance(timestamp, str):
            return False
        try:
            if _parse_timestamp(timestamp) < since:
                return False
        except ValueError:
            return False
    contains = getattr(args, "contains", None)
    if contains:
        haystack = json.dumps(record, sort_keys=True).lower()
        if contains.lower() not in haystack:
            return False
    for expression in getattr(args, "where", None) or []:
        if not _matches_where(record, expression):
            return False
    status = getattr(args, "status", None)
    if status and _get_path(record, "payload.status") != status:
        return False
    room = getattr(args, "room", None)
    if room is not None and _get_path(record, "payload.room_id") != room:
        return False
    return True


def _selected_records(
    args: argparse.Namespace,
    *,
    forced_events: set[str] | None = None,
    stderr: TextIO = sys.stderr,
) -> list[Record]:
    records: deque[Record] = deque(maxlen=args.limit)
    for record in _iter_records(_source_lines(args), stderr):
        if _matches_record(record, args, forced_events):
            records.append(record)
    selected = list(records)
    if not getattr(args, "chronological", False):
        selected.reverse()
    return selected


def _short_timestamp(record: Record) -> str:
    timestamp = str(record.get("timestamp") or "")
    return timestamp.replace("T", " ").replace("+00:00", "Z")


def _range_text(before: Any, after: Any) -> str:
    if before is None and after is None:
        return ""
    return f"{before if before is not None else '?'}->{after if after is not None else '?'}"


def _summarize_record(record: Record) -> str:
    event_type = record.get("event_type")
    payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
    if event_type == "animation.gem_attempt":
        status = payload.get("status", "?")
        room = payload.get("room_id", "?")
        objects = _range_text(
            payload.get("room_object_count_before"),
            payload.get("room_object_count_after"),
        )
        counter = _range_text(payload.get("gem_counter_before"), payload.get("gem_counter_after"))
        if status == "spawned":
            gem = payload.get("spawned_object_name") or payload.get("spawned_object_id") or "gem"
            return f"spawned {gem} room {room} objects {objects} counter {counter}".strip()
        return f"{status} room {room} objects {objects} counter {counter}".strip()
    if event_type == "animation.tick":
        routine = payload.get("routine_name") or payload.get("routine_name_before") or "?"
        dispatched = payload.get("dispatched_event_count", "?")
        failures = payload.get("dispatch_failure_count", "?")
        return f"routine {routine} dispatched {dispatched} failures {failures}"
    pairs = [f"{key}={value}" for key, value in list(payload.items())[:4]]
    return ", ".join(pairs)


def _print_records(records: list[Record], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(records, indent=2, sort_keys=True))
        return
    if output_format == "jsonl":
        for record in records:
            print(json.dumps(record, sort_keys=True))
        return
    rows = [
        [
            _short_timestamp(record),
            str(record.get("userid") or ""),
            str(record.get("event_type") or ""),
            _summarize_record(record),
        ]
        for record in records
    ]
    _print_table(["timestamp", "userid", "event_type", "summary"], rows)


def _print_table(headers: list[str], rows: list[list[str]]) -> None:
    if not rows:
        print("No matching records.")
        return
    widths = [
        max(len(header), *(len(str(row[index])) for row in rows))
        for index, header in enumerate(headers)
    ]
    print("  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(str(value).ljust(widths[index]) for index, value in enumerate(row)))


def _cmd_latest(args: argparse.Namespace) -> int:
    records = _selected_records(args)
    _print_records(records, args.format)
    return 0


def _cmd_gems(args: argparse.Namespace) -> int:
    records = _selected_records(args, forced_events={"animation.gem_attempt"})
    if args.format in {"json", "jsonl"}:
        _print_records(records, args.format)
        return 0
    rows = []
    for record in records:
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        rows.append(
            [
                _short_timestamp(record),
                str(payload.get("status") or ""),
                str(payload.get("room_id") or ""),
                str(payload.get("spawned_object_name") or payload.get("spawned_object_id") or ""),
                _range_text(
                    payload.get("room_object_count_before"),
                    payload.get("room_object_count_after"),
                ),
                _range_text(payload.get("gem_counter_before"), payload.get("gem_counter_after")),
                str(payload.get("dispatch_status") or ""),
            ]
        )
    _print_table(["timestamp", "status", "room", "gem", "objects", "counter", "dispatch"], rows)
    return 0


def _cmd_types(args: argparse.Namespace) -> int:
    counts: Counter[str] = Counter()
    latest_by_type: dict[str, str] = defaultdict(str)
    for record in _iter_records(_source_lines(args), sys.stderr):
        if not _matches_record(record, args):
            continue
        event_type = str(record.get("event_type") or "")
        counts[event_type] += 1
        latest_by_type[event_type] = str(record.get("timestamp") or latest_by_type[event_type])

    summaries = [
        {
            "event_type": event_type,
            "count": int(count),
            "latest_timestamp": latest_by_type[event_type],
        }
        for event_type, count in counts.most_common(args.limit)
    ]
    if args.format == "json":
        print(json.dumps(summaries, indent=2, sort_keys=True))
        return 0
    if args.format == "jsonl":
        for summary in summaries:
            print(json.dumps(summary, sort_keys=True))
        return 0
    rows = [
        [summary["event_type"], str(summary["count"]), summary["latest_timestamp"]]
        for summary in summaries
    ]
    _print_table(["event_type", "count", "latest_timestamp"], rows)
    return 0


def _add_common_filters(parser: argparse.ArgumentParser, *, include_event: bool = True) -> None:
    parser.add_argument("--limit", type=_positive_int, default=10, help="Rows to show")
    parser.add_argument("--userid", help="Only include records for this userid")
    if include_event:
        parser.add_argument("--event", action="append", help="Exact event_type to include")
    parser.add_argument("--where", action="append", help="Filter with dotted FIELD=VALUE")
    parser.add_argument("--contains", help="Case-insensitive substring search across the record")
    parser.add_argument("--since", type=_parse_timestamp, help="Only include records at/after ISO time")
    parser.add_argument(
        "--chronological",
        action="store_true",
        help="Show oldest-to-newest among the selected recent rows",
    )
    parser.add_argument(
        "--format",
        choices=["table", "json", "jsonl"],
        default="table",
        help="Output format",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect Kyrgame telemetry JSONL logs")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--file", type=Path, help="Read a specific .jsonl file")
    source.add_argument("--dir", type=Path, help="Read <dir>/<log>.jsonl")
    source.add_argument(
        "--docker",
        action="store_true",
        help="Read from the running Docker Compose backend with cat",
    )
    parser.add_argument("--log", default="system", help="Log basename when using --dir/env/default")
    parser.add_argument("--compose-project", default=DEFAULT_COMPOSE_PROJECT)
    parser.add_argument("--compose-service", default=DEFAULT_COMPOSE_SERVICE)
    parser.add_argument("--container-file", help="Container path when using --docker")

    subparsers = parser.add_subparsers(dest="command", required=True)

    latest = subparsers.add_parser("latest", help="Show recent matching records")
    _add_common_filters(latest)
    latest.set_defaults(func=_cmd_latest)

    gems = subparsers.add_parser("gems", help="Shortcut for animation.gem_attempt records")
    _add_common_filters(gems, include_event=False)
    gems.add_argument("--status", choices=["spawned", "skipped_capacity"], help="Gem attempt status")
    gems.add_argument("--room", type=int, help="Gem attempt room_id")
    gems.set_defaults(func=_cmd_gems)

    types = subparsers.add_parser("types", help="Count event types")
    _add_common_filters(types)
    types.set_defaults(func=_cmd_types)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover - CLI shim
    raise SystemExit(main())
