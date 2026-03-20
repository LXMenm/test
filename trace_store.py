"""Trace store for multi-agent trace events using file / dual / mysql backends."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime
import json
import os
import threading
from typing import Any, Dict, List

from config import TRACE_STORE_MODE
from repositories.trace_repo_mysql import (
    append_trace_event_mysql as _append_trace_event_mysql,
    emit_trace_event_mysql as _emit_trace_event_mysql,
    list_trace_events_mysql as _list_trace_events_mysql,
)
from trace_catalog import NODE_TO_AGENT


_EVENTS_DIR = os.path.join(".cache", "events")
_TRACE_PATH = os.path.join(_EVENTS_DIR, "trace_events.jsonl")
_SUBSCRIBERS: dict[str, set[asyncio.Queue]] = defaultdict(set)
_SEQ: dict[str, int] = defaultdict(int)
_LOCK = threading.Lock()
_VALID_TRACE_STORE_MODES = {"file", "dual", "mysql"}


def _ensure_dir() -> None:
    os.makedirs(_EVENTS_DIR, exist_ok=True)


def _store_mode() -> str:
    mode = str(TRACE_STORE_MODE or "file").strip().lower()
    if mode not in _VALID_TRACE_STORE_MODES:
        print(f"[TraceStore] invalid TRACE_STORE_MODE={TRACE_STORE_MODE!r}, fallback to file")
        return "file"
    return mode


def _log(action: str, detail: str | None = None) -> None:
    suffix = f" {detail}" if detail else ""
    print(f"[TraceStore:{_store_mode()}] {action}{suffix}")


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="milliseconds") + "Z"


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

    node = normalized.get("node") or normalized.get("agent")
    payload = normalized.get("payload")
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        payload = {"value": payload}
    agent_id = normalized.get("agent_id") or payload.get("agent_id")
    if not agent_id and isinstance(node, str):
        agent_id = NODE_TO_AGENT.get(node)
    if agent_id:
        normalized["agent_id"] = agent_id
        payload["agent_id"] = agent_id
    normalized["payload"] = payload
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


def _append_trace_event_to_file(event: Dict[str, Any]) -> None:
    _ensure_dir()
    with open(_TRACE_PATH, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False))
        handle.write("\n")


def _emit_trace_event_to_file(event: Dict[str, Any]) -> Dict[str, Any]:
    _append_trace_event_to_file(event)
    return event


def _list_trace_events_from_file(trace_id: str) -> List[Dict[str, Any]]:
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


def _fanout(trace_id: str, event: Dict[str, Any]) -> None:
    subscribers = list(_SUBSCRIBERS.get(trace_id, set()))
    for queue in subscribers:
        try:
            queue.put_nowait(event)
        except Exception:
            continue


def append_trace_event(trace_id: str, event: Dict[str, Any]) -> None:
    """Append a single trace event to the configured store and fanout to subscribers."""
    normalized = _normalize_event(trace_id, event)
    mode = _store_mode()

    if mode == "mysql":
        _log("append_trace_event", "via mysql")
        _append_trace_event_mysql(trace_id, normalized)
    elif mode == "dual":
        _log("append_trace_event", "dual-write file+mysql")
        _append_trace_event_to_file(normalized)
        _append_trace_event_mysql(trace_id, normalized)
    else:
        _log("append_trace_event", "via file")
        _append_trace_event_to_file(normalized)

    _fanout(trace_id, normalized)


def emit_trace_event(trace_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
    """Normalized append+publish helper for streaming trace events."""
    normalized = _normalize_event(trace_id, event)
    mode = _store_mode()

    if mode == "mysql":
        _log("emit_trace_event", "via mysql")
        _emit_trace_event_mysql(trace_id, normalized)
    elif mode == "dual":
        _log("emit_trace_event", "dual-write file+mysql")
        _emit_trace_event_to_file(normalized)
        _emit_trace_event_mysql(trace_id, normalized)
    else:
        _log("emit_trace_event", "via file")
        _emit_trace_event_to_file(normalized)

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
    """List trace events for a specific trace id using the configured store."""
    mode = _store_mode()
    if mode == "mysql":
        _log("list_trace_events", "via mysql")
        return _list_trace_events_mysql(trace_id)
    if mode == "dual":
        _log("list_trace_events", "via file (dual-read)")
        return _list_trace_events_from_file(trace_id)
    _log("list_trace_events", "via file")
    return _list_trace_events_from_file(trace_id)
