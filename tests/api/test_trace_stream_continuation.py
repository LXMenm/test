from __future__ import annotations

from fastapi.testclient import TestClient

import app as app_module


class _AsyncQueue:
    def __init__(self, items):
        self._items = list(items)

    async def get(self):
        if not self._items:
            raise RuntimeError("queue exhausted")
        return self._items.pop(0)


def test_trace_api_returns_second_round_confirm_input_under_same_trace(monkeypatch):
    trace_id = "trace-same"
    events = [
        {"trace_id": trace_id, "node": "AwaitUserConfirmation", "status": "end", "seq": 1},
        {"trace_id": trace_id, "agent": "confirm_input", "step": "confirm_input", "seq": 2},
        {"trace_id": trace_id, "node": "Final", "status": "end", "seq": 3},
    ]
    monkeypatch.setattr(app_module, "list_trace_events", lambda _trace_id: list(events) if _trace_id == trace_id else [])
    client = TestClient(app_module.app)

    resp = client.get(f"/api/traces/{trace_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["trace_id"] == trace_id
    assert [evt.get("seq") for evt in body["events"]] == [1, 2, 3]
    assert any((evt.get("agent") or "") == "confirm_input" for evt in body["events"])


def test_trace_stream_does_not_close_on_await_user_confirmation(monkeypatch):
    trace_id = "trace-stream"
    history = [
        {"trace_id": trace_id, "node": "AwaitUserConfirmation", "status": "end", "seq": 1, "ts": "t1"},
    ]
    queued = _AsyncQueue(
        [
            {"trace_id": trace_id, "agent": "confirm_input", "step": "confirm_input", "seq": 2, "ts": "t2"},
            {"trace_id": trace_id, "node": "Final", "status": "end", "seq": 3, "ts": "t3"},
        ]
    )

    monkeypatch.setattr(app_module, "list_trace_events", lambda _trace_id: list(history) if _trace_id == trace_id else [])
    monkeypatch.setattr(app_module, "subscribe_trace", lambda _trace_id: queued)
    monkeypatch.setattr(app_module, "unsubscribe_trace", lambda *_args, **_kwargs: None)
    client = TestClient(app_module.app)

    with client.stream("GET", f"/api/traces/{trace_id}/stream") as resp:
        assert resp.status_code == 200
        chunks = list(resp.iter_text())
    joined = "".join(chunks)
    assert "AwaitUserConfirmation" in joined
    assert "confirm_input" in joined
    assert '"node": "Final"' in joined


def test_trace_panel_stage_sequence_start_continue_wait_confirm_complete(monkeypatch):
    trace_id = "trace-seq"
    events = [
        {"trace_id": trace_id, "node": "PrecheckUploadInit", "status": "end", "seq": 1},
        {"trace_id": trace_id, "node": "ContinueFromPrecheck", "status": "start", "seq": 2},
        {"trace_id": trace_id, "node": "AwaitUserConfirmation", "status": "end", "seq": 3},
        {"trace_id": trace_id, "agent": "confirm_input", "step": "confirm_input", "seq": 4},
        {"trace_id": trace_id, "node": "Final", "status": "end", "seq": 5},
    ]
    monkeypatch.setattr(app_module, "list_trace_events", lambda _trace_id: list(events) if _trace_id == trace_id else [])
    client = TestClient(app_module.app)

    resp = client.get(f"/api/traces/{trace_id}")
    assert resp.status_code == 200
    returned = resp.json()["events"]
    assert [evt.get("seq") for evt in returned] == [1, 2, 3, 4, 5]
    assert returned[2]["node"] == "AwaitUserConfirmation"
    assert returned[3]["agent"] == "confirm_input"
    assert returned[4]["node"] == "Final"
