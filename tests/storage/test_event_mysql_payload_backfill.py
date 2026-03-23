from __future__ import annotations

from datetime import datetime

from mysql_models import DiagnosisEventORM
from repositories import event_repo_mysql


def test_event_row_payload_backfills_non_empty_root_fields_from_row_and_meta() -> None:
    row = DiagnosisEventORM(
        event_id="evt-backfill",
        trace_id="trace-backfill",
        ts=datetime(2026, 3, 22, 10, 0, 0),
        farmer_id="F1001",
        base_id="B1001",
        final_disease="晚疫病",
        final_source="rule",
        risk_tags_json=["HIGH_HUMIDITY"],
        risk_items_json=[{"code": "HIGH_HUMIDITY", "label": "高湿", "reason": "棚内湿度高"}],
        fallback_reason_json=["low_confidence"],
        meta_json={
            "farmer_id": "F1001",
            "base_id": "B1001",
            "risk_tags": ["HIGH_HUMIDITY"],
            "risk_items": [{"code": "HIGH_HUMIDITY", "label": "高湿", "reason": "棚内湿度高"}],
            "risk_summary": "HIGH_HUMIDITY",
        },
        payload_json={
            "event_id": "evt-backfill",
            "trace_id": "trace-backfill",
            "risk_tags": [],
            "risk_items": [],
            "fallback_reason": [],
            "meta": {
                "risk_tags": [],
                "risk_items": [],
            },
        },
    )

    payload = event_repo_mysql._row_to_event_payload(row)

    assert payload["risk_tags"] == ["HIGH_HUMIDITY"]
    assert payload["risk_items"] == [{"code": "HIGH_HUMIDITY", "label": "高湿", "reason": "棚内湿度高"}]
    assert payload["fallback_reason"] == ["low_confidence"]
    assert payload["meta"]["risk_tags"] == ["HIGH_HUMIDITY"]
    assert payload["meta"]["risk_items"] == [{"code": "HIGH_HUMIDITY", "label": "高湿", "reason": "棚内湿度高"}]
