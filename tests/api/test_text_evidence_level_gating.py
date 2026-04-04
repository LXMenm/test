from __future__ import annotations

import agents as agents_module
from state import create_initial_state


class _Engine:
    def __init__(self):
        self.last_text_probs = None
        self.last_text_active = None

    def predict_text_proba(self, **_kwargs):
        return {"早疫病": 1.0}

    def fuse_multimodal_probs(self, **kwargs):
        self.last_text_probs = dict(kwargs.get("text_probs") or {})
        self.last_text_active = bool(kwargs.get("text_evidence_active"))
        text_probs = dict(kwargs.get("text_probs") or {})
        return (text_probs or {"未知待确认": 0.0}), {
            "normalized_weights": {"image": 0.0, "text": 1.0 if text_probs else 0.0, "prior": 0.0},
            "has_image": False,
            "has_text": bool(text_probs),
            "fusion_case": "text_only",
            "image_reliable": False,
            "text_reliable": bool(text_probs),
            "supplement_mode": "text",
        }

    def _get_disease_description(self, disease, _symptoms):
        return f"{disease}"


class _KB:
    def __init__(self, *, tiers=None, candidates=None, follow_ups=None, discriminative=False):
        self.symptom_tiers = tiers or {}
        self.symptom_candidates = candidates or {}
        self._follow_ups = follow_ups or ["请补充病斑形态"]
        self._discriminative = discriminative

    def normalize_symptoms(self, symptoms):
        return [str(item).strip() for item in (symptoms or []) if str(item).strip()]

    def has_effective_text_evidence(self, symptoms, **_kwargs):
        return bool(symptoms)

    def has_discriminative_text_evidence(self, symptoms):
        if self._discriminative:
            return True
        return any(self.symptom_tiers.get(s) == "discriminative" for s in (symptoms or []))

    def get_candidate_diseases_from_symptoms(self, symptoms):
        out = []
        for symptom in symptoms or []:
            out.extend(self.symptom_candidates.get(symptom, []))
        dedup = []
        for item in out:
            if item not in dedup:
                dedup.append(item)
        return dedup

    def generate_text_follow_up_questions(self, _symptoms, text_probs=None):
        _ = text_probs
        return list(self._follow_ups)

    def rerank_text_candidates_with_discriminators(self, scores, _symptoms):
        return scores


def _run_diag(monkeypatch, *, symptoms, kb):
    engine = _Engine()
    monkeypatch.setattr(agents_module, "kb_manager", kb)
    monkeypatch.setattr(agents_module, "resolve_model", lambda *_args, **_kwargs: (type("M", (), {"model_id": "m", "display_name": "m", "backend": "mock", "model_path": "/tmp/m"})(), []))
    monkeypatch.setattr(agents_module, "get_diagnosis_engine", lambda **_kwargs: engine)
    monkeypatch.setattr(agents_module, "get_admin_flag", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(agents_module, "get_runtime_thresholds", lambda: {"diagnosis_conf_threshold": 0.7, "low_margin_threshold": 0.1, "image_top1_threshold": 0.7, "text_top1_threshold": 0.7})
    monkeypatch.setattr(agents_module, "build_reliability_summary", lambda **_kwargs: {"reliability_issue_types": [], "supplement_mode": "text"})
    monkeypatch.setattr(agents_module, "evaluate_confirmation_decision", lambda **_kwargs: {"fusion_case": "text_only", "weak_conflict_flag": False, "modality_conflict_flag": False, "image_reliable": False, "text_reliable": True, "supplement_mode": "text", "need_confirm": False, "reasons": [], "should_clear_confirm": False})
    monkeypatch.setattr(agents_module, "make_confidence_flags", lambda *_args, **_kwargs: {"need_confirm": False, "reasons": []})
    monkeypatch.setattr(agents_module, "append_trace_event", lambda *_args, **_kwargs: None)

    state = create_initial_state("diag")
    state["crop_type"] = "番茄"
    state["symptoms"] = symptoms
    state["personalization_flags"] = {}
    out = agents_module.diagnosis_agent(state)
    return out, engine


def test_weak_text_evidence_participates_with_low_weight(monkeypatch):
    kb = _KB(tiers={"发黄": "generic"}, candidates={"发黄": []}, follow_ups=["请补充病斑边缘"])
    out, engine = _run_diag(monkeypatch, symptoms=["发黄"], kb=kb)
    assert engine.last_text_active is True
    assert engine.last_text_probs == {"早疫病": 0.35}
    assert out["diagnosis_evidence"]["text_top3"]


def test_none_text_evidence_still_disables_text_branch(monkeypatch):
    kb = _KB()
    out, engine = _run_diag(monkeypatch, symptoms=[], kb=kb)
    assert engine.last_text_active is False
    assert engine.last_text_probs == {}
    assert out["diagnosis_evidence"]["text_top3"] == []


def test_discriminative_text_evidence_upgrades_text_strength(monkeypatch):
    kb = _KB(tiers={"叶背白霉": "discriminative"}, candidates={"叶背白霉": ["晚疫病"]}, discriminative=True)
    _out, engine = _run_diag(monkeypatch, symptoms=["叶背白霉"], kb=kb)
    assert engine.last_text_active is True
    assert engine.last_text_probs == {"早疫病": 1.1}


def test_weak_text_triggers_follow_up_instead_of_being_dropped(monkeypatch):
    kb = _KB(tiers={"发黄": "generic"}, candidates={"发黄": []}, follow_ups=["请补充叶背是否有霉层"])
    out, _engine = _run_diag(monkeypatch, symptoms=["发黄"], kb=kb)
    assert out["personalization_flags"]["need_confirm"] is True
    assert "weak_text_evidence" in (out["personalization_flags"].get("fallback_reason") or [])
    assert out["diagnosis_follow_up_questions"]
