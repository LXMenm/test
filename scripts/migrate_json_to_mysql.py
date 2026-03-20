from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any, Dict, Iterable

from sqlalchemy.exc import IntegrityError


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from repositories.event_repo_mysql import append_event_mysql  # noqa: E402
from repositories.profile_repo_mysql import save_profile_payload  # noqa: E402
from repositories.trace_repo_mysql import append_trace_event_mysql  # noqa: E402


Stats = Dict[str, int]

DEFAULT_PROFILE_DIR = Path("data/profiles")
DEFAULT_EVENT_FILE_CANDIDATES = [
    Path("diagnosis_events.jsonl"),
    Path(".cache/events/diagnosis_events.jsonl"),
    Path("data/events/diagnosis_events.jsonl"),
]
DEFAULT_TRACE_FILE_CANDIDATES = [
    Path("trace_events.jsonl"),
    Path(".cache/events/trace_events.jsonl"),
    Path(".cache/trace_events.jsonl"),
    Path("data/traces/trace_events.jsonl"),
]


def _init_stats() -> Stats:
    return {
        "total": 0,
        "migrated": 0,
        "skipped": 0,
        "duplicates": 0,
        "errors": 0,
        "parse_skipped": 0,
        "missing_event_id_fixed": 0,
        "missing_trace_seq_fixed": 0,
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_load_json(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[migrate] skip invalid json file: {path} ({exc})")
        return None

    if not isinstance(data, dict):
        print(f"[migrate] skip non-object profile payload: {path}")
        return None

    return data


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any] | None]:
    if not path.exists():
        return

    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            payload = line.strip()
            if not payload:
                continue

            try:
                record = json.loads(payload)
            except json.JSONDecodeError as exc:
                print(f"[migrate] skip invalid jsonl line: {path}:{line_no} ({exc})")
                yield None
                continue

            if not isinstance(record, dict):
                print(f"[migrate] skip non-object jsonl line: {path}:{line_no}")
                yield None
                continue

            yield record


def _is_duplicate_integrity_error(exc: IntegrityError, keywords: tuple[str, ...]) -> bool:
    message = str(exc).lower()
    return any(keyword in message for keyword in keywords)


