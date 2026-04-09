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
        ("waiting_for_expert_decision", False, "pending_confirmation"),
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
    assert body["display_symptoms"] == ["叶片卷曲"]
    assert body["display_symptom_count"] == 1


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
