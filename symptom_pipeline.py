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


def get_text_evidence_level(symptoms_profile: dict, kb_manager: Any) -> str:
    normalized_tokens = [str(item).strip() for item in (symptoms_profile or {}).get("normalized_tokens", []) if str(item).strip()]
    if not normalized_tokens:
        return "none"

    try:
        if kb_manager.has_discriminative_text_evidence(normalized_tokens):
            return "strong"
    except Exception:
        pass

    discriminative_tokens = [str(item).strip() for item in (symptoms_profile or {}).get("discriminative_tokens", []) if str(item).strip()]
    if discriminative_tokens:
        return "strong"

    candidate_diseases = [str(item).strip() for item in (symptoms_profile or {}).get("candidate_diseases", []) if str(item).strip()]
    if len(candidate_diseases) >= 2:
        return "medium"
    if len(candidate_diseases) == 1:
        return "medium"

    generic_tokens = [str(item).strip() for item in (symptoms_profile or {}).get("generic_tokens", []) if str(item).strip()]
    unknown_tokens = [str(item).strip() for item in (symptoms_profile or {}).get("unknown_tokens", []) if str(item).strip()]
    if generic_tokens or unknown_tokens:
        return "weak"

    return "weak"
