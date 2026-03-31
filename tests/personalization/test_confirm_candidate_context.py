from __future__ import annotations

from types import SimpleNamespace
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
        "status": "waiting_for_supplement",
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


class _DummyImageEngine:
    def diagnose_from_image(self, _):
        return "早疫病", 0.93, {"早疫病": 0.93, "晚疫病": 0.07}

    def diagnose_from_symptoms(self, **kwargs):
        return "早疫病", 0.75, "rule"

    def _get_disease_description(self, disease_type, symptoms):
        return f"{disease_type} - {','.join(symptoms or [])}"


class _StaticGraph:
    def __init__(self, final_state):
        self.final_state = final_state

    def invoke(self, state, config=None):
        merged = dict(state)
        merged.update(self.final_state)
        return merged


def _post_diagnose_image(client: TestClient) -> dict:
    response = client.post(
        "/api/diagnose-image",
        files={"file": ("case.jpg", b"fake-jpeg-content", "image/jpeg")},
        data={"crop_type": "番茄", "symptoms": "叶片黄化"},
    )
    response.raise_for_status()
    return response.json()


def _setup_diagnose_image_stubs(monkeypatch, final_state: dict) -> None:
    monkeypatch.setattr(app_module, "Image", SimpleNamespace(open=lambda *_args, **_kwargs: SimpleNamespace(verify=lambda: None)))
    monkeypatch.setattr(app_module, "resolve_model", lambda model_id, allow_torch=False: (
        SimpleNamespace(model_id="mock-model", display_name="Mock Model", backend="mock", model_path="/models/mock.bin"),
        [],
    ))
    monkeypatch.setattr(app_module, "get_diagnosis_engine", lambda **kwargs: _DummyImageEngine())
    monkeypatch.setattr(app_module, "build_graph", lambda: _StaticGraph(final_state))


