from __future__ import annotations

from typing import Any

CONFUSING_PAIRS: list[dict[str, Any]] = [
    {
        "pair": ("细菌性斑点病", "早疫病"),
        "confidence_threshold": 0.72,
        "keywords": ["水渍", "油浸", "小黑点", "痂状", "裂纹"],
    },
    {
        "pair": ("早疫病", "靶斑病"),
        "confidence_threshold": 0.76,
        "keywords": ["同心轮纹", "靶心", "圆斑", "黑色小点"],
    },
    {
        "pair": ("黄化曲叶病毒病", "花叶病毒病"),
        "confidence_threshold": 0.68,
        "keywords": ["黄化上卷", "花叶", "畸形", "节间缩短", "蕨叶"],
    },
    {
        "pair": ("蜘蛛螨", "早疫病"),
        "confidence_threshold": 0.70,
        "keywords": ["细网", "叶背虫点", "青铜化", "黄白小点"],
    },
]


def _normalize_symptoms(symptoms: list[str] | None) -> list[str]:
    return [str(s).strip().lower() for s in (symptoms or []) if str(s).strip()]


def handle_confusing_cases(
    top_class: str | None,
    *,
    symptoms: list[str] | None,
    confidence: float,
    top_candidates: list[tuple[str, float]] | None = None,
    fallback_reason: str | None = None,
    fusion_case: str | None = None,
) -> dict[str, Any]:
    symptoms_norm = _normalize_symptoms(symptoms)
    candidates = [name for name, _ in (top_candidates or [])]
    fallback_text = str(fallback_reason or "").lower()
    fusion_text = str(fusion_case or "").lower()
    top_class = str(top_class or "").strip()
    if not top_class:
        return {
            "is_adjusted": False,
            "label_changed": False,
            "confidence_changed": False,
            "original_class": None,
            "adjusted_class": None,
            "target_confusing_class": None,
            "adjusted_confidence": float(confidence),
            "reason": "",
        }

    for rule in CONFUSING_PAIRS:
        a, b = rule["pair"]
        pair_threshold = float(rule.get("confidence_threshold", 0.80))
        image_only_threshold = min(pair_threshold, 0.80)
        if top_class not in {a, b}:
            continue
        other = b if top_class == a else a
        has_pair_context = other in candidates or "conflict" in fallback_text or "conflict" in fusion_text
        keyword_hit = any(any(k in sym for k in rule.get("keywords", [])) for sym in symptoms_norm)
        if keyword_hit and has_pair_context:
            return {
                "is_adjusted": True,
                "label_changed": True,
                "confidence_changed": True,
                "original_class": top_class,
                "adjusted_class": other,
                "target_confusing_class": other,
                "adjusted_confidence": max(float(confidence) * 0.92, pair_threshold * 0.95),
                "reason": f"匹配易混淆对{a}/{b}并命中区分关键词，执行类别修正",
            }
        if (not symptoms_norm) and confidence >= image_only_threshold and has_pair_context:
            return {
                "is_adjusted": True,
                "label_changed": False,
                "confidence_changed": True,
                "original_class": top_class,
                "adjusted_class": top_class,
                "target_confusing_class": other,
                "adjusted_confidence": max(pair_threshold, float(confidence) * 0.85),
                "reason": f"命中易混淆对{a}/{b}，无症状证据时仅下调置信度",
            }

    return {
        "is_adjusted": False,
        "label_changed": False,
        "confidence_changed": False,
        "original_class": top_class,
        "adjusted_class": top_class,
        "target_confusing_class": None,
        "adjusted_confidence": float(confidence),
        "reason": "",
    }

