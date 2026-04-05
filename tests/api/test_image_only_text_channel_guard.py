from state import create_initial_state
import agents as agents_module
from app import build_trace_query


class _FakeKB:
    symptom_tiers = {
        "发黄": "generic",
        "卷曲": "generic",
    }
    symptom_candidates = {
        "发黄": ["晚疫病", "早疫病"],
        "卷曲": ["黄化曲叶病毒病"],
    }

    @staticmethod
    def normalize_symptoms(symptoms):
        alias = {"叶子发黄": "发黄", "卷叶": "卷曲"}
        out = []
        for item in symptoms or []:
            token = alias.get(str(item).strip(), str(item).strip())
            if token and token not in out:
                out.append(token)
        return out

    @staticmethod
    def has_effective_text_evidence(symptoms, **_kwargs):
        return bool(symptoms)

    def has_discriminative_text_evidence(self, _symptoms):
        return False

    def get_candidate_diseases_from_symptoms(self, symptoms):
        merged = []
        for symptom in symptoms or []:
            for disease in self.symptom_candidates.get(symptom, []):
                if disease not in merged:
                    merged.append(disease)
        return merged

    @staticmethod
    def generate_text_follow_up_questions(symptoms):
        return [f"请补充{symptom}细节" for symptom in (symptoms or [])][:3]

    @staticmethod
    def rerank_text_candidates_with_discriminators(scores, _symptoms):
        return scores

    @staticmethod
    def map_image_label_to_disease(label):
        return str(label)


class _EngineNoTextForImageOnly:
    def __init__(self) -> None:
        self.text_called = False

    def predict_image_proba(self, _image_path):
        return {"晚疫病": 0.9, "早疫病": 0.1}

    def predict_text_proba(self, **_kwargs):
        self.text_called = True
        return {"晚疫病": 0.6, "早疫病": 0.4}

    def build_prior_proba(self, **_kwargs):
        return {"晚疫病": 0.7, "早疫病": 0.3}

    def fuse_multimodal_probs(self, image_probs, text_probs, prior_probs, **_kwargs):
        _ = prior_probs
        return image_probs or text_probs, {
            "normalized_weights": {"image": 1.0, "text": 0.0, "prior": 0.0},
            "has_text": bool(text_probs),
            "has_prior": bool(prior_probs),
            "insufficient_evidence": False,
        }

    def build_diagnosis_evidence(self, **kwargs):
        return {
            "raw_symptoms": kwargs["raw_symptoms"],
            "normalized_symptoms": kwargs["normalized_symptoms"],
            "text_top3": sorted(kwargs["text_probs"].items(), key=lambda x: x[1], reverse=True)[:3],
            "image_top3": sorted(kwargs["image_probs"].items(), key=lambda x: x[1], reverse=True)[:3],
            "prior_top3": sorted(kwargs["prior_probs"].items(), key=lambda x: x[1], reverse=True)[:3],
            "fusion_top3": sorted(kwargs["fusion_probs"].items(), key=lambda x: x[1], reverse=True)[:3],
            "weights": {"image": 1.0, "text": 0.0, "prior": 0.0},
            "fusion_meta": kwargs["fusion_meta"],
            "modality_conflict_flag": False,
            "image_reliable": True,
            "text_reliable": False,
            "reliability_issue_types": [],
            "supplement_mode": "none",
            "final_disease": kwargs["final_disease"],
            "final_confidence": kwargs["final_confidence"],
            "final_source": kwargs["final_source"],
            "concise_summary": "ok",
            "detailed_reason": "ok",
            "summary": "ok",
        }

    @staticmethod
    def _get_disease_description(_disease, _symptoms):
        return "desc"


def test_build_trace_query_excludes_non_symptom_context() -> None:
    query = build_trace_query(
        crop_type="番茄",
        symptoms_list=[],
        growth_stage="FLOWERING",
        image_path="/tmp/img.jpg",
    )
    assert query == ""


def test_image_only_reception_does_not_inject_growth_stage_as_symptom(monkeypatch) -> None:
    monkeypatch.setattr(agents_module, "kb_manager", _FakeKB())
    monkeypatch.setattr(agents_module, "append_trace_event", lambda *_args, **_kwargs: None)

    state = create_initial_state("")
    state["image_path"] = "dummy.jpg"
    state["crop_growth_stage"] = "FLOWERING"
    state["environment"] = "棚内高湿"
    state["symptoms"] = []
    state["user_symptom_text"] = ""

    out = agents_module.reception_agent(state)

    assert out["symptoms"] == []
    assert out["normalized_symptoms"] == []
    profile = out.get("symptom_evidence_profile") or {}
    assert profile.get("raw_tokens") == []
    assert profile.get("normalized_tokens") == []
    assert profile.get("text_evidence_level") == "none"


def test_image_only_profile_fields_do_not_generate_text_top3(monkeypatch) -> None:
    monkeypatch.setattr(agents_module, "kb_manager", _FakeKB())
    monkeypatch.setattr(agents_module, "append_trace_event", lambda *_args, **_kwargs: None)
    engine = _EngineNoTextForImageOnly()
    monkeypatch.setattr(agents_module, "get_diagnosis_engine", lambda **_kwargs: engine)

    state = create_initial_state("")
    state["crop_type"] = "番茄"
    state["crop_growth_stage"] = "FLOWERING"
    state["environment"] = "棚内高湿"
    state["symptoms"] = []
    state["image_path"] = "dummy.jpg"

    out = agents_module.diagnosis_agent(state)

    assert engine.text_called is False
    assert out["normalized_symptoms"] == []
    assert out["text_probs"] == {}
    assert out["text_top3"] == []


def test_ambiguous_user_symptom_still_treated_as_weak_text(monkeypatch) -> None:
    monkeypatch.setattr(agents_module, "kb_manager", _FakeKB())
    profile = agents_module._build_consistent_symptom_profile(["看起来不太对劲"])

    assert profile["raw_tokens"]
    assert profile["text_evidence_level"] != "none"
