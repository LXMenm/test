from __future__ import annotations

import agents as agents_module
from state import create_initial_state


class _EngineTextOnly:
    def predict_text_proba(self, **kwargs):
        return {"黄化曲叶病毒病": 0.82, "花叶病毒病": 0.18}

    def build_prior_proba(self, **kwargs):
        return {}

    def fuse_multimodal_probs(self, image_probs, text_probs, prior_probs, image_confidence=0.0, text_confidence=0.0):
        return dict(text_probs), {
            "has_image": False,
            "has_text": True,
            "has_prior": False,
            "normalized_weights": {"image": 0.0, "text": 1.0, "prior": 0.0},
            "post_fusion_top3": sorted(text_probs.items(), key=lambda x: x[1], reverse=True)[:3],
        }

    def build_diagnosis_evidence(self, **kwargs):
        return {
            "normalized_symptoms": kwargs["normalized_symptoms"],
            "raw_symptoms": kwargs["raw_symptoms"],
            "image_top3": [],
            "text_top3": sorted(kwargs["text_probs"].items(), key=lambda x: x[1], reverse=True)[:3],
            "prior_top3": [],
            "fusion_top3": sorted(kwargs["fusion_probs"].items(), key=lambda x: x[1], reverse=True)[:3],
            "weights": kwargs["fusion_meta"].get("normalized_weights", {}),
            "modality_conflict_flag": kwargs["modality_conflict_flag"],
            "final_disease": kwargs["final_disease"],
            "final_confidence": kwargs["final_confidence"],
            "final_source": kwargs["final_source"],
            "concise_summary": "文本分支主导",
            "detailed_reason": "仅文本输入",
            "summary": "文本分支主导",
        }

    def _get_disease_description(self, disease_type, symptoms):
        return f"{disease_type}:{','.join(symptoms or [])}"


class _EngineImageOnly:
    def predict_image_proba(self, _):
        return {"细菌性斑点病": 0.97, "早疫病": 0.03}

    def predict_text_proba(self, **kwargs):
        return {}

    def build_prior_proba(self, **kwargs):
        return {"细菌性斑点病": 0.6, "叶霉病": 0.4}

    def fuse_multimodal_probs(self, image_probs, text_probs, prior_probs, image_confidence=0.0, text_confidence=0.0):
        # 模拟修复后的 IMAGE_ONLY 弱先验
        fused = {
            "细菌性斑点病": 0.95 * 0.97 + 0.05 * 0.6,
            "早疫病": 0.95 * 0.03,
            "叶霉病": 0.05 * 0.4,
        }
        total = sum(fused.values())
        fused = {k: v / total for k, v in fused.items()}
        return fused, {
            "has_image": True,
            "has_text": False,
            "has_prior": True,
            "normalized_weights": {"image": 0.95, "text": 0.0, "prior": 0.05},
            "post_fusion_top3": sorted(fused.items(), key=lambda x: x[1], reverse=True)[:3],
        }

    def build_diagnosis_evidence(self, **kwargs):
        return {"summary": "image-only", "concise_summary": "image-only", "detailed_reason": "image-only"}

    def _get_disease_description(self, disease_type, symptoms):
        return disease_type


class _EngineImageTextConsistent:
    def predict_image_proba(self, _):
        return {"细菌性斑点病": 0.88, "早疫病": 0.12}

    def predict_text_proba(self, **kwargs):
        return {"细菌性斑点病": 0.73, "晚疫病": 0.27}

    def build_prior_proba(self, **kwargs):
        return {"细菌性斑点病": 0.6, "叶霉病": 0.4}

    def fuse_multimodal_probs(self, image_probs, text_probs, prior_probs, image_confidence=0.0, text_confidence=0.0):
        fused = {
            "细菌性斑点病": 0.60 * 0.88 + 0.35 * 0.73 + 0.05 * 0.6,
            "早疫病": 0.60 * 0.12,
            "晚疫病": 0.35 * 0.27,
            "叶霉病": 0.05 * 0.4,
        }
        total = sum(fused.values())
        fused = {k: v / total for k, v in fused.items()}
        return fused, {"normalized_weights": {"image": 0.60, "text": 0.35, "prior": 0.05}}

    def build_diagnosis_evidence(self, **kwargs):
        return {
            "modality_conflict_flag": kwargs["modality_conflict_flag"],
            "detailed_reason": "consistent",
            "concise_summary": "consistent",
            "summary": "consistent",
        }

    def _get_disease_description(self, disease_type, symptoms):
        return disease_type


