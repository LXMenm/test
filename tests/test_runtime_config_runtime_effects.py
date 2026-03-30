from __future__ import annotations

import pytest

import agents as agents_module
import diagnosis_model as dm
import llm_utils
from state import create_initial_state


def _base_supervisor_state():
    state = create_initial_state("test")
    state["final_disease"] = "早疫病"
    state["kb_snapshot"] = {"disease": "早疫病"}
    state["treatment_plan"] = "已有治疗方案"
    state["prevention_advice"] = "已有预防建议"
    return state


def test_confirm_round_limit_changes_supervisor_route(monkeypatch):
    state = create_initial_state("test")
    state["final_disease"] = "早疫病"
    flags = {"need_confirm": True}

    monkeypatch.setattr(agents_module, "get_admin_flag", lambda path, default=None: 0 if path == "workflow.confirm_round_limit" else default)
    state["confirm_round_index"] = 0
    action, is_complete, _, reasons = agents_module._deterministic_supervisor_decision(state, flags, [])
    assert action == "manual_review"
    assert is_complete is True
    assert "need_confirm_manual_review" in reasons

    monkeypatch.setattr(agents_module, "get_admin_flag", lambda path, default=None: 2 if path == "workflow.confirm_round_limit" else default)
    action, is_complete, _, reasons = agents_module._deterministic_supervisor_decision(state, flags, [])
    assert action == "await_user_confirmation"
    assert is_complete is True
    assert "need_confirm_wait_user" in reasons


def test_validator_rewrite_limit_controls_retry(monkeypatch):
    state = _base_supervisor_state()
    state["verification_result"] = {"passed": False}
    state["verification_passed"] = False
    state["rewrite_count"] = 1

    config = {
        "workflow.enable_validator_agent": True,
        "llm.enable_constraint_validation": True,
        "llm.enable_llm": True,
        "workflow.validator_rewrite_limit": 1,
    }
    monkeypatch.setattr(agents_module, "get_admin_flag", lambda path, default=None: config.get(path, default))
    action, _, _, reasons = agents_module._deterministic_supervisor_decision(state, {}, [])
    assert action == "end"
    assert "verification_failed_max_retry" in reasons

    config["workflow.validator_rewrite_limit"] = 2
    action, _, _, reasons = agents_module._deterministic_supervisor_decision(state, {}, [])
    assert action == "treatment"
    assert "verification_failed_rewrite" in reasons


def test_validator_agent_and_constraint_switches_affect_main_flow(monkeypatch):
    state = _base_supervisor_state()
    state["verification_result"] = None

    config = {
        "workflow.enable_validator_agent": False,
        "llm.enable_constraint_validation": True,
        "llm.enable_llm": True,
    }
    monkeypatch.setattr(agents_module, "get_admin_flag", lambda path, default=None: config.get(path, default))
    action, is_complete, _, reasons = agents_module._deterministic_supervisor_decision(state, {}, [])
    assert action == "end"
    assert is_complete is True
    assert "verification_disabled" in reasons

    config["workflow.enable_validator_agent"] = True
    config["llm.enable_constraint_validation"] = False
    action, is_complete, _, reasons = agents_module._deterministic_supervisor_decision(state, {}, [])
    assert action == "end"
    assert is_complete is True
    assert "verification_disabled" in reasons

    config["llm.enable_constraint_validation"] = True
    action, is_complete, _, reasons = agents_module._deterministic_supervisor_decision(state, {}, [])
    assert action == "verification"
    assert is_complete is False
    assert "missing_verification" in reasons


def test_enable_llm_is_global_degrade_switch(monkeypatch):
    state = create_initial_state("test")
    state["final_disease"] = "早疫病"
    state["kb_snapshot"] = {"disease": "早疫病"}

    config = {
        "llm.enable_llm": False,
        "llm.enable_treatment_generation": True,
        "workflow.enable_validator_agent": True,
        "llm.enable_constraint_validation": True,
    }
    monkeypatch.setattr(agents_module, "get_admin_flag", lambda path, default=None: config.get(path, default))
    action, is_complete, _, reasons = agents_module._deterministic_supervisor_decision(state, {}, [])
    assert action == "end"
    assert is_complete is True
    assert "treatment_generation_disabled" in reasons

    monkeypatch.setattr(llm_utils, "get_admin_flag", lambda path, default=None: False if path == "llm.enable_llm" else default)
    with pytest.raises(RuntimeError, match="LLM_DISABLED_BY_ADMIN_CONFIG"):
        llm_utils.call_llm("hello")


def test_enable_treatment_generation_switch(monkeypatch):
    state = create_initial_state("test")
    state["final_disease"] = "早疫病"
    state["kb_snapshot"] = {"disease": "早疫病"}

    config = {
        "llm.enable_llm": True,
        "llm.enable_treatment_generation": False,
    }
    monkeypatch.setattr(agents_module, "get_admin_flag", lambda path, default=None: config.get(path, default))
    action, is_complete, _, reasons = agents_module._deterministic_supervisor_decision(state, {}, [])
    assert action == "end"
    assert is_complete is True
    assert "treatment_generation_disabled" in reasons


def test_text_backend_switches_rule_bert_auto(monkeypatch):
    engine = dm.DiseaseDiagnosisEngine.__new__(dm.DiseaseDiagnosisEngine)

    class _KB:
        @staticmethod
        def normalize_symptoms(symptoms):
            return list(symptoms or [])

    monkeypatch.setattr(dm, "_get_kb_manager", lambda: _KB())
    monkeypatch.setattr(engine, "predict_text_proba_rule_based", lambda **kwargs: {"rule": 1.0})
    monkeypatch.setattr(engine, "predict_text_proba_bert", lambda **kwargs: {"bert": 1.0})

    monkeypatch.setattr(dm, "get_admin_flag", lambda path, default=None: "rule" if path == "model_fusion.text_backend" else default)
    assert engine.predict_text_proba(symptoms=["斑点"]) == {"rule": 1.0}

    monkeypatch.setattr(dm, "get_admin_flag", lambda path, default=None: "bert" if path == "model_fusion.text_backend" else default)
    assert engine.predict_text_proba(symptoms=["斑点"]) == {"bert": 1.0}

    monkeypatch.setattr(engine, "predict_text_proba_bert", lambda **kwargs: {})
    monkeypatch.setattr(dm, "get_admin_flag", lambda path, default=None: "auto" if path == "model_fusion.text_backend" else default)
    assert engine.predict_text_proba(symptoms=["斑点"]) == {"rule": 1.0}
