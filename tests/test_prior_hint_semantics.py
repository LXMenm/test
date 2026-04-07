from diagnosis_model import DiseaseDiagnosisEngine


def test_prior_display_uses_hint_score_not_hard_probability() -> None:
    engine = DiseaseDiagnosisEngine.__new__(DiseaseDiagnosisEngine)
    prior_probs = {"叶霉病": 1.0}

    evidence = DiseaseDiagnosisEngine.build_diagnosis_evidence(
        engine,
        normalized_symptoms=[],
        raw_symptoms=[],
        image_probs={},
        text_probs={},
        prior_probs=prior_probs,
        fusion_probs={"叶霉病": 1.0},
        fusion_meta={},
        modality_conflict_flag=False,
        final_disease="叶霉病",
        final_confidence=1.0,
        final_source="prior",
    )

    assert evidence["prior_semantics"] == "hint_score_preference"
    assert "prior_top3_raw" not in evidence
    assert "debug_prior_top3_raw" not in evidence
    assert evidence["prior_top3"][0][0] == "叶霉病"
    assert evidence["prior_top3"][0][1] < 1.0


def test_prior_raw_and_hint_are_both_preserved_for_debug_and_analysis() -> None:
    engine = DiseaseDiagnosisEngine.__new__(DiseaseDiagnosisEngine)
    fused, meta = DiseaseDiagnosisEngine.fuse_multimodal_probs(
        engine,
        image_probs={},
        text_probs={},
        prior_probs={"叶霉病": 0.7, "晚疫病": 0.3},
        text_evidence_active=False,
    )

    assert fused
    assert "pre_fusion_top3_raw" in meta
    assert "pre_fusion_top3_hint" in meta
    assert meta["pre_fusion_top3_raw"]["prior"]
    assert meta["pre_fusion_top3_hint"]["prior"]


def test_detailed_reason_uses_prior_preference_wording_instead_of_final_like_probability() -> None:
    engine = DiseaseDiagnosisEngine.__new__(DiseaseDiagnosisEngine)
    evidence = DiseaseDiagnosisEngine.build_diagnosis_evidence(
        engine,
        normalized_symptoms=[],
        raw_symptoms=[],
        image_probs={"叶霉病": 0.6},
        text_probs={},
        prior_probs={"叶霉病": 1.0},
        fusion_probs={"叶霉病": 0.8},
        fusion_meta={},
        modality_conflict_flag=False,
        final_disease="叶霉病",
        final_confidence=0.8,
        final_source="fusion",
    )

    reason = evidence["detailed_reason"]
    assert "先验偏好top1" in reason
    assert "hint=" in reason
    assert "raw=1.00" not in reason


def test_prior_raw_scores_available_only_in_debug_mode() -> None:
    engine = DiseaseDiagnosisEngine.__new__(DiseaseDiagnosisEngine)
    evidence = DiseaseDiagnosisEngine.build_diagnosis_evidence(
        engine,
        normalized_symptoms=[],
        raw_symptoms=[],
        image_probs={},
        text_probs={},
        prior_probs={"叶霉病": 1.0},
        fusion_probs={"叶霉病": 1.0},
        fusion_meta={},
        modality_conflict_flag=False,
        final_disease="叶霉病",
        final_confidence=1.0,
        final_source="prior",
        include_prior_raw_debug=True,
    )

    assert evidence["debug_prior_top3_raw"][0] == ("叶霉病", 1.0)
    assert evidence["debug_prior_semantics"] == "raw_probability_debug_only"


def test_prior_display_changes_do_not_affect_fusion_math() -> None:
    engine = DiseaseDiagnosisEngine.__new__(DiseaseDiagnosisEngine)
    fused = {"叶霉病": 0.55, "晚疫病": 0.45}
    top1 = max(fused.items(), key=lambda item: item[1])[0]
    evidence = DiseaseDiagnosisEngine.build_diagnosis_evidence(
        engine,
        normalized_symptoms=[],
        raw_symptoms=[],
        image_probs={"叶霉病": 0.7, "晚疫病": 0.3},
        text_probs={"叶霉病": 0.4, "晚疫病": 0.6},
        prior_probs={"叶霉病": 1.0},
        fusion_probs=fused,
        fusion_meta={},
        modality_conflict_flag=False,
        final_disease=top1,
        final_confidence=fused[top1],
        final_source="fusion",
    )
    assert evidence["fusion_top3"][0][0] == top1
