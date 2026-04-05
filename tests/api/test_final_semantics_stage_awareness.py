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

    assert "final_disease" not in body or body["final_disease"] is None
    assert body["final_disease_compat"] == "晚疫病"
    assert body["compatibility_final_fields"] is True
    assert body["result_stage"] == "awaiting_confirmation"
    assert body["is_final_result"] is False
