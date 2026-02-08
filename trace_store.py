"""Trace store for multi-agent trace events using JSONL."""

from __future__ import annotations

from datetime import datetime
import json
import os
from typing import Any, Dict, List


_EVENTS_DIR = os.path.join(".cache", "events")
_TRACE_PATH = os.path.join(_EVENTS_DIR, "trace_events.jsonl")


def _ensure_dir() -> None:
    os.makedirs(_EVENTS_DIR, exist_ok=True)


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.utcfromtimestamp(value)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        ts = value.rstrip("Z")
        try:
            return datetime.fromisoformat(ts)
        except ValueError:
            return None
    return None


def append_trace_event(trace_id: str, event: Dict[str, Any]) -> None:
    """Append a single trace event to the JSONL store."""
    if "ts" not in event:
        event["ts"] = _now_iso()
    event["trace_id"] = trace_id
    _ensure_dir()
    with open(_TRACE_PATH, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False))
        handle.write("\n")


def list_trace_events(trace_id: str) -> List[Dict[str, Any]]:
    """List trace events for a specific trace id sorted by ts ascending."""
    if not os.path.exists(_TRACE_PATH):
        return []
    events: List[Dict[str, Any]] = []
    with open(_TRACE_PATH, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("trace_id") != trace_id:
                continue
            events.append(event)
    events.sort(key=lambda event: _parse_ts(event.get("ts")) or datetime.min)
    return events
