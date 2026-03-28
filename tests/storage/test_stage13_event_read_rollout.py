from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

import app as app_module
import event_store


class _InMemoryEventMysqlRepo:
    def __init__(self, initial_events: list[dict[str, Any]] | None = None):
        self._events = [dict(event) for event in (initial_events or [])]

    def append_event_mysql(self, event: dict[str, Any]) -> dict[str, Any]:
        payload = dict(event)
        self._events.append(payload)
        self._events.sort(key=lambda item: item.get("ts") or "", reverse=True)
        return payload

    def list_events_mysql(self, limit: int = 100) -> list[dict[str, Any]]:
        return [dict(event) for event in self._events[:limit]]

    def list_events_range_mysql(self, start: Any = None, end: Any = None, limit: int = 100) -> list[dict[str, Any]]:
        return [dict(event) for event in self._filter_by_range(start, end)[:limit]]

    def stats_by_disease_mysql(self, start: Any = None, end: Any = None) -> dict[str, int]:
        counts: dict[str, int] = {}
        for event in self._filter_by_range(start, end):
            disease = str(event.get("final_disease") or "").strip()
            if disease:
                counts[disease] = counts.get(disease, 0) + 1
        return counts

    def stats_by_disease_range_mysql(self, start: Any = None, end: Any = None) -> dict[str, int]:
        return self.stats_by_disease_mysql(start=start, end=end)

    def timeseries_mysql(self, start: Any = None, end: Any = None) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for event in self._filter_by_range(start, end):
            ts = str(event.get("ts") or "")
            if "T" not in ts:
                continue
            day = ts.split("T", 1)[0]
            counts[day] = counts.get(day, 0) + 1
        return [{"date": day, "count": counts[day]} for day in sorted(counts.keys())]

    def timeseries_range_mysql(self, start: Any = None, end: Any = None) -> list[dict[str, Any]]:
        return self.timeseries_mysql(start=start, end=end)

    def geo_points_mysql(self, start: Any = None, end: Any = None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for event in self._filter_by_range(start, end):
            meta = event.get("meta") if isinstance(event.get("meta"), dict) else {}
            lat = meta.get("lat") if meta.get("lat") is not None else event.get("lat")
            lon = meta.get("lon") if meta.get("lon") is not None else event.get("lon")
            if lat is None or lon is None:
                continue
            items.append(
                {
                    "event_id": event.get("event_id"),
                    "lat": lat,
                    "lon": lon,
                    "disease": event.get("final_disease"),
                    "trace_id": event.get("trace_id"),
                    "farmer_id": event.get("farmer_id"),
                    "base_id": event.get("base_id"),
                    "ts": event.get("ts"),
                    "image_url": event.get("image_url"),
                    "confidence_pct": event.get("final_confidence"),
                }
            )
        return items

    def geo_points_range_mysql(self, start: Any = None, end: Any = None) -> list[dict[str, Any]]:
        return self.geo_points_mysql(start=start, end=end)

    def model_usage_mysql(self, start: Any = None, end: Any = None) -> dict[str, int]:
        counts: dict[str, int] = {}
        for event in self._filter_by_range(start, end):
            meta = event.get("meta") if isinstance(event.get("meta"), dict) else {}
            label = str(meta.get("model_display_name") or event.get("model_display_name") or "未知模型").strip() or "未知模型"
            counts[label] = counts.get(label, 0) + 1
        return counts

    def model_usage_range_mysql(self, start: Any = None, end: Any = None) -> dict[str, int]:
        return self.model_usage_mysql(start=start, end=end)

    def get_latest_event_by_trace_mysql(self, trace_id: str) -> dict[str, Any]:
        for event in self._events:
            if event.get("trace_id") == trace_id:
                return dict(event)
        return {}

    def _filter_by_range(self, start: Any, end: Any) -> list[dict[str, Any]]:
        start_date = str(start) if start else None
        end_date = str(end) if end else None
        items: list[dict[str, Any]] = []
        for event in self._events:
            ts = str(event.get("ts") or "")
            day = ts.split("T", 1)[0] if "T" in ts else ""
            if start_date and day < start_date:
                continue
            if end_date and day > end_date:
                continue
            items.append(dict(event))
        return items


def _event_payload(*, event_id: str, trace_id: str, disease: str, ts: str, farmer_id: str, base_id: str, model: str, filtered_reasons: list[str] | None = None) -> dict[str, Any]:
    filtered_reasons = filtered_reasons or []
    return {
        "event_id": event_id,
        "trace_id": trace_id,
        "ts": ts,
        "farmer_id": farmer_id,
        "base_id": base_id,
        "final_disease": disease,
        "final_confidence": 0.81,
        "final_source": "fusion",
        "status": "completed",
        "filtered": bool(filtered_reasons),
        "filtered_reasons": filtered_reasons,
        "workflow_degraded": False,
        "elapsed_ms": 123.0,
        "image_url": f"/uploads/{event_id}.jpg",
        "meta": {
            "model_display_name": model,
            "farmer_id": farmer_id,
            "base_id": base_id,
            "lat": 36.9,
            "lon": 118.8,
        },
        "treatment": {"plan": "按方案处置"},
    }


def _install_event_repo(monkeypatch, tmp_path: Path, *, mode: str, repo: _InMemoryEventMysqlRepo) -> None:
    events_dir = tmp_path / ".cache" / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(event_store, "_EVENTS_DIR", str(events_dir))
    monkeypatch.setattr(event_store, "_EVENTS_PATH", str(events_dir / "diagnosis_events.jsonl"))
    monkeypatch.setattr(event_store, "EVENT_STORE_MODE", mode)
    monkeypatch.setattr(
        event_store,
        "_get_mysql_repo",
        lambda: {
            "append_event_mysql": repo.append_event_mysql,
            "get_latest_event_by_trace_mysql": repo.get_latest_event_by_trace_mysql,
            "list_events_mysql": repo.list_events_mysql,
            "list_events_range_mysql": repo.list_events_range_mysql,
            "stats_by_disease_mysql": repo.stats_by_disease_mysql,
            "stats_by_disease_range_mysql": repo.stats_by_disease_range_mysql,
            "timeseries_mysql": repo.timeseries_mysql,
            "timeseries_range_mysql": repo.timeseries_range_mysql,
            "geo_points_mysql": repo.geo_points_mysql,
            "geo_points_range_mysql": repo.geo_points_range_mysql,
            "model_usage_mysql": repo.model_usage_mysql,
            "model_usage_range_mysql": repo.model_usage_range_mysql,
        },
    )


def test_event_dual_baseline_keeps_file_reads(monkeypatch, tmp_path: Path) -> None:
    repo = _InMemoryEventMysqlRepo()
    _install_event_repo(monkeypatch, tmp_path, mode="dual", repo=repo)
    client = TestClient(app_module.app)

    payload = _event_payload(
        event_id="evt-dual-1",
        trace_id="trace-dual-1",
        disease="晚疫病",
        ts="2026-03-20T10:00:00Z",
        farmer_id="FDUAL",
        base_id="BDUAL",
        model="Dual Model",
        filtered_reasons=["禁药规则"],
    )
    event_store.append_event(payload)

    events_resp = client.get("/api/events")
    assert events_resp.status_code == 200
    assert events_resp.json()["events"][0]["event_id"] == "evt-dual-1"

    disease_resp = client.get("/api/stats/disease")
    assert disease_resp.status_code == 200
    assert disease_resp.json()["items"][0]["disease"] == "晚疫病"



def test_event_mysql_routes_and_latest_case_lookup(monkeypatch, tmp_path: Path) -> None:
    today = datetime.now(timezone.utc).replace(microsecond=0)
    yesterday = today - timedelta(days=1)
    target_event = _event_payload(
        event_id="evt-target",
        trace_id="trace-target",
        disease="早疫病",
        ts=yesterday.isoformat().replace("+00:00", "Z"),
        farmer_id="FMYSQL",
        base_id="BMYSQL",
        model="MySQL Model",
        filtered_reasons=["安全间隔不足"],
    )
    recent_event = _event_payload(
        event_id="evt-recent",
        trace_id="trace-recent",
        disease="晚疫病",
        ts=today.isoformat().replace("+00:00", "Z"),
        farmer_id="FMYSQL",
        base_id="BMYSQL",
        model="MySQL Model",
    )
    repo = _InMemoryEventMysqlRepo([recent_event, target_event])
    _install_event_repo(monkeypatch, tmp_path, mode="mysql", repo=repo)
    client = TestClient(app_module.app)

    events_resp = client.get("/api/events")
    assert events_resp.status_code == 200
    assert {item["event_id"] for item in events_resp.json()["events"]} == {"evt-recent", "evt-target"}

    disease_resp = client.get("/api/stats/disease")
    assert disease_resp.status_code == 200
    assert {item["disease"] for item in disease_resp.json()["items"]} == {"早疫病", "晚疫病"}

    timeseries_resp = client.get("/api/stats/timeseries")
    assert timeseries_resp.status_code == 200
    assert len(timeseries_resp.json()["items"]) >= 1

    geo_resp = client.get("/api/stats/geo")
    assert geo_resp.status_code == 200
    assert len(geo_resp.json()["items"]) == 2

    models_resp = client.get("/api/stats/models")
    assert models_resp.status_code == 200
    assert models_resp.json()["items"][0]["model"] == "MySQL Model"

    summary_resp = client.get("/api/stats/summary")
    assert summary_resp.status_code == 200
    assert summary_resp.json()["total"] == 2

    filter_reasons_resp = client.get("/api/stats/filter-reasons")
    assert filter_reasons_resp.status_code == 200
    assert filter_reasons_resp.json()["items"][0]["name"] == "安全间隔不足"

    by_farmer_resp = client.get("/api/stats/by-farmer")
    assert by_farmer_resp.status_code == 200
    assert by_farmer_resp.json()["items"][0]["farmer_id"] == "FMYSQL"

    latest_event = app_module._latest_case_event_by_trace("trace-target")
    assert latest_event["event_id"] == "evt-target"
