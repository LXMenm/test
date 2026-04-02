from __future__ import annotations

import diagnosis_model as dm
from confusion_handling import handle_confusing_cases


def test_fusion_uses_adjusted_text_distribution_and_inserts_new_class(monkeypatch):
    engine = dm.DiseaseDiagnosisEngine(backend="tf", model_path="/tmp/not-exist.keras")

    def fake_handle(top_class, **kwargs):
        if kwargs.get("fusion_case") == "text_only":
            return {
                "is_adjusted": True,
                "label_changed": True,
                "confidence_changed": True,
                "original_class": top_class,
                "adjusted_class": "早疫病",
                "target_confusing_class": "早疫病",
                "adjusted_confidence": 0.78,
                "reason": "unit-test",
            }
        return {
            "is_adjusted": False,
            "label_changed": False,
            "confidence_changed": False,
            "original_class": top_class,
            "adjusted_class": top_class,
            "target_confusing_class": None,
            "adjusted_confidence": 0.0,
            "reason": "",
        }

    monkeypatch.setattr(dm, "handle_confusing_cases", fake_handle)

    image_probs = {"细菌性斑点病": 0.82, "健康": 0.18}
    text_probs = {"细菌性斑点病": 0.66, "健康": 0.34}
    fused, meta = engine.fuse_multimodal_probs(image_probs, text_probs, {}, normalized_symptoms=["轮纹"])

    adjusted_text_top3 = (meta.get("pre_fusion_top3_adjusted") or {}).get("text") or []
    adjusted_labels = [name for name, _ in adjusted_text_top3]
    assert "早疫病" in adjusted_labels
    assert "早疫病" in fused


def test_confusing_pair_threshold_and_flags_are_applied():
    result = handle_confusing_cases(
        "早疫病",
        symptoms=[],
        confidence=0.9,
        top_candidates=[("早疫病", 0.9), ("细菌性斑点病", 0.1)],
    )
    assert result["is_adjusted"] is True
    assert result["confidence_changed"] is True
    assert "target_confusing_class" in result

