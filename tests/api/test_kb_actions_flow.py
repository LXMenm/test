from __future__ import annotations

import json

import agents as agents_module
from knowledge_base.kb_manager import KnowledgeBaseManager
from state import create_initial_state


def test_kb_treatment_plan_and_snapshot_include_actions():
    kb = KnowledgeBaseManager()
    plan = kb.get_treatment_plan("早疫病")
    assert isinstance(plan.get("actions"), dict)
    assert plan["actions"]["treatment_plan"]["FAMILY"]
    assert plan["actions"]["treatment_plan"]["MID"]
    assert plan["actions"]["treatment_plan"]["ENTERPRISE"]

    state = create_initial_state("作物类型：番茄")
    state["final_disease"] = "早疫病"
    state = agents_module.kb_retrieval_agent(state)

    snapshot = state.get("kb_snapshot") or {}
    assert isinstance(snapshot.get("actions"), dict)
    assert isinstance(snapshot.get("ingredients"), list)
    assert snapshot.get("actions", {}).get("treatment_plan", {}).get("FAMILY")


def test_treatment_agent_falls_back_to_kb_actions_on_constraint_violation(monkeypatch):
    state = create_initial_state("作物类型：番茄")
    state["final_disease"] = "早疫病"
    state["disease_type"] = "早疫病"
    state["crop_growth_stage"] = "结果期"
    state["symptoms"] = ["叶片黄化", "褐色病斑"]
    state["disease_description"] = "叶片出现典型同心轮纹"
    state["kb_snapshot"] = {
        "disease": "早疫病",
        "description": "测试快照",
        "treatment": "旧文本方案",
        "prevention": "旧文本预防",
        "ingredients": ["代森锰锌"],
        "actions": {
            "immediate_actions": ["KB动作-立即隔离病叶"],
            "treatment_plan": {
                "FAMILY": ["KB动作-FAMILY-避免禁用成分，优先物理防治"],
                "MID": ["KB动作-MID-分区处置"],
                "ENTERPRISE": ["KB动作-ENTERPRISE-SOP执行"],
            },
            "prevention_plan": ["KB动作-预防-加强通风"],
            "resistance_management": ["KB动作-抗性-轮换机制"],
            "safety_notes": ["KB动作-安全-遵守安全间隔"],
            "follow_up": ["KB动作-复查-48小时复核"],
        },
    }
    state["personalization_flags"] = {
        "farm_scale": "SMALL",
        "pesticide_access_level": "NONE",
        "equipment": [],
        "banned_ingredients": ["代森锰锌"],
    }
    state["personalization_policy"] = {
        "hard_constraints": {
            "banned_ingredients": ["代森锰锌"],
            "forbid_professional_pesticides": True,
        }
    }

    calls = {"n": 0}

    def _mock_call_llm(prompt: str, system_prompt: str, temperature: float = 0.3):
        if "输出JSON schema" in prompt and '"treatment_plan"' in prompt:
            calls["n"] += 1
            payload = {
                "overview": "违规方案",
                "immediate_actions": ["建议使用代森锰锌"],
                "treatment_plan": {
                    "FAMILY": ["建议使用代森锰锌进行喷施"],
                    "MID": ["建议使用代森锰锌进行喷施"],
                    "ENTERPRISE": ["建议使用代森锰锌进行喷施"],
                },
                "prevention_plan": ["保持通风"],
                "resistance_management": ["轮换机制"],
                "safety_notes": ["遵守安全间隔"],
                "follow_up": ["48小时复查"],
                "personalization_reasons": [],
                "follow_up_questions": [],
            }
            return json.dumps(payload, ensure_ascii=False)
        return "{}"

    monkeypatch.setattr(agents_module, "call_llm", _mock_call_llm)

    updated = agents_module.treatment_agent(state)
    plan = updated.get("treatment_plan") or ""
    flags = updated.get("personalization_flags") or {}

    assert calls["n"] == 2
    assert "KB动作-FAMILY-避免禁用成分" in plan
    assert flags.get("llm_failed") is True
    assert flags.get("llm_failed_reason") == "constraint_violation"
