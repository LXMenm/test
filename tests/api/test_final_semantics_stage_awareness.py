from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app as app_module


def _prepare_common_mocks(monkeypatch, tmp_path: Path, *, need_confirm: bool) -> None:
    saved = tmp_path / "diag.jpg"
    saved.write_bytes(b"fake")

    async def _fake_save_uploaded_image(*_args, **_kwargs):
        return saved.name, saved

    class _Graph:
        def invoke(self, initial_state, config=None):
            _ = config
            out = dict(initial_state)
            out.update(
                {
                    "trace_id": initial_state.get("trace_id"),
                    "final_disease": "晚疫病",
                    "final_confidence": 0.62 if need_confirm else 0.91,
                    "final_source": "fusion",
                    "fusion_top3": [("晚疫病", 0.62), ("叶霉病", 0.38)] if need_confirm else [("晚疫病", 0.91), ("叶霉病", 0.09)],
                    "text_top3": [("晚疫病", 0.6), ("叶霉病", 0.4)] if need_confirm else [("晚疫病", 0.9), ("叶霉病", 0.1)],
                    "diagnosis_evidence": {"fusion_top3": [("晚疫病", 0.62), ("叶霉病", 0.38)]},
                    "image_result": {"disease": "晚疫病", "confidence": 0.72, "top3": [{"disease": "晚疫病", "prob": 0.72}]},
                    "personalization_flags": {"need_confirm": need_confirm, "fallback_reason": ["low_confidence"] if need_confirm else []},
                    "follow_up_questions": ["请补充病斑边缘形态"] if need_confirm else [],
                    "profile_follow_up_questions": [],
                    "diagnosis_follow_up_questions": [],
                    "verification_result": None,
                    "verification_passed": None,
                    "verification_risk_level": None,
                    "verification_issues": [],
                    "verification_summary": None,
                    "workflow_degraded": False,
                    "degraded_reason": None,
                    "debug_diagnosis": {},
                }
            )
            return out

    monkeypatch.setattr(app_module, "_save_uploaded_image", _fake_save_uploaded_image)
    monkeypatch.setattr(app_module, "emit_node_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(app_module, "emit_final_event_once", lambda *args, **kwargs: None)
    monkeypatch.setattr(app_module, "append_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app_module, "list_trace_events", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(app_module, "_resolve_profile_and_base", lambda *_args, **_kwargs: (None, None, None))
    monkeypatch.setattr(app_module, "build_personalization_context", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app_module, "build_personalization_flags", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(app_module, "_build_personalization_meta", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(app_module, "resolve_model", lambda *_args, **_kwargs: (SimpleNamespace(model_path="/tmp/mock.bin", backend="mock", model_id="mock", display_name="mock"), []))
    monkeypatch.setattr(app_module, "build_graph", lambda: _Graph())
    monkeypatch.setattr(app_module, "_build_degraded_treatment", lambda *_args, **_kwargs: (None, {}))


def test_need_confirm_response_is_marked_provisional_not_authoritative(monkeypatch, tmp_path):
    _prepare_common_mocks(monkeypatch, tmp_path, need_confirm=True)
    client = TestClient(app_module.app)

    resp = client.post(
        "/api/diagnose-image",
        files={"file": ("case.jpg", b"fake-jpeg-content", "image/jpeg")},
        data={"crop_type": "番茄"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "waiting_for_supplement"
    assert body["result_stage"] == "awaiting_confirmation"
    assert body["is_final_result"] is False
    assert body["final_result_authoritative"] is False


def test_waiting_stage_exposes_provisional_fields(monkeypatch, tmp_path):
    _prepare_common_mocks(monkeypatch, tmp_path, need_confirm=True)
    client = TestClient(app_module.app)

    body = client.post(
        "/api/diagnose-image",
        files={"file": ("case.jpg", b"fake-jpeg-content", "image/jpeg")},
        data={"crop_type": "番茄"},
    ).json()

    assert body["provisional_disease"] == "晚疫病"
    assert body["provisional_confidence"] == 0.62
    assert body["provisional_source"] == "fusion"
    assert body["current_top1"] == "晚疫病"


def test_completed_stage_keeps_final_semantics(monkeypatch, tmp_path):
    _prepare_common_mocks(monkeypatch, tmp_path, need_confirm=False)
    client = TestClient(app_module.app)

    body = client.post(
        "/api/diagnose-image",
        files={"file": ("case.jpg", b"fake-jpeg-content", "image/jpeg")},
        data={"crop_type": "番茄"},
    ).json()

    assert body["status"] == "completed"
    assert body["result_stage"] == "diagnosis_completed"
    assert body["is_final_result"] is True
    assert body["final_result_authoritative"] is True
    assert body["final_disease"] == "晚疫病"
    assert body["final_source"] == "fusion"
    assert "display_symptoms" in body
    assert "display_symptom_count" in body
    assert body["display_symptom_count"] == len(body["display_symptoms"])
    assert "final_status" in body
    assert "execution_allowed" in body
    assert "treatment_actionable" in body
    assert "treatment_reference_only" in body


def test_compat_final_fields_can_exist_but_stage_still_distinguishes_non_final(monkeypatch, tmp_path):
    _prepare_common_mocks(monkeypatch, tmp_path, need_confirm=True)
    client = TestClient(app_module.app)

    body = client.post(
        "/api/diagnose-image",
        files={"file": ("case.jpg", b"fake-jpeg-content", "image/jpeg")},
        data={"crop_type": "番茄"},
    ).json()

    assert "final_disease" not in body
    assert body["final_disease_compat"] == "晚疫病"
    assert body["compatibility_final_fields"] is True
    assert body["result_stage"] == "awaiting_confirmation"
    assert body["is_final_result"] is False


def test_non_final_statuses_share_same_canonical_downgrade_rules():
    cases = [
        ("waiting_for_supplement", True, "awaiting_confirmation"),
        ("waiting_for_expert_decision", False, "pending_expert_decision"),
        ("pending_expert_review", False, "pending_expert_review"),
    ]
    for status, need_confirm, expected_stage in cases:
        payload = {
            "status": status,
            "need_confirm": need_confirm,
            "final_disease": "晚疫病",
            "final_confidence": 0.62,
            "final_source": "fusion",
        }
        out = app_module._apply_result_semantics(payload)
        assert out["result_stage"] == expected_stage
        assert out["is_final_result"] is False
        assert out["final_result_authoritative"] is False
        assert out["provisional_disease"] == "晚疫病"
        assert out["final_disease_compat"] == "晚疫病"
        assert "final_disease" not in out
        assert "final_confidence" not in out
        assert "final_source" not in out


def _prepare_confirm_core_mocks(monkeypatch, tmp_path: Path, *, previous_status: str, previous_final_disease: str = "晚疫病"):
    image_id = "confirm.jpg"
    (tmp_path / image_id).write_bytes(b"fake-image")
    monkeypatch.setattr(app_module, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(app_module, "emit_node_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(app_module, "emit_final_event_once", lambda *args, **kwargs: None)
    monkeypatch.setattr(app_module, "list_trace_events", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(app_module, "_resolve_profile_and_base", lambda *_args, **_kwargs: (None, None, None))
    monkeypatch.setattr(app_module, "build_personalization_context", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app_module, "build_personalization_flags", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(app_module, "_build_personalization_meta", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(app_module, "_get_request_actor", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app_module, "_apply_farmer_scope", lambda _actor, farmer_id: farmer_id)
    monkeypatch.setattr(app_module, "merge_follow_up_questions", lambda old, new, active=True: (list(new), list(old)))
    monkeypatch.setattr(app_module, "build_confirm_explanation_v2", lambda **_kwargs: {})
    monkeypatch.setattr(app_module, "_derive_fusion_mode", lambda *_args, **_kwargs: "fusion")

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
            return []

    monkeypatch.setattr(app_module, "get_kb_manager", lambda: _KB())

    previous_event = {
        "trace_id": "trace-confirm",
        "status": previous_status,
        "image_id": image_id,
        "final_disease": previous_final_disease,
        "final_confidence": 0.66,
        "final_source": "fusion",
        "symptoms": ["发黄"],
        "image_result": {"disease": previous_final_disease, "confidence": 0.66, "top3": [("晚疫病", 0.66)]},
        "diagnosis_evidence": {"fusion_top3": [("晚疫病", 0.66)]},
        "fusion_top3": [("晚疫病", 0.66)],
        "text_top3": [("晚疫病", 0.6)],
    }
    monkeypatch.setattr(app_module, "_latest_case_event_by_trace", lambda *_args, **_kwargs: dict(previous_event))

    captured_events: list[dict] = []
    monkeypatch.setattr(app_module, "append_event", lambda evt: captured_events.append(dict(evt)))
    return image_id, captured_events


def test_diagnose_confirm_waiting_stage_hides_canonical_final_fields(monkeypatch, tmp_path):
    image_id, captured_events = _prepare_confirm_core_mocks(monkeypatch, tmp_path, previous_status="waiting_for_supplement")

    class _Graph:
        def invoke(self, state, config=None):
            _ = config
            out = dict(state)
            out.update(
                {
                    "trace_id": state.get("trace_id"),
                    "next_action": "await_user_confirmation",
                    "final_disease": "晚疫病",
                    "final_confidence": 0.63,
                    "final_source": "fusion",
                    "image_diagnosis": {"top1": {"disease": "晚疫病", "confidence": 0.7}, "top3": [("晚疫病", 0.7)]},
                    "image_result": {"disease": "晚疫病", "confidence": 0.7, "top3": [("晚疫病", 0.7)]},
                    "personalization_flags": {"need_confirm": True, "fallback_reason": ["low_confidence"], "follow_up_questions": []},
                    "fusion_top3": [("晚疫病", 0.63)],
                    "text_top3": [("晚疫病", 0.61)],
                    "diagnosis_evidence": {"fusion_top3": [("晚疫病", 0.63)]},
                    "supplement_mode": "text_only",
                }
            )
            return out

    monkeypatch.setattr(app_module, "build_graph", lambda: _Graph())
    client = TestClient(app_module.app)
    resp = client.post(
        "/api/diagnose-confirm",
        json={"trace_id": "trace-confirm", "image_id": image_id, "crop_type": "番茄", "choice": "other", "symptoms": ["发黄"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "waiting_for_supplement"
    assert body["result_stage"] == "awaiting_confirmation"
    assert "final_disease" not in body
    assert body["provisional_disease"] == "晚疫病"
    assert body["final_disease_compat"] == "晚疫病"
    assert captured_events
    persisted = captured_events[-1]
    assert persisted["status"] == "waiting_for_supplement"
    assert persisted["result_stage"] == "awaiting_confirmation"
    assert "final_disease" not in persisted


def test_diagnose_confirm_pending_expert_review_hides_canonical_final_fields(monkeypatch, tmp_path):
    image_id, captured_events = _prepare_confirm_core_mocks(monkeypatch, tmp_path, previous_status="waiting_for_expert_decision")
    monkeypatch.setattr(app_module, "build_graph", lambda: None)
    client = TestClient(app_module.app)
    resp = client.post(
        "/api/diagnose-confirm",
        json={
            "trace_id": "trace-confirm",
            "image_id": image_id,
            "crop_type": "番茄",
            "final_decision": "request_expert_review",
            "symptoms": ["发黄"],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending_expert_review"
    assert body["result_stage"] == "pending_expert_review"
    assert body["is_final_result"] is False
    assert "final_disease" not in body
    assert body["provisional_disease"] == "晚疫病"
    assert body["final_disease_compat"] == "晚疫病"
    assert captured_events
    persisted = captured_events[-1]
    assert persisted["status"] == "pending_expert_review"
    assert persisted["result_stage"] == "pending_expert_review"
    assert "final_disease" not in persisted


def test_display_symptoms_has_single_canonical_source_for_ui_count():
    payload = {
        "status": "waiting_for_supplement",
        "need_confirm": True,
        "final_disease": "晚疫病",
        "normalized_symptoms": [],
        "diagnosis_evidence": {"raw_symptoms": ["卷叶", "叶背白霉"], "normalized_symptoms": ["叶片卷曲", "叶背白霉"]},
        "symptom_evidence_profile": {"raw_tokens": ["卷叶"], "normalized_tokens": ["叶片卷曲"]},
    }
    out = app_module._apply_result_semantics(payload)
    assert out["display_symptoms"] == ["叶片卷曲"]
    assert out["display_symptom_count"] == 1
    assert out["normalized_symptoms"] == ["叶片卷曲"]


def test_display_symptoms_stays_stable_when_debug_evidence_changes():
    payload = {
        "status": "completed",
        "need_confirm": False,
        "final_disease": "晚疫病",
        "normalized_symptoms": ["叶片卷曲", "叶背白霉"],
        "diagnosis_evidence": {"raw_symptoms": ["卷叶"], "normalized_symptoms": ["叶片卷曲"]},
        "symptom_evidence_profile": {"raw_tokens": ["随机token"], "normalized_tokens": ["随机标准化token"]},
    }
    out = app_module._apply_result_semantics(payload)
    assert out["display_symptoms"] == ["叶片卷曲", "叶背白霉"]
    assert out["display_symptom_count"] == 2


def test_verification_failed_is_not_plain_completed_anymore():
    payload = {
        "status": "completed",
        "need_confirm": False,
        "final_disease": "晚疫病",
        "treatment_available": True,
        "verification_available": True,
        "verification_passed": False,
    }
    out = app_module._apply_result_semantics(payload)
    assert out["result_stage"] == "diagnosis_completed"
    assert out["status"] == "completed_verification_failed"
    assert out["final_status"] == "completed_verification_failed"
    assert len(out["status"]) <= 32
    assert out["execution_allowed"] is False
    assert out["treatment_actionable"] is False
    assert out["treatment_reference_only"] is True
    assert out["manual_review_required_before_execution"] is True


def test_verification_passed_keeps_completed_semantics_and_actionable_gate():
    payload = {
        "status": "completed",
        "need_confirm": False,
        "final_disease": "晚疫病",
        "treatment_available": True,
        "verification_available": True,
        "verification_passed": True,
    }
    out = app_module._apply_result_semantics(payload)
    assert out["status"] == "completed"
    assert out["final_status"] == "completed"
    assert out["execution_allowed"] is True
    assert out["treatment_actionable"] is True
    assert out["treatment_reference_only"] is False


def test_serialize_final_response_backfills_execution_gate_when_values_are_none():
    payload = {
        "status": "completed",
        "need_confirm": False,
        "final_disease": "晚疫病",
        "treatment_available": True,
        "verification_passed": True,
        "final_status": None,
        "execution_allowed": None,
        "treatment_actionable": None,
        "treatment_reference_only": None,
    }
    out = app_module.serialize_final_response(payload)
    assert out["final_status"] == "completed"
    assert out["execution_allowed"] is True
    assert out["treatment_actionable"] is True
    assert out["treatment_reference_only"] is False


def test_verification_failed_sets_reference_only_true_even_without_treatment_available():
    payload = {
        "status": "completed",
        "need_confirm": False,
        "verification_passed": False,
        "treatment_available": False,
    }
    out = app_module._apply_result_semantics(payload)
    assert out["status"] == "completed_verification_failed"
    assert out["final_status"] == "completed_verification_failed"
    assert out["execution_allowed"] is False
    assert out["treatment_actionable"] is False
    assert out["treatment_reference_only"] is True


def test_waiting_api_and_persist_payload_share_same_provisional_and_display_semantics(monkeypatch, tmp_path):
    _prepare_common_mocks(monkeypatch, tmp_path, need_confirm=True)
    captured_events: list[dict] = []
    monkeypatch.setattr(app_module, "append_event", lambda evt: captured_events.append(dict(evt)))

    class _GraphWithSymptoms:
        def invoke(self, initial_state, config=None):
            _ = config
            out = dict(initial_state)
            out.update(
                {
                    "trace_id": initial_state.get("trace_id"),
                    "final_disease": "晚疫病",
                    "final_confidence": 0.62,
                    "final_source": "fusion",
                    "image_result": {"disease": "晚疫病", "confidence": 0.72, "top3": [("晚疫病", 0.72)]},
                    "personalization_flags": {"need_confirm": True, "fallback_reason": ["low_confidence"]},
                    "diagnosis_evidence": {"raw_symptoms": ["卷叶"], "normalized_symptoms": ["叶片卷曲"]},
                    "symptom_evidence_profile": {"raw_tokens": ["卷叶"], "normalized_tokens": ["叶片卷曲"]},
                    "normalized_symptoms": ["叶片卷曲"],
                }
            )
            return out

    monkeypatch.setattr(app_module, "build_graph", lambda: _GraphWithSymptoms())
    client = TestClient(app_module.app)
    body = client.post(
        "/api/diagnose-image",
        files={"file": ("case.jpg", b"fake-jpeg-content", "image/jpeg")},
        data={"crop_type": "番茄"},
    ).json()

    assert captured_events
    persisted = captured_events[-1]
    assert body["result_stage"] == "awaiting_confirmation"
    assert persisted["result_stage"] == "awaiting_confirmation"
    assert "final_disease" not in body
    assert "final_disease" not in persisted
    assert body["provisional_disease"] == persisted["provisional_disease"] == "晚疫病"
    assert body["display_symptoms"] == persisted["display_symptoms"] == ["叶片卷曲"]
    assert body["display_symptom_count"] == persisted["display_symptom_count"] == 1
    for key in (
        "final_status",
        "execution_allowed",
        "treatment_actionable",
        "treatment_reference_only",
    ):
        assert key in body
        assert key in persisted


def test_confirm_choice_response_uses_single_display_symptoms_source(monkeypatch, tmp_path):
    image_id, _captured_events = _prepare_confirm_core_mocks(monkeypatch, tmp_path, previous_status="waiting_for_supplement")

    class _Graph:
        def invoke(self, state, config=None):
            _ = config
            out = dict(state)
            out.update(
                {
                    "trace_id": state.get("trace_id"),
                    "next_action": "end",
                    "final_disease": "晚疫病",
                    "final_confidence": 0.93,
                    "final_source": "user_confirmed_candidate",
                    "image_diagnosis": {"top1": {"disease": "晚疫病", "confidence": 0.9}, "top3": [("晚疫病", 0.9)]},
                    "diagnosis_evidence": {"raw_symptoms": ["卷叶"], "normalized_symptoms": ["叶片卷曲"]},
                    "symptom_evidence_profile": {"raw_tokens": ["卷叶"], "normalized_tokens": ["叶片卷曲"]},
                    "normalized_symptoms": ["叶片卷曲"],
                    "personalization_flags": {"need_confirm": False, "fallback_reason": [], "follow_up_questions": []},
                    "verification_result": {"passed": True},
                    "verification_passed": True,
                    "verification_risk_level": "low",
                    "verification_issues": [],
                    "verification_summary": "ok",
                }
            )
            return out

    monkeypatch.setattr(app_module, "build_graph", lambda: _Graph())
    client = TestClient(app_module.app)
    resp = client.post(
        "/api/diagnose-confirm",
        json={"trace_id": "trace-confirm", "image_id": image_id, "crop_type": "番茄", "choice": "晚疫病", "symptoms": ["卷叶"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    for key in (
        "display_symptoms",
        "display_symptom_count",
        "final_status",
        "execution_allowed",
        "treatment_actionable",
        "treatment_reference_only",
    ):
        assert key in body
    assert body["display_symptoms"] == ["叶片卷曲"]
    assert body["display_symptom_count"] == 1
    assert body["display_symptom_count"] == len(body["display_symptoms"])
    assert body["final_status"] == "completed"
    assert body["execution_allowed"] is True
    assert body["treatment_actionable"] is True
    assert body["treatment_reference_only"] is False


def test_confirm_choice_completed_verification_failed_includes_execution_gate_contract(monkeypatch, tmp_path):
    image_id, _captured_events = _prepare_confirm_core_mocks(monkeypatch, tmp_path, previous_status="waiting_for_supplement")

    class _Graph:
        def invoke(self, state, config=None):
            _ = config
            out = dict(state)
            out.update(
                {
                    "trace_id": state.get("trace_id"),
                    "next_action": "end",
                    "final_disease": "晚疫病",
                    "final_confidence": 0.88,
                    "final_source": "fusion",
                    "image_diagnosis": {"top1": {"disease": "晚疫病", "confidence": 0.88}, "top3": [("晚疫病", 0.88)]},
                    "normalized_symptoms": ["叶片卷曲"],
                    "diagnosis_evidence": {"normalized_symptoms": ["叶片卷曲"]},
                    "personalization_flags": {"need_confirm": False, "fallback_reason": [], "follow_up_questions": []},
                    "llm_failed": False,
                    "llm_failed_reason": "constraint_violation",
                    "verification_result": {"passed": False, "issues": ["x"]},
                    "verification_passed": False,
                    "verification_risk_level": "high",
                    "verification_issues": ["x"],
                    "verification_summary": "fail",
                    "treatment_plan": "仅供参考方案",
                    "prevention_advice": "仅供参考预防",
                }
            )
            return out

    monkeypatch.setattr(app_module, "build_graph", lambda: _Graph())
    client = TestClient(app_module.app)
    resp = client.post(
        "/api/diagnose-confirm",
        json={"trace_id": "trace-confirm", "image_id": image_id, "crop_type": "番茄", "choice": "晚疫病", "symptoms": ["卷叶"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    for key in (
        "display_symptoms",
        "display_symptom_count",
        "final_status",
        "execution_allowed",
        "treatment_actionable",
        "treatment_reference_only",
    ):
        assert key in body
    assert body["status"] == "completed_verification_failed"
    assert body["final_status"] == "completed_verification_failed"
    assert body["execution_allowed"] is False
    assert body["treatment_actionable"] is False
    assert body["treatment_reference_only"] is True
    assert body["manual_review_required_before_execution"] is True
    assert body["display_symptom_count"] == len(body["display_symptoms"])
    assert body["llm_failed"] is False
    assert body.get("llm_failed_reason") is None


def test_completed_response_still_has_display_fields_when_normalized_symptoms_missing(monkeypatch, tmp_path):
    _prepare_common_mocks(monkeypatch, tmp_path, need_confirm=False)

    class _GraphCompletedNoNormalized:
        def invoke(self, initial_state, config=None):
            _ = config
            out = dict(initial_state)
            out.update(
                {
                    "trace_id": initial_state.get("trace_id"),
                    "final_disease": "晚疫病",
                    "final_confidence": 0.91,
                    "final_source": "fusion",
                    "image_result": {"disease": "晚疫病", "confidence": 0.72, "top3": [("晚疫病", 0.72)]},
                    "personalization_flags": {"need_confirm": False, "fallback_reason": []},
                    "normalized_symptoms": [],
                    "diagnosis_evidence": {"raw_symptoms": ["卷叶"], "normalized_symptoms": ["叶片卷曲"]},
                    "symptom_evidence_profile": {"raw_tokens": ["卷叶"], "normalized_tokens": ["叶片卷曲"]},
                }
            )
            return out

    monkeypatch.setattr(app_module, "build_graph", lambda: _GraphCompletedNoNormalized())
    client = TestClient(app_module.app)
    body = client.post(
        "/api/diagnose-image",
        files={"file": ("case.jpg", b"fake-jpeg-content", "image/jpeg")},
        data={"crop_type": "番茄"},
    ).json()
    assert body["status"] == "completed"
    assert body["display_symptoms"] == ["叶片卷曲"]
    assert body["display_symptom_count"] == 1
    assert body["display_symptom_count"] == len(body["display_symptoms"])


def test_serialize_event_dto_backfills_display_fields_for_latest_event_paths():
    dto = app_module._serialize_event_dto(
        {
            "status": "completed",
            "need_confirm": False,
            "normalized_symptoms": [],
            "diagnosis_evidence": {"normalized_symptoms": ["叶片卷曲"]},
        }
    )
    assert dto["display_symptoms"] == ["叶片卷曲"]
    assert dto["display_symptom_count"] == 1
    assert dto["display_symptom_count"] == len(dto["display_symptoms"])


def test_confirm_event_payload_matches_api_response_for_display_and_execution_fields(monkeypatch, tmp_path):
    image_id, captured_events = _prepare_confirm_core_mocks(monkeypatch, tmp_path, previous_status="waiting_for_supplement")

    class _Graph:
        def invoke(self, state, config=None):
            _ = config
            out = dict(state)
            out.update(
                {
                    "trace_id": state.get("trace_id"),
                    "next_action": "end",
                    "final_disease": "晚疫病",
                    "final_confidence": 0.9,
                    "final_source": "fusion",
                    "image_diagnosis": {"top1": {"disease": "晚疫病", "confidence": 0.9}, "top3": [("晚疫病", 0.9)]},
                    "normalized_symptoms": ["叶片卷曲"],
                    "diagnosis_evidence": {"normalized_symptoms": ["叶片卷曲"]},
                    "personalization_flags": {"need_confirm": False, "fallback_reason": [], "follow_up_questions": []},
                    "verification_result": {"passed": False},
                    "verification_passed": False,
                    "verification_risk_level": "high",
                    "verification_issues": ["issue"],
                    "verification_summary": "fail",
                    "treatment_plan": "仅供参考方案",
                    "prevention_advice": "仅供参考预防",
                }
            )
            return out

    monkeypatch.setattr(app_module, "build_graph", lambda: _Graph())
    client = TestClient(app_module.app)
    resp = client.post(
        "/api/diagnose-confirm",
        json={"trace_id": "trace-confirm", "image_id": image_id, "crop_type": "番茄", "choice": "晚疫病", "symptoms": ["卷叶"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert captured_events
    persisted = captured_events[-1]
    for key in (
        "display_symptoms",
        "display_symptom_count",
        "final_status",
        "execution_allowed",
        "treatment_actionable",
        "treatment_reference_only",
    ):
        assert body.get(key) == persisted.get(key)


def test_confirm_waiting_await_user_event_payload_contains_display_and_execution_fields(monkeypatch, tmp_path):
    image_id, _captured_events = _prepare_confirm_core_mocks(monkeypatch, tmp_path, previous_status="waiting_for_supplement")
    emitted: list[dict] = []

    class _Graph:
        def invoke(self, state, config=None):
            _ = config
            out = dict(state)
            out.update(
                {
                    "trace_id": state.get("trace_id"),
                    "next_action": "await_user_confirmation",
                    "final_disease": "晚疫病",
                    "final_confidence": 0.63,
                    "final_source": "fusion",
                    "image_diagnosis": {"top1": {"disease": "晚疫病", "confidence": 0.7}, "top3": [("晚疫病", 0.7)]},
                    "normalized_symptoms": ["叶片卷曲"],
                    "diagnosis_evidence": {"normalized_symptoms": ["叶片卷曲"]},
                    "personalization_flags": {"need_confirm": True, "fallback_reason": ["low_confidence"], "follow_up_questions": []},
                }
            )
            return out

    def _capture_emit(_trace_id, *, node, status, message=None, payload=None):
        emitted.append({"node": node, "status": status, "message": message, "payload": payload})
        return {}

    monkeypatch.setattr(app_module, "build_graph", lambda: _Graph())
    monkeypatch.setattr(app_module, "emit_node_event", _capture_emit)
    client = TestClient(app_module.app)
    resp = client.post(
        "/api/diagnose-confirm",
        json={"trace_id": "trace-confirm", "image_id": image_id, "crop_type": "番茄", "choice": "other", "symptoms": ["卷叶"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    await_events = [item for item in emitted if item.get("node") == "AwaitUserConfirmation" and item.get("status") == "end"]
    assert await_events
    payload = await_events[-1]["payload"] or {}
    for key in (
        "display_symptoms",
        "display_symptom_count",
        "final_status",
        "execution_allowed",
        "treatment_actionable",
        "treatment_reference_only",
    ):
        assert payload.get(key) == body.get(key)


def test_confirm_completed_final_event_payload_contains_display_and_execution_fields(monkeypatch, tmp_path):
    image_id, _captured_events = _prepare_confirm_core_mocks(monkeypatch, tmp_path, previous_status="waiting_for_supplement")
    emitted_final: list[dict] = []

    class _Graph:
        def invoke(self, state, config=None):
            _ = config
            out = dict(state)
            out.update(
                {
                    "trace_id": state.get("trace_id"),
                    "next_action": "end",
                    "final_disease": "晚疫病",
                    "final_confidence": 0.9,
                    "final_source": "fusion",
                    "image_diagnosis": {"top1": {"disease": "晚疫病", "confidence": 0.9}, "top3": [("晚疫病", 0.9)]},
                    "normalized_symptoms": ["叶片卷曲"],
                    "diagnosis_evidence": {"normalized_symptoms": ["叶片卷曲"]},
                    "personalization_flags": {"need_confirm": False, "fallback_reason": [], "follow_up_questions": []},
                    "verification_result": {"passed": True},
                    "verification_passed": True,
                    "verification_risk_level": "low",
                    "verification_issues": [],
                    "verification_summary": "ok",
                }
            )
            return out

    def _capture_final(trace_id, *, status, message, payload=None):
        emitted_final.append({"trace_id": trace_id, "status": status, "message": message, "payload": payload})
        return {}

    monkeypatch.setattr(app_module, "build_graph", lambda: _Graph())
    monkeypatch.setattr(app_module, "emit_final_event_once", _capture_final)
    client = TestClient(app_module.app)
    resp = client.post(
        "/api/diagnose-confirm",
        json={"trace_id": "trace-confirm", "image_id": image_id, "crop_type": "番茄", "choice": "晚疫病", "symptoms": ["卷叶"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert emitted_final
    payload = (emitted_final[-1].get("payload") or {})
    for key in (
        "display_symptoms",
        "display_symptom_count",
        "final_status",
        "execution_allowed",
        "treatment_actionable",
        "treatment_reference_only",
    ):
        assert payload.get(key) == body.get(key)


def test_confirm_waiting_for_expert_decision_emits_terminal_event_aligned_with_api(monkeypatch, tmp_path):
    image_id, _captured_events = _prepare_confirm_core_mocks(monkeypatch, tmp_path, previous_status="waiting_for_supplement")
    emitted: list[dict] = []

    class _Graph:
        def invoke(self, state, config=None):
            _ = config
            out = dict(state)
            out.update(
                {
                    "trace_id": state.get("trace_id"),
                    "next_action": "manual_review",
                    "final_disease": "晚疫病",
                    "final_confidence": 0.64,
                    "final_source": "fusion",
                    "image_diagnosis": {"top1": {"disease": "晚疫病", "confidence": 0.7}, "top3": [("晚疫病", 0.7)]},
                    "normalized_symptoms": ["叶片卷曲"],
                    "diagnosis_evidence": {"normalized_symptoms": ["叶片卷曲"]},
                    "personalization_flags": {"need_confirm": False, "fallback_reason": [], "follow_up_questions": []},
                    "expert_review_actions": ["use_current_result", "request_expert_review"],
                }
            )
            return out

    def _capture_emit(_trace_id, *, node, status, message=None, payload=None):
        emitted.append({"node": node, "status": status, "message": message, "payload": payload})
        return {}

    monkeypatch.setattr(app_module, "build_graph", lambda: _Graph())
    monkeypatch.setattr(app_module, "emit_node_event", _capture_emit)
    client = TestClient(app_module.app)
    resp = client.post(
        "/api/diagnose-confirm",
        json={"trace_id": "trace-confirm", "image_id": image_id, "crop_type": "番茄", "choice": "other", "symptoms": ["卷叶"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "waiting_for_expert_decision"
    assert body["final_status"] == "waiting_for_expert_decision"
    assert body["result_stage"] == "pending_expert_decision"
    assert body["is_final_result"] is False
    assert body["final_result_authoritative"] is False

    terminal_events = [item for item in emitted if item.get("node") == "AwaitExpertDecision" and item.get("status") == "end"]
    assert terminal_events
    payload = terminal_events[-1].get("payload") or {}
    for key in (
        "status",
        "final_status",
        "result_stage",
        "display_symptoms",
        "display_symptom_count",
        "execution_allowed",
        "treatment_actionable",
        "treatment_reference_only",
        "provisional_disease",
    ):
        assert payload.get(key) == body.get(key)


def test_serialize_final_response_normalizes_llm_failed_reason_contract():
    out = app_module.serialize_final_response(
        {
            "status": "completed",
            "need_confirm": False,
            "llm_failed": False,
            "llm_failed_reason": "constraint_violation",
        }
    )
    assert out["llm_failed"] is False
    assert out.get("llm_failed_reason") is None


def test_llm_failed_reason_is_null_when_llm_failed_is_false():
    out = app_module.serialize_final_response(
        {
            "status": "completed",
            "need_confirm": False,
            "llm_failed": False,
            "llm_failed_reason": "constraint_violation",
        }
    )
    assert out["llm_failed"] is False
    assert out.get("llm_failed_reason") is None


def test_confirm_completed_fields_exist_after_result_semantics_after_serialize_and_in_api_response(monkeypatch, tmp_path):
    image_id, _captured_events = _prepare_confirm_core_mocks(monkeypatch, tmp_path, previous_status="waiting_for_supplement")
    captured_raw_before_result: dict | None = None
    captured_after_result: dict | None = None
    captured_after_serialize: dict | None = None

    original_apply = app_module._apply_result_semantics
    original_serialize = app_module.serialize_final_response

    def _wrapped_apply(payload):
        nonlocal captured_raw_before_result
        nonlocal captured_after_result
        if isinstance(payload, dict) and payload.get("status") in {"completed", "completed_verification_failed"} and "events" in payload:
            captured_raw_before_result = dict(payload)
        out = original_apply(payload)
        if isinstance(payload, dict) and payload.get("status") in {"completed", "completed_verification_failed"} and "events" in payload:
            captured_after_result = dict(out)
        return out

    def _wrapped_serialize(payload):
        nonlocal captured_after_serialize
        out = original_serialize(payload)
        if isinstance(payload, dict) and payload.get("status") in {"completed", "completed_verification_failed"} and "events" in payload:
            captured_after_serialize = dict(out)
        return out

    class _Graph:
        def invoke(self, state, config=None):
            _ = config
            out = dict(state)
            out.update(
                {
                    "trace_id": state.get("trace_id"),
                    "next_action": "end",
                    "final_disease": "晚疫病",
                    "final_confidence": 0.9,
                    "final_source": "fusion",
                    "image_diagnosis": {"top1": {"disease": "晚疫病", "confidence": 0.9}, "top3": [("晚疫病", 0.9)]},
                    "normalized_symptoms": ["叶片卷曲"],
                    "diagnosis_evidence": {"normalized_symptoms": ["叶片卷曲"]},
                    "personalization_flags": {"need_confirm": False, "fallback_reason": [], "follow_up_questions": []},
                    "verification_result": {"passed": False},
                    "verification_passed": False,
                    "verification_risk_level": "high",
                    "verification_issues": ["issue"],
                    "verification_summary": "fail",
                    "treatment_plan": "仅供参考方案",
                    "prevention_advice": "仅供参考预防",
                }
            )
            return out

    monkeypatch.setattr(app_module, "_apply_result_semantics", _wrapped_apply)
    monkeypatch.setattr(app_module, "serialize_final_response", _wrapped_serialize)
    monkeypatch.setattr(app_module, "build_graph", lambda: _Graph())

    client = TestClient(app_module.app)
    resp = client.post(
        "/api/diagnose-confirm",
        json={"trace_id": "trace-confirm", "image_id": image_id, "crop_type": "番茄", "choice": "晚疫病", "symptoms": ["卷叶"]},
    )
    assert resp.status_code == 200
    body = resp.json()

    assert captured_raw_before_result is not None
    assert captured_after_result is not None
    assert captured_after_serialize is not None
    # 原始 response_payload 阶段允许缺字段；关键是统一收口后与最终出站不能丢。
    for key in (
        "display_symptoms",
        "display_symptom_count",
        "final_status",
        "execution_allowed",
        "treatment_actionable",
        "treatment_reference_only",
    ):
        assert key not in captured_raw_before_result or captured_raw_before_result.get(key) is None
    for one in (captured_after_result, captured_after_serialize, body):
        for key in (
            "display_symptoms",
            "display_symptom_count",
            "final_status",
            "execution_allowed",
            "treatment_actionable",
            "treatment_reference_only",
        ):
            assert key in one
    assert body["status"] == "completed_verification_failed"
    assert body["final_status"] == "completed_verification_failed"
    assert body["execution_allowed"] is False
    assert body["treatment_actionable"] is False
    assert body["treatment_reference_only"] is True
    assert body["display_symptom_count"] == len(body["display_symptoms"])


def test_confirm_choice_completed_final_response_keeps_display_and_execution_contract_after_serialize(monkeypatch, tmp_path):
    image_id, _captured_events = _prepare_confirm_core_mocks(monkeypatch, tmp_path, previous_status="waiting_for_supplement")

    class _Graph:
        def invoke(self, state, config=None):
            _ = config
            out = dict(state)
            out.update(
                {
                    "trace_id": state.get("trace_id"),
                    "next_action": "end",
                    "final_disease": "晚疫病",
                    "final_confidence": 0.91,
                    "final_source": "fusion",
                    "image_diagnosis": {"top1": {"disease": "晚疫病", "confidence": 0.91}, "top3": [("晚疫病", 0.91)]},
                    "normalized_symptoms": ["叶片卷曲"],
                    "diagnosis_evidence": {"normalized_symptoms": ["叶片卷曲"]},
                    "personalization_flags": {"need_confirm": False, "fallback_reason": [], "follow_up_questions": []},
                    "verification_result": {"passed": True},
                    "verification_passed": True,
                    "verification_risk_level": "low",
                    "verification_issues": [],
                    "verification_summary": "ok",
                }
            )
            return out

    monkeypatch.setattr(app_module, "build_graph", lambda: _Graph())
    client = TestClient(app_module.app)
    body = client.post(
        "/api/diagnose-confirm",
        json={"trace_id": "trace-confirm", "image_id": image_id, "crop_type": "番茄", "choice": "晚疫病", "symptoms": ["卷叶"]},
    ).json()
    for key in (
        "display_symptoms",
        "display_symptom_count",
        "final_status",
        "execution_allowed",
        "treatment_actionable",
        "treatment_reference_only",
        "result_stage",
        "is_final_result",
        "final_result_authoritative",
    ):
        assert key in body
    assert body["status"] == "completed"
    assert body["final_status"] == "completed"
    assert body["result_stage"] == "diagnosis_completed"
    assert body["is_final_result"] is True
    assert body["final_result_authoritative"] is True
    assert body["execution_allowed"] is True
    assert body["treatment_actionable"] is True
    assert body["treatment_reference_only"] is False
    assert body["display_symptom_count"] == len(body["display_symptoms"])


def test_confirm_choice_completed_verification_failed_final_response_keeps_display_and_execution_contract_after_serialize(monkeypatch, tmp_path):
    image_id, _captured_events = _prepare_confirm_core_mocks(monkeypatch, tmp_path, previous_status="waiting_for_supplement")

    class _Graph:
        def invoke(self, state, config=None):
            _ = config
            out = dict(state)
            out.update(
                {
                    "trace_id": state.get("trace_id"),
                    "next_action": "end",
                    "final_disease": "晚疫病",
                    "final_confidence": 0.86,
                    "final_source": "fusion",
                    "image_diagnosis": {"top1": {"disease": "晚疫病", "confidence": 0.86}, "top3": [("晚疫病", 0.86)]},
                    "normalized_symptoms": ["叶片卷曲"],
                    "diagnosis_evidence": {"normalized_symptoms": ["叶片卷曲"]},
                    "personalization_flags": {"need_confirm": False, "fallback_reason": [], "follow_up_questions": []},
                    "verification_result": {"passed": False, "issues": ["x"]},
                    "verification_passed": False,
                    "verification_risk_level": "high",
                    "verification_issues": ["x"],
                    "verification_summary": "fail",
                    "treatment_plan": "仅供参考方案",
                    "prevention_advice": "仅供参考预防",
                }
            )
            return out

    monkeypatch.setattr(app_module, "build_graph", lambda: _Graph())
    client = TestClient(app_module.app)
    body = client.post(
        "/api/diagnose-confirm",
        json={"trace_id": "trace-confirm", "image_id": image_id, "crop_type": "番茄", "choice": "晚疫病", "symptoms": ["卷叶"]},
    ).json()
    for key in (
        "display_symptoms",
        "display_symptom_count",
        "final_status",
        "execution_allowed",
        "treatment_actionable",
        "treatment_reference_only",
        "result_stage",
        "is_final_result",
        "final_result_authoritative",
    ):
        assert key in body
    assert body["status"] == "completed_verification_failed"
    assert body["final_status"] == "completed_verification_failed"
    assert body["result_stage"] == "diagnosis_completed"
    assert body["is_final_result"] is True
    assert body["final_result_authoritative"] is True
    assert body["execution_allowed"] is False
    assert body["treatment_actionable"] is False
    assert body["treatment_reference_only"] is True
    assert body["manual_review_required_before_execution"] is True
    assert body["display_symptom_count"] == len(body["display_symptoms"])


def test_final_completed_response_keeps_result_stage_and_final_flags():
    out = app_module.serialize_final_response(
        app_module._apply_result_semantics(
            {
                "status": "completed",
                "need_confirm": False,
                "final_disease": "晚疫病",
                "verification_passed": True,
                "treatment_available": True,
            }
        )
    )
    assert out["result_stage"] == "diagnosis_completed"
    assert out["is_final_result"] is True
    assert out["final_result_authoritative"] is True
    assert out["final_status"] == "completed"
    assert out["execution_allowed"] is True


def test_final_completed_response_does_not_drop_verification_contract_after_graph_execution(monkeypatch, tmp_path):
    image_id, _captured_events = _prepare_confirm_core_mocks(monkeypatch, tmp_path, previous_status="waiting_for_supplement")
    captured_graph_out: dict | None = None
    captured_after_result: dict | None = None
    captured_after_serialize: dict | None = None

    original_apply = app_module._apply_result_semantics
    original_serialize = app_module.serialize_final_response

    def _wrapped_apply(payload):
        nonlocal captured_after_result
        out = original_apply(payload)
        if isinstance(payload, dict) and payload.get("status") in {"completed", "completed_verification_failed"} and "events" in payload:
            captured_after_result = dict(out)
        return out

    def _wrapped_serialize(payload):
        nonlocal captured_after_serialize
        out = original_serialize(payload)
        if isinstance(payload, dict) and payload.get("status") in {"completed", "completed_verification_failed"} and "events" in payload:
            captured_after_serialize = dict(out)
        return out

    class _Graph:
        def invoke(self, state, config=None):
            nonlocal captured_graph_out
            _ = config
            out = dict(state)
            out.update(
                {
                    "trace_id": state.get("trace_id"),
                    "next_action": "end",
                    "final_disease": "晚疫病",
                    "final_confidence": 0.89,
                    "final_source": "fusion",
                    "image_diagnosis": {"top1": {"disease": "晚疫病", "confidence": 0.89}, "top3": [("晚疫病", 0.89)]},
                    "normalized_symptoms": ["叶片卷曲"],
                    "diagnosis_evidence": {"normalized_symptoms": ["叶片卷曲"]},
                    "personalization_flags": {"need_confirm": False, "fallback_reason": [], "follow_up_questions": []},
                    "verification_result": {"passed": False, "issues": ["x"]},
                    "verification_passed": False,
                    "verification_risk_level": "high",
                    "verification_issues": ["x"],
                    "verification_summary": "fail",
                    "treatment_plan": "仅供参考方案",
                    "prevention_advice": "仅供参考预防",
                }
            )
            captured_graph_out = dict(out)
            return out

    monkeypatch.setattr(app_module, "_apply_result_semantics", _wrapped_apply)
    monkeypatch.setattr(app_module, "serialize_final_response", _wrapped_serialize)
    monkeypatch.setattr(app_module, "build_graph", lambda: _Graph())

    client = TestClient(app_module.app)
    body = client.post(
        "/api/diagnose-confirm",
        json={"trace_id": "trace-confirm", "image_id": image_id, "crop_type": "番茄", "choice": "晚疫病", "symptoms": ["卷叶"]},
    ).json()

    assert captured_graph_out is not None
    assert captured_after_result is not None
    assert captured_after_serialize is not None
    assert (captured_graph_out.get("verification_result") or {}).get("passed") is False
    assert captured_after_result.get("verification_passed") is False
    assert captured_after_serialize.get("verification_passed") is False
    assert body.get("verification_passed") is False
    assert body["status"] == "completed_verification_failed"
    assert body["manual_review_required_before_execution"] is True


def test_waiting_for_supplement_api_and_event_behavior_does_not_regress(monkeypatch, tmp_path):
    _prepare_common_mocks(monkeypatch, tmp_path, need_confirm=True)
    captured_events: list[dict] = []
    monkeypatch.setattr(app_module, "append_event", lambda evt: captured_events.append(dict(evt)))
    client = TestClient(app_module.app)
    body = client.post(
        "/api/diagnose-image",
        files={"file": ("case.jpg", b"fake-jpeg-content", "image/jpeg")},
        data={"crop_type": "番茄"},
    ).json()
    assert body["status"] == "waiting_for_supplement"
    assert body["result_stage"] == "awaiting_confirmation"
    assert body["is_final_result"] is False
    assert body["final_result_authoritative"] is False
    for key in (
        "display_symptoms",
        "display_symptom_count",
        "final_status",
        "execution_allowed",
        "treatment_actionable",
        "treatment_reference_only",
    ):
        assert key in body
    assert captured_events
    event = captured_events[-1]
    for key in (
        "display_symptoms",
        "display_symptom_count",
        "final_status",
        "execution_allowed",
        "treatment_actionable",
        "treatment_reference_only",
    ):
        assert key in event


def test_final_completed_response_keeps_unified_contract_fields(monkeypatch, tmp_path):
    image_id, _captured_events = _prepare_confirm_core_mocks(monkeypatch, tmp_path, previous_status="waiting_for_supplement")
    checkpoints: dict[str, dict] = {}
    contract_keys = (
        "display_symptoms",
        "display_symptom_count",
        "final_status",
        "execution_allowed",
        "treatment_actionable",
        "treatment_reference_only",
        "result_stage",
        "is_final_result",
        "final_result_authoritative",
    )
    original_apply = app_module._apply_result_semantics
    original_serialize = app_module.serialize_final_response

    def _wrapped_apply(payload):
        out = original_apply(payload)
        if isinstance(payload, dict) and payload.get("status") in {"completed", "completed_verification_failed"} and "events" in payload:
            checkpoints["after_apply"] = dict(out)
        return out

    def _wrapped_serialize(payload):
        out = original_serialize(payload)
        if isinstance(payload, dict) and payload.get("status") in {"completed", "completed_verification_failed"} and "events" in payload:
            checkpoints["after_serialize"] = dict(out)
        return out

    class _Graph:
        def invoke(self, state, config=None):
            _ = config
            out = dict(state)
            out.update(
                {
                    "trace_id": state.get("trace_id"),
                    "next_action": "end",
                    "final_disease": "晚疫病",
                    "final_confidence": 0.91,
                    "final_source": "fusion",
                    "image_diagnosis": {"top1": {"disease": "晚疫病", "confidence": 0.91}, "top3": [("晚疫病", 0.91)]},
                    "normalized_symptoms": ["叶片卷曲"],
                    "diagnosis_evidence": {"normalized_symptoms": ["叶片卷曲"]},
                    "personalization_flags": {"need_confirm": False, "fallback_reason": [], "follow_up_questions": []},
                    "verification_result": {"passed": True},
                    "verification_passed": True,
                    "verification_risk_level": "low",
                    "verification_issues": [],
                    "verification_summary": "ok",
                }
            )
            checkpoints["graph_output"] = dict(out)
            return out

    monkeypatch.setattr(app_module, "_apply_result_semantics", _wrapped_apply)
    monkeypatch.setattr(app_module, "serialize_final_response", _wrapped_serialize)
    monkeypatch.setattr(app_module, "build_graph", lambda: _Graph())

    client = TestClient(app_module.app)
    body = client.post(
        "/api/diagnose-confirm",
        json={"trace_id": "trace-confirm", "image_id": image_id, "crop_type": "番茄", "choice": "晚疫病", "symptoms": ["卷叶"]},
    ).json()
    checkpoints["before_return"] = dict(body)

    for point in ("after_apply", "after_serialize", "before_return"):
        snapshot = checkpoints.get(point) or {}
        for key in contract_keys:
            assert key in snapshot
    # graph 输出为状态机原始结果，不要求带统一 contract 字段
    for key in contract_keys:
        assert key not in checkpoints["graph_output"]


def test_final_completed_verification_failed_response_keeps_unified_contract_fields(monkeypatch, tmp_path):
    image_id, _captured_events = _prepare_confirm_core_mocks(monkeypatch, tmp_path, previous_status="waiting_for_supplement")

    class _Graph:
        def invoke(self, state, config=None):
            _ = config
            out = dict(state)
            out.update(
                {
                    "trace_id": state.get("trace_id"),
                    "next_action": "end",
                    "final_disease": "晚疫病",
                    "final_confidence": 0.86,
                    "final_source": "fusion",
                    "image_diagnosis": {"top1": {"disease": "晚疫病", "confidence": 0.86}, "top3": [("晚疫病", 0.86)]},
                    "normalized_symptoms": ["叶片卷曲"],
                    "diagnosis_evidence": {"normalized_symptoms": ["叶片卷曲"]},
                    "personalization_flags": {"need_confirm": False, "fallback_reason": [], "follow_up_questions": []},
                    "verification_result": {"passed": False, "issues": ["x"]},
                    "verification_passed": False,
                    "verification_risk_level": "high",
                    "verification_issues": ["x"],
                    "verification_summary": "fail",
                    "treatment_plan": "仅供参考方案",
                    "prevention_advice": "仅供参考预防",
                }
            )
            return out

    monkeypatch.setattr(app_module, "build_graph", lambda: _Graph())
    client = TestClient(app_module.app)
    body = client.post(
        "/api/diagnose-confirm",
        json={"trace_id": "trace-confirm", "image_id": image_id, "crop_type": "番茄", "choice": "晚疫病", "symptoms": ["卷叶"]},
    ).json()
    for key in (
        "display_symptoms",
        "display_symptom_count",
        "final_status",
        "execution_allowed",
        "treatment_actionable",
        "treatment_reference_only",
        "result_stage",
        "is_final_result",
        "final_result_authoritative",
    ):
        assert key in body


def test_final_completed_response_has_final_stage_flags():
    out = app_module.serialize_final_response(app_module._apply_result_semantics({"status": "completed", "need_confirm": False}))
    assert out["result_stage"] == "diagnosis_completed"
    assert out["is_final_result"] is True
    assert out["final_result_authoritative"] is True


def test_final_completed_verification_failed_response_has_final_stage_flags():
    out = app_module.serialize_final_response(
        app_module._apply_result_semantics(
            {"status": "completed", "need_confirm": False, "verification_result": {"passed": False}, "verification_passed": False}
        )
    )
    assert out["status"] == "completed_verification_failed"
    assert out["result_stage"] == "diagnosis_completed"
    assert out["is_final_result"] is True
    assert out["final_result_authoritative"] is True


def test_final_display_symptom_count_matches_display_symptoms_length():
    out = app_module.serialize_final_response(
        app_module._apply_result_semantics(
            {"status": "completed", "need_confirm": False, "normalized_symptoms": ["叶片卷曲", "叶片卷曲", "叶缘坏死"]}
        )
    )
    assert out["display_symptom_count"] == len(out["display_symptoms"])


def test_waiting_for_supplement_behavior_does_not_regress(monkeypatch, tmp_path):
    test_waiting_for_supplement_api_and_event_behavior_does_not_regress(monkeypatch, tmp_path)


def test_final_response_keeps_verification_contract_after_unified_contract_fix(monkeypatch, tmp_path):
    image_id, _captured_events = _prepare_confirm_core_mocks(monkeypatch, tmp_path, previous_status="waiting_for_supplement")

    class _Graph:
        def invoke(self, state, config=None):
            _ = config
            out = dict(state)
            out.update(
                {
                    "trace_id": state.get("trace_id"),
                    "next_action": "end",
                    "final_disease": "晚疫病",
                    "final_confidence": 0.86,
                    "final_source": "fusion",
                    "image_diagnosis": {"top1": {"disease": "晚疫病", "confidence": 0.86}, "top3": [("晚疫病", 0.86)]},
                    "normalized_symptoms": ["叶片卷曲"],
                    "diagnosis_evidence": {"normalized_symptoms": ["叶片卷曲"]},
                    "personalization_flags": {"need_confirm": False, "fallback_reason": [], "follow_up_questions": []},
                    "verification_result": {"passed": False, "must_fix": ["x"]},
                    "verification_passed": False,
                    "verification_risk_level": "high",
                    "verification_issues": ["x"],
                    "verification_summary": "fail",
                }
            )
            return out

    monkeypatch.setattr(app_module, "build_graph", lambda: _Graph())
    client = TestClient(app_module.app)
    body = client.post(
        "/api/diagnose-confirm",
        json={"trace_id": "trace-confirm", "image_id": image_id, "crop_type": "番茄", "choice": "晚疫病", "symptoms": ["卷叶"]},
    ).json()
    assert body["verification_available"] is True
    assert body["verification_passed"] is False
    assert isinstance(body["verification_result"], dict)
    assert body["verification_summary"] == "fail"


def test_verification_passed_is_downgraded_when_blocking_must_fix_exists():
    payload = {
        "status": "completed",
        "need_confirm": False,
        "verification_passed": True,
        "verification_result": {
            "passed": True,
            "must_fix": ["必须先修复后才能执行"],
            "issues": [],
        },
        "treatment_available": True,
        "verification_available": True,
    }
    out = app_module._apply_result_semantics(payload)
    assert out["verification_passed"] is False
    assert (out.get("verification_result") or {}).get("passed") is False
    assert out["status"] == "completed_verification_failed"
    assert out["execution_allowed"] is False
    assert out["manual_review_required_before_execution"] is True


def test_serialize_final_response_moves_evidence_final_fields_to_debug_namespace():
    out = app_module.serialize_final_response(
        {
            "status": "completed",
            "need_confirm": False,
            "final_disease": "晚疫病",
            "final_source": "user_confirmed_candidate",
            "diagnosis_evidence": {
                "final_disease": "融合候选1",
                "final_source": "fusion",
                "summary": "融合 top1",
                "fusion_top3": [("晚疫病", 0.66)],
            },
        }
    )
    evidence = out["diagnosis_evidence"]
    assert "final_disease" not in evidence
    assert "final_source" not in evidence
    assert "summary" not in evidence
    assert evidence["evidence_final_disease"] == "融合候选1"
    assert evidence["evidence_final_source"] == "fusion"
    assert evidence["evidence_summary"] == "融合 top1"


def test_emit_node_event_truncates_status_and_message_and_payload_error_summary(monkeypatch):
    captured: dict = {}

    def _fake_emit_trace_event(_trace_id, payload):
        captured.update(payload)
        return payload

    monkeypatch.setattr(app_module, "emit_trace_event", _fake_emit_trace_event)
    app_module.emit_node_event(
        "trace-x",
        node="Persist",
        status="x" * 80,
        message="m" * 400,
        payload={"error_summary": "e" * 1200},
    )
    assert len(captured["status"]) <= 32
    assert len(captured["message"]) <= 255
    assert len((captured.get("payload") or {}).get("error_summary") or "") <= 500


def test_diagnose_image_persist_error_keeps_short_trace_message_and_puts_details_in_payload(monkeypatch, tmp_path):
    _prepare_common_mocks(monkeypatch, tmp_path, need_confirm=True)
    persisted_events: list[dict] = []
    emitted: list[dict] = []

    def _failing_append(_evt):
        if not persisted_events:
            persisted_events.append({"first_call": True})
            raise RuntimeError("db error " + ("x" * 600))
        persisted_events.append({"second_call": True})

    def _capture_emit(_trace_id, *, node, status, message=None, payload=None):
        emitted.append({"node": node, "status": status, "message": message, "payload": payload})
        return {}

    monkeypatch.setattr(app_module, "append_event", _failing_append)
    monkeypatch.setattr(app_module, "emit_node_event", _capture_emit)

    client = TestClient(app_module.app)
    resp = client.post(
        "/api/diagnose-image",
        files={"file": ("case.jpg", b"fake-jpeg-content", "image/jpeg")},
        data={"crop_type": "番茄"},
    )
    assert resp.status_code == 200
    persist_errors = [item for item in emitted if item.get("node") == "Persist" and item.get("status") == "error"]
    assert persist_errors
    one = persist_errors[-1]
    assert one["message"] == "事件落盘失败"
    assert len(one["message"]) <= 255
    assert (one.get("payload") or {}).get("error_type") == "RuntimeError"
    assert "db error" in ((one.get("payload") or {}).get("error_summary") or "")
    assert len((one.get("payload") or {}).get("error_summary") or "") <= 500


def test_diagnose_confirm_persist_error_keeps_short_trace_message_and_puts_details_in_payload(monkeypatch, tmp_path):
    image_id, _captured_events = _prepare_confirm_core_mocks(monkeypatch, tmp_path, previous_status="waiting_for_supplement")
    emitted: list[dict] = []
    append_calls = {"n": 0}

    class _Graph:
        def invoke(self, state, config=None):
            _ = config
            out = dict(state)
            out.update(
                {
                    "trace_id": state.get("trace_id"),
                    "next_action": "await_user_confirmation",
                    "final_disease": "晚疫病",
                    "final_confidence": 0.63,
                    "final_source": "fusion",
                    "image_diagnosis": {"top1": {"disease": "晚疫病", "confidence": 0.7}, "top3": [("晚疫病", 0.7)]},
                    "personalization_flags": {"need_confirm": True, "fallback_reason": ["low_confidence"], "follow_up_questions": []},
                    "fusion_top3": [("晚疫病", 0.63)],
                    "text_top3": [("晚疫病", 0.61)],
                    "diagnosis_evidence": {"fusion_top3": [("晚疫病", 0.63)]},
                    "supplement_mode": "text_only",
                }
            )
            return out

    def _failing_append(_evt):
        append_calls["n"] += 1
        raise ValueError("confirm persist error " + ("y" * 600))

    def _capture_emit(_trace_id, *, node, status, message=None, payload=None):
        emitted.append({"node": node, "status": status, "message": message, "payload": payload})
        return {}

    monkeypatch.setattr(app_module, "build_graph", lambda: _Graph())
    monkeypatch.setattr(app_module, "append_event", _failing_append)
    monkeypatch.setattr(app_module, "emit_node_event", _capture_emit)
    client = TestClient(app_module.app)
    resp = client.post(
        "/api/diagnose-confirm",
        json={"trace_id": "trace-confirm", "image_id": image_id, "crop_type": "番茄", "choice": "other", "symptoms": ["发黄"]},
    )
    assert resp.status_code == 200
    assert append_calls["n"] >= 1
    persist_errors = [item for item in emitted if item.get("node") == "Persist" and item.get("status") == "error"]
    assert persist_errors
    one = persist_errors[-1]
    assert one["message"] == "确认轮事件落盘失败"
    assert len(one["message"]) <= 255
    assert (one.get("payload") or {}).get("error_type") == "ValueError"
    assert "confirm persist error" in ((one.get("payload") or {}).get("error_summary") or "")
    assert len((one.get("payload") or {}).get("error_summary") or "") <= 500
