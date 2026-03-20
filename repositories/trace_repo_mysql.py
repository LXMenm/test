"""MySQL trace 事件仓储层。"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from db import get_db_session
from mysql_models import TraceEventORM


@contextmanager
def _session_scope(session: Session | None = None) -> Iterator[Session]:
    if session is not None:
        yield session
        return
    with get_db_session() as managed_session:
        yield managed_session


def _utc_now() -> datetime:
    return datetime.utcnow().replace(microsecond=0)


def _dt_to_iso(value: Any) -> Optional[str]:
    dt = _parse_dt(value)
    if dt is None:
        return None
    return dt.replace(microsecond=0).isoformat() + "Z"


def _parse_dt(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time())
    elif isinstance(value, (int, float)):
        try:
            dt = datetime.utcfromtimestamp(value)
        except (OverflowError, OSError, ValueError):
            return None
    elif isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(normalized)
        except ValueError:
            return None
    else:
        return None

    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _as_payload_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _row_to_trace_payload(row: TraceEventORM) -> dict[str, Any]:
    payload = _as_payload_dict(row.payload_json)
    if not payload:
        payload = {}

    payload.setdefault("trace_id", row.trace_id)
    payload.setdefault("seq", row.seq)
    payload.setdefault("node", row.node)
    payload.setdefault("agent", row.agent)
    payload.setdefault("agent_id", row.agent_id)
    payload.setdefault("status", row.status)
    payload.setdefault("message", row.message)
    payload.setdefault("ts", _dt_to_iso(row.ts))
    return payload


def _next_seq(trace_id: str, session: Session | None = None) -> int:
    normalized_trace_id = str(trace_id or "").strip()
    if not normalized_trace_id:
        raise ValueError("trace_id is required")

    with _session_scope(session) as active_session:
        current = active_session.execute(
            select(func.max(TraceEventORM.seq)).where(TraceEventORM.trace_id == normalized_trace_id)
        ).scalar_one()
        return (int(current) if current is not None else 0) + 1


def _trace_event_to_orm_kwargs(
    trace_id: str,
    event: Dict[str, Any],
    seq: int | None = None,
    session: Session | None = None,
) -> dict[str, Any]:
    normalized_trace_id = str(trace_id or "").strip()
    if not normalized_trace_id:
        raise ValueError("trace_id is required")
    if not isinstance(event, dict):
        raise TypeError("event must be a dict")

    payload = dict(event)
    resolved_seq = seq
    if resolved_seq is None:
        raw_seq = payload.get("seq")
        if raw_seq is not None:
            try:
                resolved_seq = int(raw_seq)
            except (TypeError, ValueError):
                resolved_seq = None
    if resolved_seq is None:
        resolved_seq = _next_seq(normalized_trace_id, session=session)

    ts = _parse_dt(payload.get("ts")) or _utc_now()

    payload["trace_id"] = normalized_trace_id
    payload["seq"] = resolved_seq
    payload["ts"] = _dt_to_iso(ts)

    return {
        "trace_id": normalized_trace_id,
        "seq": resolved_seq,
        "node": payload.get("node"),
        "agent": payload.get("agent"),
        "agent_id": payload.get("agent_id"),
        "status": payload.get("status"),
        "message": payload.get("message"),
        "payload_json": payload,
        "ts": ts,
    }


def append_trace_event_mysql(trace_id: str, event: Dict[str, Any]) -> dict[str, Any]:
    with get_db_session() as session:
        try:
            kwargs = _trace_event_to_orm_kwargs(trace_id, event, session=session)
            row = TraceEventORM(**kwargs)
            session.add(row)
            session.commit()
            session.refresh(row)
            return _row_to_trace_payload(row)
        except Exception:
            session.rollback()
            raise


def emit_trace_event_mysql(trace_id: str, payload: Dict[str, Any]) -> dict[str, Any]:
    return append_trace_event_mysql(trace_id, payload)


def list_trace_events_mysql(trace_id: str) -> List[Dict[str, Any]]:
    normalized_trace_id = str(trace_id or "").strip()
    if not normalized_trace_id:
        return []

    with get_db_session() as session:
        rows = session.execute(
            select(TraceEventORM)
            .where(TraceEventORM.trace_id == normalized_trace_id)
            .order_by(TraceEventORM.seq.asc(), TraceEventORM.id.asc())
        ).scalars().all()
        return [_row_to_trace_payload(row) for row in rows]


def delete_trace_events_mysql(trace_id: str) -> int:
    normalized_trace_id = str(trace_id or "").strip()
    if not normalized_trace_id:
        return 0

    with get_db_session() as session:
        try:
            result = session.execute(
                delete(TraceEventORM).where(TraceEventORM.trace_id == normalized_trace_id)
            )
            session.commit()
            return int(result.rowcount or 0)
        except Exception:
            session.rollback()
            raise