def _find_first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def _stable_hash_id(prefix: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _normalize_event_for_migration(event: dict[str, Any], stats: Stats) -> dict[str, Any]:
    normalized = dict(event)

    event_id = normalized.get("event_id") or normalized.get("id")
    if not event_id:
        event_id = _stable_hash_id("evt_migrated", normalized)
        stats["missing_event_id_fixed"] += 1
    elif not normalized.get("event_id"):
        stats["missing_event_id_fixed"] += 1

    normalized["event_id"] = str(event_id)

    if not normalized.get("ts"):
        normalized["ts"] = _now_iso()

    return normalized


def _normalize_trace_for_migration(
    event: dict[str, Any],
    seq_counters: dict[str, int],
    stats: Stats,
) -> tuple[str, dict[str, Any]] | None:
    normalized = dict(event)

    trace_id = str(normalized.get("trace_id") or "").strip()
    if not trace_id:
        return None

    raw_seq = normalized.get("seq")
    seq_value: int | None = None

    if raw_seq is not None:
        try:
            seq_value = int(raw_seq)
        except Exception:
            seq_value = None

    if seq_value is None:
        seq_value = seq_counters[trace_id] + 1
        stats["missing_trace_seq_fixed"] += 1

    seq_counters[trace_id] = max(seq_counters[trace_id], seq_value)
    normalized["seq"] = seq_value

    if not normalized.get("ts"):
        normalized["ts"] = _now_iso()

    return trace_id, normalized


def migrate_profiles(profile_dir: Path) -> Stats:
    stats = _init_stats()

    if not profile_dir.exists():
        print(f"[migrate] profile dir not found, skip: {profile_dir}")
        return stats

    print(f"[migrate] profile source: {profile_dir}")

    for path in sorted(profile_dir.glob("*.json")):
        stats["total"] += 1

        payload = _safe_load_json(path)
        if payload is None:
            stats["skipped"] += 1
            stats["parse_skipped"] += 1
            continue

        try:
            save_profile_payload(payload)
            stats["migrated"] += 1
        except Exception as exc:
            stats["errors"] += 1
            print(f"[migrate] profile import failed: {path} ({exc})")

    return stats


def migrate_events(events_path: Path) -> Stats:
    stats = _init_stats()

    print(f"[migrate] event source: {events_path}")

    if not events_path.exists():
        print(f"[migrate] event jsonl not found, skip: {events_path}")
        return stats

    for event in _iter_jsonl(events_path):
        stats["total"] += 1

        if event is None:
            stats["skipped"] += 1
            stats["parse_skipped"] += 1
            continue

        normalized = _normalize_event_for_migration(event, stats)

        try:
            append_event_mysql(normalized)
            stats["migrated"] += 1
        except IntegrityError as exc:
            if _is_duplicate_integrity_error(exc, ("event_id", "duplicate", "unique")):
                stats["duplicates"] += 1
                stats["skipped"] += 1
                print(f"[migrate] skip duplicate event_id={normalized.get('event_id')}")
            else:
                stats["errors"] += 1
                print(
                    f"[migrate] event integrity error event_id={normalized.get('event_id')} ({exc})"
                )
        except Exception as exc:
            stats["errors"] += 1
            print(
                f"[migrate] event import failed event_id={normalized.get('event_id')} ({exc})"
            )

    return stats


def migrate_traces(trace_path: Path) -> Stats:
    stats = _init_stats()

    print(f"[migrate] trace source: {trace_path}")

    if not trace_path.exists():
        print(f"[migrate] trace jsonl not found, skip: {trace_path}")
        return stats

    seq_counters: dict[str, int] = defaultdict(int)

    for event in _iter_jsonl(trace_path):
        stats["total"] += 1

        if event is None:
            stats["skipped"] += 1
            stats["parse_skipped"] += 1
            continue

        normalized_result = _normalize_trace_for_migration(event, seq_counters, stats)
        if normalized_result is None:
            stats["skipped"] += 1
            print("[migrate] skip trace event without trace_id")
            continue

        trace_id, normalized = normalized_result

        try:
            append_trace_event_mysql(trace_id, normalized)
            stats["migrated"] += 1
        except IntegrityError as exc:
            if _is_duplicate_integrity_error(exc, ("trace_id", "seq", "duplicate", "unique")):
                stats["duplicates"] += 1
                stats["skipped"] += 1
                print(
                    f"[migrate] skip duplicate trace event trace_id={trace_id} seq={normalized.get('seq')}"
                )
            else:
                stats["errors"] += 1
                print(
                    f"[migrate] trace integrity error trace_id={trace_id} seq={normalized.get('seq')} ({exc})"
                )
        except Exception as exc:
            stats["errors"] += 1
            print(
                f"[migrate] trace import failed trace_id={trace_id} seq={normalized.get('seq')} ({exc})"
            )

    return stats


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="One-off migration script for importing file-based data into MySQL."
    )
    parser.add_argument(
        "--profiles-dir",
        type=Path,
        default=DEFAULT_PROFILE_DIR,
        help="Directory containing profile JSON files.",
    )
    parser.add_argument(
        "--events",
        type=Path,
        default=None,
        help="Path to diagnosis events JSONL file.",
    )
    parser.add_argument(
        "--traces",
        type=Path,
        default=None,
        help="Path to trace events JSONL file.",
    )
    return parser.parse_args()


def main() -> dict[str, Stats]:
    args = _parse_args()

    profiles_dir = args.profiles_dir
    events_path = args.events or _find_first_existing(DEFAULT_EVENT_FILE_CANDIDATES)
    trace_path = args.traces or _find_first_existing(DEFAULT_TRACE_FILE_CANDIDATES)

    if events_path is None:
        print(f"[migrate] no event file found in candidates: {DEFAULT_EVENT_FILE_CANDIDATES}")
        events_path = Path("diagnosis_events.jsonl")

    if trace_path is None:
        print(f"[migrate] no trace file found in candidates: {DEFAULT_TRACE_FILE_CANDIDATES}")
        trace_path = Path("trace_events.jsonl")

    summary = {
        "profiles": migrate_profiles(profiles_dir),
        "events": migrate_events(events_path),
        "traces": migrate_traces(trace_path),
    }

    totals = {
        "profiles": summary["profiles"],
        "events": summary["events"],
        "traces": summary["traces"],
        "errors": (
            summary["profiles"]["errors"]
            + summary["events"]["errors"]
            + summary["traces"]["errors"]
        ),
    }

    print(json.dumps(totals, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    main()
