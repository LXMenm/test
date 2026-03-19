from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from PIL import Image

import app as app_module


class _DummyImageEngine:
    def diagnose_from_image(self, _):
        return "细菌性斑点病", 0.96, {"细菌性斑点病": 0.96, "早疫病": 0.04}

    def diagnose_from_symptoms(self, **kwargs):
        return "细菌性斑点病", 0.8, "rule"


class _Graph:
    def __init__(self, need_confirm: bool):
        self.need_confirm = need_confirm

    def invoke(self, state, config=None):
        state = dict(state)
        state["trace_id"] = state.get("trace_id") or "trace-test"
        state["final_disease"] = "细菌性斑点病"
        state["final_confidence"] = 0.92 if not self.need_confirm else 0.42
        state["final_source"] = "fusion"
        state["image_confidence"] = 0.96
        state["text_confidence"] = 0.0
        state["diagnosis_evidence"] = {"summary": "test"}
        state["modality_conflict_flag"] = False
        state["normalized_symptoms"] = []
        state["personalization_flags"] = {
            "need_confirm": self.need_confirm,
            "follow_up_questions": ["请补充叶片近照"],
        }
        if not self.need_confirm:
            state["treatment_plan"] = "测试治疗方案"
            state["prevention_advice"] = "测试预防建议"
        return state


def _mock_build_graph(need_confirm: bool):
    return lambda: _Graph(need_confirm=need_confirm)


def _make_image_bytes() -> bytes:
    img = Image.new("RGB", (8, 8), color=(255, 0, 0))
    out = BytesIO()
    img.save(out, format="JPEG")
    return out.getvalue()


def _seed_upload(tmp_path: Path, image_id: str) -> Path:
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / image_id).write_bytes(_make_image_bytes())
    return upload_dir


def test_diagnose_image_completed_has_none_expert_review(monkeypatch, tmp_path):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(app_module, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(app_module, "get_diagnosis_engine", lambda **kwargs: _DummyImageEngine())
    monkeypatch.setattr(app_module, "build_graph", _mock_build_graph(need_confirm=False))
    monkeypatch.setattr(app_module, "resolve_model", lambda model_id, allow_torch=True: (
        SimpleNamespace(model_id="tf_default", display_name="TF", backend="tf", model_path="dummy.h5"),
        [],
    ))

    client = TestClient(app_module.app)
    resp = client.post(
        "/api/diagnose-image",
        files={"file": ("leaf.jpg", _make_image_bytes(), "image/jpeg")},
        data={"crop_type": "番茄"},
    )
    resp.raise_for_status()
    body = resp.json()
    assert body["status"] == "completed"
    assert body["expert_review_recommended"] is False
    assert body["expert_review_selected"] is False
    assert body["expert_review_status"] == "NONE"


def test_diagnose_image_waiting_for_supplement(monkeypatch, tmp_path):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(app_module, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(app_module, "get_diagnosis_engine", lambda **kwargs: _DummyImageEngine())
    monkeypatch.setattr(app_module, "build_graph", _mock_build_graph(need_confirm=True))
    monkeypatch.setattr(app_module, "resolve_model", lambda model_id, allow_torch=True: (
        SimpleNamespace(model_id="tf_default", display_name="TF", backend="tf", model_path="dummy.h5"),
        [],
    ))

    client = TestClient(app_module.app)
    resp = client.post(
        "/api/diagnose-image",
        files={"file": ("leaf.jpg", _make_image_bytes(), "image/jpeg")},
        data={"crop_type": "番茄"},
    )
    resp.raise_for_status()
    body = resp.json()
    assert body["status"] == "waiting_for_supplement"


def _mock_resume_from_confirm_input(state, **kwargs):
    state["symptoms"] = kwargs.get("merged_symptoms") or []
    state["image_path"] = kwargs.get("image_path")
    state["image_diagnosis"] = {
        "top1": {"disease": "细菌性斑点病", "confidence": 0.42},
        "top3": [("细菌性斑点病", 0.42), ("早疫病", 0.35), ("晚疫病", 0.23)],
    }
    state["final_disease"] = "细菌性斑点病"
    state["treatment_plan"] = "测试治疗方案"
    state["prevention_advice"] = "测试预防建议"
    return state


def _mock_supervisor_recommend_expert(state):
    state["next_action"] = "end"
    state["is_complete"] = True
    flags = dict(state.get("personalization_flags") or {})
    flags["need_confirm"] = True
    flags["expert_review_recommended"] = True
    state["personalization_flags"] = flags
    return state


def test_confirm_decline_expert_review_completed(monkeypatch, tmp_path):
    upload_dir = _seed_upload(tmp_path, "case-decline.jpg")
    monkeypatch.setattr(app_module, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(app_module, "resume_from_confirm_input", _mock_resume_from_confirm_input)
    monkeypatch.setattr(app_module, "supervisor_agent", _mock_supervisor_recommend_expert)

    client = TestClient(app_module.app)
    resp = client.post(
        "/api/diagnose-confirm",
        json={
            "trace_id": "trace-decline",
            "image_id": "case-decline.jpg",
            "crop_type": "番茄",
            "symptoms": ["斑点"],
            "choice": "other",
            "expert_review_decision": "decline",
        },
    )
    resp.raise_for_status()
    body = resp.json()
    assert body["status"] == "completed"
    assert body["expert_review_recommended"] is True
    assert body["expert_review_selected"] is False
    assert body["expert_review_status"] == "DECLINED"
    assert body["treatment_available"] is True


def test_confirm_accept_expert_review_pending(monkeypatch, tmp_path):
    upload_dir = _seed_upload(tmp_path, "case-accept.jpg")
    monkeypatch.setattr(app_module, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(app_module, "resume_from_confirm_input", _mock_resume_from_confirm_input)
    monkeypatch.setattr(app_module, "supervisor_agent", _mock_supervisor_recommend_expert)

    client = TestClient(app_module.app)
    resp = client.post(
        "/api/diagnose-confirm",
        json={
            "trace_id": "trace-accept",
            "image_id": "case-accept.jpg",
            "crop_type": "番茄",
            "symptoms": ["斑点"],
            "choice": "other",
            "expert_review_decision": "accept",
        },
    )
    resp.raise_for_status()
    body = resp.json()
    assert body["status"] == "pending_expert_review"
    assert body["expert_review_recommended"] is True
    assert body["expert_review_selected"] is True
    assert body["expert_review_status"] == "PENDING"
    assert body["treatment_available"] is False
