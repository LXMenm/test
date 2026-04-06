from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

import app as app_module


class _DummyImageEngine:
    def diagnose_from_image(self, _):
        return "早疫病", 0.91, {"早疫病": 0.91, "晚疫病": 0.09}

    def diagnose_from_symptoms(self, **kwargs):
        return "早疫病", 0.75, "rule"


class _StaticGraph:
    def __init__(self, final_state):
        self.final_state = final_state

    def invoke(self, state, config=None):
        merged = dict(state)
        merged.update(self.final_state)
        return merged


def test_build_confirm_explanation_mapping_cases() -> None:
    cases = [
        # 强冲突
        (
            {"fusion_case": "conflict", "image_reliable": True, "text_reliable": True, "fallback_reason": ["image_text_conflict"]},
            "IMAGE_TEXT_CONFLICT",
            "reupload_image_and_verify_symptoms",
            "image_and_text",
            ["image", "symptoms"],
        ),
        # 弱冲突 + image_only：不能升级成 IMAGE_TEXT_CONFLICT
        (
            {
                "fusion_case": "image_weak_text_strong",
                "image_reliable": False,
                "text_reliable": True,
                "supplement_mode": "image_only",
                "fallback_reason": ["low_confidence", "weak_image_text_conflict"],
            },
            "IMAGE_QUALITY_LOW",
            "reupload_image",
            "image",
            ["image"],
        ),
        # 文本弱
        (
            {"image_reliable": True, "text_reliable": False, "supplement_mode": "text_only", "fallback_reason": []},
            "SYMPTOM_TEXT_INSUFFICIENT",
            "supplement_symptoms",
            "text",
            ["symptoms"],
        ),
        # 双弱
        (
            {
                "fusion_case": "both_weak",
                "image_reliable": False,
                "text_reliable": False,
                "supplement_mode": "image_and_text",
                "fallback_reason": ["both_modalities_weak"],
            },
            "BOTH_IMAGE_AND_TEXT_WEAK",
            "reupload_image_and_supplement_symptoms",
            "image_and_text",
            ["image", "symptoms"],
        ),
        # low_margin + image_only
        (
            {"supplement_mode": "image_only", "fallback_reason": ["low_margin"]},
            "LOW_DISCRIMINATION_NEED_KEY_FEATURES",
            "supplement_key_features",
            "image",
            ["image"],
        ),
        # low_margin + text_only
        (
            {"supplement_mode": "text_only", "fallback_reason": ["low_margin"]},
            "LOW_DISCRIMINATION_NEED_KEY_FEATURES",
            "supplement_key_features",
            "text",
            ["symptoms"],
        ),
    ]
    for overrides, code, action, ui_mode, fields in cases:
        payload = {
            "need_confirm": True,
            "fusion_case": None,
            "image_reliable": None,
            "text_reliable": None,
            "supplement_mode": "none",
            "fallback_reason": [],
            "follow_up_questions": [],
        }
        payload.update(overrides)
        result = app_module.build_confirm_explanation_v2(**payload)
        assert result["confirm_reason_code"] == code
        assert result["recommended_action"] == action
        assert result["confirm_ui_mode"] == ui_mode
        assert result["confirm_fields"] == fields

    regression_payload = {
        "need_confirm": True,
        "fusion_case": "image_weak_text_strong",
        "image_reliable": False,
        "text_reliable": True,
        "supplement_mode": "image_only",
        "fallback_reason": ["low_confidence", "weak_image_text_conflict"],
        "follow_up_questions": [],
    }
    regression_result = app_module.build_confirm_explanation_v2(**regression_payload)
    assert regression_result["confirm_reason_code"] != "IMAGE_TEXT_CONFLICT"


def test_build_confirm_explanation_image_only_must_not_be_overridden_by_conflict_reason() -> None:
    payload = {
        "need_confirm": True,
        "fusion_case": "image_weak_text_strong",
        "image_reliable": False,
        "text_reliable": True,
        "supplement_mode": "image_only",
        "fallback_reason": ["low_confidence", "weak_image_text_conflict", "image_text_conflict"],
        "follow_up_questions": ["请补充叶背特征"],
    }
    result = app_module.build_confirm_explanation_v2(**payload)
    assert result["confirm_reason_code"] == "IMAGE_QUALITY_LOW"
    assert result["confirm_ui_mode"] == "image"
    assert result["recommended_action"] == "reupload_image"
    assert result["confirm_fields"] == ["image"]
    assert "重新上传图片" in (result["confirm_message"] or "")
    assert result["confirm_reason_code"] != "IMAGE_TEXT_CONFLICT"
    assert result["confirm_ui_mode"] != "image_and_text"


def test_blurry_conflict_case_explain_should_be_image_quality_low() -> None:
    payload = {
        "need_confirm": True,
        "fusion_case": "image_weak_text_strong",
        "image_reliable": False,
        "text_reliable": True,
        "supplement_mode": "image_only",
        "fallback_reason": ["weak_image_text_conflict"],
        "follow_up_questions": [],
    }
    result = app_module.build_confirm_explanation_v2(**payload)
    assert result["confirm_reason_code"] == "IMAGE_QUALITY_LOW"
    assert result["confirm_ui_mode"] == "image"
    assert result["recommended_action"] == "reupload_image"
    assert result["confirm_reason_code"] != "IMAGE_TEXT_CONFLICT"
    assert result["confirm_ui_mode"] != "image_and_text"


