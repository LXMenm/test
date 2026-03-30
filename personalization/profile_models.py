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
    harvest_window_mode: Literal["auto", "manual"] = Field(
        default="auto",
        description="采收窗口来源：auto=根据播种日期自动估算（无播种日期时回退手工值）；manual=始终使用手工输入",
    )
    prefer_organic: bool = Field(default=False, description="是否偏好有机/低残留方案")




class RiskItem(BaseModel):
    """农业风险标签条目。"""

    code: str
    label: str
    level: Literal["low", "medium", "high", "warning"] = "low"
    reason: str
    source: Optional[
        Literal[
            "structured_weather",
            "weather_text",
            "growth_stage",
            "harvest_window",
            "sowing_date_estimate",
            "conflict_check",
            "context_check",
        ]
    ] = None

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
    last_weather_refresh_at: Optional[str] = None
    weather_temperature_2m: Optional[float] = None
    weather_wind_speed_10m: Optional[float] = None
    relative_humidity_2m: Optional[float] = None
    precipitation: Optional[float] = None
    rain_risk: Optional[float] = None
    risk_tags: List[str] = Field(default_factory=list)
    risk_items: List[RiskItem] = Field(default_factory=list)
    risk_reasons: List[str] = Field(default_factory=list)
    risk_updated_at: Optional[str] = None

    @model_validator(mode="after")
    def normalize_fields(self) -> "BaseProfile":
        if not self.internal_base_uid:
            self.internal_base_uid = uuid4().hex
        self.growth_stage = normalize_growth_stage(self.growth_stage)
        self.sowing_date = normalize_sowing_date(self.sowing_date)
        return self


class FarmerProfile(BaseModel):
    """统一档案模型（农户/专家/管理员）。"""

    farmer_id: str
    name: Optional[str] = None
    display_name: Optional[str] = None
    role_type: Literal["FARMER", "EXPERT", "ADMIN"] = "FARMER"
    owner_user_id: Optional[str] = None
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

    @model_validator(mode="after")
    def normalize_profile_identity(self) -> "FarmerProfile":
        self.role_type = str(self.role_type or "FARMER").strip().upper()  # type: ignore[assignment]
        if self.role_type not in {"FARMER", "EXPERT", "ADMIN"}:
            self.role_type = "FARMER"
        if not self.owner_user_id:
            self.owner_user_id = self.farmer_id
        if not self.display_name:
            self.display_name = self.name or self.farmer_id
        return self

    def ensure_timestamp(self) -> None:
        """填充更新时间。"""
        if not self.updated_at:
            self.updated_at = datetime.utcnow().isoformat() + "Z"



def compute_profile_hash(profile: FarmerProfile) -> str:
    """生成档案的哈希，便于日志溯源。"""

    canonical = json.dumps(profile.model_dump(), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
