from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
import agents as agents_module
from personalization.profile_rules import apply_personalization_to_treatment
from personalization.profile_models import FarmerProfile, BaseProfile, TreatmentConstraint
from agents import _find_missing_profile_fields
from personalization.profile_store import save_profile
import personalization.profile_store as profile_store
from knowledge_base import get_kb_manager


class _DummyEngine:
    def diagnose_from_image(self, _):
        return "早疫病", 0.93, {"早疫病": 0.93, "晚疫病": 0.07}

    def diagnose_from_symptoms(self, **kwargs):
        return "早疫病", 0.86, "rule"

    def _get_disease_description(self, disease_type, symptoms):
        return f"{disease_type}:{','.join(symptoms or [])}"


class _DummyGraph:
    def invoke(self, state, config=None):
        state = agents_module.diagnosis_agent(state)
        state = agents_module.kb_retrieval_agent(state)
        state = agents_module.treatment_agent(state)
        return state


def _mock_call_llm(prompt: str, system_prompt: str, temperature: float = 0.3):
    if "输出JSON schema" in prompt and '"treatment_plan"' in prompt:
        payload = {
            "overview": "番茄早疫病处置",
            "immediate_actions": ["移除病叶", "化学农药请按标签执行"],
            "treatment_plan": {
                "FAMILY": ["家庭场景优先低门槛路径，必要时化学药剂点喷"],
                "MID": ["分区人工处置并滚动复查"],
                "ENTERPRISE": ["按SOP规模化执行与台账复盘"],
            },
            "prevention_plan": ["通风控湿", "清园"],
            "resistance_management": ["轮换作用机制"],
            "safety_notes": ["采收窗口遵循安全间隔"],
            "follow_up": ["48小时复查"],
            "personalization_reasons": ["约束已应用"],
            "follow_up_questions": [],
        }
        return json.dumps(payload, ensure_ascii=False)
    if "请输出1-2条与位置/设施/偏好有关的诊断风险提醒" in prompt:
        return "注意持续通风控湿"
    return "{}"


def test_constraint_diff_prefer_organic_and_banned_components():
    plan = "建议使用代森锰锌与化学农药轮换。"
    prevention = "必要时补喷化学药剂。"

    _, _, with_constraints = apply_personalization_to_treatment(
        plan,
        prevention,
        {"prefer_organic": True, "banned_ingredients": ["代森锰锌"], "harvest_window_days": None},
    )
    _, _, without_constraints = apply_personalization_to_treatment(
        plan,
        prevention,
        {"prefer_organic": False, "banned_ingredients": [], "harvest_window_days": None},
    )

    assert with_constraints["personalization_applied"] is True
    assert with_constraints["filtered"] is True
    assert "代森锰锌" in with_constraints["filtered_components"]
    assert any("移除" in item for item in with_constraints["filtered_reasons"])

    assert without_constraints["personalization_applied"] is False
    assert without_constraints["filtered"] is False
    assert without_constraints["filtered_reasons"] == []
    assert without_constraints["filtered_components"] == []


def test_constraint_diff_harvest_window_only_adds_warning():
    plan = "建议先清理病叶并改善通风。"
    prevention = "保持清园。"
    new_plan, _, outputs = apply_personalization_to_treatment(
        plan,
        prevention,
        {"prefer_organic": False, "banned_ingredients": [], "harvest_window_days": 3},
    )

    assert outputs["personalization_applied"] is True
    assert outputs["filtered"] is True
    assert outputs["filtered_components"] == []
    assert any("采收窗口限制" in item for item in outputs["filtered_reasons"])
    assert "临近采收" in new_plan


def test_missing_optional_fields_still_returns_treatment_and_followups(monkeypatch, tmp_path):
    monkeypatch.setattr(profile_store, "PROFILE_DIR", tmp_path / "profiles")

    profile = FarmerProfile(
        farmer_id="MISSING_OPT",
        farm_scale="MEDIUM",
        pesticide_access_level="LIMITED",
        equipment=[],
        cultivation_mode="SOIL",
        bases={
            "B1": BaseProfile(base_id="B1", location="山东", environment="温室", growth_stage=None),
        },
        active_base_id="B1",
        constraints=TreatmentConstraint(prefer_organic=True, banned_ingredients=[], harvest_window_days=None),
    )
    save_profile(profile)

    monkeypatch.setattr(app_module, "get_diagnosis_engine", lambda **kwargs: _DummyEngine())
    monkeypatch.setattr(agents_module, "get_diagnosis_engine", lambda **kwargs: _DummyEngine())
    monkeypatch.setattr(app_module, "build_graph", lambda: _DummyGraph())
    monkeypatch.setattr(agents_module, "call_llm", _mock_call_llm)

    client = TestClient(app_module.app)
    image_path = Path("exam.JPG")
    with image_path.open("rb") as f:
        resp = client.post(
            "/api/diagnose-image",
            files={"file": (image_path.name, f, "image/jpeg")},
            data={"crop_type": "番茄", "symptoms": "叶片有斑点", "farmer_id": "MISSING_OPT", "base_id": "B1"},
        )
    resp.raise_for_status()
    payload = resp.json()

    assert (payload.get("treatment") or {}).get("plan")

    missing = _find_missing_profile_fields(profile, profile.bases.get("B1"), policy=None)
    assert "growth_stage" in missing
    assert "equipment" not in missing


def test_virus_disease_kb_has_no_cure_claims():
    kb = get_kb_manager()
    plan = kb.get_treatment_plan("黄化曲叶病毒病")
    text = f"{plan.get('treatment','')}\n{plan.get('prevention','')}"
    assert "特效药" not in text
    assert "治愈病毒病" not in text
