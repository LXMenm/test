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
    def rerank_text_candidates_with_discriminators(scores, _symptoms):
        return scores

    @staticmethod
    def score_diseases_from_text(**_kwargs):
        return {"晚疫病": 0.6, "黄化曲叶病毒病": 0.4}

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


def _profile_buckets(state_or_profile) -> tuple[list[str], list[str], list[str]]:
    profile = state_or_profile.get("symptom_evidence_profile", state_or_profile)
    return (
        list(profile.get("unknown_tokens") or []),
        list(profile.get("generic_tokens") or []),
        list(profile.get("discriminative_tokens") or []),
    )


def _prepare_diagnosis_agent_mocks(monkeypatch, fake_kb: _FakeKB) -> None:
    monkeypatch.setattr(agents_module, "kb_manager", fake_kb)
    monkeypatch.setattr(agents_module, "append_trace_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        agents_module,
        "resolve_model",
        lambda model_id, allow_torch=False: (
            type("ResolvedModel", (), {"model_id": model_id or "mock", "model_path": "/tmp/mock.bin", "backend": "mock", "display_name": "mock"})(),
            [],
        ),
    )
    monkeypatch.setattr(
        agents_module,
        "get_diagnosis_engine",
        lambda **_kwargs: type(
            "Engine",
            (),
            {
                "predict_text_proba": staticmethod(lambda **__kwargs: {"晚疫病": 0.6, "黄化曲叶病毒病": 0.4}),
                "build_prior_proba": staticmethod(lambda **__kwargs: {}),
                "fuse_multimodal_probs": staticmethod(
                    lambda **__kwargs: (
                        {"晚疫病": 0.6, "黄化曲叶病毒病": 0.4},
                        {"fusion_case": "text_only"},
                    )
                ),
                "_get_disease_description": staticmethod(lambda disease, symptoms: f"{disease}:{','.join(symptoms or [])}"),
            },
        )(),
    )
    monkeypatch.setattr(
        agents_module,
        "get_admin_flag",
        lambda key, default=None: {
            "workflow.enable_personalization_agent": False,
            "model_fusion.enable_image_model": False,
            "model_fusion.enable_text_model": True,
        }.get(key, default),
    )


def test_reception_and_confirm_input_classify_same_symptom_consistently(monkeypatch) -> None:
    fake_kb = _FakeKB()
    monkeypatch.setattr(agents_module, "kb_manager", fake_kb)
    monkeypatch.setattr(agents_module, "append_trace_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        agents_module,
        "call_llm",
        lambda *_args, **_kwargs: '{"growth_stage": null, "symptoms": ["卷叶", "叶子发黄", "未知症状"]}',
    )

    reception_state = create_initial_state("番茄叶片异常")
    reception_out = agents_module.reception_agent(reception_state)

    confirm_state = create_initial_state("confirm")
    confirm_state["incoming_symptoms"] = ["卷叶", "叶子发黄", "未知症状"]
    confirm_state["historical_symptoms"] = []
    confirm_out = agents_module.confirm_input_step(confirm_state)

    assert _profile_buckets(reception_out) == _profile_buckets(confirm_out)


def test_free_text_symptom_not_dropped_in_reception_if_preserved_in_confirm(monkeypatch) -> None:
    fake_kb = _FakeKB()
    monkeypatch.setattr(agents_module, "kb_manager", fake_kb)
    monkeypatch.setattr(agents_module, "append_trace_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        agents_module,
        "call_llm",
        lambda *_args, **_kwargs: '{"growth_stage": null, "symptoms": []}',
    )

    reception_state = create_initial_state("霉层明显")
    reception_out = agents_module.reception_agent(reception_state)

    confirm_state = create_initial_state("confirm")
    confirm_state["incoming_symptoms"] = ["霉层明显"]
    confirm_state["historical_symptoms"] = []
    confirm_out = agents_module.confirm_input_step(confirm_state)

    assert "霉层明显" in (reception_out.get("symptoms") or [])
    assert "霉层明显" in (confirm_out.get("symptoms") or [])


def test_diagnosis_agent_rebuild_matches_upstream_profile_classification(monkeypatch) -> None:
    fake_kb = _FakeKB()
    _prepare_diagnosis_agent_mocks(monkeypatch, fake_kb)

    upstream_profile = build_symptom_evidence_profile(["卷叶", "叶子发黄", "未知症状"], fake_kb)
    state = create_initial_state("番茄叶片异常")
    state["crop_type"] = "番茄"
    state["symptoms"] = list(upstream_profile["raw_tokens"])
    state["normalized_symptoms"] = list(upstream_profile["normalized_tokens"])
    state["symptom_evidence_profile"] = dict(upstream_profile)
    state["crop_growth_stage"] = None
    state["image_path"] = None
    out = agents_module.diagnosis_agent(state)

    assert _profile_buckets(out) == _profile_buckets(upstream_profile)


def test_same_input_yields_same_unknown_generic_discriminative_buckets_across_stages(monkeypatch) -> None:
    fake_kb = _FakeKB()
    monkeypatch.setattr(agents_module, "kb_manager", fake_kb)
    monkeypatch.setattr(agents_module, "append_trace_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        agents_module,
        "call_llm",
        lambda *_args, **_kwargs: '{"growth_stage": null, "symptoms": ["卷叶", "叶子发黄", "未知症状"]}',
    )

    reception_state = create_initial_state("番茄叶片异常")
    reception_out = agents_module.reception_agent(reception_state)

    confirm_state = create_initial_state("confirm")
    confirm_state["incoming_symptoms"] = ["卷叶", "叶子发黄", "未知症状"]
    confirm_state["historical_symptoms"] = []
    confirm_out = agents_module.confirm_input_step(confirm_state)

    _prepare_diagnosis_agent_mocks(monkeypatch, fake_kb)
    diagnosis_state = create_initial_state("diagnosis")
    diagnosis_state["crop_type"] = "番茄"
    diagnosis_state["symptoms"] = ["卷叶", "叶子发黄", "未知症状"]
    diagnosis_state["crop_growth_stage"] = None
    diagnosis_state["image_path"] = None
    diagnosis_out = agents_module.diagnosis_agent(diagnosis_state)

    assert _profile_buckets(reception_out) == _profile_buckets(confirm_out) == _profile_buckets(diagnosis_out)
