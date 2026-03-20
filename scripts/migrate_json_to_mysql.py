"""One-off migration script for importing file-based data into MySQL."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any, Dict, Iterable

from sqlalchemy.exc import IntegrityError


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from event_store import _EVENTS_PATH  # noqa: E402
from personalization.profile_store import PROFILE_DIR  # noqa: E402
from repositories.event_repo_mysql import append_event_mysql  # noqa: E402
from repositories.profile_repo_mysql import save_profile_payload  # noqa: E402
from repositories.trace_repo_mysql import append_trace_event_mysql  # noqa: E402
from trace_store import _TRACE_PATH  # noqa: E402


Stats = Dict[str, int]


def _init_stats() -> Stats:
    return {
        "migrated": 0,
        "skipped": 0,
        "errors": 0,
    }


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


def migrate_profiles() -> Stats:
    stats = _init_stats()
    profile_dir = Path(PROFILE_DIR)
    if not profile_dir.exists():
        print(f"[migrate] profile dir not found, skip: {profile_dir}")
        return stats

    for path in sorted(profile_dir.glob("*.json")):
        payload = _safe_load_json(path)
        if payload is None:
            stats["skipped"] += 1
            continue
        try:
            save_profile_payload(payload)
            stats["migrated"] += 1
        except Exception as exc:
            stats["errors"] += 1
            print(f"[migrate] profile import failed: {path} ({exc})")
    return stats


def migrate_events() -> Stats:
    stats = _init_stats()
    events_path = Path(_EVENTS_PATH)
    if not events_path.exists():
        print(f"[migrate] event jsonl not found, skip: {events_path}")
        return stats

    for event in _iter_jsonl(events_path):
        if event is None:
            stats["skipped"] += 1
            continue
        if not event.get("event_id"):
            stats["skipped"] += 1
            print("[migrate] skip event without event_id")
            continue
        try:
            append_event_mysql(event)
            stats["migrated"] += 1
        except IntegrityError as exc:
            if _is_duplicate_integrity_error(exc, ("event_id", "duplicate", "unique")):
                stats["skipped"] += 1
                print(f"[migrate] skip duplicate event_id={event.get('event_id')}")
            else:
                stats["errors"] += 1
                print(f"[migrate] event integrity error event_id={event.get('event_id')} ({exc})")
        except Exception as exc:
            stats["errors"] += 1
            print(f"[migrate] event import failed event_id={event.get('event_id')} ({exc})")
    return stats


def migrate_traces() -> Stats:
    stats = _init_stats()
    trace_path = Path(_TRACE_PATH)
    if not trace_path.exists():
        print(f"[migrate] trace jsonl not found, skip: {trace_path}")
        return stats

    for event in _iter_jsonl(trace_path):
        if event is None:
            stats["skipped"] += 1
            continue
        trace_id = str(event.get("trace_id") or "").strip()
        if not trace_id:
            stats["skipped"] += 1
            print("[migrate] skip trace event without trace_id")
            continue
        try:
            append_trace_event_mysql(trace_id, event)
            stats["migrated"] += 1
        except IntegrityError as exc:
            if _is_duplicate_integrity_error(exc, ("trace_id", "seq", "duplicate", "unique")):
                stats["skipped"] += 1
                print(
                    f"[migrate] skip duplicate trace event trace_id={trace_id} seq={event.get('seq')}"
                )
            else:
                stats["errors"] += 1
                print(
                    f"[migrate] trace integrity error trace_id={trace_id} seq={event.get('seq')} ({exc})"
                )
        except Exception as exc:
            stats["errors"] += 1
            print(f"[migrate] trace import failed trace_id={trace_id} seq={event.get('seq')} ({exc})")
    return stats


def main() -> dict[str, Stats]:
    summary = {
        "profiles": migrate_profiles(),
        "events": migrate_events(),
        "traces": migrate_traces(),
    }
    totals = {
        "migrated_profiles": summary["profiles"]["migrated"],
        "skipped_profiles": summary["profiles"]["skipped"],
        "profile_errors": summary["profiles"]["errors"],
        "migrated_events": summary["events"]["migrated"],
        "skipped_events": summary["events"]["skipped"],
        "event_errors": summary["events"]["errors"],
        "migrated_traces": summary["traces"]["migrated"],
        "skipped_traces": summary["traces"]["skipped"],
        "trace_errors": summary["traces"]["errors"],
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
