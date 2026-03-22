"""MySQL 诊断事件仓储层。"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import select

from db import get_db_session
from mysql_models import DiagnosisEventORM


def _now_dt() -> datetime:
    return datetime.utcnow().replace(microsecond=0)


def _now_iso() -> str:
    return _now_dt().isoformat() + "Z"


def _parse_dt(value: Any) -> Optional[datetime]:
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


def _parse_date_value(value: Any) -> Optional[date]:
    dt = _parse_dt(value)
    return dt.date() if dt else None


def _in_date_range(ts: datetime, start: Any = None, end: Any = None) -> bool:
    start_date = _parse_date_value(start)
    end_date = _parse_date_value(end)
    ts_date = ts.date()
    if start_date and ts_date < start_date:
        return False
    if end_date and ts_date > end_date:
        return False
    return True


def _within_days(ts: datetime, days: int, now: datetime) -> bool:
    return ts >= now - timedelta(days=days)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _is_non_empty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


def _set_non_empty(payload: dict[str, Any], key: str, value: Any) -> None:
    if _is_non_empty(payload.get(key)):
        return
    if _is_non_empty(value):
        payload[key] = value


def _dt_to_iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(microsecond=0).isoformat() + "Z"
    if isinstance(value, str):
        return value
    return str(value)


def _pick(event: dict[str, Any], key: str, default: Any = None) -> Any:
    if event.get(key) is not None:
        return event.get(key)
    meta = _as_dict(event.get("meta"))
    if meta.get(key) is not None:
        return meta.get(key)
    return default


def _get_final_disease(event: Dict[str, Any]) -> Optional[str]:
    if event.get("final_disease"):
        return event.get("final_disease")
    image_result = _as_dict(event.get("image_result"))
    if image_result.get("disease"):
        return image_result.get("disease")
    rule_result = _as_dict(event.get("rule_result"))
    if rule_result.get("rule_disease"):
        return rule_result.get("rule_disease")
    return event.get("disease") or event.get("disease_name")


def _get_confidence_pct(event: Dict[str, Any]) -> Optional[float]:
    rule_result = _as_dict(event.get("rule_result"))
    if event.get("fallback_used") is True and rule_result.get("rule_confidence_pct") is not None:
        return rule_result.get("rule_confidence_pct")
    image_result = _as_dict(event.get("image_result"))
    if image_result.get("confidence_pct") is not None:
        return image_result.get("confidence_pct")
    if event.get("final_confidence") is not None:
        return event.get("final_confidence")
    return event.get("confidence_pct")


def _event_to_orm_kwargs(event: dict[str, Any]) -> dict[str, Any]:
    payload = dict(event)
    event_id = str(payload.get("event_id") or uuid4().hex)
    ts = _parse_dt(payload.get("ts")) or _now_dt()

    payload["event_id"] = event_id
    payload["ts"] = _dt_to_iso(ts)

    meta = _as_dict(payload.get("meta"))
    lat = payload.get("lat") if payload.get("lat") is not None else meta.get("lat")
    lon = payload.get("lon") if payload.get("lon") is not None else meta.get("lon")

    model_display_name = (
        _pick(payload, "model_display_name")
        or str(meta.get("model_display_name") or "").strip()
        or None
    )
    model_id = _pick(payload, "model_id")
    final_disease = _get_final_disease(payload)
    final_confidence = payload.get("final_confidence")
    if final_confidence is None:
        final_confidence = _get_confidence_pct(payload)

    return {
        "event_id": event_id,
        "trace_id": str(_pick(payload, "trace_id") or event_id),
        "ts": ts,
        "farmer_id": _pick(payload, "farmer_id"),
        "base_id": _pick(payload, "base_id"),
        "crop_type": _pick(payload, "crop_type"),
        "growth_stage": _pick(payload, "growth_stage"),
        "final_disease": final_disease,
        "final_confidence": final_confidence,
        "final_source": _pick(payload, "final_source"),
        "model_id": model_id,
        "model_display_name": model_display_name,
        "status": _pick(payload, "status"),
        "need_confirm": _pick(payload, "need_confirm"),
        "personalization_applied": _pick(payload, "personalization_applied", False),
        "filtered": _pick(payload, "filtered", False),
        "workflow_degraded": _pick(payload, "workflow_degraded", False),
        "elapsed_ms": _pick(payload, "elapsed_ms"),
        "lat": lat,
        "lon": lon,
        "symptoms_json": _as_list(payload.get("symptoms")),
        "image_result_json": payload.get("image_result") if isinstance(payload.get("image_result"), dict) else None,
        "fallback_reason_json": payload.get("fallback_reason") if isinstance(payload.get("fallback_reason"), (dict, list)) else None,
        "rule_result_json": payload.get("rule_result") if isinstance(payload.get("rule_result"), dict) else None,
        "treatment_json": payload.get("treatment") if isinstance(payload.get("treatment"), (dict, list)) else None,
        "verification_result_json": payload.get("verification_result") if isinstance(payload.get("verification_result"), (dict, list)) else None,
        "verification_issues_json": _as_list(payload.get("verification_issues")),
        "risk_tags_json": _as_list(payload.get("risk_tags")),
        "risk_items_json": _as_list(payload.get("risk_items")),
        "text_top3_json": _as_list(payload.get("text_top3")),
        "fusion_top3_json": _as_list(payload.get("fusion_top3")),
        "diagnosis_evidence_json": payload.get("diagnosis_evidence") if isinstance(payload.get("diagnosis_evidence"), (dict, list)) else None,
        "meta_json": meta or None,
        "payload_json": payload,
    }


def _row_to_event_payload(row: DiagnosisEventORM) -> dict[str, Any]:
    payload = _as_dict(row.payload_json)
    if not payload:
        payload = {}

    payload_meta = _as_dict(payload.get("meta"))
    row_meta = _as_dict(row.meta_json)
    merged_meta = dict(payload_meta)
    for meta_key, meta_value in row_meta.items():
        if not _is_non_empty(merged_meta.get(meta_key)) and _is_non_empty(meta_value):
            merged_meta[meta_key] = meta_value
    if merged_meta:
        payload["meta"] = merged_meta

    _set_non_empty(payload, "event_id", row.event_id)
    _set_non_empty(payload, "trace_id", row.trace_id)
    _set_non_empty(payload, "ts", _dt_to_iso(row.ts))
    _set_non_empty(payload, "farmer_id", row.farmer_id)
    _set_non_empty(payload, "base_id", row.base_id)
    _set_non_empty(payload, "crop_type", row.crop_type)
    _set_non_empty(payload, "growth_stage", row.growth_stage)
    _set_non_empty(payload, "final_disease", row.final_disease)
    _set_non_empty(payload, "final_confidence", row.final_confidence)
    _set_non_empty(payload, "final_source", row.final_source)
    _set_non_empty(payload, "model_id", row.model_id)
    _set_non_empty(payload, "model_display_name", row.model_display_name)
    _set_non_empty(payload, "status", row.status)
    _set_non_empty(payload, "need_confirm", row.need_confirm)
    _set_non_empty(payload, "personalization_applied", row.personalization_applied)
    _set_non_empty(payload, "filtered", row.filtered)
    _set_non_empty(payload, "workflow_degraded", row.workflow_degraded)
    _set_non_empty(payload, "elapsed_ms", row.elapsed_ms)
    _set_non_empty(payload, "lat", row.lat)
    _set_non_empty(payload, "lon", row.lon)
    _set_non_empty(payload, "symptoms", _as_list(row.symptoms_json))
    _set_non_empty(payload, "image_result", _as_dict(row.image_result_json))
    _set_non_empty(payload, "fallback_reason", _as_list(row.fallback_reason_json))
    _set_non_empty(payload, "rule_result", _as_dict(row.rule_result_json))
    _set_non_empty(payload, "treatment", row.treatment_json)
    _set_non_empty(payload, "verification_result", row.verification_result_json)
    _set_non_empty(payload, "verification_issues", _as_list(row.verification_issues_json))
    _set_non_empty(payload, "risk_tags", _as_list(row.risk_tags_json))
    _set_non_empty(payload, "risk_items", _as_list(row.risk_items_json))
    _set_non_empty(payload, "text_top3", _as_list(row.text_top3_json))
    _set_non_empty(payload, "fusion_top3", _as_list(row.fusion_top3_json))
    _set_non_empty(payload, "diagnosis_evidence", row.diagnosis_evidence_json)
    return payload


def _list_rows(start: Any = None, end: Any = None, limit: Optional[int] = None) -> list[DiagnosisEventORM]:
    with get_db_session() as session:
        query = select(DiagnosisEventORM).order_by(DiagnosisEventORM.ts.desc())
        rows = session.execute(query).scalars().all()
        filtered = [row for row in rows if row.ts and _in_date_range(row.ts, start, end)]
        if limit is not None:
            filtered = filtered[:limit]
        return filtered


def append_event_mysql(event: dict[str, Any]) -> dict[str, Any]:
    kwargs = _event_to_orm_kwargs(event)
    row = DiagnosisEventORM(**kwargs)
    with get_db_session() as session:
        try:
            session.add(row)
            session.commit()
            session.refresh(row)
            return _row_to_event_payload(row)
        except Exception:
            session.rollback()
            raise


def list_events_mysql(limit: int = 100) -> List[Dict[str, Any]]:
    rows = _list_rows(limit=limit)
    return [_row_to_event_payload(row) for row in rows]


def get_latest_event_by_trace_mysql(trace_id: str) -> dict[str, Any]:
    normalized_trace_id = str(trace_id or "").strip()
    if not normalized_trace_id:
        return {}

    with get_db_session() as session:
        row = session.execute(
            select(DiagnosisEventORM)
            .where(DiagnosisEventORM.trace_id == normalized_trace_id)
            .order_by(DiagnosisEventORM.ts.desc(), DiagnosisEventORM.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if row is None:
            return {}
        return _row_to_event_payload(row)


def list_events_range_mysql(
    start: Any = None,
    end: Any = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    rows = _list_rows(start=start, end=end, limit=limit)
    return [_row_to_event_payload(row) for row in rows]


def stats_by_disease_mysql(start: Any = None, end: Any = None) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in _list_rows(start=start, end=end):
        disease = str(row.final_disease or "").strip()
        if not disease:
            continue
        counts[disease] = counts.get(disease, 0) + 1
    return counts


def stats_by_disease_range_mysql(start: Any = None, end: Any = None) -> Dict[str, int]:
    return stats_by_disease_mysql(start=start, end=end)


def timeseries_mysql(start: Any = None, end: Any = None) -> List[Dict[str, Any]]:
    counts: Dict[str, int] = {}
    for row in _list_rows(start=start, end=end):
        if row.ts is None:
            continue
        date_key = row.ts.date().isoformat()
        counts[date_key] = counts.get(date_key, 0) + 1
    return [{"date": day, "count": counts[day]} for day in sorted(counts.keys())]


def timeseries_range_mysql(start: Any = None, end: Any = None) -> List[Dict[str, Any]]:
    return timeseries_mysql(start=start, end=end)


def geo_points_mysql(start: Any = None, end: Any = None) -> List[Dict[str, Any]]:
    points: List[Dict[str, Any]] = []
    for row in _list_rows(start=start, end=end):
        lat = row.lat
        lon = row.lon
        if lat is None or lon is None:
            continue
        payload = _row_to_event_payload(row)
        points.append(
            {
                "event_id": row.event_id,
                "lat": lat,
                "lon": lon,
                "disease": row.final_disease,
                "trace_id": row.trace_id,
                "farmer_id": row.farmer_id,
                "base_id": row.base_id,
                "ts": payload.get("ts"),
                "image_url": payload.get("image_url"),
                "confidence_pct": _get_confidence_pct(payload),
            }
        )
    points.sort(key=lambda item: _parse_dt(item.get("ts")) or datetime.min, reverse=True)
    return points


def geo_points_range_mysql(start: Any = None, end: Any = None) -> List[Dict[str, Any]]:
    return geo_points_mysql(start=start, end=end)


def model_usage_mysql(start: Any = None, end: Any = None) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in _list_rows(start=start, end=end):
        label = (
            str(row.model_display_name or "").strip()
            or str(row.model_id or "").strip()
            or "未知模型"
        )
        counts[label] = counts.get(label, 0) + 1
    return counts


def model_usage_range_mysql(start: Any = None, end: Any = None) -> Dict[str, int]:
    return model_usage_mysql(start=start, end=end)
