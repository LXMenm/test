from __future__ import annotations

import re
from typing import Any, Iterable, Mapping


def _normalize_follow_up_question_text(text: str) -> str:
    return re.sub(r"\s+", "", text).replace("？", "").replace("?", "").rstrip("。.!！:：；;")


def _infer_follow_up_intent_key(text: str) -> str:
    normalized = _normalize_follow_up_question_text(text)
    if not normalized:
        return ""

    intent_patterns = [
        ("image_capture", ("清晰近照", "病叶正反面", "整体株型", "重新拍摄", "补充图片", "上传图片", "叶片正反面")),
        ("spot_morphology", ("病斑颜色", "边缘是否清晰", "水渍感", "霉层", "病斑是同心轮纹", "靶心状", "水渍状扩展", "病斑形态", "斑点形态", "斑点边缘")),
        ("recent_humidity_ventilation", ("高湿", "连阴雨", "通风", "棚内", "湿度")),
        ("pest_vector_activity", ("白粉虱", "蚜虫", "虫害", "虫口", "媒介昆虫")),
        ("growth_stage", ("生育期", "苗期", "开花", "结果")),
        ("equipment", ("喷施设备", "喷雾器", "弥雾机", "无人机")),
        ("farm_scale", ("种植规模", "家庭（小）", "中等", "企业级（大）")),
        ("pesticide_access_level", ("购药能力", "购药渠道", "NONE", "LIMITED", "FULL")),
        ("cultivation_mode", ("栽培模式", "土培", "水培", "基质栽培")),
        ("harvest_window_days", ("计划采收", "采收还有多少天", "距离采收")),
        ("prefer_organic", ("有机", "低残留")),
        ("banned_ingredients", ("禁用成分", "禁用药剂")),
    ]

    for intent_key, patterns in intent_patterns:
        if any(pattern in normalized for pattern in patterns):
            return intent_key
    return normalized


def _canonicalize_follow_up_question(text: str, intent_key: str) -> str:
    canonical_map = {
        "recent_humidity_ventilation": "近3天是否出现高湿、连阴雨或棚内通风不足？",
        "spot_morphology": "请描述病斑颜色、边缘是否清晰、是否有水渍感或霉层。",
    }
    return canonical_map.get(intent_key, text)


def _normalize_reason(reason: str) -> str:
    text = reason.strip()
    if not text:
        return ""
    text = " ".join(text.split())
    text = text.rstrip("。.").strip()
    if not text:
        return ""
    return f"{text}。"


def dedupe_reasons(reasons: Iterable[str | None]) -> list[str]:
    """Stable de-dup for display-layer reasons with light normalization."""
    seen: set[str] = set()
    result: list[str] = []
    for item in reasons:
        if item is None:
            continue
        normalized = _normalize_reason(str(item))
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _has_non_empty_mapping(value: Any) -> bool:
    return isinstance(value, Mapping) and any(v not in (None, "", [], {}, ()) for v in value.values())


def compute_personalization_applied(
    state: Mapping[str, Any] | None,
    flags: Mapping[str, Any] | None,
) -> bool:
    """Determine whether personalization actually participated in decision/generation."""
    state = state or {}
    flags = flags or {}

    farmer_id = str(state.get("farmer_id") or flags.get("farmer_id") or "").strip()
    if not farmer_id:
        return False

    context_text = str(state.get("personalization_context") or flags.get("personalization_context") or "").strip()
    if context_text:
        return True

    merged_reasons = dedupe_reasons([
        *(state.get("personalization_reasons") or []),
        *(flags.get("personalization_reasons") or []),
    ])
    if merged_reasons:
        return True

    policy = state.get("personalization_policy")
    if _has_non_empty_mapping(policy):
        return True

    core_flag_fields = ["farm_scale", "pesticide_access_level", "cultivation_mode", "equipment", "experience_level", "risk_preference"]
    if any(flags.get(key) not in (None, "", [], {}, ()) for key in core_flag_fields):
        return True

    return False


_MISSING_FIELD_QUESTION_TEMPLATES = {
    "growth_stage": "当前番茄处于哪个生育期（苗期/开花/结果）？",
    "equipment": "是否具备喷施设备（背负式喷雾器、弥雾机或无人机）？",
    "farm_scale": "您的种植规模属于家庭（小）/中等/企业级（大）哪一类？",
    "pesticide_access_level": "您的购药能力/渠道属于无（NONE）/受限（LIMITED）/充足（FULL）？",
    "cultivation_mode": "您的栽培模式是土培/水培/基质栽培？",
    "harvest_window_days": "距离计划采收还有多少天？",
    "prefer_organic": "是否偏好有机/低残留方案？",
    "banned_ingredients": "是否有禁用成分/禁用药剂（可填关键词列表）？",
}


def build_missing_field_questions(missing_fields: Iterable[str | None]) -> list[str]:
    """Map missing profile/input fields to user-facing supplement questions."""
    questions: list[str] = []
    for field in missing_fields:
        if field is None:
            continue
        key = str(field).strip()
        if not key:
            continue
        template = _MISSING_FIELD_QUESTION_TEMPLATES.get(key)
        if template:
            questions.append(template)
    return normalize_follow_up_questions(questions)


def normalize_follow_up_questions(items: Iterable[str | None]) -> list[str]:
    """Normalize follow-up questions to keep only user supplement questions.

    Semantics:
    - follow_up_questions only means pending information questions to ask users.
    - personalization_reasons are explanatory statements and must not enter follow_up_questions.
    - post-treatment checks should use another field (e.g. post_treatment_questions).
    """

    question_starts = ("是否", "请问", "当前", "有没有", "能否", "需要", "具备", "距离", "大概", "您的", "你")
    reason_starts = ("优先", "强调", "策略", "建议", "偏好", "购药能力受限", "未配置", "基于", "由于", "因此")

    seen: set[str] = set()
    normalized: list[str] = []

    for item in items:
        if item is None:
            continue
        text = " ".join(str(item).split()).strip()
        if not text:
            continue

        is_question_like = text.endswith(("?", "？")) or text.startswith(question_starts)
        is_reason_like = (
            ("：" in text or ":" in text) and not text.endswith(("?", "？"))
        ) or text.startswith(reason_starts)

        if is_reason_like and not is_question_like:
            continue
        if not is_question_like:
            continue

        if not text.endswith(("?", "？")):
            text = text.rstrip("。.!！:：；;") + "？"

        intent_key = _infer_follow_up_intent_key(text)
        text = _canonicalize_follow_up_question(text, intent_key)
        if not text.endswith(("?", "？")):
            text = text.rstrip("。.!！:：；;") + "？"
        key = intent_key or _normalize_follow_up_question_text(text)
        if not key or key in seen:
            continue
        seen.add(key)
        normalized.append(text)

    return normalized[:3]
