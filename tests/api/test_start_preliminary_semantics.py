from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

import app as app_module


class _StartKB:
    symptom_tiers = {"叶片黄化": "generic", "叶背白霉": "discriminative"}
    symptom_candidates = {"叶片黄化": ["黄化曲叶病毒病"], "叶背白霉": ["晚疫病"]}

    @staticmethod
    def normalize_symptoms(symptoms):
        return [str(item).strip() for item in (symptoms or []) if str(item).strip()]

    @staticmethod
    def has_effective_text_evidence(symptoms, **_kwargs):
        return bool(symptoms)

    @staticmethod
    def has_discriminative_text_evidence(symptoms):
        return "叶背白霉" in (symptoms or [])

    @staticmethod
    def get_candidate_diseases_from_symptoms(symptoms):
        if "叶背白霉" in (symptoms or []):
            return ["晚疫病"]
        return ["黄化曲叶病毒病"] if symptoms else []

    @staticmethod
    def generate_text_follow_up_questions(symptoms, text_probs=None):
        _ = text_probs
        if not symptoms:
            return []
        return ["请补充病斑是否同心轮纹", "请描述叶背是否有霉层"]


def _prepare_start_mocks(monkeypatch, *, probs):
    monkeypatch.setattr(app_module, "emit_node_event", lambda *args, **kwargs: None)

    async def _fake_save_uploaded_image(*_args, **_kwargs):
        return "img-start.jpg", app_module.UPLOAD_DIR / "img-start.jpg"

    monkeypatch.setattr(app_module, "_save_uploaded_image", _fake_save_uploaded_image)
    _ = probs
    monkeypatch.setattr(
        app_module,
        "resolve_model",
        lambda model_id, allow_torch=False: (SimpleNamespace(model_path="/tmp/mock.bin", backend="mock", model_id="mock", display_name="mock"), []),
    )
    monkeypatch.setattr(app_module, "get_diagnosis_engine", lambda **kwargs: SimpleNamespace(diagnose_from_image=lambda _path: ("早疫病", 0.78, {"早疫病": 0.78})))
    monkeypatch.setattr(app_module, "get_kb_manager", lambda: _StartKB())


def test_start_interface_returns_preliminary_not_final_semantics(monkeypatch):
    _prepare_start_mocks(monkeypatch, probs={"早疫病": 0.78, "晚疫病": 0.22})
    client = TestClient(app_module.app)

    resp = client.post(
        "/api/diagnose-image/start",
        files={"file": ("case.jpg", b"fake-jpeg-content", "image/jpeg")},
        data={"crop_type": "番茄", "symptoms": "叶片黄化，叶背白霉"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["result_stage"] == "precheck_internal"
    assert "preliminary_disease" not in body
    assert "final_disease" not in body
    assert body["interface_role"] == "internal_precheck"
    assert body["entrypoint"] == "diagnose_image_start"
    assert body["first_user_visible_result"] is False
    assert body["precheck_semantics_exposed"] is True
    assert body["user_visible"] is False
    assert body["recommended_next_step"] == "continue_to_formal_graph_diagnosis"
    assert body["recommended_next_endpoint"] == "/api/diagnose-image/continue"


def test_start_interface_does_not_expose_image_only_result_as_final(monkeypatch):
    _prepare_start_mocks(monkeypatch, probs={"早疫病": 0.93, "晚疫病": 0.07})
    client = TestClient(app_module.app)

    resp = client.post(
        "/api/diagnose-image/start",
        files={"file": ("case.jpg", b"fake-jpeg-content", "image/jpeg")},
        data={"crop_type": "番茄"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["result_stage"] == "precheck_internal"
    assert body["first_user_visible_result"] is False
    assert body["precheck_semantics_exposed"] is True
    assert "preliminary_disease" not in body
    assert "final_disease" not in body


def test_start_interface_generates_real_follow_up_questions(monkeypatch):
    _prepare_start_mocks(monkeypatch, probs={"早疫病": 0.2, "晚疫病": 0.19})
    client = TestClient(app_module.app)

    resp = client.post(
        "/api/diagnose-image/start",
        files={"file": ("case.jpg", b"fake-jpeg-content", "image/jpeg")},
        data={"crop_type": "番茄", "symptoms": "叶片黄化，叶背白霉"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["result_stage"] == "precheck_internal"
    assert "follow_up_questions" not in body
