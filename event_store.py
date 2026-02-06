"""Event store for diagnosis events using JSONL."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import os
from typing import Any, Dict, List, Optional


_EVENTS_DIR = os.path.join(".cache", "events")
_EVENTS_PATH = os.path.join(_EVENTS_DIR, "diagnosis_events.jsonl")


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


def _get_final_disease(event: Dict[str, Any]) -> Optional[str]:
    if event.get("final_disease"):
        return event.get("final_disease")
    image_result = event.get("image_result") or {}
    if image_result.get("disease"):
        return image_result.get("disease")
    rule_result = event.get("rule_result") or {}
    if rule_result.get("rule_disease"):
        return rule_result.get("rule_disease")
    return event.get("disease") or event.get("disease_name")


def _get_confidence_pct(event: Dict[str, Any]) -> Optional[float]:
    rule_result = event.get("rule_result") or {}
    if event.get("fallback_used") is True and rule_result.get("rule_confidence_pct") is not None:
        return rule_result.get("rule_confidence_pct")
    image_result = event.get("image_result") or {}
    if image_result.get("confidence_pct") is not None:
        return image_result.get("confidence_pct")
    return event.get("confidence_pct")


def append_event(event: Dict[str, Any]) -> None:
    """Append a single diagnosis event to the JSONL store."""
    if "ts" not in event:
        event["ts"] = _now_iso()
    _ensure_dir()
    with open(_EVENTS_PATH, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False))
        handle.write("\n")


def _read_events() -> List[Dict[str, Any]]:
    if not os.path.exists(_EVENTS_PATH):
        return []
    events: List[Dict[str, Any]] = []
    with open(_EVENTS_PATH, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def _within_days(ts: datetime, days: int, now: datetime) -> bool:
    return ts >= now - timedelta(days=days)


def list_events(limit: int = 50) -> List[Dict[str, Any]]:
    """Return recent events sorted by ts descending."""
    events = _read_events()
    events.sort(
        key=lambda event: _parse_ts(event.get("ts")) or datetime.min,
        reverse=True,
    )
    return events[:limit]


def stats_by_disease(days: int = 30) -> Dict[str, int]:
    """Aggregate counts by disease for events within the last N days."""
    now = datetime.utcnow()
    counts: Dict[str, int] = {}
    for event in _read_events():
        ts = _parse_ts(event.get("ts"))
        if ts is None or not _within_days(ts, days, now):
            continue
        disease = _get_final_disease(event)
        if not disease:
            continue
        counts[disease] = counts.get(disease, 0) + 1
    return counts


def timeseries(days: int = 30) -> List[Dict[str, Any]]:
    """Return daily counts for events within the last N days."""
    now = datetime.utcnow()
    counts: Dict[str, int] = {}
    for event in _read_events():
        ts = _parse_ts(event.get("ts"))
        if ts is None or not _within_days(ts, days, now):
            continue
        date_key = ts.date().isoformat()
        counts[date_key] = counts.get(date_key, 0) + 1
    dates = sorted(counts.keys())
    return [{"date": date, "count": counts[date]} for date in dates]


def geo_points(days: int = 30) -> List[Dict[str, Any]]:
    """Return geo points for recent events with location data."""
    now = datetime.utcnow()
    points: List[Dict[str, Any]] = []
    for event in _read_events():
        ts = _parse_ts(event.get("ts"))
        if ts is None or not _within_days(ts, days, now):
            continue
        meta = event.get("meta") or {}
        lat = meta.get("lat") if meta.get("lat") is not None else event.get("lat")
        lon = meta.get("lon") if meta.get("lon") is not None else event.get("lon")
        if lat is None or lon is None:
            continue
        disease = _get_final_disease(event)
        points.append(
            {
                "lat": lat,
                "lon": lon,
                "disease": disease,
                "ts": event.get("ts"),
                "image_url": event.get("image_url"),
                "confidence_pct": _get_confidence_pct(event),
            }
        )
    points.sort(
        key=lambda event: _parse_ts(event.get("ts")) or datetime.min,
        reverse=True,
    )
    return points
