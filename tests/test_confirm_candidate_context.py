from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as app_module
import event_store
import trace_store


def _setup_event_dirs(monkeypatch, tmp_path: Path) -> None:
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
    image_path = upload_dir / image_id
    image_path.write_bytes(b"fake-jpeg-content")
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
        "final_confidence": 0.82,
        "final_source": "fusion",
        "image_confidence": 0.76,
        "text_confidence": 0.82,
        "image_result": {
            "disease": "早疫病",
            "confidence": 0.76,
            "confidence_pct": 76.0,
            "top3": [
                {"disease": "早疫病", "prob": 0.76, "prob_pct": 76.0},
                {"disease": "晚疫病", "prob": 0.18, "prob_pct": 18.0},
                {"disease": "灰霉病", "prob": 0.06, "prob_pct": 6.0},
            ],
        },
        "text_top3": [
            ["早疫病", 0.82],
            ["晚疫病", 0.11],
            ["灰霉病", 0.07],
        ],
        "fusion_top3": [
            ["早疫病", 0.82],
            ["晚疫病", 0.12],
            ["灰霉病", 0.06],
        ],
        "diagnosis_evidence": {
            "final_disease": "早疫病",
            "final_confidence": 0.82,
            "text_top3": [
                ["早疫病", 0.82],
                ["晚疫病", 0.11],
                ["灰霉病", 0.07],
            ],
            "fusion_top3": [
                ["早疫病", 0.82],
                ["晚疫病", 0.12],
                ["灰霉病", 0.06],
            ],
        },
        "modality_conflict_flag": False,
        "model_display_name": "ResNet50 Tomato v1",
        "model_backend": "torch",
        "resolved_model_path": "/models/resnet50.pt",
        "meta": {
            "model_id": "resnet50",
            "model_display_name": "ResNet50 Tomato v1",
            "model_backend": "torch",
            "resolved_model_path": "/models/resnet50.pt",
            "model_fallback_reason": [],
        },
        "status": "waiting_for_confirmation",
    }
    event_store.append_event(app_module.serialize_final_response(previous_event))
    trace_store.append_trace_event(
        trace_id,
        {
            "ts": "2026-03-19T00:00:00Z",
            "agent": "diagnosis",
            "outputs": {"symptoms": ["叶片黄化"]},
        },
    )


def _install_stub_agents(monkeypatch):
    calls = {"diagnosis": 0}

    def _supervisor(state):
        if not (state.get("final_disease") or state.get("disease_type")):
            state["next_action"] = "diagnosis"
        elif not state.get("kb_snapshot"):
            state["next_action"] = "kb_retrieval"
        elif not state.get("treatment_plan") or not state.get("prevention_advice"):
            state["next_action"] = "treatment"
        elif state.get("verification_result") is None:
            state["next_action"] = "verification"
        else:
            state["next_action"] = "end"
        return state

    def _diagnosis(state):
        calls["diagnosis"] += 1
        flags = dict(state.get("personalization_flags") or {})
        flags["need_confirm"] = False
        state["personalization_flags"] = flags
        state["final_disease"] = "补充诊断病害"
        state["disease_type"] = "补充诊断病害"
        state["final_confidence"] = 0.64
        state["disease_confidence"] = 0.64
        state["final_source"] = "fusion"
        state["image_confidence"] = 0.61
        state["text_confidence"] = 0.64
        state["text_top3"] = [("补充诊断病害", 0.64), ("晚疫病", 0.22), ("灰霉病", 0.14)]
        state["fusion_top3"] = [("补充诊断病害", 0.64), ("晚疫病", 0.22), ("灰霉病", 0.14)]
        state["diagnosis_evidence"] = {"final_confidence": 0.64}
        state["modality_conflict_flag"] = False
        state["image_diagnosis"] = {
            "top1": {"disease": "补充诊断病害", "confidence": 0.61},
            "top3": [("补充诊断病害", 0.61), ("晚疫病", 0.26), ("灰霉病", 0.13)],
        }
        state["diagnosis_model_meta"] = {
            "model_id": "confirm-model",
            "model_display_name": "Confirm Model",
            "backend": "mock",
            "resolved_model_path": "/models/confirm.pt",
            "model_fallback_reason": [],
        }
        return state

    def _kb_retrieval(state):
        state["kb_snapshot"] = {"source": "test-kb"}
        return state

    def _treatment(state):
        flags = dict(state.get("personalization_flags") or {})
        flags["selected_branch"] = "FAMILY"
        state["personalization_flags"] = flags
        state["treatment_plan"] = "建议隔离病株并进行针对性用药"
        state["prevention_advice"] = "加强通风与田间卫生"
        return state

    def _verification(state):
        state["verification_result"] = {"passed": True, "risk_level": "low", "issues": []}
        state["verification_passed"] = True
        state["verification_risk_level"] = "low"
        state["verification_issues"] = []
        state["verification_summary"] = "通过"
        return state

    monkeypatch.setattr(app_module, "supervisor_agent", _supervisor)
    monkeypatch.setattr(app_module, "diagnosis_agent", _diagnosis)
    monkeypatch.setattr(app_module, "kb_retrieval_agent", _kb_retrieval)
    monkeypatch.setattr(app_module, "treatment_agent", _treatment)
    monkeypatch.setattr(app_module, "verification_agent", _verification)
    return calls


