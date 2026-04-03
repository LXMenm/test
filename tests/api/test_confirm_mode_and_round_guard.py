from __future__ import annotations

import app as app_module
import agents as agents_module
import workflow as workflow_module
from state import create_initial_state
from workflow import build_graph


def test_start_confirm_mode_image_only_for_image_quality_low():
    payload = app_module.build_start_confirm_explanation(
        need_confirm=True,
        low_conf=True,
        low_margin=False,
        symptoms_list=["叶片黄化"],
    )
    assert payload["confirm_reason_code"] == "IMAGE_QUALITY_LOW"
    assert payload["confirm_ui_mode"] == "image"
    assert payload["confirm_fields"] == ["image"]


def test_start_confirm_mode_text_only_for_text_insufficient():
    payload = app_module.build_start_confirm_explanation(
        need_confirm=True,
        low_conf=False,
        low_margin=True,
        symptoms_list=["叶片黄化"],
    )
    assert payload["confirm_reason_code"] == "LOW_DISCRIMINATION_NEED_KEY_FEATURES"
    assert payload["confirm_ui_mode"] == "text"
    assert payload["confirm_fields"] == ["symptoms"]


def test_start_confirm_mode_image_and_text_for_both_weak():
    payload = app_module.build_start_confirm_explanation(
        need_confirm=True,
        low_conf=True,
        low_margin=True,
        symptoms_list=[],
    )
    assert payload["confirm_reason_code"] == "BOTH_IMAGE_AND_TEXT_WEAK"
    assert payload["confirm_ui_mode"] == "image_and_text"
    assert payload["confirm_fields"] == ["image", "symptoms"]


def test_confirm_round_runs_diagnosis_once_per_submit(monkeypatch):
    calls = {"diagnosis": 0}

    def _diag(state):
        calls["diagnosis"] += 1
        round_idx = int(state.get("confirm_round_index") or 0)
        flags = dict(state.get("personalization_flags") or {})
        flags["need_confirm"] = True
        state["personalization_flags"] = flags
        state["final_disease"] = "疑似病害"
        state["disease_type"] = "疑似病害"
        state["final_confidence"] = 0.32
        state["disease_confidence"] = 0.32
        state["current_step"] = "diagnosis_complete"
        state["diagnosis_last_round_index"] = round_idx
        state["next_action"] = None
        return state

    monkeypatch.setattr(workflow_module, "supervisor_agent", agents_module.supervisor_agent)
    monkeypatch.setattr(workflow_module, "diagnosis_agent", _diag)
    monkeypatch.setattr(agents_module, "append_trace_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        agents_module,
        "kb_manager",
        type("KB", (), {"normalize_symptoms": staticmethod(lambda symptoms: list(symptoms))})(),
    )
    graph = build_graph()

    state_round1 = create_initial_state("confirm-round-1")
    state_round1["next_action"] = "confirm_input"
    state_round1["confirm_round_index"] = 1
    state_round1["historical_symptoms"] = ["叶片黄化"]
    state_round1["incoming_symptoms"] = ["病斑扩大"]
    out1 = graph.invoke(state_round1, config={"recursion_limit": 80})
    assert calls["diagnosis"] == 1
    assert out1.get("next_action") in {"await_user_confirmation", "manual_review"}

    state_round2 = create_initial_state("confirm-round-2")
    state_round2["next_action"] = "confirm_input"
    state_round2["confirm_round_index"] = 2
    state_round2["historical_symptoms"] = ["叶片黄化", "病斑扩大"]
    state_round2["incoming_symptoms"] = ["叶背有霉层"]
    out2 = graph.invoke(state_round2, config={"recursion_limit": 80})
    assert calls["diagnosis"] == 2
    assert out2.get("next_action") in {"await_user_confirmation", "manual_review"}
