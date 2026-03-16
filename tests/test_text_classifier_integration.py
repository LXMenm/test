from __future__ import annotations

from types import MethodType

import diagnosis_model as dm


class _StubBertClassifier:
    def predict_text_probs(self, **kwargs):
        labels = dm.DISEASE_CLASSES
        base = {label: 0.0 for label in labels}
        base["黄化曲叶病毒病"] = 0.7
        base["花叶病毒病"] = 0.2
        base["健康"] = 0.1
        return base


def _make_engine() -> dm.DiseaseDiagnosisEngine:
    engine = object.__new__(dm.DiseaseDiagnosisEngine)
    engine.text_classifier = None
    engine.text_classifier_available = None
    return engine


def test_predict_text_proba_fallbacks_to_rule_based_when_bert_unavailable():
    engine = _make_engine()
    engine.text_classifier_available = False

    def _rule(self, **kwargs):
        return {"黄化曲叶病毒病": 0.6, "花叶病毒病": 0.4}

    engine.predict_text_proba_rule_based = MethodType(_rule, engine)

    probs = dm.DiseaseDiagnosisEngine.predict_text_proba(
        engine,
        symptoms=["发黄", "卷曲"],
        growth_stage="SEEDLING",
    )
    assert probs == {"黄化曲叶病毒病": 0.6, "花叶病毒病": 0.4}


def test_predict_text_proba_bert_returns_canonical_10_class_distribution():
    engine = _make_engine()
    stub = _StubBertClassifier()

    engine._ensure_text_classifier = MethodType(lambda self: stub, engine)

    probs = dm.DiseaseDiagnosisEngine.predict_text_proba_bert(
        engine,
        symptoms=["发黄", "卷曲"],
        growth_stage="SEEDLING",
        environment="高温",
    )
    assert set(probs.keys()).issubset(set(dm.DISEASE_CLASSES))
    assert len(probs) == len(dm.DISEASE_CLASSES)
    assert abs(sum(probs.values()) - 1.0) < 1e-6


def test_predict_text_proba_returns_empty_without_text_evidence():
    engine = _make_engine()
    probs = dm.DiseaseDiagnosisEngine.predict_text_proba(engine, symptoms=[])
    assert probs == {}


def test_fuse_with_image_and_empty_text_still_works():
    engine = _make_engine()
    fused, meta = dm.DiseaseDiagnosisEngine.fuse_multimodal_probs(
        engine,
        image_probs={"细菌性斑点病": 0.88, "早疫病": 0.12},
        text_probs={},
        prior_probs={"细菌性斑点病": 1.0},
        image_confidence=0.88,
        text_confidence=0.0,
        text_evidence_active=False,
    )
    assert fused
    assert meta.get("has_text") is False
    assert max(fused.values()) >= 0.8
