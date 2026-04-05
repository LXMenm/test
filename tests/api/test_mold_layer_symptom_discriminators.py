from __future__ import annotations

import json
from pathlib import Path

from knowledge_base.kb_manager import CANONICAL_DISEASES_10, KnowledgeBaseManager
from knowledge_base.symptom_discriminators import CONFUSION_GROUPS, SYMPTOM_ALIASES, build_default_symptom_payload
from symptom_pipeline import build_symptom_evidence_profile, get_text_evidence_level


def _build_kb_like() -> KnowledgeBaseManager:
    payload = json.loads(Path("data/kb/symptom_map.json").read_text(encoding="utf-8"))
    default_payload = build_default_symptom_payload()

    aliases = {
        str(k).strip(): str(v).strip()
        for k, v in (payload.get("symptom_aliases") or {}).items()
        if str(k).strip() and str(v).strip()
    }
    for alias, canonical in SYMPTOM_ALIASES.items():
        aliases.setdefault(alias, canonical)

    candidates = {
        str(k).strip(): [str(item).strip() for item in (v or []) if str(item).strip()]
        for k, v in (payload.get("symptom_candidates") or payload.get("symptom_map") or {}).items()
        if str(k).strip()
    }

    tiers = dict(default_payload.get("symptom_tiers") or {})
    tiers.update(payload.get("symptom_tiers") or {})
    tiers = {str(k).strip(): str(v).strip().lower() for k, v in tiers.items() if str(k).strip()}

    groups = dict(default_payload.get("symptom_discriminator_groups") or {})
    groups.update(payload.get("symptom_discriminator_groups") or {})
    groups = {
        str(k).strip(): [str(item).strip() for item in (v or []) if str(item).strip()]
        for k, v in groups.items()
        if str(k).strip()
    }

    hints = dict(default_payload.get("follow_up_hints") or {})
    hints.update(payload.get("follow_up_hints") or {})
    hints = {
        str(k).strip(): [str(item).strip() for item in (v or []) if str(item).strip()]
        for k, v in hints.items()
        if str(k).strip()
    }

    kb = KnowledgeBaseManager.__new__(KnowledgeBaseManager)
    kb.symptom_aliases = aliases
    kb.symptom_candidates = candidates
    kb.symptom_tiers = tiers
    kb.symptom_discriminator_groups = groups
    kb.follow_up_hints = hints
    kb.confusion_groups = {k: list(v) for k, v in CONFUSION_GROUPS.items()}
    kb.canonical_diseases = list(CANONICAL_DISEASES_10)
    return kb


def test_mold_layer_phrases_are_normalized_to_canonical_symptoms() -> None:
    kb = _build_kb_like()
    profile = build_symptom_evidence_profile(
        ["有霉层", "叶背有霉", "霉层明显", "叶背霉层", "白色霉层", "灰白霉层", "橄榄色霉层"],
        kb,
    )
    assert profile["normalized_tokens"] == ["叶背霉层", "叶背白霉", "叶背橄榄绒霉"]


def test_mold_layer_phrases_can_enter_discriminative_tokens() -> None:
    kb = _build_kb_like()
    profile = build_symptom_evidence_profile(["叶背有霉", "白色霉层", "橄榄色霉层"], kb)
    assert profile["discriminative_tokens"] == ["叶背霉层", "叶背白霉", "叶背橄榄绒霉"]
    assert profile["unknown_tokens"] == []


def test_mold_layer_phrases_upgrade_text_strength_when_applicable() -> None:
    kb = _build_kb_like()
    profile = build_symptom_evidence_profile(["有霉层"], kb)
    assert profile["has_discriminative_text_evidence"] is True
    assert get_text_evidence_level(profile, kb) == "strong"


def test_mold_layer_phrases_can_affect_candidate_rerank() -> None:
    kb = _build_kb_like()
    normalized = kb.normalize_symptoms(["白色霉层"])
    before = {"晚疫病": 0.34, "叶霉病": 0.33, "早疫病": 0.33}
    after = kb.rerank_text_candidates_with_discriminators(dict(before), normalized)
    assert after["晚疫病"] > before["晚疫病"]
    assert max(after, key=after.get) == "晚疫病"


def test_mold_layer_follow_up_questions_or_confusion_logic_use_new_symptoms_if_applicable() -> None:
    kb = _build_kb_like()
    questions = kb.generate_text_follow_up_questions(
        ["叶背有霉"],
        text_probs={"晚疫病": 0.41, "叶霉病": 0.39, "早疫病": 0.20},
    )
    assert questions
    assert any("霉层" in q for q in questions)
