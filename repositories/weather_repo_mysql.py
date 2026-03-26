"""MySQL 天气快照仓储层。"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import select

from db import get_db_session
from mysql_models import WeatherSnapshotORM


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, (int, float)):
        try:
            return datetime.utcfromtimestamp(value)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            try:
                return datetime.strptime(value, "%Y-%m-%d")
            except ValueError:
                return None
    return None


def _dt_to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(microsecond=0).isoformat() + "Z"
    if isinstance(value, str):
        return value
    return str(value)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _in_date_range(ts: datetime | None, start: Any = None, end: Any = None) -> bool:
    if ts is None:
        return False
    start_dt = _parse_dt(start)
    end_dt = _parse_dt(end)
    ts_date = ts.date()
    if start_dt and ts_date < start_dt.date():
        return False
    if end_dt and ts_date > end_dt.date():
        return False
    return True


def _row_to_payload(row: WeatherSnapshotORM) -> dict[str, Any]:
    return {
        "id": row.id,
        "farmer_id": row.farmer_id,
        "base_id": row.base_id,
        "lat": row.lat,
        "lon": row.lon,
        "temperature": row.temperature,
        "humidity": row.humidity,
        "precipitation": row.precipitation,
        "rain_probability": row.rain_probability,
        "weather_code": row.weather_code,
        "weather_desc": row.weather_desc,
        "source": row.source,
        "snapshot_time": _dt_to_iso(row.snapshot_time),
        "raw_json": _as_dict(row.raw_json),
        "created_at": _dt_to_iso(row.created_at),
        "updated_at": _dt_to_iso(row.updated_at),
    }


def append_weather_snapshot_mysql(payload: dict[str, Any]) -> dict[str, Any]:
    row = WeatherSnapshotORM(
        farmer_id=str(payload.get("farmer_id") or "").strip() or None,
        base_id=str(payload.get("base_id") or "").strip() or None,
        lat=payload.get("lat"),
        lon=payload.get("lon"),
        temperature=payload.get("temperature"),
        humidity=payload.get("humidity"),
        precipitation=payload.get("precipitation"),
        rain_probability=payload.get("rain_probability"),
        weather_code=str(payload.get("weather_code") or "").strip() or None,
        weather_desc=str(payload.get("weather_desc") or "").strip() or None,
        source=str(payload.get("source") or "open-meteo").strip() or "open-meteo",
        snapshot_time=_parse_dt(payload.get("snapshot_time")) or datetime.utcnow(),
        raw_json=_as_dict(payload.get("raw_json")) or None,
    )
    with get_db_session() as session:
        try:
            session.add(row)
            session.commit()
            session.refresh(row)
            return _row_to_payload(row)
        except Exception:
            session.rollback()
            raise


def list_weather_snapshots_mysql(
    *,
    farmer_id: str | None = None,
    base_id: str | None = None,
    start: Any = None,
    end: Any = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    safe_limit = max(1, min(2000, int(limit)))
    with get_db_session() as session:
        query = select(WeatherSnapshotORM).order_by(
            WeatherSnapshotORM.snapshot_time.desc(),
            WeatherSnapshotORM.id.desc(),
        )
        if farmer_id:
            query = query.where(WeatherSnapshotORM.farmer_id == str(farmer_id).strip())
        if base_id:
            query = query.where(WeatherSnapshotORM.base_id == str(base_id).strip())
        rows = session.execute(query).scalars().all()
    filtered = [row for row in rows if _in_date_range(row.snapshot_time, start=start, end=end)]
    return [_row_to_payload(row) for row in filtered[:safe_limit]]


def get_latest_weather_snapshot_mysql(base_id: str) -> dict[str, Any]:
    normalized_base_id = str(base_id or "").strip()
    if not normalized_base_id:
        return {}
    with get_db_session() as session:
        row = session.execute(
            select(WeatherSnapshotORM)
            .where(WeatherSnapshotORM.base_id == normalized_base_id)
            .order_by(WeatherSnapshotORM.snapshot_time.desc(), WeatherSnapshotORM.id.desc())
            .limit(1)
        ).scalar_one_or_none()
    if row is None:
        return {}
    return _row_to_payload(row)
