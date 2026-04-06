from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
import event_store
import trace_store
from state import create_initial_state


def _setup_event_dirs(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EVENT_STORE_MODE", "file")
    monkeypatch.setattr(event_store, "EVENT_STORE_MODE", "file")
    monkeypatch.setenv("TRACE_STORE_MODE", "file")
    monkeypatch.setattr(trace_store, "TRACE_STORE_MODE", "file")
    events_dir = tmp_path / ".cache" / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(event_store, "_EVENTS_DIR", str(events_dir))
    monkeypatch.setattr(event_store, "_EVENTS_PATH", str(events_dir / "diagnosis_events.jsonl"))
    monkeypatch.setattr(trace_store, "_EVENTS_DIR", str(events_dir))
    monkeypatch.setattr(trace_store, "_TRACE_PATH", str(events_dir / "trace_events.jsonl"))
    trace_store._SEQ.clear()


def _seed_upload(tmp_path: Path, image_id: str) -> Path:
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / image_id).write_bytes(b"fake-jpeg-content")
    return upload_dir


def _seed_previous_case(trace_id: str, image_id: str) -> None:
    previous_event = {
        "id": "case-prev",
        "ts": "2026-03-19T00:00:00Z",
        "trace_id": trace_id,
        "image_id": image_id,
        "image_url": f"/uploads/{image_id}",
        "final_disease": "早疫病",
        "need_confirm": True,
        "status": "waiting_for_supplement",
        "fusion_top3": [["早疫病", 0.82], ["晚疫病", 0.12]],
        "text_top3": [["早疫病", 0.8], ["晚疫病", 0.2]],
        "image_result": {
            "disease": "早疫病",
            "confidence": 0.7,
            "top3": [{"disease": "早疫病", "prob": 0.7}, {"disease": "晚疫病", "prob": 0.2}],
        },
        "diagnosis_evidence": {"fusion_top3": [["早疫病", 0.82], ["晚疫病", 0.12]]},
    }
    event_store.append_event(app_module.serialize_final_response(previous_event))
    trace_store.append_trace_event(
        trace_id,
        {"ts": "2026-03-19T00:00:00Z", "agent": "diagnosis", "outputs": {"symptoms": ["叶片黄化"], "fusion_top3": [["早疫病", 0.82]]}},
    )


class _EchoGraph:
    def invoke(self, state, config=None):
        out = dict(state)
        out["trace_id"] = state.get("trace_id")
        out["final_disease"] = out.get("final_disease") or out.get("selected_candidate") or "早疫病"
        out["disease_type"] = out["final_disease"]
        out["final_confidence"] = out.get("final_confidence") or 0.82
        out["disease_confidence"] = out["final_confidence"]
        out["final_source"] = out.get("final_source") or "fusion"
        out["kb_snapshot"] = out.get("kb_snapshot") or {"disease": out["final_disease"]}
        out["treatment_plan"] = out.get("treatment_plan") or "mock plan"
        out["prevention_advice"] = out.get("prevention_advice") or "mock prevention"
        out["verification_result"] = out.get("verification_result") or {"passed": True}
        out["verification_passed"] = True
        out["verification_risk_level"] = "low"
        out["verification_summary"] = "通过"
        out["next_action"] = "end"
        return out


def test_create_initial_state_uses_provided_trace_id():
    state = create_initial_state("test", trace_id="trace-fixed")
    assert state["trace_id"] == "trace-fixed"


