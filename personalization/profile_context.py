"""
为 LLM 生成个性化上下文，便于诊断/治疗时使用。
"""

from typing import Optional, Dict, Any
from personalization.profile_models import FarmerProfile


def build_personalization_context(profile: Optional[FarmerProfile]) -> str:
    """
    将个人偏好转化为可注入 LLM 的上下文文本。
    """
    if not profile:
        return "无个性化偏好。"

    lines = [
        f"农户ID: {profile.farmer_id}",
        f"基地: {profile.active_base_id or profile.base_id or '未提供'}",
        f"地区: {profile.province or ''} {profile.city or ''}".strip(),
        f"位置: {profile.location or '未提供'}",
        f"设施/环境: {profile.facility or profile.environment or '未提供'}",
        f"作物: {profile.crop or '番茄'}, 生育期: {profile.growth_stage or '未提供'}",
        f"有机限制: {'是' if profile.organic_only else '否'}",
        f"禁用成分: {', '.join(profile.prohibited_chemicals) if profile.prohibited_chemicals else '无'}",
        f"采收窗口: {profile.harvest_within_days} 天内" if profile.harvest_within_days else "采收时间未指定",
        f"低置信度需确认: {'是' if profile.confirm_when_low_confidence else '否'} (阈值 {profile.low_confidence_threshold})",
    ]
    if profile.note:
        lines.append(f"备注: {profile.note}")
    return "\n".join(lines)


def build_personalization_flags(profile: Optional[FarmerProfile]) -> Dict[str, Any]:
    if not profile:
        return {}
    return {
        "confirm_when_low_confidence": profile.confirm_when_low_confidence,
        "low_confidence_threshold": profile.low_confidence_threshold,
        "organic_only": profile.organic_only,
        "prohibited_chemicals": profile.prohibited_chemicals,
        "harvest_within_days": profile.harvest_within_days,
        "province": profile.province,
        "facility": profile.facility,
    }
