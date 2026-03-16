from __future__ import annotations

import agents as agents_module
from knowledge_base import get_kb_manager
from state import create_initial_state




class _EngineImageTextActive:
    def predict_image_proba(self, _):
        return {"细菌性斑点病": 0.8, "早疫病": 0.2}

    def predict_text_proba(self, **kwargs):
        return {"细菌性斑点病": 0.7, "晚疫病": 0.3}

    def build_prior_proba(self, **kwargs):
        return {"细菌性斑点病": 1.0}

    def fuse_multimodal_probs(self, image_probs, text_probs, prior_probs, image_confidence=0.0, text_confidence=0.0, text_evidence_active=None):
        assert text_evidence_active is True
        assert bool(text_probs) is True
        return {"细菌性斑点病": 0.85, "早疫病": 0.08, "晚疫病": 0.07}, {
            "has_image": True,
            "has_text": True,
            "has_prior": True,
            "normalized_weights": {"image": 0.6, "text": 0.35, "prior": 0.05},
            "confidence_drop_reason": None,
        }

    def build_diagnosis_evidence(self, **kwargs):
        return {"detailed_reason": "image+text", "summary": "image+text"}

    def _get_disease_description(self, disease_type, symptoms):
        return disease_type


class _EngineImageOnlyNoText:
    def predict_image_proba(self, _):
        return {"细菌性斑点病": 0.88, "早疫病": 0.12}

    def predict_text_proba(self, **kwargs):
        # 无文本证据时不应被调用；若调用则会被 agent 后置清空
        return {"黄化曲叶病毒病": 0.9, "花叶病毒病": 0.1}

    def build_prior_proba(self, **kwargs):
        return {"细菌性斑点病": 1.0}

    def fuse_multimodal_probs(self, image_probs, text_probs, prior_probs, image_confidence=0.0, text_confidence=0.0, text_evidence_active=None):
        assert text_evidence_active is False
        assert text_probs == {}
        fused = {
            "细菌性斑点病": 0.95 * image_probs.get("细菌性斑点病", 0.0) + 0.05 * prior_probs.get("细菌性斑点病", 0.0),
            "早疫病": 0.95 * image_probs.get("早疫病", 0.0),
        }
        total = sum(fused.values())
        fused = {k: v / total for k, v in fused.items()}
        return fused, {
            "has_image": True,
            "has_text": False,
            "has_prior": True,
            "normalized_weights": {"image": 0.95, "text": 0.0, "prior": 0.05},
            "confidence_drop_reason": None,
        }

    def build_diagnosis_evidence(self, **kwargs):
        return {"detailed_reason": "image-only", "summary": "image-only"}

    def _get_disease_description(self, disease_type, symptoms):
        return disease_type


def test_image_only_empty_symptoms_has_no_text_branch(monkeypatch):
    monkeypatch.setattr(agents_module, "get_diagnosis_engine", lambda **kwargs: _EngineImageOnlyNoText())
    state = create_initial_state("test")
    state["crop_type"] = "番茄"
    state["symptoms"] = []
    state["image_path"] = "exam.JPG"
    state["personalization_flags"] = {"confirm_when_low_confidence": True}

    out = agents_module.diagnosis_agent(state)
    assert out["text_probs"] == {}
    assert out["fusion_meta"].get("has_text") is False
    assert out["final_confidence"] >= 0.80
    assert out["modality_conflict_flag"] is False


def test_supervisor_need_confirm_ends_current_round_without_reception_loop():
    state = create_initial_state("test")
    state["current_step"] = "diagnosis_complete"
    state["final_disease"] = "细菌性斑点病"
    state["personalization_flags"] = {
        "need_confirm": True,
        "follow_up_questions": ["请补充病斑颜色和边缘形态？"],
    }

    out = agents_module.supervisor_agent(state)
    assert out["next_action"] == "end"
    assert out["is_complete"] is True
    assert out.get("workflow_error") is None
    assert out.get("follow_up_questions")


def test_symptom_alias_normalizes_colloquial_spot_phrase():
    normalized = get_kb_manager().normalize_symptoms(["有斑点", "黄叶", "叶片卷起来"])
    assert "斑点" in normalized
    assert "发黄" in normalized
    assert "卷曲" in normalized


def test_image_only_with_profile_fields_still_no_text_branch(monkeypatch):
    monkeypatch.setattr(agents_module, "get_diagnosis_engine", lambda **kwargs: _EngineImageOnlyNoText())
    state = create_initial_state("test")
    state["crop_type"] = "番茄"
    state["symptoms"] = []
    state["image_path"] = "exam.JPG"
    state["crop_growth_stage"] = "FLOWERING"
    state["environment"] = "棚内高湿"
    state["active_profile"] = {"facility": "温室", "location": {"province": "山东"}}
    state["personalization_flags"] = {"confirm_when_low_confidence": True}

    out = agents_module.diagnosis_agent(state)
    assert out["normalized_symptoms"] == []
    assert out["text_probs"] == {}
    assert out.get("text_top3") == []
    assert out["fusion_meta"].get("has_text") is False
    assert out["fusion_meta"].get("has_prior") in {True, False}
    assert out["final_confidence"] >= 0.80


def test_text_branch_activates_only_with_explicit_symptoms(monkeypatch):
    monkeypatch.setattr(agents_module, "get_diagnosis_engine", lambda **kwargs: _EngineImageTextActive())
    state = create_initial_state("test")
    state["crop_type"] = "番茄"
    state["symptoms"] = ["叶子有斑点"]
    state["image_path"] = "exam.JPG"
    state["crop_growth_stage"] = "FLOWERING"
    state["environment"] = "棚内高湿"
    state["active_profile"] = {"facility": "温室", "location": {"province": "山东"}}
    state["personalization_flags"] = {"confirm_when_low_confidence": True}

    out = agents_module.diagnosis_agent(state)
    assert out["normalized_symptoms"]
    # 明确症状存在时，允许文本分支参与（此处引擎被 monkeypatch 为固定返回）
    assert out["fusion_meta"].get("has_text") is True
