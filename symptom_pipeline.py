from __future__ import annotations

from typing import Any

from symptom_parsing import parse_symptoms_input


def build_symptom_evidence_profile(symptoms: list[str], kb_manager: Any) -> dict:
    raw_tokens = parse_symptoms_input(symptoms)

    try:
        normalized_tokens = kb_manager.normalize_symptoms(raw_tokens)
    except Exception:
        normalized_tokens = list(raw_tokens)

    tier_map = getattr(kb_manager, "symptom_tiers", {}) or {}
    candidate_map = getattr(kb_manager, "symptom_candidates", {}) or {}

    unknown_tokens: list[str] = []
    generic_tokens: list[str] = []
    discriminative_tokens: list[str] = []

    for token in normalized_tokens:
        tier = str(tier_map.get(token, "")).strip().lower()
        has_candidates = bool(candidate_map.get(token))
        if tier == "discriminative":
            discriminative_tokens.append(token)
        elif tier == "generic":
            generic_tokens.append(token)
        elif not has_candidates:
            unknown_tokens.append(token)

    try:
        has_any_text_evidence = bool(kb_manager.has_effective_text_evidence(normalized_tokens))
    except Exception:
        has_any_text_evidence = bool(normalized_tokens)

    try:
        has_discriminative_text_evidence = bool(kb_manager.has_discriminative_text_evidence(normalized_tokens))
    except Exception:
        has_discriminative_text_evidence = bool(discriminative_tokens)

    try:
        candidate_diseases = list(kb_manager.get_candidate_diseases_from_symptoms(normalized_tokens) or [])
    except Exception:
        candidate_diseases = []

    try:
        follow_up_hints = list(kb_manager.generate_text_follow_up_questions(normalized_tokens) or [])
    except Exception:
        follow_up_hints = []

    return {
        "raw_tokens": raw_tokens,
        "normalized_tokens": normalized_tokens,
        "unknown_tokens": unknown_tokens,
        "generic_tokens": generic_tokens,
        "discriminative_tokens": discriminative_tokens,
        "has_any_text_evidence": has_any_text_evidence,
        "has_discriminative_text_evidence": has_discriminative_text_evidence,
        "candidate_diseases": candidate_diseases,
        "follow_up_hints": follow_up_hints,
    }
