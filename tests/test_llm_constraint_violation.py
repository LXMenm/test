from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
import agents as agents_module
import personalization.profile_store as profile_store
from personalization.profile_models import FarmerProfile, TreatmentConstraint
from personalization.profile_store import save_profile


class _DummyEngine:
    def diagnose_from_image(self, _):
        return "早疫病", 0.95, {"早疫病": 0.95, "晚疫病": 0.05}

    def diagnose_from_symptoms(self, **kwargs):
        return "早疫病", 0.80, "rule"

    def _get_disease_description(self, disease_type, symptoms):
        return f"{disease_type} - {','.join(symptoms or [])}"


def _make_profile() -> FarmerProfile:
    return FarmerProfile(
        farmer_id="F_LLM",
        farm_scale="SMALL",
        pesticide_access_level="NONE",
        equipment=[],
        cultivation_mode="SOIL",
        constraints=TreatmentConstraint(
            prefer_organic=False,
            banned_ingredients=["代森锰锌"],
            harvest_window_days=None,
        ),
    )


def _seed_upload(tmp_path: Path, image_id: str) -> Path:
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    image_path = upload_dir / image_id
    image_path.write_bytes(b"fake-jpeg-content")
    return upload_dir


def _mock_reception_diagnosis(state):
    state["image_diagnosis"] = {
        "top1": {"disease": "早疫病", "confidence": 0.95},
        "top3": [("早疫病", 0.95), ("晚疫病", 0.05)],
    }
    state["final_disease"] = "早疫病"
    state["disease_type"] = "早疫病"
    state["disease_description"] = "叶片出现典型病斑"
    return state


def _mock_kb_retrieval(state):
    state["kb_snapshot"] = {"source": "test-kb"}
    return state


def _make_llm_payload(line: str) -> str:
    payload = {
        "overview": "番茄早疫病综合处置",
        "immediate_actions": ["移除重病叶", "加强通风"],
        "treatment_plan": {
            "FAMILY": [line],
            "MID": ["中等规模方案"],
            "ENTERPRISE": ["企业级方案，含SOP和监测"],
        },
        "prevention_plan": ["清园", "控湿"],
        "resistance_management": ["轮换作用机制"],
        "safety_notes": ["按标签与安全间隔执行"],
        "follow_up": ["48小时复查"],
        "personalization_reasons": ["基于档案约束"],
        "follow_up_questions": [],
    }
    return json.dumps(payload, ensure_ascii=False)


def _post_confirm(client: TestClient, image_id: str) -> dict:
    response = client.post(
        "/api/diagnose-confirm",
        json={
            "trace_id": "trace-test",
            "previous_trace_id": "trace-test",
            "image_id": image_id,
            "crop_type": "番茄",
            "symptoms": ["叶片黄化", "斑点"],
            "choice": "other",
            "farmer_id": "F_LLM",
        },
    )
    response.raise_for_status()
    return response.json()


def test_llm_constraint_violation_retry_success(monkeypatch, tmp_path):
    monkeypatch.setattr(profile_store, "PROFILE_DIR", tmp_path / "profiles")
    save_profile(_make_profile())

    upload_dir = _seed_upload(tmp_path, "case-success.jpg")
    monkeypatch.setattr(app_module, "UPLOAD_DIR", upload_dir)

    monkeypatch.setattr(app_module, "diagnosis_agent", _mock_reception_diagnosis)
    monkeypatch.setattr(app_module, "kb_retrieval_agent", _mock_kb_retrieval)
    monkeypatch.setattr(agents_module, "get_diagnosis_engine", lambda **kwargs: _DummyEngine())

    calls = {"n": 0}

    def _mock_call_llm(prompt: str, system_prompt: str, temperature: float = 0.3):
        if "输出JSON schema" in prompt and '"treatment_plan"' in prompt:
            calls["n"] += 1
            if calls["n"] == 1:
                return _make_llm_payload("建议使用代森锰锌进行处理")
            return _make_llm_payload("建议采用物理防治与咨询当地农技")
        return "{}"

    monkeypatch.setattr(agents_module, "call_llm", _mock_call_llm)

    client = TestClient(app_module.app)
    body = _post_confirm(client, "case-success.jpg")

    plan = ((body.get("treatment") or {}).get("plan") or "")
    assert calls["n"] == 2
    assert "代森锰锌" not in plan
    assert body.get("llm_failed") is False


def test_llm_constraint_violation_retry_then_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(profile_store, "PROFILE_DIR", tmp_path / "profiles")
    save_profile(_make_profile())

    upload_dir = _seed_upload(tmp_path, "case-fallback.jpg")
    monkeypatch.setattr(app_module, "UPLOAD_DIR", upload_dir)

    monkeypatch.setattr(app_module, "diagnosis_agent", _mock_reception_diagnosis)
    monkeypatch.setattr(app_module, "kb_retrieval_agent", _mock_kb_retrieval)
    monkeypatch.setattr(agents_module, "get_diagnosis_engine", lambda **kwargs: _DummyEngine())

    calls = {"n": 0}

    def _mock_call_llm(prompt: str, system_prompt: str, temperature: float = 0.3):
        if "输出JSON schema" in prompt and '"treatment_plan"' in prompt:
            calls["n"] += 1
            return _make_llm_payload("建议使用代森锰锌进行处理")
        return "{}"

    monkeypatch.setattr(agents_module, "call_llm", _mock_call_llm)

    client = TestClient(app_module.app)
    body = _post_confirm(client, "case-fallback.jpg")

    plan = ((body.get("treatment") or {}).get("plan") or "")
    assert calls["n"] == 2
    assert "代森锰锌" not in plan
    assert body.get("llm_failed") is True
    assert body.get("llm_failed_reason") == "constraint_violation"
