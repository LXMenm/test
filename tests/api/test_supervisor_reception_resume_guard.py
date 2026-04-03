from __future__ import annotations

import agents as agents_module
import workflow as workflow_module
from state import create_initial_state
from workflow import build_graph


def test_supervisor_does_not_repeat_reception_after_reception_complete():
    decision = agents_module._deterministic_supervisor_decision(  # noqa: SLF001
        {
            "current_step": "reception_complete",
            "next_action": "reception",
            "final_disease": None,
            "disease_type": None,
            "final_confidence": None,
            "disease_confidence": None,
            "kb_snapshot": None,
            "treatment_plan": None,
            "prevention_advice": None,
            "verification_result": None,
        },
        flags={},
        missing_profile_fields=[],
    )
    assert decision[0] == "diagnosis"


def test_reception_agent_clears_stale_next_action(monkeypatch):
    monkeypatch.setattr(agents_module, "append_trace_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        agents_module,
        "kb_manager",
        type("KB", (), {"normalize_symptoms": staticmethod(lambda symptoms: list(symptoms))})(),
    )
    monkeypatch.setattr(
        agents_module,
        "call_llm",
        lambda *_args, **_kwargs: '{"growth_stage": null, "symptoms": ["叶片黄化"]}',
    )
    state = create_initial_state("番茄叶片黄化")
    state["next_action"] = "reception"
    out = agents_module.reception_agent(state)
    assert out.get("current_step") == "reception_complete"
    assert out.get("next_action") is None


def test_initial_flow_no_double_reception_and_reaches_verification(monkeypatch):
    calls = {"reception": 0, "diagnosis": 0, "kb": 0, "treatment": 0, "verification": 0}

    def _reception(state):
        calls["reception"] += 1
        state["current_step"] = "reception_complete"
        # 模拟陈旧值残留，验证 supervisor 不会再次误吃该值
        state["next_action"] = "reception"
        state["symptoms"] = ["叶片黄化"]
        state["crop_type"] = "番茄"
        return state

    def _diagnosis(state):
        calls["diagnosis"] += 1
        state["current_step"] = "diagnosis_complete"
        state["final_disease"] = "早疫病"
        state["disease_type"] = "早疫病"
        state["final_confidence"] = 0.8
        state["disease_confidence"] = 0.8
        return state

    def _kb(state):
        calls["kb"] += 1
        state["current_step"] = "kb_retrieval_complete"
        state["kb_snapshot"] = {"disease": "早疫病"}
        return state

    def _treatment(state):
        calls["treatment"] += 1
        state["current_step"] = "treatment_complete"
        state["treatment_plan"] = "mock plan"
        state["prevention_advice"] = "mock prevention"
        return state

    def _verification(state):
        calls["verification"] += 1
        state["current_step"] = "verification_complete"
        state["verification_result"] = {"passed": True}
        state["verification_passed"] = True
        return state

    monkeypatch.setattr(workflow_module, "supervisor_agent", agents_module.supervisor_agent)
    monkeypatch.setattr(workflow_module, "reception_agent", _reception)
    monkeypatch.setattr(workflow_module, "diagnosis_agent", _diagnosis)
    monkeypatch.setattr(workflow_module, "kb_retrieval_agent", _kb)
    monkeypatch.setattr(workflow_module, "treatment_agent", _treatment)
    monkeypatch.setattr(workflow_module, "verification_agent", _verification)
    monkeypatch.setattr(agents_module, "append_trace_event", lambda *_args, **_kwargs: None)

    graph = build_graph()
    state = create_initial_state("test")
    final_state = graph.invoke(state, config={"recursion_limit": 80})

    assert calls["reception"] == 1
    assert calls["diagnosis"] == 1
    assert calls["kb"] == 1
    assert calls["treatment"] == 1
    assert calls["verification"] == 1
    assert final_state.get("verification_result") is not None
    assert final_state.get("workflow_error") is None
