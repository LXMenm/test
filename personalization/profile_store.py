"""农户档案的文件读写工具（JSON 持久化）。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from .profile_models import BaseProfile, FarmerProfile, TreatmentConstraint


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
    if profile.schema_version == "1.0":
        profile.schema_version = "1.1"
    profile.ensure_timestamp()
    return profile


def save_profile(profile: FarmerProfile) -> Path:
    """保存农户档案到 JSON。"""
    if profile.schema_version == "1.0":
        profile.schema_version = "1.1"
    profile.ensure_timestamp()
    path = get_profile_path(profile.farmer_id)
    with path.open("w", encoding="utf-8") as f:
        json.dump(profile.model_dump(), f, ensure_ascii=False, indent=2)
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
    if notes is not None:
        base.notes = notes

    profile.bases[base_id] = base
    return profile


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
    return profile


def reset_profile(farmer_id: str) -> FarmerProfile:
    """重置指定农户档案为空白模板。"""
    profile = FarmerProfile(farmer_id=farmer_id)
    save_profile(profile)
    return profile
