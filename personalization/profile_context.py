"""个性化上下文生成与标志。"""
from __future__ import annotations

from typing import Dict, Optional

from .profile_constants import estimate_harvest_window_days, growth_stage_label
from .profile_models import BaseProfile, FarmerProfile, TreatmentConstraint, compute_profile_hash
from .policy_engine import PersonalizationPolicy
from .utils import dedupe_reasons


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
            parts.append(f"默认生育期: {growth_stage_label(base_profile.growth_stage)}")
        if base_profile.sowing_date:
            parts.append(f"播种日期: {base_profile.sowing_date}")
        if base_profile.notes:
            parts.append(f"备注: {base_profile.notes}")
        if base_profile.risk_tags:
            parts.append(f"农业风险标签: {', '.join(base_profile.risk_tags)}")
        if base_profile.risk_reasons:
            parts.append(f"风险提示: {'；'.join(base_profile.risk_reasons[:3])}")

    constraints = profile.constraints
    parts.append(f"种植规模: {profile.farm_scale}")
    parts.append(f"购药能力: {profile.pesticide_access_level}")
    if profile.equipment:
        parts.append(f"可用设备: {', '.join(profile.equipment)}")
    parts.append(f"栽培模式: {profile.cultivation_mode}")
    parts.append(f"经验水平: {profile.experience_level}")
    parts.append(f"风险偏好: {profile.risk_preference}")
    if constraints.banned_ingredients:
        parts.append(f"禁用成分: {', '.join(constraints.banned_ingredients)}")
    effective_harvest_days = estimate_harvest_window_days(base_profile.sowing_date) if base_profile else None
    if effective_harvest_days is None:
        effective_harvest_days = constraints.harvest_window_days
    if effective_harvest_days is not None:
        parts.append(f"距采收天数: {effective_harvest_days}天（规则估算）")
    if constraints.prefer_organic:
        parts.append("偏好有机/低残留方案")

    return "；".join(parts)


def build_personalization_flags(
    profile: Optional[FarmerProfile],
    base_profile: Optional[BaseProfile],
    policy: Optional[PersonalizationPolicy] = None,
) -> Dict:
    """构建约束与决策标志。"""
    if not profile:
        return {}

    constraints: TreatmentConstraint = profile.constraints
    effective_harvest_days = estimate_harvest_window_days(base_profile.sowing_date) if base_profile else None
    if effective_harvest_days is None:
        effective_harvest_days = constraints.harvest_window_days

    flags: Dict = {
        "confirm_when_low_confidence": profile.confirm_when_low_confidence,
        "banned_ingredients": constraints.banned_ingredients,
        "harvest_window_days": effective_harvest_days,
        "prefer_organic": constraints.prefer_organic,
        "profile_schema_version": profile.schema_version,
        "profile_updated_at": profile.updated_at,
        "profile_hash": compute_profile_hash(profile),
        "farm_scale": profile.farm_scale,
        "pesticide_access_level": profile.pesticide_access_level,
        "equipment": profile.equipment,
        "cultivation_mode": profile.cultivation_mode,
        "experience_level": profile.experience_level,
        "risk_preference": profile.risk_preference,
    }
    if policy is not None:
        flags["personalization_reasons"] = dedupe_reasons(policy.explanations)

    if base_profile:
        flags.update(
            {
                "base_id": base_profile.base_id,
                "facility": base_profile.facility,
                "province": base_profile.province,
                "location": base_profile.location,
                "environment": base_profile.environment,
                "growth_stage": base_profile.growth_stage,
                "growth_stage_label": growth_stage_label(base_profile.growth_stage),
                "sowing_date": base_profile.sowing_date,
                "risk_tags": list(base_profile.risk_tags or []),
                "risk_items": [item.model_dump() if hasattr(item, "model_dump") else item for item in (base_profile.risk_items or [])],
                "risk_reasons": list(base_profile.risk_reasons or []),
                "risk_updated_at": base_profile.risk_updated_at,
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
