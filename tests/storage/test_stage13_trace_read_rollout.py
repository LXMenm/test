from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

import app as app_module
import trace_store


class _InMemoryTraceMysqlRepo:
    def __init__(self, initial_events: dict[str, list[dict[str, Any]]] | None = None):
        self._events = {
            trace_id: [dict(event) for event in events]
            for trace_id, events in (initial_events or {}).items()
        }

    def append_trace_event_mysql(self, trace_id: str, event: dict[str, Any]) -> dict[str, Any]:
        payload = dict(event)
        payload["trace_id"] = trace_id
        items = self._events.setdefault(trace_id, [])
        items.append(payload)
        items.sort(key=lambda item: (int(item.get("seq") or 0), str(item.get("ts") or "")))
        return dict(payload)

    def emit_trace_event_mysql(self, trace_id: str, event: dict[str, Any]) -> dict[str, Any]:
        return self.append_trace_event_mysql(trace_id, event)

    def list_trace_events_mysql(self, trace_id: str) -> list[dict[str, Any]]:
        return [dict(event) for event in self._events.get(trace_id, [])]


def _trace_event(seq: int, *, node: str, status: str, ts: str, message: str, trace_id: str) -> dict[str, Any]:
    return {
        "trace_id": trace_id,
        "seq": seq,
        "node": node,
        "status": status,
        "message": message,
        "ts": ts,
        "payload": {},
    }


def _install_trace_repo(monkeypatch, tmp_path: Path, repo: _InMemoryTraceMysqlRepo, *, mode: str = "mysql") -> None:
    events_dir = tmp_path / ".cache" / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(trace_store, "_EVENTS_DIR", str(events_dir))
    monkeypatch.setattr(trace_store, "_TRACE_PATH", str(events_dir / "trace_events.jsonl"))
    monkeypatch.setattr(trace_store, "TRACE_STORE_MODE", mode)
    monkeypatch.setattr(trace_store, "_append_trace_event_mysql", repo.append_trace_event_mysql)
    monkeypatch.setattr(trace_store, "_emit_trace_event_mysql", repo.emit_trace_event_mysql)
    monkeypatch.setattr(trace_store, "_list_trace_events_mysql", repo.list_trace_events_mysql)
    trace_store._SEQ.clear()
    trace_store._SUBSCRIBERS.clear()



def test_trace_dual_baseline_keeps_file_history_readable(monkeypatch, tmp_path: Path) -> None:
    repo = _InMemoryTraceMysqlRepo()
    _install_trace_repo(monkeypatch, tmp_path, repo, mode="dual")
    client = TestClient(app_module.app)

    trace_id = "trace-dual-history"
    history_event = _trace_event(
        1,
        node="Final",
        status="end",
        ts="2026-03-20T10:00:00Z",
        message="dual done",
        trace_id=trace_id,
    )
    trace_store.emit_trace_event(trace_id, history_event)

    trace_resp = client.get(f"/api/traces/{trace_id}")
    assert trace_resp.status_code == 200
    assert trace_resp.json()["events"][0]["message"] == "dual done"



def test_trace_mysql_history_stream_and_seq_continuation(monkeypatch, tmp_path: Path) -> None:
    trace_id = "trace-mysql-history"
    repo = _InMemoryTraceMysqlRepo(
        {
            trace_id: [
                _trace_event(1, node="ParseInput", status="start", ts="2026-03-20T10:00:00Z", message="start", trace_id=trace_id),
                _trace_event(2, node="DiagnosisAgent", status="end", ts="2026-03-20T10:00:01Z", message="diagnosed", trace_id=trace_id),
                _trace_event(3, node="Final", status="end", ts="2026-03-20T10:00:02Z", message="done", trace_id=trace_id),
            ]
        }
    )
    _install_trace_repo(monkeypatch, tmp_path, repo, mode="mysql")
    client = TestClient(app_module.app)

    trace_resp = client.get(f"/api/traces/{trace_id}")
    assert trace_resp.status_code == 200
    assert [event["seq"] for event in trace_resp.json()["events"]] == [1, 2, 3]

    with client.stream("GET", f"/api/traces/{trace_id}/stream") as response:
        payload = b"".join(response.iter_raw())
    text = payload.decode("utf-8")
    assert '"seq": 1' in text
    assert '"seq": 3' in text
    assert '"node": "Final"' in text

    emitted = trace_store.emit_trace_event(
        trace_id,
        {"node": "ConfirmRound", "status": "end", "message": "confirm appended", "ts": "2026-03-20T10:00:03Z"},
    )
    assert emitted["seq"] == 4

    persisted_events = trace_store.list_trace_events(trace_id)
    assert [event["seq"] for event in persisted_events] == [1, 2, 3, 4]
    assert persisted_events[-1]["message"] == "confirm appended"