def test_build_confirm_explanation_filters_follow_ups_by_mode() -> None:
    text_mode = app_module.build_confirm_explanation_v2(
        need_confirm=True,
        fusion_case=None,
        image_reliable=True,
        text_reliable=False,
        supplement_mode="text_only",
        fallback_reason=[],
        follow_up_questions=["请重新拍一张清晰图片", "请描述病斑边缘颜色"],
    )
    assert text_mode["confirm_ui_mode"] == "text"
    assert text_mode["confirm_fields"] == ["symptoms"]
    assert "重新拍一张清晰图片" not in " ".join(text_mode["filtered_follow_up_questions"])

    image_mode = app_module.build_confirm_explanation_v2(
        need_confirm=True,
        fusion_case=None,
        image_reliable=False,
        text_reliable=True,
        supplement_mode="image_only",
        fallback_reason=[],
        follow_up_questions=["请重新拍一张清晰图片", "请描述病斑边缘颜色"],
    )
    assert image_mode["confirm_ui_mode"] == "image"
    assert image_mode["confirm_fields"] == ["image"]
    assert image_mode["filtered_follow_up_questions"] == ["请重新拍一张清晰图片"]

    both_mode = app_module.build_confirm_explanation_v2(
        need_confirm=True,
        fusion_case="both_weak",
        image_reliable=False,
        text_reliable=False,
        supplement_mode="image_and_text",
        fallback_reason=["both_modalities_weak"],
        follow_up_questions=["请重新拍一张清晰图片", "请描述病斑边缘颜色"],
    )
    assert both_mode["confirm_ui_mode"] == "image_and_text"
    assert both_mode["confirm_fields"] == ["image", "symptoms"]
    assert len(both_mode["filtered_follow_up_questions"]) == 2


