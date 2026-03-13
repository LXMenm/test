"""农户个性设置模型定义。"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Dict, List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from .profile_constants import normalize_growth_stage, normalize_sowing_date


class TreatmentConstraint(BaseModel):
    """治疗约束，控制药剂或管理措施的偏好。"""

    banned_ingredients: List[str] = Field(default_factory=list, description="禁用的有效成分关键词")
    harvest_window_days: Optional[int] = Field(
        default=None, description="距离采收的预期天数，用于限制安全间隔期"
    )
    prefer_organic: bool = Field(default=False, description="是否偏好有机/低残留方案")


class BaseProfile(BaseModel):
    """单个生产基地的资料。"""

    base_id: str
    internal_base_uid: Optional[str] = None
    name: Optional[str] = None
    location: Optional[str] = None
    province: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    city: Optional[str] = None
    district: Optional[str] = None
    facility: Optional[str] = None
    environment: Optional[str] = None
    growth_stage: Optional[str] = None
    sowing_date: Optional[str] = None
    notes: Optional[str] = None
    weather_snapshot: Optional[str] = None

    @model_validator(mode="after")
    def normalize_fields(self) -> "BaseProfile":
        if not self.internal_base_uid:
            self.internal_base_uid = uuid4().hex
        self.growth_stage = normalize_growth_stage(self.growth_stage)
        self.sowing_date = normalize_sowing_date(self.sowing_date)
        return self

    @model_validator(mode="after")
    def normalize_fields(self) -> "BaseProfile":
        if not self.internal_base_uid:
            self.internal_base_uid = uuid4().hex
        self.growth_stage = normalize_growth_stage(self.growth_stage)
        self.sowing_date = normalize_sowing_date(self.sowing_date)
        return self


class FarmerProfile(BaseModel):
    """农户整体档案。"""

    farmer_id: str
    name: Optional[str] = None
    schema_version: str = "1.2"
    updated_at: Optional[str] = None
    active_base_id: Optional[str] = None
    confirm_when_low_confidence: bool = True
    farm_scale: Literal["BALCONY", "SMALL", "MEDIUM", "LARGE", "GREENHOUSE_LARGE"] = "SMALL"
    pesticide_access_level: Literal["NONE", "LIMITED", "FULL"] = "LIMITED"
    equipment: List[Literal["HAND_SPRAYER", "BACKPACK_SPRAYER", "MIST_BLOWER", "DRONE"]] = Field(default_factory=list)
    cultivation_mode: Literal["SOIL", "HYDROPONIC", "SUBSTRATE"] = "SOIL"
    experience_level: Literal["NOVICE", "INTERMEDIATE", "EXPERT"] = "INTERMEDIATE"
    risk_preference: Literal["CONSERVATIVE", "BALANCED", "AGGRESSIVE"] = "BALANCED"
    bases: Dict[str, BaseProfile] = Field(default_factory=dict)
    constraints: TreatmentConstraint = Field(default_factory=TreatmentConstraint)

    def ensure_timestamp(self) -> None:
        """填充更新时间。"""
        if not self.updated_at:
            self.updated_at = datetime.utcnow().isoformat() + "Z"



def compute_profile_hash(profile: FarmerProfile) -> str:
    """生成档案的哈希，便于日志溯源。"""

    canonical = json.dumps(profile.model_dump(), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
