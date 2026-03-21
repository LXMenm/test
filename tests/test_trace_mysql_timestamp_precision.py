from __future__ import annotations

from datetime import datetime

from sqlalchemy.dialects import mysql

from mysql_models import TraceEventORM
from repositories import trace_repo_mysql


def test_trace_event_mysql_iso_keeps_milliseconds() -> None:
    kwargs = trace_repo_mysql._trace_event_to_orm_kwargs(
        "trace-ms",
        {
            "node": "DiagnosisAgent",
            "status": "end",
            "message": "done",
            "ts": "2026-03-20T10:00:00.123456Z",
        },
        seq=1,
    )

    assert kwargs["ts"].microsecond == 123456
    assert kwargs["payload_json"]["ts"] == "2026-03-20T10:00:00.123Z"


def test_trace_event_mysql_row_payload_keeps_milliseconds() -> None:
    row = TraceEventORM(
        trace_id="trace-ms",
        seq=1,
        node="DiagnosisAgent",
        agent=None,
        agent_id=None,
        status="end",
        message="done",
        payload_json={},
        ts=datetime(2026, 3, 20, 10, 0, 0, 987000),
    )

    payload = trace_repo_mysql._row_to_trace_payload(row)

    assert payload["ts"] == "2026-03-20T10:00:00.987Z"


def test_trace_event_mysql_column_uses_millisecond_precision_for_mysql() -> None:
    mysql_type = TraceEventORM.__table__.c.ts.type.dialect_impl(mysql.dialect())
    created_at_type = TraceEventORM.__table__.c.created_at.type.dialect_impl(mysql.dialect())

    assert getattr(mysql_type, "fsp", None) == 3
    assert getattr(created_at_type, "fsp", None) == 3