class _EngineImageTextConflict:
    def predict_image_proba(self, _):
        return {"早疫病": 0.86, "晚疫病": 0.14}

    def predict_text_proba(self, **kwargs):
        return {"黄化曲叶病毒病": 0.81, "花叶病毒病": 0.19}

    def build_prior_proba(self, **kwargs):
        return {"叶霉病": 1.0}

    def fuse_multimodal_probs(self, image_probs, text_probs, prior_probs, image_confidence=0.0, text_confidence=0.0):
        fused = {
            "早疫病": 0.45 * 0.86,
            "晚疫病": 0.45 * 0.14,
            "黄化曲叶病毒病": 0.45 * 0.81,
            "花叶病毒病": 0.45 * 0.19,
            "叶霉病": 0.10 * 1.0,
        }
        total = sum(fused.values())
        fused = {k: v / total for k, v in fused.items()}
        return fused, {
            "normalized_weights": {"image": 0.45, "text": 0.45, "prior": 0.10},
            "confidence_drop_reason": "image_text_conflict",
        }

    def build_diagnosis_evidence(self, **kwargs):
        return {
            "modality_conflict_flag": kwargs["modality_conflict_flag"],
            "detailed_reason": "图像与文本冲突",
            "concise_summary": "冲突",
            "summary": "冲突",
        }

    def _get_disease_description(self, disease_type, symptoms):
        return disease_type


def _run_with_engine(monkeypatch, engine, *, symptoms=None, image_path=None):
    monkeypatch.setattr(agents_module, "get_diagnosis_engine", lambda **kwargs: engine)
    state = create_initial_state("test")
    state["crop_type"] = "番茄"
    state["symptoms"] = symptoms or []
    state["image_path"] = image_path
    state["personalization_flags"] = {"confirm_when_low_confidence": True}
    return agents_module.diagnosis_agent(state)


def test_text_only_regression(monkeypatch):
    state = _run_with_engine(monkeypatch, _EngineTextOnly(), symptoms=["发黄", "卷曲", "生长缓慢"], image_path=None)
    assert state["final_source"] == "fusion"
    assert state["text_probs"]
    assert not state["image_probs"]
    assert state["final_disease"] == "黄化曲叶病毒病"


def test_image_only_high_conf_not_over_diluted(monkeypatch):
    state = _run_with_engine(monkeypatch, _EngineImageOnly(), symptoms=[], image_path="exam.JPG")
    assert state["final_disease"] == "细菌性斑点病"
    assert state["image_confidence"] >= 0.95
    assert state["final_confidence"] >= 0.85


def test_image_text_consistent_confidence_reasonable(monkeypatch):
    state = _run_with_engine(monkeypatch, _EngineImageTextConsistent(), symptoms=["斑点", "水渍"], image_path="exam.JPG")
    assert state["final_disease"] == "细菌性斑点病"
    assert state["modality_conflict_flag"] is False
    assert state["final_confidence"] >= 0.70


def test_image_text_conflict_generates_conflict_evidence(monkeypatch):
    state = _run_with_engine(monkeypatch, _EngineImageTextConflict(), symptoms=["发黄", "卷曲", "生长缓慢"], image_path="exam.JPG")
    assert state["modality_conflict_flag"] is True
    assert state["diagnosis_evidence"]
    assert "冲突" in (state["diagnosis_evidence"].get("detailed_reason") or "")
    assert state.get("follow_up_questions")
