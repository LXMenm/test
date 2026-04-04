from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

import app as app_module
from symptom_parsing import parse_symptoms_input


def test_parse_symptoms_input_supports_chinese_punctuation() -> None:
    raw = "叶片黄化，病斑扩大、边缘发黑；叶背白霉\n茎部褐变"
    assert parse_symptoms_input(raw) == ["叶片黄化", "病斑扩大", "边缘发黑", "叶背白霉", "茎部褐变"]


def test_parse_symptoms_input_supports_json_list_string() -> None:
    raw = '["叶片黄化", "病斑扩大", "叶背白霉"]'
    assert parse_symptoms_input(raw) == ["叶片黄化", "病斑扩大", "叶背白霉"]


def test_parse_symptoms_input_dedupes_and_strips() -> None:
    raw = " 叶片黄化 ，叶片黄化,  病斑扩大 ; \n病斑扩大  "
    assert parse_symptoms_input(raw) == ["叶片黄化", "病斑扩大"]


def test_diagnose_confirm_accepts_mixed_punctuation_symptoms(monkeypatch) -> None:
    def _fake_core(_request, payload):
        return {"symptoms": app_module._normalize_symptoms_input(payload.get("symptoms"))}

    monkeypatch.setattr(app_module, "_diagnose_confirm_core", _fake_core)

    client = TestClient(app_module.app)
    resp = client.post(
        "/api/diagnose-confirm",
        json={"trace_id": "t-1", "image_id": "img-1.jpg", "symptoms": "叶片黄化，病斑扩大;叶背白霉\n茎部褐变"},
    )
    assert resp.status_code == 200
    assert resp.json()["symptoms"] == ["叶片黄化", "病斑扩大", "叶背白霉", "茎部褐变"]


def test_diagnose_image_start_accepts_mixed_punctuation_symptoms(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "emit_node_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(app_module, "cleanup_old_uploads", lambda: None)
    async def _fake_save_uploaded_image(*_args, **_kwargs):
        return "img-1.jpg", app_module.UPLOAD_DIR / "img-1.jpg"

    monkeypatch.setattr(app_module, "_save_uploaded_image", _fake_save_uploaded_image)
    monkeypatch.setattr(
        app_module,
        "resolve_model",
        lambda model_id, allow_torch=False: (SimpleNamespace(model_path="/tmp/mock.bin", backend="mock", model_id="mock", display_name="mock"), []),
    )
    monkeypatch.setattr(app_module, "get_diagnosis_engine", lambda **kwargs: SimpleNamespace(diagnose_from_image=lambda _path: ("早疫病", 0.1, {"早疫病": 0.1})))

    client = TestClient(app_module.app)
    resp = client.post(
        "/api/diagnose-image/start",
        files={"file": ("case.jpg", b"fake-jpeg-content", "image/jpeg")},
        data={"crop_type": "番茄", "symptoms": "叶片黄化，病斑扩大;叶背白霉\n茎部褐变"},
    )
    assert resp.status_code == 200
    assert resp.json()["follow_up_questions"] == ["叶片黄化", "病斑扩大", "叶背白霉"]
