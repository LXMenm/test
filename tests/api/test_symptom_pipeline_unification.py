from __future__ import annotations

from fastapi.testclient import TestClient

import agents as agents_module
import app as app_module
from state import create_initial_state
from symptom_pipeline import build_symptom_evidence_profile


class _FakeKB:
    symptom_tiers = {
        "叶片卷曲": "discriminative",
        "叶背白霉": "discriminative",
        "发黄": "generic",
    }
    symptom_candidates = {
        "叶片卷曲": ["黄化曲叶病毒病"],
        "叶背白霉": ["晚疫病"],
        "发黄": ["黄化曲叶病毒病", "缺素症"],
    }

    @staticmethod
    def normalize_symptoms(symptoms):
        alias = {"卷叶": "叶片卷曲", "叶子发黄": "发黄", "病斑原形": "病斑圆形"}
        out = []
        for item in symptoms or []:
            token = alias.get(str(item).strip(), str(item).strip())
            if token and token not in out:
                out.append(token)
        return out

    @staticmethod
    def has_effective_text_evidence(symptoms, **_kwargs):
        return bool(symptoms)

    def has_discriminative_text_evidence(self, symptoms):
        return any(self.symptom_tiers.get(s) == "discriminative" for s in symptoms)

    def get_candidate_diseases_from_symptoms(self, symptoms):
        items = []
        for symptom in symptoms:
            items.extend(self.symptom_candidates.get(symptom, []))
        deduped = []
        for item in items:
            if item not in deduped:
                deduped.append(item)
        return deduped

    @staticmethod
    def generate_text_follow_up_questions(symptoms, text_probs=None):
        _ = text_probs
        return [f"请补充{symptom}的细节" for symptom in symptoms][:3]


def test_symptom_pipeline_returns_normalized_and_discriminative_tokens() -> None:
    profile = build_symptom_evidence_profile(["卷叶", "叶子发黄", "未知症状", "卷叶"], _FakeKB())
    assert profile["raw_tokens"] == ["卷叶", "叶子发黄", "未知症状"]
    assert profile["normalized_tokens"] == ["叶片卷曲", "发黄", "未知症状"]
    assert profile["discriminative_tokens"] == ["叶片卷曲"]
    assert profile["generic_tokens"] == ["发黄"]
    assert profile["unknown_tokens"] == ["未知症状"]
    assert profile["has_any_text_evidence"] is True
    assert profile["has_discriminative_text_evidence"] is True
    assert profile["candidate_diseases"] == ["黄化曲叶病毒病", "缺素症"]


def test_confirm_flow_uses_shared_symptom_pipeline(monkeypatch) -> None:
    calls: list[list[str]] = []

    def _fake_build(symptoms, _kb):
        calls.append(list(symptoms or []))
        tokens = [str(item).strip() for item in (symptoms or []) if str(item).strip()]
        deduped = []
        for token in tokens:
            if token not in deduped:
                deduped.append(token)
        return {
            "raw_tokens": deduped,
            "normalized_tokens": deduped,
            "unknown_tokens": [],
            "generic_tokens": [],
            "discriminative_tokens": [],
            "has_any_text_evidence": bool(deduped),
            "has_discriminative_text_evidence": False,
            "candidate_diseases": [],
            "follow_up_hints": [],
        }

    monkeypatch.setattr(app_module, "build_symptom_evidence_profile", _fake_build)
    monkeypatch.setattr(app_module, "get_kb_manager", lambda: _FakeKB())
    monkeypatch.setattr(app_module, "list_trace_events", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(app_module, "_latest_case_event_by_trace", lambda *_args, **_kwargs: None)

    client = TestClient(app_module.app)
    resp = client.post(
        "/api/diagnose-confirm",
        json={"trace_id": "trace-same", "image_id": "missing.jpg", "symptoms": "卷叶，叶子发黄"},
    )
    assert resp.status_code == 404
    assert calls
    assert any("卷叶" in bucket for bucket in calls)


def test_reception_and_confirm_do_not_diverge_on_same_symptoms(monkeypatch) -> None:
    fake_kb = _FakeKB()
    monkeypatch.setattr(agents_module, "kb_manager", fake_kb)
    monkeypatch.setattr(agents_module, "append_trace_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        agents_module,
        "call_llm",
        lambda *_args, **_kwargs: '{"growth_stage": null, "symptoms": ["卷叶", "病斑原形", "叶背白霉"]}',
    )

    reception_state = create_initial_state("番茄叶片异常")
    reception_out = agents_module.reception_agent(reception_state)

    confirm_state = create_initial_state("confirm")
    confirm_state["incoming_symptoms"] = ["卷叶", "病斑原形", "叶背白霉"]
    confirm_state["historical_symptoms"] = []
    confirm_out = agents_module.confirm_input_step(confirm_state)

    assert reception_out["normalized_symptoms"] == confirm_out["normalized_symptoms"]
