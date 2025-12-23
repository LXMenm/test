"""个性化上下文生成与标志。"""
from __future__ import annotations

from typing import Dict, Optional

from .profile_models import BaseProfile, FarmerProfile, TreatmentConstraint, compute_profile_hash


def build_personalization_context(
    profile: Optional[FarmerProfile], base_profile: Optional[BaseProfile]
) -> Optional[str]:
    """构建用于提示词的个性化上下文。"""
    if not profile:
        return None

    parts = [f"农户ID: {profile.farmer_id}"]
    if profile.name:
        parts.append(f"姓名/联系人: {profile.name}")
    if base_profile:
        parts.append(f"基地ID: {base_profile.base_id}")
        if base_profile.name:
            parts.append(f"基地名称: {base_profile.name}")
        if base_profile.location:
            parts.append(f"位置: {base_profile.location}")
        if base_profile.province:
            parts.append(f"省份: {base_profile.province}")
        if base_profile.facility:
            parts.append(f"设施类型: {base_profile.facility}")
        if base_profile.environment:
            parts.append(f"近期环境: {base_profile.environment}")
        if base_profile.growth_stage:
            parts.append(f"默认生育期: {base_profile.growth_stage}")
        if base_profile.notes:
            parts.append(f"备注: {base_profile.notes}")

    constraints = profile.constraints
    if constraints.banned_ingredients:
        parts.append(f"禁用成分: {', '.join(constraints.banned_ingredients)}")
    if constraints.harvest_window_days:
        parts.append(f"距采收天数: {constraints.harvest_window_days}天")
    if constraints.prefer_organic:
        parts.append("偏好有机/低残留方案")

    return "；".join(parts)


def build_personalization_flags(
    profile: Optional[FarmerProfile], base_profile: Optional[BaseProfile]
) -> Dict:
    """构建约束与决策标志。"""
    if not profile:
        return {}

    constraints: TreatmentConstraint = profile.constraints
    flags: Dict = {
        "confirm_when_low_confidence": profile.confirm_when_low_confidence,
        "banned_ingredients": constraints.banned_ingredients,
        "harvest_window_days": constraints.harvest_window_days,
        "prefer_organic": constraints.prefer_organic,
        "profile_schema_version": profile.schema_version,
        "profile_updated_at": profile.updated_at,
        "profile_hash": compute_profile_hash(profile),
    }

    if base_profile:
        flags.update(
            {
                "base_id": base_profile.base_id,
                "facility": base_profile.facility,
                "province": base_profile.province,
                "location": base_profile.location,
                "environment": base_profile.environment,
                "growth_stage": base_profile.growth_stage,
            }
        )
    return flags


def apply_base_profile_to_state(state: Dict, base_profile: Optional[BaseProfile]) -> None:
    """将基地常用信息补全到状态（仅填充缺失字段）。"""
    if not base_profile:
        return

    if not state.get("location") and base_profile.location:
        state["location"] = base_profile.location
    if not state.get("province") and base_profile.province:
        state["province"] = base_profile.province
    if not state.get("facility") and base_profile.facility:
        state["facility"] = base_profile.facility
    if not state.get("environment") and base_profile.environment:
        state["environment"] = base_profile.environment

    if not state.get("crop_growth_stage") and base_profile.growth_stage:
        state["crop_growth_stage"] = base_profile.growth_stage
