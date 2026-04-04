from __future__ import annotations

import agents as agents_module
from agents import confirm_choice_step


def _base_state() -> dict:
    return {
        "selected_candidate": "晚疫病",
        "inherited_context": {
            "fusion_top3": [["晚疫病", 0.62], ["早疫病", 0.31]],
            "final_confidence": 0.62,
        },
        "personalization_flags": {"need_confirm": True},
    }


def test_confirm_choice_preserves_top_level_symptoms_from_inherited_context(monkeypatch):
    monkeypatch.setattr(agents_module, "append_trace_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        agents_module,
        "kb_manager",
        type("KB", (), {"normalize_symptoms": staticmethod(lambda s: [str(i).strip() for i in s if str(i).strip()])})(),
    )
    state = _base_state()
    state["inherited_context"]["symptoms"] = ["叶片黄化", "叶背白霉"]
    out = confirm_choice_step(state)
    assert out["symptoms"] == ["叶片黄化", "叶背白霉"]
    trace_outputs = (out.get("trace_events") or [])[-1]["outputs"]
    assert trace_outputs["symptoms"] == ["叶片黄化", "叶背白霉"]


def test_confirm_choice_preserves_normalized_symptoms_from_diagnosis_evidence(monkeypatch):
    monkeypatch.setattr(agents_module, "append_trace_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        agents_module,
        "kb_manager",
        type("KB", (), {"normalize_symptoms": staticmethod(lambda s: [str(i).strip() for i in s if str(i).strip()])})(),
    )
    state = _base_state()
    state["diagnosis_evidence"] = {"normalized_symptoms": ["叶片卷曲", "叶背白霉"], "raw_symptoms": ["卷叶", "叶背白霉"]}
    out = confirm_choice_step(state)
    assert out["normalized_symptoms"] == ["叶片卷曲", "叶背白霉"]


def test_confirm_choice_does_not_rerun_diagnosis_but_keeps_symptom_fields(monkeypatch):
    calls = {"build_profile": 0}

    def _fake_build(symptoms, _kb):
        calls["build_profile"] += 1
        tokens = [str(i).strip() for i in (symptoms or []) if str(i).strip()]
        return {
            "raw_tokens": tokens,
            "normalized_tokens": tokens,
            "unknown_tokens": [],
            "generic_tokens": [],
            "discriminative_tokens": [],
            "has_any_text_evidence": bool(tokens),
            "has_discriminative_text_evidence": False,
            "candidate_diseases": [],
            "follow_up_hints": [],
        }

    monkeypatch.setattr(agents_module, "append_trace_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(agents_module, "build_symptom_evidence_profile", _fake_build)
    monkeypatch.setattr(
        agents_module,
        "kb_manager",
        type("KB", (), {"normalize_symptoms": staticmethod(lambda s: [str(i).strip() for i in s if str(i).strip()])})(),
    )
    state = _base_state()
    state["inherited_context"]["symptoms"] = ["叶片黄化"]
    out = confirm_choice_step(state)
    assert out["final_source"] == "user_confirmed_candidate"
    assert out["next_action"] == "supervisor"
    assert out["symptom_evidence_profile"]["raw_tokens"] == ["叶片黄化"]
    assert calls["build_profile"] <= 1


def test_confirm_response_top_level_and_diagnosis_evidence_symptoms_are_consistent(monkeypatch):
    monkeypatch.setattr(agents_module, "append_trace_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        agents_module,
        "kb_manager",
        type("KB", (), {"normalize_symptoms": staticmethod(lambda s: [str(i).strip() for i in s if str(i).strip()])})(),
    )
    state = _base_state()
    state["diagnosis_evidence"] = {"raw_symptoms": ["卷叶", "叶背白霉"], "normalized_symptoms": ["叶片卷曲", "叶背白霉"]}
    out = confirm_choice_step(state)
    assert out["diagnosis_evidence"]["raw_symptoms"] == out["symptoms"]
    assert out["diagnosis_evidence"]["normalized_symptoms"] == out["normalized_symptoms"]