def _install_recommend_expert_review_agents(monkeypatch):
    calls = {"diagnosis": 0}

    def _supervisor(state):
        if not (state.get("final_disease") or state.get("disease_type")):
            state["next_action"] = "diagnosis"
        elif (state.get("personalization_flags") or {}).get("need_confirm"):
            state["next_action"] = "manual_review"
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
        flags["need_confirm"] = True
        state["personalization_flags"] = flags
        state["final_disease"] = "疑似晚疫病"
        state["disease_type"] = "疑似晚疫病"
        state["final_confidence"] = 0.41
        state["disease_confidence"] = 0.41
        state["final_source"] = "fusion"
        state["image_confidence"] = 0.38
        state["text_confidence"] = 0.41
        state["text_top3"] = [("疑似晚疫病", 0.41), ("早疫病", 0.35), ("灰霉病", 0.24)]
        state["fusion_top3"] = [("疑似晚疫病", 0.41), ("早疫病", 0.35), ("灰霉病", 0.24)]
        state["diagnosis_evidence"] = {"final_confidence": 0.41}
        state["modality_conflict_flag"] = True
        state["image_diagnosis"] = {
            "top1": {"disease": "疑似晚疫病", "confidence": 0.38},
            "top3": [("疑似晚疫病", 0.38), ("早疫病", 0.34), ("灰霉病", 0.28)],
        }
        state["diagnosis_model_meta"] = {
            "model_id": "supplement-model",
            "model_display_name": "Supplement Model",
            "backend": "mock",
            "resolved_model_path": "/models/supplement.bin",
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
        state["treatment_plan"] = "保守处理并持续观察"
        state["prevention_advice"] = "加强通风，避免高湿"
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


def _post_confirm(
    client: TestClient,
    *,
    trace_id: str,
    image_id: str,
    choice: str | None = None,
    final_decision: str | None = None,
) -> dict:
    payload = {
        "trace_id": trace_id,
        "previous_trace_id": trace_id,
        "image_id": image_id,
        "crop_type": "番茄",
        "symptoms": ["叶片黄化"],
    }
    if choice is not None:
        payload["choice"] = choice
    if final_decision is not None:
        payload["final_decision"] = final_decision
    response = client.post(
        "/api/diagnose-confirm",
        json=payload,
    )
    response.raise_for_status()
    return response.json()


def test_initial_high_confidence_completes_without_expert_review(monkeypatch, tmp_path):
    _setup_event_dirs(monkeypatch, tmp_path)
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(app_module, "UPLOAD_DIR", upload_dir)
    _setup_diagnose_image_stubs(
        monkeypatch,
        {
            "final_disease": "早疫病",
            "final_confidence": 0.93,
            "final_source": "fusion",
            "diagnosis_model_meta": {
                "model_id": "mock-model",
                "model_display_name": "Mock Model",
                "backend": "mock",
                "resolved_model_path": "/models/mock.bin",
                "model_fallback_reason": [],
            },
            "personalization_flags": {"need_confirm": False},
            "treatment_plan": "常规处理方案",
            "prevention_advice": "加强通风与清园",
            "image_confidence": 0.93,
            "text_top3": [],
            "fusion_top3": [("早疫病", 0.93), ("晚疫病", 0.07)],
        },
    )

    client = TestClient(app_module.app)
    body = _post_diagnose_image(client)

    assert body["status"] == "completed"
    assert body["expert_review_recommended"] is False
    assert body["expert_review_selected"] is False
    assert body["expert_review_status"] == "NONE"


def test_initial_low_confidence_enters_waiting_for_supplement(monkeypatch, tmp_path):
    _setup_event_dirs(monkeypatch, tmp_path)
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(app_module, "UPLOAD_DIR", upload_dir)
    _setup_diagnose_image_stubs(
        monkeypatch,
        {
            "final_disease": "疑似晚疫病",
            "final_confidence": 0.46,
            "final_source": "fusion",
            "diagnosis_evidence": {"weights": {"image": 1.0, "text": 0.0, "prior": 0.0}},
            "diagnosis_model_meta": {
                "model_id": "mock-model",
                "model_display_name": "Mock Model",
                "backend": "mock",
                "resolved_model_path": "/models/mock.bin",
                "model_fallback_reason": [],
            },
            "personalization_flags": {
                "need_confirm": True,
                "follow_up_questions": ["请补充病斑边缘形态"],
                "fallback_reason": ["low_confidence", "image_text_conflict"],
            },
            "image_confidence": 0.46,
            "fusion_top3": [("疑似晚疫病", 0.46), ("早疫病", 0.33), ("灰霉病", 0.21)],
        },
    )

    client = TestClient(app_module.app)
    body = _post_diagnose_image(client)

    assert body["status"] == "waiting_for_supplement"
    assert body["expert_review_status"] == "NONE"
    assert body["need_confirm"] is True
    assert body["confirm_reasons"] == ["low_confidence", "image_text_conflict"]
    assert body.get("fallback_reason") is None
    assert body["fusion_mode"] == "gated_image_only"


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
    assert body["status"] == "completed"
    assert body["expert_review_recommended"] is False
    assert body["previous_trace_id"] == "trace-other"
    assert body["confirm_round_parent_trace_id"] == "trace-other"

    confirm_input_events = [
        event for event in body["events"]
        if event.get("agent") == "confirm_input"
    ]
    assert confirm_input_events
    confirm_inputs = confirm_input_events[-1]["inputs"]
    assert confirm_inputs["previous_trace_id"] == "trace-other"
    assert confirm_inputs["confirm_round_parent_trace_id"] == "trace-other"


def test_supplement_low_confidence_requires_expert_decision_without_additional_supplement(monkeypatch, tmp_path):
    _setup_event_dirs(monkeypatch, tmp_path)
    upload_dir = _seed_upload(tmp_path, "supplement-expert-decision.jpg")
    monkeypatch.setattr(app_module, "UPLOAD_DIR", upload_dir)
    _seed_previous_case("trace-expert-decision", "supplement-expert-decision.jpg")
    _install_recommend_expert_review_agents(monkeypatch)

    client = TestClient(app_module.app)
    response = client.post(
        "/api/diagnose-confirm",
        json={
            "trace_id": "trace-expert-decision",
            "previous_trace_id": "trace-expert-decision",
            "image_id": "supplement-expert-decision.jpg",
            "crop_type": "番茄",
            "symptoms": ["病斑扩大"],
            "choice": "other",
        },
    )
    response.raise_for_status()
    body = response.json()

    assert body["status"] == "waiting_for_expert_decision"
    assert body["expert_review_recommended"] is True
    assert body["expert_review_selected"] is False
    assert body["expert_review_status"] == "NONE"
    assert body["need_confirm"] is False
    assert body["expert_review_actions"] == ["use_current_result", "request_expert_review"]
    assert body["treatment_available"] is False
    assert body.get("treatment") is not None
    assert (body.get("treatment") or {}).get("plan") in (None, "")


def test_supplement_low_confidence_decline_expert_review_returns_completed_with_treatment(monkeypatch, tmp_path):
    _setup_event_dirs(monkeypatch, tmp_path)
    upload_dir = _seed_upload(tmp_path, "supplement-decline.jpg")
    monkeypatch.setattr(app_module, "UPLOAD_DIR", upload_dir)
    _seed_previous_case("trace-decline", "supplement-decline.jpg")
    _install_recommend_expert_review_agents(monkeypatch)

    client = TestClient(app_module.app)
    pre_response = client.post(
        "/api/diagnose-confirm",
        json={
            "trace_id": "trace-decline",
            "previous_trace_id": "trace-decline",
            "image_id": "supplement-decline.jpg",
            "crop_type": "番茄",
            "symptoms": ["病斑扩大"],
            "choice": "other",
        },
    )
    pre_response.raise_for_status()
    assert pre_response.json()["status"] == "waiting_for_expert_decision"

    response = client.post(
        "/api/diagnose-confirm",
        json={
            "trace_id": "trace-decline",
            "previous_trace_id": "trace-decline",
            "image_id": "supplement-decline.jpg",
            "crop_type": "番茄",
            "symptoms": ["病斑扩大"],
            "final_decision": "use_current_result",
        },
    )
    response.raise_for_status()
    body = response.json()

    assert body["status"] == "completed"
    assert body["expert_review_recommended"] is True
    assert body["expert_review_selected"] is False
    assert body["expert_review_status"] == "DECLINED"
    assert body["expert_review_actions"] == ["use_current_result", "request_expert_review"]
    assert body["treatment_available"] is True
    assert (body.get("treatment") or {}).get("plan")
    # 前端应隐藏“是否专家复核”二选一区（仅 waiting_for_expert_decision 才展示）
    should_show_expert_review_decision = (
        body["status"] == "waiting_for_expert_decision"
        and body["expert_review_recommended"] is True
        and body["expert_review_status"] != "PENDING"
    )
    assert should_show_expert_review_decision is False


def test_supplement_low_confidence_accept_expert_review_returns_pending(monkeypatch, tmp_path):
    _setup_event_dirs(monkeypatch, tmp_path)
    upload_dir = _seed_upload(tmp_path, "supplement-accept.jpg")
    monkeypatch.setattr(app_module, "UPLOAD_DIR", upload_dir)
    _seed_previous_case("trace-accept", "supplement-accept.jpg")
    _install_recommend_expert_review_agents(monkeypatch)

    client = TestClient(app_module.app)
    pre_response = client.post(
        "/api/diagnose-confirm",
        json={
            "trace_id": "trace-accept",
            "previous_trace_id": "trace-accept",
            "image_id": "supplement-accept.jpg",
            "crop_type": "番茄",
            "symptoms": ["病斑扩大"],
            "choice": "other",
        },
    )
    pre_response.raise_for_status()
    assert pre_response.json()["status"] == "waiting_for_expert_decision"

    response = client.post(
        "/api/diagnose-confirm",
        json={
            "trace_id": "trace-accept",
            "previous_trace_id": "trace-accept",
            "image_id": "supplement-accept.jpg",
            "crop_type": "番茄",
            "symptoms": ["病斑扩大"],
            "final_decision": "request_expert_review",
        },
    )
    response.raise_for_status()
    body = response.json()

    assert body["status"] == "pending_expert_review"
    assert body["expert_review_recommended"] is True
    assert body["expert_review_selected"] is True
    assert body["expert_review_status"] == "PENDING"
    assert body["expert_review_actions"] == ["use_current_result", "request_expert_review"]
    assert body["treatment_available"] is False
    assert body.get("treatment") is None
    # 前端应进入“待专家复核”态：不再显示二选一区且隐藏治疗方案区块。
    should_show_expert_review_decision = (
        body["status"] == "waiting_for_expert_decision"
        and body["expert_review_recommended"] is True
        and body["expert_review_status"] != "PENDING"
    )
    should_hide_treatment = (
        body["status"] == "pending_expert_review"
        or should_show_expert_review_decision
        or body["status"] == "waiting_for_supplement"
    )
    assert should_show_expert_review_decision is False
    assert should_hide_treatment is True


def test_waiting_for_expert_decision_rejects_choice_confirmation(monkeypatch, tmp_path):
    _setup_event_dirs(monkeypatch, tmp_path)
    upload_dir = _seed_upload(tmp_path, "supplement-choice-invalid.jpg")
    monkeypatch.setattr(app_module, "UPLOAD_DIR", upload_dir)
    _seed_previous_case("trace-choice-invalid", "supplement-choice-invalid.jpg")
    _install_recommend_expert_review_agents(monkeypatch)

    client = TestClient(app_module.app)
    pre_response = client.post(
        "/api/diagnose-confirm",
        json={
            "trace_id": "trace-choice-invalid",
            "previous_trace_id": "trace-choice-invalid",
            "image_id": "supplement-choice-invalid.jpg",
            "crop_type": "番茄",
            "symptoms": ["病斑扩大"],
            "choice": "other",
        },
    )
    pre_response.raise_for_status()
    assert pre_response.json()["status"] == "waiting_for_expert_decision"

    bad_response = client.post(
        "/api/diagnose-confirm",
        json={
            "trace_id": "trace-choice-invalid",
            "previous_trace_id": "trace-choice-invalid",
            "image_id": "supplement-choice-invalid.jpg",
            "crop_type": "番茄",
            "symptoms": ["病斑扩大"],
            "choice": "晚疫病",
        },
    )
    assert bad_response.status_code == 400
    assert "waiting_for_expert_decision" in str((bad_response.json() or {}).get("detail"))
