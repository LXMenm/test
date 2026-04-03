from __future__ import annotations

import agents as agents_module
from knowledge_base import get_kb_manager
from state import create_initial_state


class _KBStub:
    def normalize_symptoms(self, symptoms):
        return list(symptoms or [])

    def has_effective_text_evidence(self, symptoms, **kwargs):
        return bool(symptoms)

    def score_diseases_from_text(self, **kwargs):
        return {"细菌性斑点病": 1.0}


def _patch_kb(monkeypatch):
    monkeypatch.setattr(agents_module, "kb_manager", _KBStub())
    monkeypatch.setattr(agents_module, "append_trace", lambda *args, **kwargs: None)




class _EngineImageTextActive:
    def predict_image_proba(self, _):
        return {"细菌性斑点病": 0.8, "早疫病": 0.2}

    def predict_text_proba(self, **kwargs):
        return {"细菌性斑点病": 0.7, "晚疫病": 0.3}

    def build_prior_proba(self, **kwargs):
        return {"细菌性斑点病": 1.0}

    def fuse_multimodal_probs(self, image_probs, text_probs, prior_probs, image_confidence=0.0, text_confidence=0.0, text_evidence_active=None, **kwargs):
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

    def fuse_multimodal_probs(self, image_probs, text_probs, prior_probs, image_confidence=0.0, text_confidence=0.0, text_evidence_active=None, **kwargs):
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


class _EngineNoEvidence:
    def build_prior_proba(self, **kwargs):
        return {}

    def fuse_multimodal_probs(self, image_probs, text_probs, prior_probs, image_confidence=0.0, text_confidence=0.0, text_evidence_active=None, **kwargs):
        return {}, {
            "has_image": False,
            "has_text": False,
            "has_prior": False,
            "fusion_case": "prior_only",
            "insufficient_evidence": True,
            "degraded_reason": "no_active_evidence",
            "normalized_weights": {"image": 0.0, "text": 0.0, "prior": 0.0},
        }

    def build_diagnosis_evidence(self, **kwargs):
        return {"summary": "no-evidence"}

    def _get_disease_description(self, disease_type, symptoms):
        return disease_type


class _EngineBranchFailure:
    def __init__(self, fail_on: str):
        self.fail_on = fail_on

    def predict_image_proba(self, _):
        if self.fail_on == "image":
            raise RuntimeError("image_fail")
        return {"细菌性斑点病": 1.0}

    def predict_text_proba(self, **kwargs):
        if self.fail_on == "text":
            raise RuntimeError("text_fail")
        return {"细菌性斑点病": 1.0}

    def build_prior_proba(self, **kwargs):
        if self.fail_on == "prior":
            raise RuntimeError("prior_fail")
        return {"细菌性斑点病": 1.0}

    def fuse_multimodal_probs(self, image_probs, text_probs, prior_probs, image_confidence=0.0, text_confidence=0.0, text_evidence_active=None, **kwargs):
        fused = {}
        for probs in (image_probs, text_probs, prior_probs):
            for k, v in probs.items():
                fused[k] = fused.get(k, 0.0) + float(v)
        total = sum(fused.values())
        fused = {k: v / total for k, v in fused.items()} if total > 0 else {}
        return fused, {"has_image": bool(image_probs), "has_text": bool(text_probs), "has_prior": bool(prior_probs), "normalized_weights": {"image": 0.4, "text": 0.4, "prior": 0.2}}

    def build_diagnosis_evidence(self, **kwargs):
        return {"summary": "branch-failure"}

    def _get_disease_description(self, disease_type, symptoms):
        return disease_type


def test_image_only_empty_symptoms_has_no_text_branch(monkeypatch):
    _patch_kb(monkeypatch)
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


def test_no_evidence_not_healthy(monkeypatch):
    _patch_kb(monkeypatch)
    monkeypatch.setattr(agents_module, "get_diagnosis_engine", lambda **kwargs: _EngineNoEvidence())
    state = create_initial_state("test")
    state["crop_type"] = "番茄"
    state["symptoms"] = []
    state["image_path"] = None
    state["personalization_flags"] = {}

    out = agents_module.diagnosis_agent(state)
    assert out["final_disease"] != "健康"
    assert out["final_source"] == "insufficient_evidence"
    assert out["personalization_flags"]["need_confirm"] is True
    assert "insufficient_evidence" in (out["personalization_flags"].get("fallback_reason") or [])
    assert out.get("workflow_degraded") is True
    assert "no_active_evidence" in str(out.get("degraded_reason") or "")


def test_branch_failures_set_degraded_flags(monkeypatch):
    _patch_kb(monkeypatch)
    for fail_on, expected in [
        ("image", "image_branch_failed"),
        ("text", "text_branch_failed"),
        ("prior", "prior_branch_failed"),
    ]:
        def _factory(_fail_on=fail_on, **kwargs):
            return _EngineBranchFailure(_fail_on)
        monkeypatch.setattr(agents_module, "get_diagnosis_engine", _factory)
        state = create_initial_state("test")
        state["crop_type"] = "番茄"
        state["symptoms"] = ["叶片有斑点"]
        state["image_path"] = "exam.JPG"
        state["personalization_flags"] = {}
        out = agents_module.diagnosis_agent(state)
        assert out.get("workflow_degraded") is True
        assert expected in str(out.get("degraded_reason") or "")
        assert isinstance(out.get("diagnosis_evidence"), dict)


def test_follow_up_questions_separated_and_merged(monkeypatch):
    _patch_kb(monkeypatch)
    monkeypatch.setattr(agents_module, "get_diagnosis_engine", lambda **kwargs: _EngineNoEvidence())
    state = create_initial_state("图像路径: exam.JPG")
    state["personalization_flags"] = {}
    state = agents_module.reception_agent(state)
    state["profile_follow_up_questions"] = ["请补充种植地区？"]
    state["follow_up_questions"] = ["请补充种植地区？"]
    state["symptoms"] = []
    state["image_path"] = None

    out = agents_module.diagnosis_agent(state)
    assert out.get("profile_follow_up_questions") == ["请补充种植地区？"]
    assert isinstance(out.get("diagnosis_follow_up_questions"), list)
    assert "请补充种植地区？" in (out.get("follow_up_questions") or [])
