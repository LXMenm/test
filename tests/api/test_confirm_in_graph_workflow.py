from __future__ import annotations

import workflow as workflow_module
import agents as agents_module
from agents import confirm_choice_step
from state import create_initial_state
from workflow import build_graph, route_next_step


def _stub_supervisor(state):
    requested = str(state.get("next_action") or "")
    if requested in {"confirm_input", "confirm_choice", "diagnosis", "verification", "end", "manual_review", "await_user_confirmation"}:
        return {**state, "next_action": requested}
    if not (state.get("final_disease") or state.get("disease_type")):
        return {**state, "next_action": "diagnosis"}
    if state.get("verification_result") is None:
        return {**state, "next_action": "verification"}
    return {**state, "next_action": "end"}


def test_route_next_step_supports_confirm_nodes():
    assert route_next_step({"next_action": "confirm_input"}) == "confirm_input"
    assert route_next_step({"next_action": "confirm_choice"}) == "confirm_choice"


def test_build_graph_contains_confirm_nodes():
    graph = build_graph()
    graph_nodes = set(graph.get_graph().nodes.keys())
    assert "confirm_input" in graph_nodes
    assert "confirm_choice" in graph_nodes


def test_confirm_input_runs_in_graph_and_calls_diagnosis(monkeypatch):
    calls = {"diagnosis": 0}

    def _diag(state):
        calls["diagnosis"] += 1
        state["final_disease"] = "补充诊断病害"
        state["disease_type"] = "补充诊断病害"
        state["final_confidence"] = 0.66
        state["disease_confidence"] = 0.66
        state["next_action"] = "end"
        return state

    monkeypatch.setattr(workflow_module, "supervisor_agent", _stub_supervisor)
    monkeypatch.setattr(workflow_module, "diagnosis_agent", _diag)
    monkeypatch.setattr(agents_module, "append_trace_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(agents_module, "kb_manager", type("KB", (), {"normalize_symptoms": staticmethod(lambda s: list(s))})())
    graph = build_graph()
    state = create_initial_state("confirm")
    state["trace_id"] = "trace-confirm-input"
    state["next_action"] = "confirm_input"
    state["historical_symptoms"] = ["叶片黄化"]
    state["incoming_symptoms"] = ["病斑扩大"]
    final_state = graph.invoke(state)
    assert calls["diagnosis"] == 1
    agents = [event.get("agent") for event in final_state.get("trace_events", [])]
    assert "confirm_input" in agents


def test_confirm_choice_runs_in_graph_without_re_diagnosis_and_to_verification(monkeypatch):
    calls = {"diagnosis": 0, "verification": 0}

    def _diag(state):
        calls["diagnosis"] += 1
        return state

    def _verify(state):
        calls["verification"] += 1
        state["verification_result"] = {"passed": True}
        state["next_action"] = "end"
        return state

    monkeypatch.setattr(workflow_module, "supervisor_agent", _stub_supervisor)
    monkeypatch.setattr(workflow_module, "diagnosis_agent", _diag)
    monkeypatch.setattr(workflow_module, "verification_agent", _verify)
    monkeypatch.setattr(agents_module, "append_trace_event", lambda *_args, **_kwargs: None)
    graph = build_graph()
    state = create_initial_state("confirm-choice")
    state["trace_id"] = "trace-confirm-choice"
    state["next_action"] = "confirm_choice"
    state["selected_candidate"] = "晚疫病"
    state["inherited_context"] = {"fusion_top3": [["早疫病", 0.7], ["晚疫病", 0.2]], "final_confidence": 0.7}
    final_state = graph.invoke(state)
    assert calls["diagnosis"] == 0
    assert calls["verification"] == 1
    agents = [event.get("agent") for event in final_state.get("trace_events", [])]
    assert "confirm_choice" in agents
    assert final_state.get("final_source") == "user_confirmed_candidate"


def test_confirm_choice_confidence_inheritance_fallbacks():
    top1 = confirm_choice_step({
        "selected_candidate": "早疫病",
        "inherited_context": {"fusion_top3": [["早疫病", 0.81], ["晚疫病", 0.12]]},
        "personalization_flags": {"need_confirm": True},
    })
    assert top1["final_confidence"] == 0.81

    non_top1 = confirm_choice_step({
        "selected_candidate": "晚疫病",
        "inherited_context": {"fusion_top3": [["早疫病", 0.81], ["晚疫病", 0.12]]},
        "personalization_flags": {"need_confirm": True},
    })
    assert non_top1["final_confidence"] == 0.12

    image_fallback = confirm_choice_step({
        "selected_candidate": "灰霉病",
        "inherited_context": {"image_top3": [["灰霉病", 0.33]], "fusion_top3": []},
        "personalization_flags": {"need_confirm": True},
    })
    assert image_fallback["final_confidence"] == 0.33

    evidence_fallback = confirm_choice_step({
        "selected_candidate": "叶霉病",
        "inherited_context": {
            "fusion_top3": [],
            "image_top3": [],
            "diagnosis_evidence": {"fusion_top3": [["叶霉病", 0.27]]},
        },
        "personalization_flags": {"need_confirm": True},
    })
    assert evidence_fallback["final_confidence"] == 0.27