def test_start_continue_reuses_same_trace_id(monkeypatch, tmp_path):
    class _KB:
        @staticmethod
        def normalize_symptoms(symptoms):
            return [str(item).strip() for item in (symptoms or []) if str(item).strip()]

        @staticmethod
        def has_effective_text_evidence(symptoms, **_kwargs):
            return bool(symptoms)

        @staticmethod
        def has_discriminative_text_evidence(_symptoms):
            return False

        @staticmethod
        def get_candidate_diseases_from_symptoms(_symptoms):
            return []

        @staticmethod
        def generate_text_follow_up_questions(_symptoms, text_probs=None):
            _ = text_probs
            return ["请补充关键症状"]

    _setup_event_dirs(monkeypatch, tmp_path)
    monkeypatch.setattr(app_module, "Image", type("PIL", (), {"open": staticmethod(lambda *_args, **_kwargs: type("X", (), {"verify": staticmethod(lambda: None)})())}))
    monkeypatch.setattr(app_module, "resolve_model", lambda *_args, **_kwargs: (type("M", (), {"model_id": "m", "display_name": "m", "backend": "mock", "model_path": "/tmp/m"})(), []))
    monkeypatch.setattr(app_module, "get_diagnosis_engine", lambda **_kwargs: type("E", (), {"diagnose_from_image": staticmethod(lambda *_: ("早疫病", 0.9, {"早疫病": 0.9})), "diagnose_from_symptoms": staticmethod(lambda **_: ("早疫病", 0.8, "rule")), "_get_disease_description": staticmethod(lambda *_: "desc")})())
    monkeypatch.setattr(app_module, "build_graph", lambda: _EchoGraph())
    monkeypatch.setattr(app_module, "get_kb_manager", lambda: _KB())
    monkeypatch.setattr(app_module, "UPLOAD_DIR", tmp_path / "uploads")
    (tmp_path / "uploads").mkdir(parents=True, exist_ok=True)

    client = TestClient(app_module.app)
    start_resp = client.post(
        "/api/diagnose-image/start",
        files={"file": ("img.jpg", b"fake-jpeg-content", "image/jpeg")},
        data={"crop_type": "番茄", "symptoms": "叶片黄化"},
    )
    start_resp.raise_for_status()
    start_body = start_resp.json()
    trace_id = start_body["trace_id"]
    image_id = start_body["image_id"]

    continue_resp = client.post(
        "/api/diagnose-image/continue",
        json={"trace_id": trace_id, "image_id": image_id, "crop_type": "番茄", "symptoms": "叶片黄化"},
    )
    continue_resp.raise_for_status()
    continue_body = continue_resp.json()
    assert continue_body["trace_id"] == trace_id
    assert continue_body["entrypoint"] == "diagnose_image_continue"
    assert continue_body["precheck_semantics_exposed"] is False
    events = event_store.list_events(limit=20)
    chain_events = [evt for evt in events if evt.get("trace_id") == trace_id]
    assert chain_events
    latest = chain_events[-1]
    assert latest.get("result_stage") == "diagnosis_completed"
    assert latest.get("precheck_semantics_exposed") is False


def test_confirm_other_and_choice_reuse_same_trace_id(monkeypatch, tmp_path):
    _setup_event_dirs(monkeypatch, tmp_path)
    upload_dir = _seed_upload(tmp_path, "chain.jpg")
    monkeypatch.setattr(app_module, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(app_module, "build_graph", lambda: _EchoGraph())
    trace_id = "trace-chain-1"
    _seed_previous_case(trace_id, "chain.jpg")
    client = TestClient(app_module.app)

    other_resp = client.post(
        "/api/diagnose-confirm",
        json={
            "trace_id": trace_id,
            "previous_trace_id": trace_id,
            "image_id": "chain.jpg",
            "crop_type": "番茄",
            "symptoms": ["病斑扩大"],
            "choice": "other",
        },
    )
    other_resp.raise_for_status()
    other_body = other_resp.json()
    assert other_body["trace_id"] == trace_id

    confirm_resp = client.post(
        "/api/diagnose-confirm",
        json={
            "trace_id": trace_id,
            "previous_trace_id": trace_id,
            "image_id": "chain.jpg",
            "crop_type": "番茄",
            "symptoms": ["病斑扩大"],
            "choice": "早疫病",
        },
    )
    confirm_resp.raise_for_status()
    confirm_body = confirm_resp.json()
    assert confirm_body["trace_id"] == trace_id
