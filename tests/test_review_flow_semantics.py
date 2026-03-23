from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi.testclient import TestClient

import app as app_module


class _InMemoryCaseRepo:
    def __init__(self, initial_events: list[dict[str, Any]]):
        self.events = [dict(item) for item in initial_events]
        self._sort()

    def _sort(self) -> None:
        self.events.sort(key=lambda item: str(item.get("ts") or ""), reverse=True)

    def list_events(self, limit: int = 200000) -> list[dict[str, Any]]:
        return [dict(item) for item in self.events[:limit]]

    def list_events_range(self, start: str | None = None, end: str | None = None, limit: int = 200000) -> list[dict[str, Any]]:
        def _in_range(item: dict[str, Any]) -> bool:
            ts = str(item.get("ts") or "")
            day = ts.split("T", 1)[0] if "T" in ts else ""
            if start and day < start:
                return False
            if end and day > end:
                return False
            return True

        filtered = [dict(item) for item in self.events if _in_range(item)]
        return filtered[:limit]

    def append_event(self, event: dict[str, Any]) -> dict[str, Any]:
        payload = dict(event)
        self.events.append(payload)
        self._sort()
        return payload

    def get_latest_event_by_trace(self, trace_id: str) -> dict[str, Any]:
        for item in self.events:
            if str(item.get("trace_id") or "").strip() == trace_id:
                return dict(item)
        return {}


def _event(
    *,
    trace_id: str,
    status: str,
    disease: str,
    expert_review_status: str = "NONE",
    assigned_expert_id: str | None = None,
    review_flow_status: str = "normal",
    ts: str,
) -> dict[str, Any]:
    return {
        "id": f"case-{trace_id}-{status}",
        "event_id": f"evt-{trace_id}-{status}",
        "trace_id": trace_id,
        "ts": ts,
        "farmer_id": "F0001",
        "final_disease": disease,
        "status": status,
        "expert_review_status": expert_review_status,
        "assigned_expert_id": assigned_expert_id,
        "review_flow_status": review_flow_status,
        "review_flow_note": "note",
        "meta": {"farmer_id": "F0001", "base_id": "B01", "farmer_name": "农户1"},
        "image_result": {"top3": [[disease, 0.9]]},
        "treatment": {"plan": "处置方案", "prevention": "预防方案"},
    }


def _install_repo(monkeypatch, repo: _InMemoryCaseRepo) -> None:
    monkeypatch.setattr(app_module, "list_events", repo.list_events)
    monkeypatch.setattr(app_module, "list_events_range", repo.list_events_range)
    monkeypatch.setattr(app_module, "append_event", repo.append_event)
    monkeypatch.setattr(app_module, "get_latest_event_by_trace", repo.get_latest_event_by_trace)


def _headers(role: str = "ADMIN", user_id: str = "A0001") -> dict[str, str]:
    return {"X-User-Role": role, "X-User-Id": user_id}


