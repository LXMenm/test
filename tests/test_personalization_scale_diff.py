from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
import agents as agents_module
from personalization.profile_models import FarmerProfile, TreatmentConstraint
from personalization.profile_store import save_profile
import personalization.profile_store as profile_store


def _make_profile(
    farmer_id: str,
    *,
    farm_scale: str,
    pesticide_access_level: str,
    equipment: list[str],
    cultivation_mode: str,
) -> FarmerProfile:
    return FarmerProfile(
        farmer_id=farmer_id,
        farm_scale=farm_scale,
        pesticide_access_level=pesticide_access_level,
        equipment=equipment,
        cultivation_mode=cultivation_mode,
        constraints=TreatmentConstraint(
            prefer_organic=True,
            banned_ingredients=["百菌清"],
            harvest_window_days=5,
        ),
    )


class _DummyEngine:
    def diagnose_from_image(self, _):
        return "早疫病", 0.93, {"早疫病": 0.93, "晚疫病": 0.07}

    def diagnose_from_symptoms(self, **kwargs):
        return "早疫病", 0.85, "rule"

    def _get_disease_description(self, disease_type, symptoms):
        return f"{disease_type} - {','.join(symptoms or [])}"


class _DummyGraph:
    def invoke(self, state):
        state = agents_module.diagnosis_agent(state)
        state = agents_module.kb_retrieval_agent(state)
        state = agents_module.treatment_agent(state)
        return state


def _mock_call_llm(prompt: str, system_prompt: str, temperature: float = 0.3):
    if "输出JSON schema" in prompt and '"treatment_plan"' in prompt:
        payload = {
            "overview": "番茄早疫病综合处置",
            "immediate_actions": ["移除重病叶", "加强通风并保持叶面干燥"],
            "treatment_plan": {
                "BALCONY": [
                    "家庭场景：采用人工摘除病叶+低毒生物措施，避免专业化学农药依赖",
                    "小喷壶点喷可执行替代方案，必要时咨询当地农技",
                ],
                "SMALL_MEDIUM": [
                    "分区喷施与病株隔离，按标签合规执行",
                ],
                "LARGE_MECHANIZED": [
                    "制定规模化喷施SOP与巡检计划",
                    "使用无人机喷施流程结合弥雾设备提高覆盖率",
                    "建立周度监测与复查记录",
                ],
            },
            "prevention_plan": ["修剪清园", "降低湿度", "加强监测"],
            "resistance_management": ["轮换不同作用机制"],
            "safety_notes": ["临近采收注意安全间隔"],
            "follow_up": ["48-72小时复查病斑变化"],
            "personalization_reasons": [
                "种植规模差异导致执行路径不同",
                "购药能力与设备条件决定可执行方案边界",
            ],
            "follow_up_questions": ["近期湿度是否持续偏高？"],
        }
        return json.dumps(payload, ensure_ascii=False)

    if "请输出1-2条与位置/设施/偏好有关的诊断风险提醒" in prompt:
        return "温室需重点通风除湿，减少叶面结露。"

    return "{}"


def _run_once(client: TestClient, farmer_id: str) -> dict:
    image_path = Path("exam.JPG")
    with image_path.open("rb") as f:
        files = {"file": (image_path.name, f, "image/jpeg")}
        data = {
            "crop_type": "番茄",
            "symptoms": "叶片黄化,斑点",
            "farmer_id": farmer_id,
        }
        response = client.post("/api/diagnose-image", files=files, data=data)
    response.raise_for_status()
    return response.json()


def test_personalization_scale_diff_endpoint(monkeypatch, tmp_path):
    monkeypatch.setattr(profile_store, "PROFILE_DIR", tmp_path / "profiles")

    save_profile(
        _make_profile(
            "FA",
            farm_scale="BALCONY",
            pesticide_access_level="NONE",
            equipment=[],
            cultivation_mode="SOIL",
        )
    )
    save_profile(
        _make_profile(
            "FB",
            farm_scale="GREENHOUSE_LARGE",
            pesticide_access_level="FULL",
            equipment=["DRONE", "MIST_BLOWER"],
            cultivation_mode="SOIL",
        )
    )

    monkeypatch.setattr(app_module, "get_diagnosis_engine", lambda **kwargs: _DummyEngine())
    monkeypatch.setattr(agents_module, "get_diagnosis_engine", lambda **kwargs: _DummyEngine())
    monkeypatch.setattr(app_module, "build_graph", lambda: _DummyGraph())
    monkeypatch.setattr(agents_module, "call_llm", _mock_call_llm)

    client = TestClient(app_module.app)
    resp_a = _run_once(client, "FA")
    resp_b = _run_once(client, "FB")

    reasons_a = resp_a.get("personalization_reasons") or []
    reasons_b = resp_b.get("personalization_reasons") or []
    assert len(reasons_a) >= 2
    assert len(reasons_b) >= 2
    assert any("规模" in r or "购药" in r or "设备" in r for r in reasons_a)
    assert any("规模" in r or "购药" in r or "设备" in r for r in reasons_b)

    treatment_a = ((resp_a.get("treatment") or {}).get("plan") or "")
    treatment_b = ((resp_b.get("treatment") or {}).get("plan") or "")

    forbidden_a = ["无人机", "DRONE", "规模化喷施", "机械化"]
    for kw in forbidden_a:
        assert kw not in treatment_a

    expected_b = ["无人机", "喷施流程", "规模化", "SOP", "监测"]
    assert any(kw in treatment_b for kw in expected_b)

    assert treatment_a != treatment_b
