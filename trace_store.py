"""Trace store for multi-agent trace events using JSONL."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime
import json
import os
import threading
from typing import Any, Dict, List


_EVENTS_DIR = os.path.join(".cache", "events")
_TRACE_PATH = os.path.join(_EVENTS_DIR, "trace_events.jsonl")
_SUBSCRIBERS: dict[str, set[asyncio.Queue]] = defaultdict(set)
_SEQ: dict[str, int] = defaultdict(int)
_LOCK = threading.Lock()


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


def _normalize_event(trace_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(event)
    if "ts" not in normalized:
        normalized["ts"] = _now_iso()
    normalized["trace_id"] = trace_id
    with _LOCK:
        if "seq" not in normalized:
            _SEQ[trace_id] += 1
            normalized["seq"] = _SEQ[trace_id]
        else:
            try:
                seq_val = int(normalized["seq"])
                _SEQ[trace_id] = max(_SEQ[trace_id], seq_val)
            except Exception:
                _SEQ[trace_id] += 1
                normalized["seq"] = _SEQ[trace_id]
    return normalized


def _fanout(trace_id: str, event: Dict[str, Any]) -> None:
    subscribers = list(_SUBSCRIBERS.get(trace_id, set()))
    for queue in subscribers:
        try:
            queue.put_nowait(event)
        except Exception:
            continue


def append_trace_event(trace_id: str, event: Dict[str, Any]) -> None:
    """Append a single trace event to the JSONL store and fanout to subscribers."""
    normalized = _normalize_event(trace_id, event)
    _ensure_dir()
    with open(_TRACE_PATH, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(normalized, ensure_ascii=False))
        handle.write("\n")
    _fanout(trace_id, normalized)


def emit_trace_event(trace_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
    """Normalized append+publish helper for streaming trace events."""
    normalized = _normalize_event(trace_id, event)
    _ensure_dir()
    with open(_TRACE_PATH, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(normalized, ensure_ascii=False))
        handle.write("\n")
    _fanout(trace_id, normalized)
    return normalized


def subscribe(trace_id: str) -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue(maxsize=256)
    _SUBSCRIBERS[trace_id].add(queue)
    return queue


def unsubscribe(trace_id: str, queue: asyncio.Queue) -> None:
    subscribers = _SUBSCRIBERS.get(trace_id)
    if not subscribers:
        return
    subscribers.discard(queue)
    if not subscribers:
        _SUBSCRIBERS.pop(trace_id, None)


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
