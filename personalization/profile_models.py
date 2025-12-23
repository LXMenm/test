"""
个性化配置模型。
使用 dataclass 以减少依赖（无需 SQL/ORM），并保持字段清晰。
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime


@dataclass
class FarmerProfile:
    """
    农户个性化配置。
    """

    farmer_id: str
    base_id: Optional[str] = None
    active_base_id: Optional[str] = None
    name: Optional[str] = None
    province: Optional[str] = None
    city: Optional[str] = None
    location: Optional[str] = None
    environment: Optional[str] = None  # 露地/温室等
    facility: Optional[str] = None  # 设施名称或类型
    crop: Optional[str] = "番茄"
    growth_stage: Optional[str] = None
    organic_only: bool = False
    prohibited_chemicals: List[str] = field(default_factory=list)
    confirm_when_low_confidence: bool = True
    low_confidence_threshold: float = 0.6
    harvest_within_days: Optional[int] = None
    note: Optional[str] = None
    profile_schema_version: str = "1.0"
    profile_updated_at: Optional[str] = None  # ISO 格式

    extra: Dict[str, Any] = field(default_factory=dict)

    def touch_updated_at(self) -> None:
        self.profile_updated_at = datetime.utcnow().isoformat() + "Z"