def test_diagnose_image_returns_explain_fields(monkeypatch):
    monkeypatch.setattr(app_module, "emit_node_event", lambda *args, **kwargs: {})
    monkeypatch.setattr(app_module, "emit_final_event_once", lambda *args, **kwargs: True)
    monkeypatch.setattr(app_module, "append_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(app_module, "list_trace_events", lambda *args, **kwargs: [])
    monkeypatch.setattr(app_module, "Image", SimpleNamespace(open=lambda *_args, **_kwargs: SimpleNamespace(verify=lambda: None)))
    monkeypatch.setattr(
        app_module,
        "resolve_model",
        lambda model_id, allow_torch=False: (SimpleNamespace(model_id="mock-model", display_name="Mock Model", backend="mock", model_path="/models/mock.bin"), []),
    )
    monkeypatch.setattr(app_module, "get_diagnosis_engine", lambda **kwargs: _DummyImageEngine())
    monkeypatch.setattr(
        app_module,
        "build_graph",
        lambda: _StaticGraph(
                {
                    "trace_id": "t-image",
                    "final_disease": "早疫病",
                    "final_confidence": 0.6,
                    "final_source": "fusion",
                    "image_result": {
                        "disease": "早疫病",
                        "confidence": 0.91,
                        "top3": [("早疫病", 0.91), ("晚疫病", 0.09)],
                    },
                    "fusion_case": "conflict",
                    "image_reliable": False,
                    "text_reliable": True,
                "supplement_mode": "image_and_text",
                "personalization_flags": {"need_confirm": True, "fallback_reason": ["image_text_conflict"], "follow_up_questions": ["请补充病斑边缘特征"]},
            }
        ),
    )

    client = TestClient(app_module.app)
    resp = client.post("/api/diagnose-image", files={"file": ("case.jpg", b"fake-jpeg-content", "image/jpeg")}, data={"crop_type": "番茄"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["confirm_reason_code"] == "IMAGE_QUALITY_LOW"
    assert data["confirm_ui_mode"] == "image"
    assert data["confirm_fields"] == ["image"]
    assert data["follow_up_questions"] == []
    assert "请优先补充" not in (data.get("confirm_message") or "")
    assert data["recommended_action"] == "reupload_image"


def test_confirm_and_retry_endpoints_compatible_and_support_modes(monkeypatch):
    calls = []

    def _fake_core(_request, payload):
        calls.append(dict(payload))
        return {
            "trace_id": payload.get("trace_id") or "t-confirm",
            "image_id": payload.get("image_id") or "img-x.jpg",
            "status": "waiting_for_supplement",
            "need_confirm": True,
            "confirm_reason_code": "SYMPTOM_TEXT_INSUFFICIENT",
            "confirm_reason_text": "症状描述不足，缺少区分病害的关键信息",
            "recommended_action": "supplement_symptoms",
            "confirm_ui_mode": "text",
            "confirm_fields": ["symptoms"],
            "confirm_message": "症状描述不足，缺少区分病害的关键信息",
            "image_result": {"disease": "早疫病", "confidence": 0.5, "confidence_pct": 50.0, "top3": []},
            "final_disease": "早疫病",
            "fallback_used": False,
            "filtered": False,
            "filtered_reasons": [],
            "filtered_components": [],
            "personalization_reasons": [],
            "follow_up_questions": [],
            "historical_follow_up_questions": [],
            "missing_profile_fields": [],
            "expert_review_actions": [],
        }

    monkeypatch.setattr(app_module, "_diagnose_confirm_core", _fake_core)
    monkeypatch.setattr(app_module, "Image", SimpleNamespace(open=lambda *_args, **_kwargs: SimpleNamespace(verify=lambda: None)))

    client = TestClient(app_module.app)

    # 旧接口纯文本兼容
    r1 = client.post("/api/diagnose-confirm", json={"trace_id": "t1", "image_id": "img1.jpg", "symptoms": ["叶片黄化"]})
    assert r1.status_code == 200
    assert r1.json()["confirm_reason_code"] == "SYMPTOM_TEXT_INSUFFICIENT"

    # retry: 仅症状
    r2 = client.post("/api/diagnose-retry", data={"trace_id": "t2", "image_id": "img2.jpg", "symptoms": "叶片黄化,病斑扩大"})
    assert r2.status_code == 200

    # retry: 仅换图
    r3 = client.post("/api/diagnose-retry", data={"trace_id": "t3", "image_id": "img3.jpg"}, files={"file": ("new.jpg", b"fake-jpeg-content", "image/jpeg")})
    assert r3.status_code == 200

    # retry: 图 + 症状
    r4 = client.post(
        "/api/diagnose-retry",
        data={"trace_id": "t4", "image_id": "img4.jpg", "symptoms": "[\"卷叶\", \"黄化\"]"},
        files={"file": ("new2.jpg", b"fake-jpeg-content", "image/jpeg")},
    )
    assert r4.status_code == 200

    assert len(calls) == 4
    assert calls[1]["symptoms"] == ["叶片黄化", "病斑扩大"]
    assert calls[2]["image_id"] != "img3.jpg"
    assert calls[3]["symptoms"] == ["卷叶", "黄化"]


def test_diagnose_confirm_chain_filters_follow_ups_to_text_mode(monkeypatch, tmp_path):
    trace_id = "trace-confirm-filter"
    image_id = "confirm.jpg"
    (tmp_path / image_id).write_bytes(b"fake")
    monkeypatch.setattr(app_module, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(app_module, "emit_node_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(app_module, "emit_final_event_once", lambda *args, **kwargs: None)
    monkeypatch.setattr(app_module, "append_event", lambda *args, **kwargs: None)

    previous_case_event = {
        "trace_id": trace_id,
        "status": "waiting_for_supplement",
        "symptoms": ["叶片发黄"],
        "final_disease": "早疫病",
        "final_confidence": 0.61,
        "final_source": "fusion",
        "follow_up_questions": ["请补拍整株图片", "请描述病斑颜色"],
    }
    monkeypatch.setattr(app_module, "_latest_case_event_by_trace", lambda _trace_id: dict(previous_case_event))
    monkeypatch.setattr(app_module, "list_trace_events", lambda _trace_id: [dict(previous_case_event)])

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
    monkeypatch.setattr(app_module, "_resolve_profile_and_base", lambda *_args, **_kwargs: (None, None, None))
    monkeypatch.setattr(app_module, "build_personalization_context", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app_module, "build_personalization_flags", lambda *_args, **_kwargs: {})

    class _Graph:
        def invoke(self, state, config=None):
            _ = config
            out = dict(state)
            out.update(
                {
                    "final_disease": "早疫病",
                    "final_confidence": 0.61,
                    "final_source": "fusion",
                    "fusion_case": "image_weak_text_strong",
                    "image_reliable": True,
                    "text_reliable": False,
                    "supplement_mode": "text_only",
                    "personalization_flags": {
                        "need_confirm": True,
                        "fallback_reason": ["low_margin"],
                        "follow_up_questions": ["请补拍整株图片", "请描述病斑颜色"],
                    },
                    "follow_up_questions": ["请补拍整株图片", "请描述病斑颜色"],
                    "profile_follow_up_questions": [],
                    "diagnosis_follow_up_questions": [],
                    "diagnosis_evidence": {},
                    "image_result": {"disease": "早疫病", "confidence": 0.61, "top3": [("早疫病", 0.61)]},
                }
            )
            return out

    monkeypatch.setattr(app_module, "build_graph", lambda: _Graph())

    client = TestClient(app_module.app)
    resp = client.post(
        "/api/diagnose-confirm",
        json={"trace_id": trace_id, "image_id": image_id, "symptoms": "叶片发黄", "choice": "other"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["confirm_ui_mode"] == "text"
    assert body["confirm_fields"] == ["symptoms"]
    assert all("图" not in q for q in body["follow_up_questions"])
    assert "补拍" not in (body.get("confirm_message") or "")
