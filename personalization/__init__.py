"""
个性化配置模块

提供农户档案的模型定义、存储读写、上下文生成与规则过滤等工具。
"""

from .profile_models import BaseProfile, FarmerProfile, TreatmentConstraint, compute_profile_hash
from .profile_store import load_profile, save_profile, list_profile_ids, reset_profile
from .profile_context import (
    build_personalization_context,
    build_personalization_flags,
    apply_base_profile_to_state,
)
from .profile_rules import filter_treatment_by_constraints

__all__ = [
    "BaseProfile",
    "FarmerProfile",
    "TreatmentConstraint",
    "compute_profile_hash",
    "load_profile",
    "save_profile",
    "list_profile_ids",
    "reset_profile",
    "build_personalization_context",
    "build_personalization_flags",
    "apply_base_profile_to_state",
    "filter_treatment_by_constraints",
]
