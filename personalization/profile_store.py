"""农户档案的文件读写工具（JSON 持久化）。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from .profile_constants import estimate_harvest_window_days
from .profile_models import BaseProfile, FarmerProfile, TreatmentConstraint
from .risk_tags import build_base_risk_tags


PROFILE_DIR = Path("data/profiles")


def _ensure_dir() -> None:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)


def get_profile_path(farmer_id: str) -> Path:
    """返回档案文件路径。"""
    _ensure_dir()
    return PROFILE_DIR / f"{farmer_id}.json"


def list_profile_ids() -> List[str]:
    """列出已有的 farmer_id 列表。"""
    _ensure_dir()
    return sorted(p.stem for p in PROFILE_DIR.glob("*.json"))


def _ensure_profile_compatibility(profile: FarmerProfile) -> FarmerProfile:
    if profile.schema_version in {"1.0", "1.1"}:
        profile.schema_version = "1.2"

    # 兼容旧档案：没有 internal_base_uid / sowing_date 时自动补齐。
    for base_id, base in list(profile.bases.items()):
        if not base.base_id:
            base.base_id = base_id
        if not base.internal_base_uid:
            # BaseProfile validator 会补 uid；这里显式触发确保存盘一致。
            profile.bases[base_id] = BaseProfile.model_validate(base.model_dump())

    # 采收窗口优先由播种日期估算（按活跃基地）；旧值作为回退。
    active_base = profile.bases.get(profile.active_base_id or "") if profile.active_base_id else None
    if active_base and active_base.sowing_date:
        estimated_days = estimate_harvest_window_days(active_base.sowing_date)
        if estimated_days is not None:
            profile.constraints.harvest_window_days = estimated_days

    harvest_hint = profile.constraints.harvest_window_days
    for base_id, base in list(profile.bases.items()):
        risk_payload = build_base_risk_tags(base, harvest_window_days=harvest_hint if profile.active_base_id == base_id else None)
        base.risk_tags = [str(item).strip() for item in (risk_payload.get("risk_tags") or []) if str(item).strip()]
        base.risk_reasons = [str(item).strip() for item in (risk_payload.get("risk_reasons") or []) if str(item).strip()]
        base.risk_updated_at = risk_payload.get("risk_updated_at")
        base.risk_items = risk_payload.get("risk_items") or []
        profile.bases[base_id] = BaseProfile.model_validate(base.model_dump())

    profile.ensure_timestamp()
    return profile


def load_profile(farmer_id: str) -> Optional[FarmerProfile]:
    """读取指定农户档案。"""
    path = get_profile_path(farmer_id)
    if not path.exists():
        return None

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    try:
        profile = FarmerProfile.model_validate(data)
    except Exception:
        return None
    return _ensure_profile_compatibility(profile)


def save_profile(profile: FarmerProfile) -> Path:
    """保存农户档案到 JSON。"""
    normalized = _ensure_profile_compatibility(profile)
    path = get_profile_path(normalized.farmer_id)
    with path.open("w", encoding="utf-8") as f:
        json.dump(normalized.model_dump(), f, ensure_ascii=False, indent=2)
    return path


def upsert_base(
    profile: FarmerProfile,
    base_id: str,
    *,
    name: Optional[str] = None,
    location: Optional[str] = None,
    province: Optional[str] = None,
    facility: Optional[str] = None,
    environment: Optional[str] = None,
    growth_stage: Optional[str] = None,
    sowing_date: Optional[str] = None,
    notes: Optional[str] = None,
) -> FarmerProfile:
    """创建或更新基地信息。"""
    if base_id in profile.bases:
        base = profile.bases[base_id]
    else:
        base = BaseProfile(base_id=base_id)

    if name is not None:
        base.name = name
    if location is not None:
        base.location = location
    if province is not None:
        base.province = province
    if facility is not None:
        base.facility = facility
    if environment is not None:
        base.environment = environment
    if growth_stage is not None:
        base.growth_stage = growth_stage
    if sowing_date is not None:
        base.sowing_date = sowing_date
    if notes is not None:
        base.notes = notes

    profile.bases[base_id] = BaseProfile.model_validate(base.model_dump())
    return _ensure_profile_compatibility(profile)


def update_constraints(
    profile: FarmerProfile,
    *,
    banned_ingredients: Optional[List[str]] = None,
    harvest_window_days: Optional[int] = None,
    prefer_organic: Optional[bool] = None,
) -> FarmerProfile:
    """更新治疗约束。"""
    constraints: TreatmentConstraint = profile.constraints
    if banned_ingredients is not None:
        constraints.banned_ingredients = banned_ingredients
    if harvest_window_days is not None:
        constraints.harvest_window_days = harvest_window_days
    if prefer_organic is not None:
        constraints.prefer_organic = prefer_organic
    profile.constraints = constraints
    return _ensure_profile_compatibility(profile)


def reset_profile(farmer_id: str) -> FarmerProfile:
    """重置指定农户档案为空白模板。"""
    profile = FarmerProfile(farmer_id=farmer_id)
    save_profile(profile)
    return profile
