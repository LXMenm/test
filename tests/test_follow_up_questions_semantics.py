from __future__ import annotations

import agents as agents_module
from personalization.utils import normalize_follow_up_questions
from state import create_initial_state


def test_normalize_follow_up_questions_filters_reasons_and_keeps_questions():
    items = [
        "购药能力受限：优先可获得且操作简化的方案",
        "土培场景强调通风",
        "是否具备喷施设备（背负式喷雾器、弥雾机或无人机）",
        "当前番茄处于哪个生育期（苗期/开花/结果）",
    ]

    normalized = normalize_follow_up_questions(items)

    assert all(q.endswith(("？", "?")) for q in normalized)
    assert all("购药能力受限" not in q for q in normalized)
    assert all("土培场景强调" not in q for q in normalized)
    assert any("喷施设备" in q for q in normalized)
    assert any("生育期" in q for q in normalized)


def test_supervisor_follow_ups_only_from_missing_fields_not_personalization_reasons(monkeypatch):
    monkeypatch.setattr(agents_module, "append_trace", lambda *args, **kwargs: None)
    state = create_initial_state("作物类型：番茄")
    state["current_step"] = "diagnosis_complete"
    state["final_disease"] = "早疫病"
    state["disease_type"] = "早疫病"
    state["kb_snapshot"] = {"disease": "早疫病", "treatment": "t", "prevention": "p"}
    state["treatment_plan"] = "已有治疗"
    state["prevention_advice"] = "已有预防"

    flags = state.get("personalization_flags") or {}
    flags["missing_profile_fields"] = ["equipment", "growth_stage"]
    flags["follow_up_questions"] = [
        "购药能力受限：优先可获得且操作简化的方案",
        "土培场景强调叶面干燥",
    ]
    flags["need_confirm"] = False
    flags["personalization_reasons"] = ["购药能力受限：优先可获得且操作简化的方案"]
    state["personalization_flags"] = flags

    updated = agents_module.supervisor_agent(state)
    follow_ups = (updated.get("personalization_flags") or {}).get("follow_up_questions") or []

    assert follow_ups
    assert all(item.endswith(("？", "?")) for item in follow_ups)
    assert all("购药能力受限" not in item for item in follow_ups)
    assert any("喷施设备" in item for item in follow_ups)
    assert any("生育期" in item for item in follow_ups)


def test_normalize_follow_up_questions_semantic_dedup_keeps_single_environment_prompt():
    items = [
        "近期是否高湿、连阴雨、棚内通风差？",
        "近3天是否出现高湿、连阴雨或棚内通风不足？",
        "请描述病斑颜色、边缘是否清晰、是否有水渍感或霉层。",
        "病斑是同心轮纹、靶心状还是水渍状扩展？",
    ]

    normalized = normalize_follow_up_questions(items)

    assert normalized.count("近3天是否出现高湿、连阴雨或棚内通风不足？") == 1
    assert sum("病斑" in item for item in normalized) == 1
    assert all(item.endswith(("？", "?")) for item in normalized)
