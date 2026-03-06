from __future__ import annotations

import json
from pathlib import Path

import agents as agents_module
from state import create_initial_state
from workflow import build_graph


class _DummyEngine:
    def diagnose_from_image(self, _):
        return "蜘蛛螨", 0.97, {"蜘蛛螨": 0.97, "早疫病": 0.03}

    def diagnose_from_symptoms(self, **kwargs):
        return "非番茄作物", 0.0, "本系统仅支持番茄病害诊断"

    def _get_disease_description(self, disease_type, symptoms):
        return f"{disease_type} - {','.join(symptoms or [])}"


def _mock_call_llm(prompt: str, system_prompt: str, temperature: float = 0.3):
    if "输出JSON schema" in prompt and '"treatment_plan"' in prompt:
        payload = {
            "overview": "蜘蛛螨处置",
            "immediate_actions": ["去除重度受害叶片"],
            "treatment_plan": {
                "BALCONY": ["阳台场景先进行局部处理"],
                "SMALL_MEDIUM": ["常规喷施并复查"],
                "LARGE_MECHANIZED": ["规模化执行并复查"],
            },
            "prevention_plan": ["加强通风", "降低叶面湿度"],
            "resistance_management": ["轮换作用机制"],
            "safety_notes": ["遵守标签与安全间隔"],
            "follow_up": ["48小时复查"],
            "personalization_reasons": ["图像高置信度，优先直接处置"],
            "follow_up_questions": [],
        }
        return json.dumps(payload, ensure_ascii=False)

    if "请输出1-2条与位置/设施/偏好有关的诊断风险提醒" in prompt:
        return "温室注意通风降湿。"

    return json.dumps({"growth_stage": None, "symptoms": ["叶片失绿", "有斑点"]}, ensure_ascii=False)


def test_first_diagnosis_has_image_path_and_no_confirm(monkeypatch, tmp_path):
    image = tmp_path / "leaf.jpg"
    image.write_bytes(b"fake")

    monkeypatch.setattr(agents_module, "get_diagnosis_engine", lambda **kwargs: _DummyEngine())
    monkeypatch.setattr(agents_module, "call_llm", _mock_call_llm)

    state = create_initial_state(f"作物类型：番茄，图片路径：{image}")
    graph = build_graph()
    final_state = graph.invoke(state, config={"recursion_limit": 80})

    diagnosis_events = [e for e in final_state.get("trace_events", []) if e.get("agent") == "diagnosis"]
    assert diagnosis_events, "缺少 diagnosis trace"
    assert diagnosis_events[0].get("inputs", {}).get("image_path")

    steps = [e.get("step") for e in final_state.get("trace_events", [])]
    assert "kb_retrieval_complete" in steps
    assert "treatment_complete" in steps

    flags = final_state.get("personalization_flags") or {}
    assert flags.get("need_confirm") is False

    decisions = [e.get("decision", {}) for e in final_state.get("trace_events", []) if e.get("agent") == "supervisor"]
    actions = [d.get("next_action") for d in decisions if isinstance(d, dict)]
    assert "reception" not in actions[1:], "不应在首次高置信诊断后自动进入二次确认链路"
