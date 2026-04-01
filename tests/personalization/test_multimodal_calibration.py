from __future__ import annotations

import agents as agents_module
from diagnosis_model import DiseaseDiagnosisEngine
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
    monkeypatch.setattr(agents_module, "append_trace_event", lambda *args, **kwargs: None)
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


class _EngineConflictSpecific:
    def predict_image_proba(self, _):
        return {"细菌性斑点病": 0.70, "早疫病": 0.30}

    def predict_text_proba(self, **kwargs):
        return {"黄化曲叶病毒病": 0.75, "花叶病毒病": 0.25}

    def build_prior_proba(self, **kwargs):
        return {}

    def fuse_multimodal_probs(self, image_probs, text_probs, prior_probs, image_confidence=0.0, text_confidence=0.0, text_evidence_active=None):
        # 冲突时给出保守分布，触发 need_confirm
        return {
            "细菌性斑点病": 0.46,
            "黄化曲叶病毒病": 0.44,
            "早疫病": 0.06,
            "花叶病毒病": 0.04,
        }, {
            "has_image": True,
            "has_text": True,
            "has_prior": False,
            "normalized_weights": {"image": 0.5, "text": 0.5, "prior": 0.0},
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


def test_specific_conflict_sets_modality_flag_and_need_confirm(monkeypatch):
    state = _run_with_engine(monkeypatch, _EngineConflictSpecific(), symptoms=["发黄", "卷曲"], image_path="exam.JPG")
    assert state["modality_conflict_flag"] is True
    assert state["fusion_meta"].get("confidence_drop_reason") == "image_text_conflict"
    assert state["personalization_flags"].get("need_confirm") is True


class _EngineRealFusionWeakText:
    def __init__(self):
        self._fuser = DiseaseDiagnosisEngine.__new__(DiseaseDiagnosisEngine)

    def predict_image_proba(self, _):
        return {"细菌性斑点病": 0.9607, "早疫病": 0.0393}

    def predict_text_proba(self, **kwargs):
        return {"健康": 0.1425, "细菌性斑点病": 0.1385, "晚疫病": 0.1000}

    def build_prior_proba(self, **kwargs):
        return {}

    def fuse_multimodal_probs(self, image_probs, text_probs, prior_probs, image_confidence=0.0, text_confidence=0.0, text_evidence_active=None):
        return DiseaseDiagnosisEngine.fuse_multimodal_probs(
            self._fuser,
            image_probs=image_probs,
            text_probs=text_probs,
            prior_probs=prior_probs,
            image_confidence=image_confidence,
            text_confidence=text_confidence,
            text_evidence_active=text_evidence_active,
        )

    def build_diagnosis_evidence(self, **kwargs):
        return {
            "modality_conflict_flag": kwargs["modality_conflict_flag"],
            "detailed_reason": "real-fusion-weak-text",
            "concise_summary": "real-fusion-weak-text",
            "summary": "real-fusion-weak-text",
        }

    def _get_disease_description(self, disease_type, symptoms):
        return disease_type


class _EngineRealFusionConsistentReliable:
    def __init__(self):
        self._fuser = DiseaseDiagnosisEngine.__new__(DiseaseDiagnosisEngine)

    def predict_image_proba(self, _):
        return {"细菌性斑点病": 0.91, "早疫病": 0.09}

    def predict_text_proba(self, **kwargs):
        return {"细菌性斑点病": 0.72, "晚疫病": 0.20, "健康": 0.08}

    def build_prior_proba(self, **kwargs):
        return {}

    def fuse_multimodal_probs(self, image_probs, text_probs, prior_probs, image_confidence=0.0, text_confidence=0.0, text_evidence_active=None):
        return DiseaseDiagnosisEngine.fuse_multimodal_probs(
            self._fuser,
            image_probs=image_probs,
            text_probs=text_probs,
            prior_probs=prior_probs,
            image_confidence=image_confidence,
            text_confidence=text_confidence,
            text_evidence_active=text_evidence_active,
        )

    def build_diagnosis_evidence(self, **kwargs):
        return {"modality_conflict_flag": kwargs["modality_conflict_flag"], "summary": "consistent-reliable"}

    def _get_disease_description(self, disease_type, symptoms):
        return disease_type


class _EngineRealFusionConflictReliable:
    def __init__(self):
        self._fuser = DiseaseDiagnosisEngine.__new__(DiseaseDiagnosisEngine)

    def predict_image_proba(self, _):
        return {"细菌性斑点病": 0.90, "早疫病": 0.10}

    def predict_text_proba(self, **kwargs):
        return {"健康": 0.70, "细菌性斑点病": 0.20, "晚疫病": 0.10}

    def build_prior_proba(self, **kwargs):
        return {}

    def fuse_multimodal_probs(self, image_probs, text_probs, prior_probs, image_confidence=0.0, text_confidence=0.0, text_evidence_active=None):
        return DiseaseDiagnosisEngine.fuse_multimodal_probs(
            self._fuser,
            image_probs=image_probs,
            text_probs=text_probs,
            prior_probs=prior_probs,
            image_confidence=image_confidence,
            text_confidence=text_confidence,
            text_evidence_active=text_evidence_active,
        )

    def build_diagnosis_evidence(self, **kwargs):
        return {"modality_conflict_flag": kwargs["modality_conflict_flag"], "summary": "conflict-reliable"}

    def _get_disease_description(self, disease_type, symptoms):
        return disease_type


def test_image_strong_text_weak_no_conflict_and_no_confirm(monkeypatch):
    state = _run_with_engine(monkeypatch, _EngineRealFusionWeakText(), symptoms=["叶片有斑点"], image_path="exam.JPG")
    assert state["fusion_meta"].get("image_reliable") is True
    assert state["fusion_meta"].get("text_reliable") is False
    assert state["modality_conflict_flag"] is False
    assert state["fusion_meta"].get("fusion_case") == "image_strong_text_weak"
    assert state["fusion_meta"].get("confidence_drop_reason") != "image_text_conflict"
    assert state["personalization_flags"].get("need_confirm") is False
    assert state["final_confidence"] >= 0.85


def test_image_strong_text_consistent_reliable(monkeypatch):
    state = _run_with_engine(monkeypatch, _EngineRealFusionConsistentReliable(), symptoms=["叶片有斑点"], image_path="exam.JPG")
    assert state["fusion_meta"].get("image_reliable") is True
    assert state["fusion_meta"].get("text_reliable") is True
    assert state["modality_conflict_flag"] is False
    assert state["fusion_meta"].get("fusion_case") == "consistent"
    assert state["final_confidence"] >= 0.70


def test_image_strong_text_conflict_reliable_sets_need_confirm(monkeypatch):
    state = _run_with_engine(monkeypatch, _EngineRealFusionConflictReliable(), symptoms=["叶片疑似健康"], image_path="exam.JPG")
    assert state["fusion_meta"].get("image_reliable") is True
    assert state["fusion_meta"].get("text_reliable") is True
    assert state["modality_conflict_flag"] is True
    assert state["fusion_meta"].get("fusion_case") == "conflict"
    assert state["fusion_meta"].get("confidence_drop_reason") == "image_text_conflict"
    assert state["personalization_flags"].get("need_confirm") is True


class _EngineBlurryEarlyBlightConflict:
    def __init__(self):
        self._fuser = DiseaseDiagnosisEngine.__new__(DiseaseDiagnosisEngine)

    def predict_image_proba(self, _):
        return {"蜘蛛螨": 0.8969, "早疫病": 0.0529, "晚疫病": 0.05}

    def predict_text_proba(self, **kwargs):
        return {"早疫病": 0.5611, "叶斑病": 0.1342, "晚疫病": 0.3047}

    def build_prior_proba(self, **kwargs):
        return {}

    def fuse_multimodal_probs(self, image_probs, text_probs, prior_probs, image_confidence=0.0, text_confidence=0.0, text_evidence_active=None, normalized_symptoms=None, image_quality_flags=None, image_quality_hint=None):
        return DiseaseDiagnosisEngine.fuse_multimodal_probs(
            self._fuser,
            image_probs=image_probs,
            text_probs=text_probs,
            prior_probs=prior_probs,
            image_confidence=image_confidence,
            text_confidence=text_confidence,
            text_evidence_active=text_evidence_active,
            normalized_symptoms=normalized_symptoms,
            image_quality_flags=image_quality_flags,
            image_quality_hint=image_quality_hint,
        )

    def build_diagnosis_evidence(self, **kwargs):
        return {"modality_conflict_flag": kwargs["modality_conflict_flag"], "summary": "blurry-image-strong-text"}

    def _get_disease_description(self, disease_type, symptoms):
        return disease_type


def test_blurry_early_blight_image_with_strong_text_should_downgrade_to_image_only(monkeypatch):
    monkeypatch.setattr(agents_module, "get_diagnosis_engine", lambda **kwargs: _EngineBlurryEarlyBlightConflict())
    monkeypatch.setattr(agents_module, "append_trace_event", lambda *args, **kwargs: None)
    state = create_initial_state("test")
    state["crop_type"] = "番茄"
    state["symptoms"] = ["同心轮纹", "老叶先发病"]
    state["image_path"] = "blurry.JPG"
    state["personalization_flags"] = {"confirm_when_low_confidence": True}
    state["image_quality_flags"] = ["blur", "disease-region-unclear"]
    state = agents_module.diagnosis_agent(state)
    assert state["image_reliable"] is False
    assert state["text_reliable"] is True
    assert state["fusion_meta"].get("fusion_case") == "image_weak_text_strong"
    assert state["supplement_mode"] == "image_only"
    assert state["fusion_meta"].get("image_downgraded_on_conflict") is True
    assert state["personalization_flags"].get("need_confirm") is True
    reasons = state["personalization_flags"].get("fallback_reason") or []
    assert "weak_image_text_conflict" in reasons


class _EngineRealFusionImageWeakTextStrong:
    def __init__(self):
        self._fuser = DiseaseDiagnosisEngine.__new__(DiseaseDiagnosisEngine)

    def predict_image_proba(self, _):
        return {"细菌性斑点病": 0.42, "早疫病": 0.35, "晚疫病": 0.23}

    def predict_text_proba(self, **kwargs):
        return {"健康": 0.62, "细菌性斑点病": 0.18, "晚疫病": 0.20}

    def build_prior_proba(self, **kwargs):
        return {}

    def fuse_multimodal_probs(self, image_probs, text_probs, prior_probs, image_confidence=0.0, text_confidence=0.0, text_evidence_active=None):
        return DiseaseDiagnosisEngine.fuse_multimodal_probs(
            self._fuser,
            image_probs=image_probs,
            text_probs=text_probs,
            prior_probs=prior_probs,
            image_confidence=image_confidence,
            text_confidence=text_confidence,
            text_evidence_active=text_evidence_active,
        )

    def build_diagnosis_evidence(self, **kwargs):
        return {"modality_conflict_flag": kwargs["modality_conflict_flag"], "summary": "image-weak-text-strong"}

    def _get_disease_description(self, disease_type, symptoms):
        return disease_type


class _EngineRealFusionBothWeak:
    def __init__(self):
        self._fuser = DiseaseDiagnosisEngine.__new__(DiseaseDiagnosisEngine)

    def predict_image_proba(self, _):
        return {"细菌性斑点病": 0.38, "早疫病": 0.31, "晚疫病": 0.31}

    def predict_text_proba(self, **kwargs):
        return {"健康": 0.16, "细菌性斑点病": 0.14, "晚疫病": 0.12}

    def build_prior_proba(self, **kwargs):
        return {}

    def fuse_multimodal_probs(self, image_probs, text_probs, prior_probs, image_confidence=0.0, text_confidence=0.0, text_evidence_active=None):
        return DiseaseDiagnosisEngine.fuse_multimodal_probs(
            self._fuser,
            image_probs=image_probs,
            text_probs=text_probs,
            prior_probs=prior_probs,
            image_confidence=image_confidence,
            text_confidence=text_confidence,
            text_evidence_active=text_evidence_active,
        )

    def build_diagnosis_evidence(self, **kwargs):
        return {"modality_conflict_flag": kwargs["modality_conflict_flag"], "summary": "both-weak"}

    def _get_disease_description(self, disease_type, symptoms):
        return disease_type


def test_image_weak_text_strong_text_dominant_no_confirm(monkeypatch):
    state = _run_with_engine(monkeypatch, _EngineRealFusionImageWeakTextStrong(), symptoms=["叶片状态尚可"], image_path="exam.JPG")
    assert state["fusion_meta"].get("image_reliable") is False
    assert state["fusion_meta"].get("text_reliable") is True
    assert state["fusion_meta"].get("fusion_case") == "image_weak_text_strong"
    assert state["modality_conflict_flag"] is False
    assert state["personalization_flags"].get("need_confirm") is False


def test_image_weak_text_weak_sets_need_confirm(monkeypatch):
    state = _run_with_engine(monkeypatch, _EngineRealFusionBothWeak(), symptoms=["有点异常"], image_path="exam.JPG")
    assert state["fusion_meta"].get("image_reliable") is False
    assert state["fusion_meta"].get("text_reliable") is False
    assert state["fusion_meta"].get("fusion_case") == "both_weak"
    assert state["modality_conflict_flag"] is False
    assert state["personalization_flags"].get("need_confirm") is True
    assert state["final_confidence"] < 0.6
