from __future__ import annotations

from fastapi.testclient import TestClient

import app as app_module


def test_serialize_final_response_backfills_root_canonical_fields_from_meta() -> None:
    payload = app_module.serialize_final_response(
        {
            "trace_id": "trace-meta-root",
            "risk_tags": [],
            "risk_items": [],
            "meta": {
                "risk_tags": ["HIGH_HUMIDITY"],
                "risk_items": [{"code": "HIGH_HUMIDITY", "label": "高湿", "reason": "连续阴雨"}],
                "risk_summary": "HIGH_HUMIDITY",
            },
        }
    )

    assert payload["risk_tags"] == ["HIGH_HUMIDITY"]
    assert payload["risk_items"] == [{"code": "HIGH_HUMIDITY", "label": "高湿", "reason": "连续阴雨"}]
    assert payload["risk_summary"] == "HIGH_HUMIDITY"


def test_api_events_injects_trace_steps(monkeypatch) -> None:
    monkeypatch.setattr(
        app_module,
        "list_events",
        lambda limit=50: [
            {
                "event_id": "evt-trace-steps",
                "trace_id": "trace-steps",
                "ts": "2026-03-22T10:00:00Z",
                "final_disease": "晚疫病",
                "meta": {"risk_tags": ["HIGH_HUMIDITY"]},
            }
        ],
    )
    monkeypatch.setattr(
        app_module,
        "list_trace_events",
        lambda trace_id: [
            {"trace_id": trace_id, "seq": 1, "node": "DiagnosisAgent", "status": "end", "message": "诊断完成", "ts": "2026-03-22T10:00:00Z"},
            {"trace_id": trace_id, "seq": 2, "node": "TreatmentAgent", "status": "end", "message": "方案生成完成", "ts": "2026-03-22T10:00:01Z"},
        ],
    )

    client = TestClient(app_module.app)
    response = client.get("/api/events")

    assert response.status_code == 200
    payload = response.json()["events"][0]
    assert payload["risk_tags"] == ["HIGH_HUMIDITY"]
    assert payload["trace_steps"][0]["node"] == "DiagnosisAgent"
    assert payload["trace_events"][1]["message"] == "方案生成完成"