def _post_confirm(client: TestClient, *, trace_id: str, image_id: str, choice: str) -> dict:
    response = client.post(
        "/api/diagnose-confirm",
        json={
            "trace_id": trace_id,
            "previous_trace_id": trace_id,
            "image_id": image_id,
            "crop_type": "番茄",
            "symptoms": ["叶片黄化"],
            "choice": choice,
        },
    )
    response.raise_for_status()
    return response.json()


def test_confirm_top1_candidate_inherits_previous_context(monkeypatch, tmp_path):
    _setup_event_dirs(monkeypatch, tmp_path)
    upload_dir = _seed_upload(tmp_path, "confirm-top1.jpg")
    monkeypatch.setattr(app_module, "UPLOAD_DIR", upload_dir)
    _seed_previous_case("trace-top1", "confirm-top1.jpg")
    calls = _install_stub_agents(monkeypatch)

    client = TestClient(app_module.app)
    body = _post_confirm(client, trace_id="trace-top1", image_id="confirm-top1.jpg", choice="早疫病")

    assert calls["diagnosis"] == 0
    assert body["final_confidence"] == pytest.approx(0.82)
    assert body["final_source"] == "user_confirmed_candidate"
    assert body["model_display_name"] == "ResNet50 Tomato v1"
    assert body["image_result"]["top3"][0]["disease"] == "早疫病"
    assert body["selected_branch"] == "FAMILY"


def test_confirm_non_top1_candidate_uses_candidate_probability(monkeypatch, tmp_path):
    _setup_event_dirs(monkeypatch, tmp_path)
    upload_dir = _seed_upload(tmp_path, "confirm-top3.jpg")
    monkeypatch.setattr(app_module, "UPLOAD_DIR", upload_dir)
    _seed_previous_case("trace-top3", "confirm-top3.jpg")
    _install_stub_agents(monkeypatch)

    client = TestClient(app_module.app)
    body = _post_confirm(client, trace_id="trace-top3", image_id="confirm-top3.jpg", choice="晚疫病")

    assert body["final_confidence"] == pytest.approx(0.12)
    assert body["final_confidence"] > 0
    assert body["final_source"] == "user_confirmed_candidate"


def test_confirm_other_keeps_original_rediagnosis_branch(monkeypatch, tmp_path):
    _setup_event_dirs(monkeypatch, tmp_path)
    upload_dir = _seed_upload(tmp_path, "confirm-other.jpg")
    monkeypatch.setattr(app_module, "UPLOAD_DIR", upload_dir)
    _seed_previous_case("trace-other", "confirm-other.jpg")
    calls = _install_stub_agents(monkeypatch)

    client = TestClient(app_module.app)
    body = _post_confirm(client, trace_id="trace-other", image_id="confirm-other.jpg", choice="other")

    assert calls["diagnosis"] == 1
    assert body["final_disease"] == "补充诊断病害"
    assert body["final_confidence"] == pytest.approx(0.64)
    assert body["final_source"] == "fusion"
