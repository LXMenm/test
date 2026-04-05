from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app as app_module


def _stub_graph_result(initial_state: dict) -> dict:
    out = dict(initial_state)
    out.update(
        {
            "trace_id": initial_state.get("trace_id"),
            "final_disease": "晚疫病",
            "final_confidence": 0.82,
            "final_source": "fusion",
            "fusion_top3": [("晚疫病", 0.82), ("叶霉病", 0.18)],
            "text_top3": [("晚疫病", 0.6), ("叶霉病", 0.4)],
            "diagnosis_evidence": {"fusion_top3": [("晚疫病", 0.82), ("叶霉病", 0.18)]},
            "image_result": {
                "disease": "晚疫病",
                "confidence": 0.79,
                "top3": [
                    {"disease": "晚疫病", "prob": 0.79},
                    {"disease": "叶霉病", "prob": 0.21},
                ],
            },
            "personalization_flags": {},
            "follow_up_questions": [],
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


def _prepare_formal_diagnose_mocks(monkeypatch, tmp_path: Path):
    counter = {"diagnose_from_image": 0}
    saved = tmp_path / "formal.jpg"
    saved.write_bytes(b"fake")

    async def _fake_save_uploaded_image(*_args, **_kwargs):
        return saved.name, saved

    class _Engine:
        def diagnose_from_image(self, _path):
            counter["diagnose_from_image"] += 1
            return "早疫病", 0.9, {"早疫病": 0.9}

    class _Graph:
        def invoke(self, initial_state, config=None):
            _ = config
            return _stub_graph_result(initial_state)

    monkeypatch.setattr(app_module, "_save_uploaded_image", _fake_save_uploaded_image)
    monkeypatch.setattr(app_module, "emit_node_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(app_module, "emit_final_event_once", lambda *args, **kwargs: None)
    monkeypatch.setattr(app_module, "append_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app_module, "list_trace_events", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        app_module,
        "resolve_model",
        lambda model_id, allow_torch=False: (
            SimpleNamespace(model_path="/tmp/mock.bin", backend="mock", model_id="mock", display_name="mock"),
            [],
        ),
    )
    monkeypatch.setattr(app_module, "get_diagnosis_engine", lambda **_kwargs: _Engine())
    monkeypatch.setattr(app_module, "build_graph", lambda: _Graph())
    monkeypatch.setattr(app_module, "_build_degraded_treatment", lambda *_args, **_kwargs: (None, {}))
    return counter


def test_single_request_has_no_duplicate_image_precheck_before_graph(monkeypatch, tmp_path):
    counter = _prepare_formal_diagnose_mocks(monkeypatch, tmp_path)
    client = TestClient(app_module.app)
    resp = client.post(
        "/api/diagnose-image",
        files={"file": ("case.jpg", b"fake-jpeg-content", "image/jpeg")},
        data={"crop_type": "番茄"},
    )
    assert resp.status_code == 200
    assert counter["diagnose_from_image"] == 0


def test_start_precheck_is_not_used_as_first_user_visible_diagnosis_result(monkeypatch, tmp_path):
    saved = tmp_path / "start.jpg"
    saved.write_bytes(b"fake")

    async def _fake_save_uploaded_image(*_args, **_kwargs):
        return saved.name, saved

    monkeypatch.setattr(app_module, "_save_uploaded_image", _fake_save_uploaded_image)
    monkeypatch.setattr(app_module, "emit_node_event", lambda *args, **kwargs: None)
    client = TestClient(app_module.app)

    resp = client.post(
        "/api/diagnose-image/start",
        files={"file": ("case.jpg", b"fake-jpeg-content", "image/jpeg")},
        data={"crop_type": "番茄"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["result_stage"] == "precheck_internal"
    assert body["user_visible"] is False
    assert "preliminary_disease" not in body
    assert "final_disease" not in body


def test_formal_diagnosis_returns_fusion_top1_as_first_visible_result(monkeypatch, tmp_path):
    _prepare_formal_diagnose_mocks(monkeypatch, tmp_path)
    client = TestClient(app_module.app)

    resp = client.post(
        "/api/diagnose-image",
        files={"file": ("case.jpg", b"fake-jpeg-content", "image/jpeg")},
        data={"crop_type": "番茄"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["final_disease"] == "晚疫病"
    assert body["final_source"] == "fusion"
    assert "preliminary_disease" not in body


def test_continue_or_equivalent_path_does_not_duplicate_image_only_diagnosis(monkeypatch, tmp_path):
    counter = _prepare_formal_diagnose_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr(app_module, "UPLOAD_DIR", tmp_path)
    image_id = "continue.jpg"
    (tmp_path / image_id).write_bytes(b"fake")
    client = TestClient(app_module.app)

    resp = client.post(
        "/api/diagnose-image/continue",
        json={"image_id": image_id, "trace_id": "trace-continue", "crop_type": "番茄"},
    )
    assert resp.status_code == 200
    assert counter["diagnose_from_image"] == 0