def test_admin_review_task_status_buckets(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    repo = _InMemoryCaseRepo(
        [
            _event(trace_id="t1", status="pending_expert_review", disease="晚疫病", ts=(now.isoformat())),
            _event(trace_id="t2", status="pending_expert_review", disease="早疫病", assigned_expert_id="E0001", expert_review_status="PENDING", ts=(now.isoformat())),
        ]
    )
    _install_repo(monkeypatch, repo)
    client = TestClient(app_module.app)

    pending_resp = client.get("/api/admin/reviews?status=pending", headers=_headers())
    assert pending_resp.status_code == 200
    assert pending_resp.json()["items"][0]["review_task_status"] == "UNASSIGNED"

    assigned_resp = client.get("/api/admin/reviews?status=assigned", headers=_headers())
    assert assigned_resp.status_code == 200
    assert assigned_resp.json()["items"][0]["review_task_status"] == "ASSIGNED"


def test_expert_submit_returns_completed_review_task_status(monkeypatch) -> None:
    now = datetime.now(timezone.utc).isoformat()
    repo = _InMemoryCaseRepo(
        [
            _event(
                trace_id="trace-submit",
                status="pending_expert_review",
                disease="晚疫病",
                assigned_expert_id="E0001",
                expert_review_status="PENDING",
                ts=now,
            )
        ]
    )
    _install_repo(monkeypatch, repo)
    client = TestClient(app_module.app)

    resp = client.post(
        "/api/expert-reviews/trace-submit/submit",
        headers=_headers(role="EXPERT", user_id="E0001"),
        json={"expert_review_result": "灰霉病", "expert_review_notes": "专家确认"},
    )
    assert resp.status_code == 200
    item = resp.json()["item"]
    assert item["status"] == "completed"
    assert item["review_task_status"] == "COMPLETED"


def test_admin_close_marks_cancelled_and_moves_bucket(monkeypatch) -> None:
    now = datetime.now(timezone.utc).isoformat()
    repo = _InMemoryCaseRepo(
        [
            _event(trace_id="trace-close", status="pending_expert_review", disease="叶霉病", assigned_expert_id="E0002", expert_review_status="PENDING", ts=now),
        ]
    )
    _install_repo(monkeypatch, repo)
    client = TestClient(app_module.app)

    close_resp = client.post(
        "/api/admin/reviews/trace-close/flow-status",
        headers=_headers(),
        json={"admin_flag": "closed", "admin_note": "管理员关闭"},
    )
    assert close_resp.status_code == 200
    item = close_resp.json()["item"]
    assert item["status"] == "cancelled"
    assert item["review_task_status"] == "CANCELLED"

    pending_resp = client.get("/api/admin/reviews?status=pending", headers=_headers())
    assert pending_resp.status_code == 200
    assert pending_resp.json()["count"] == 0

    assigned_resp = client.get("/api/admin/reviews?status=assigned", headers=_headers())
    assert assigned_resp.status_code == 200
    assert assigned_resp.json()["count"] == 0

    completed_resp = client.get("/api/admin/reviews?status=completed", headers=_headers())
    assert completed_resp.status_code == 200
    assert completed_resp.json()["items"][0]["review_task_status"] == "CANCELLED"


def test_stats_exclude_non_terminal_by_default(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    repo = _InMemoryCaseRepo(
        [
            _event(trace_id="s1", status="completed", disease="晚疫病", ts=now.isoformat()),
            _event(trace_id="s2", status="cancelled", disease="早疫病", ts=now.isoformat()),
            _event(trace_id="s3", status="pending_expert_review", disease="灰霉病", ts=now.isoformat()),
            _event(trace_id="s4", status="waiting_for_supplement", disease="叶霉病", ts=now.isoformat()),
            _event(trace_id="s5", status="waiting_for_expert_decision", disease="疫霉根腐病", ts=now.isoformat()),
        ]
    )
    _install_repo(monkeypatch, repo)
    client = TestClient(app_module.app)

    summary_resp = client.get("/api/stats/summary")
    assert summary_resp.status_code == 200
    assert summary_resp.json()["total"] == 2

    disease_resp = client.get("/api/stats/disease")
    assert disease_resp.status_code == 200
    diseases = {item["disease"] for item in disease_resp.json()["items"]}
    assert diseases == {"晚疫病", "早疫病"}

    include_resp = client.get("/api/stats/summary?include_non_terminal=true")
    assert include_resp.status_code == 200
    assert include_resp.json()["total"] == 5


def test_admin_detail_contains_derived_fields_for_frontend(monkeypatch) -> None:
    now = datetime.now(timezone.utc).isoformat()
    repo = _InMemoryCaseRepo(
        [
            _event(trace_id="trace-detail", status="pending_expert_review", disease="晚疫病", assigned_expert_id="E0009", expert_review_status="PENDING", review_flow_status="abnormal", ts=now),
        ]
    )
    _install_repo(monkeypatch, repo)
    client = TestClient(app_module.app)

    resp = client.get("/api/admin/reviews/trace-detail", headers=_headers())
    assert resp.status_code == 200
    item = resp.json()["item"]
    assert item["case_status"] == "pending_expert_review"
    assert item["review_task_status"] == "ASSIGNED"
    assert item["admin_flag"] == "abnormal"
    assert "admin_note" in item
