"""Event store supporting file / dual / mysql modes."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import json
import os
from typing import Any, Dict, List, Optional

from config import EVENT_STORE_MODE


_EVENTS_DIR = os.path.join(".cache", "events")
_EVENTS_PATH = os.path.join(_EVENTS_DIR, "diagnosis_events.jsonl")


def _ensure_dir() -> None:
    os.makedirs(_EVENTS_DIR, exist_ok=True)


def _log_store_action(message: str) -> None:
    print(f"[EventStore:{EVENT_STORE_MODE}] {message}")


def _get_mysql_repo():
    from repositories.event_repo_mysql import (
        append_event_mysql,
        geo_points_mysql,
        geo_points_range_mysql,
        list_events_mysql,
        list_events_range_mysql,
        model_usage_mysql,
        model_usage_range_mysql,
        stats_by_disease_mysql,
        stats_by_disease_range_mysql,
        timeseries_mysql,
        timeseries_range_mysql,
    )

    return {
        "append_event_mysql": append_event_mysql,
        "list_events_mysql": list_events_mysql,
        "list_events_range_mysql": list_events_range_mysql,
        "stats_by_disease_mysql": stats_by_disease_mysql,
        "stats_by_disease_range_mysql": stats_by_disease_range_mysql,
        "timeseries_mysql": timeseries_mysql,
        "timeseries_range_mysql": timeseries_range_mysql,
        "geo_points_mysql": geo_points_mysql,
        "geo_points_range_mysql": geo_points_range_mysql,
        "model_usage_mysql": model_usage_mysql,
        "model_usage_range_mysql": model_usage_range_mysql,
    }


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.utcfromtimestamp(value).replace(tzinfo=None)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        ts = value.rstrip("Z")
        try:
            dt = datetime.fromisoformat(ts)
            return dt.replace(tzinfo=None)
        except ValueError:
            return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    return None


def _parse_date_str(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _in_date_range(ts: datetime, start_date: date | None, end_date: date | None) -> bool:
    ts_date = ts.date()
    if start_date and ts_date < start_date:
        return False
    if end_date and ts_date > end_date:
        return False
    return True


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


def _append_event_to_file(event: Dict[str, Any]) -> None:
    payload = dict(event)
    if "ts" not in payload:
        payload["ts"] = _now_iso()
    _ensure_dir()
    with open(_EVENTS_PATH, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False))
        handle.write("\n")


def _read_events_from_file() -> List[Dict[str, Any]]:
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


def _list_events_range_from_file(
    start: str | None = None,
    end: str | None = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    start_date = _parse_date_str(start)
    end_date = _parse_date_str(end)
    events = []
    for event in _read_events_from_file():
        ts = _parse_ts(event.get("ts"))
        if ts is None or not _in_date_range(ts, start_date, end_date):
            continue
        events.append(event)
    events.sort(
        key=lambda event: _parse_ts(event.get("ts")) or datetime.min,
        reverse=True,
    )
    return events[:limit]


def _list_events_from_file(limit: int = 50) -> List[Dict[str, Any]]:
    events = _read_events_from_file()
    events.sort(
        key=lambda event: _parse_ts(event.get("ts")) or datetime.min,
        reverse=True,
    )
    return events[:limit]


def _stats_by_disease_from_file(days: int = 30) -> Dict[str, int]:
    now = datetime.utcnow()
    counts: Dict[str, int] = {}
    for event in _read_events_from_file():
        ts = _parse_ts(event.get("ts"))
        if ts is None or not _within_days(ts, days, now):
            continue
        disease = _get_final_disease(event)
        if not disease:
            continue
        counts[disease] = counts.get(disease, 0) + 1
    return counts


def _stats_by_disease_range_from_file(start: str | None = None, end: str | None = None) -> Dict[str, int]:
    start_date = _parse_date_str(start)
    end_date = _parse_date_str(end)
    counts: Dict[str, int] = {}
    for event in _read_events_from_file():
        ts = _parse_ts(event.get("ts"))
        if ts is None or not _in_date_range(ts, start_date, end_date):
            continue
        disease = _get_final_disease(event)
        if not disease:
            continue
        counts[disease] = counts.get(disease, 0) + 1
    return counts


def _timeseries_from_file(days: int = 30) -> List[Dict[str, Any]]:
    now = datetime.utcnow()
    counts: Dict[str, int] = {}
    for event in _read_events_from_file():
        ts = _parse_ts(event.get("ts"))
        if ts is None or not _within_days(ts, days, now):
            continue
        date_key = ts.date().isoformat()
        counts[date_key] = counts.get(date_key, 0) + 1
    dates = sorted(counts.keys())
    return [{"date": day, "count": counts[day]} for day in dates]


def _timeseries_range_from_file(start: str | None = None, end: str | None = None) -> List[Dict[str, Any]]:
    start_date = _parse_date_str(start)
    end_date = _parse_date_str(end)
    counts: Dict[str, int] = {}
    for event in _read_events_from_file():
        ts = _parse_ts(event.get("ts"))
        if ts is None or not _in_date_range(ts, start_date, end_date):
            continue
        date_key = ts.date().isoformat()
        counts[date_key] = counts.get(date_key, 0) + 1
    dates = sorted(counts.keys())
    return [{"date": day, "count": counts[day]} for day in dates]


def _geo_points_from_file(days: int = 30) -> List[Dict[str, Any]]:
    now = datetime.utcnow()
    points: List[Dict[str, Any]] = []
    for event in _read_events_from_file():
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


def _geo_points_range_from_file(start: str | None = None, end: str | None = None) -> List[Dict[str, Any]]:
    start_date = _parse_date_str(start)
    end_date = _parse_date_str(end)
    points: List[Dict[str, Any]] = []
    for event in _read_events_from_file():
        ts = _parse_ts(event.get("ts"))
        if ts is None or not _in_date_range(ts, start_date, end_date):
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


def _model_usage_range_from_file(start: str | None = None, end: str | None = None) -> Dict[str, int]:
    start_date = _parse_date_str(start)
    end_date = _parse_date_str(end)
    counts: Dict[str, int] = {}
    for event in _read_events_from_file():
        ts = _parse_ts(event.get("ts"))
        if ts is None or not _in_date_range(ts, start_date, end_date):
            continue
        meta = event.get("meta") if isinstance(event.get("meta"), dict) else {}
        label = (
            str(meta.get("model_display_name") or "").strip()
            or str(meta.get("model_id") or "").strip()
            or str(event.get("model_display_name") or "").strip()
            or str(event.get("model_id") or "").strip()
            or "未知模型"
        )
        counts[label] = counts.get(label, 0) + 1
    return counts


def append_event(event: Dict[str, Any]) -> None:
    """Append a single diagnosis event to the active store."""
    mode = (EVENT_STORE_MODE or "file").lower()
    if mode == "mysql":
        _log_store_action("append_event via mysql")
        repo = _get_mysql_repo()
        repo["append_event_mysql"](event)
        return

    _log_store_action("append_event via file")
    _append_event_to_file(event)
    if mode == "dual":
        _log_store_action("append_event dual-write mysql")
        repo = _get_mysql_repo()
        repo["append_event_mysql"](event)


def list_events_range(start: str | None = None, end: str | None = None, limit: int = 50) -> List[Dict[str, Any]]:
    """Return recent events sorted by ts descending within a date range."""
    mode = (EVENT_STORE_MODE or "file").lower()
    if mode == "mysql":
        _log_store_action("list_events_range via mysql")
        repo = _get_mysql_repo()
        return repo["list_events_range_mysql"](start=start, end=end, limit=limit)

    return _list_events_range_from_file(start=start, end=end, limit=limit)


def list_events(limit: int = 50) -> List[Dict[str, Any]]:
    """Return recent events sorted by ts descending."""
    mode = (EVENT_STORE_MODE or "file").lower()
    if mode == "mysql":
        _log_store_action("list_events via mysql")
        repo = _get_mysql_repo()
        return repo["list_events_mysql"](limit=limit)

    return _list_events_from_file(limit=limit)


def stats_by_disease(days: int = 30) -> Dict[str, int]:
    """Aggregate counts by disease for events within the last N days."""
    mode = (EVENT_STORE_MODE or "file").lower()
    if mode == "mysql":
        _log_store_action("stats_by_disease via mysql")
        start = (datetime.utcnow() - timedelta(days=days)).date().isoformat()
        repo = _get_mysql_repo()
        return repo["stats_by_disease_mysql"](start=start, end=None)

    return _stats_by_disease_from_file(days=days)


def stats_by_disease_range(start: str | None = None, end: str | None = None) -> Dict[str, int]:
    """Aggregate counts by disease for events within a date range."""
    mode = (EVENT_STORE_MODE or "file").lower()
    if mode == "mysql":
        _log_store_action("stats_by_disease_range via mysql")
        repo = _get_mysql_repo()
        return repo["stats_by_disease_range_mysql"](start=start, end=end)

    return _stats_by_disease_range_from_file(start=start, end=end)


def timeseries(days: int = 30) -> List[Dict[str, Any]]:
    """Return daily counts for events within the last N days."""
    mode = (EVENT_STORE_MODE or "file").lower()
    if mode == "mysql":
        _log_store_action("timeseries via mysql")
        start = (datetime.utcnow() - timedelta(days=days)).date().isoformat()
        repo = _get_mysql_repo()
        return repo["timeseries_mysql"](start=start, end=None)

    return _timeseries_from_file(days=days)


def timeseries_range(start: str | None = None, end: str | None = None) -> List[Dict[str, Any]]:
    """Return daily counts for events within a date range."""
    mode = (EVENT_STORE_MODE or "file").lower()
    if mode == "mysql":
        _log_store_action("timeseries_range via mysql")
        repo = _get_mysql_repo()
        return repo["timeseries_range_mysql"](start=start, end=end)

    return _timeseries_range_from_file(start=start, end=end)


def geo_points(days: int = 30) -> List[Dict[str, Any]]:
    """Return geo points for recent events with location data."""
    mode = (EVENT_STORE_MODE or "file").lower()
    if mode == "mysql":
        _log_store_action("geo_points via mysql")
        start = (datetime.utcnow() - timedelta(days=days)).date().isoformat()
        repo = _get_mysql_repo()
        return repo["geo_points_mysql"](start=start, end=None)

    return _geo_points_from_file(days=days)


def geo_points_range(start: str | None = None, end: str | None = None) -> List[Dict[str, Any]]:
    """Return geo points for events within a date range."""
    mode = (EVENT_STORE_MODE or "file").lower()
    if mode == "mysql":
        _log_store_action("geo_points_range via mysql")
        repo = _get_mysql_repo()
        return repo["geo_points_range_mysql"](start=start, end=end)

    return _geo_points_range_from_file(start=start, end=end)


def model_usage_range(start: str | None = None, end: str | None = None) -> Dict[str, int]:
    """Aggregate model usage counts within a date range."""
    mode = (EVENT_STORE_MODE or "file").lower()
    if mode == "mysql":
        _log_store_action("model_usage_range via mysql")
        repo = _get_mysql_repo()
        return repo["model_usage_range_mysql"](start=start, end=end)

    return _model_usage_range_from_file(start=start, end=end)
