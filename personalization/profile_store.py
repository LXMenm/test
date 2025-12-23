"""
Profile 存取模块：基于 JSON 文件持久化，无需 SQL。
路径：data/profiles/{farmer_id}.json
"""

import json
import os
from typing import Optional, Dict, Any
from datetime import datetime
import hashlib

from personalization.profile_models import FarmerProfile

PROFILE_DIR = os.path.join("data", "profiles")


def ensure_profile_dir() -> None:
    os.makedirs(PROFILE_DIR, exist_ok=True)


def profile_path(farmer_id: str) -> str:
    ensure_profile_dir()
    return os.path.join(PROFILE_DIR, f"{farmer_id}.json")


def load_profile(farmer_id: str) -> Optional[FarmerProfile]:
    path = profile_path(farmer_id)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return FarmerProfile(**data)


def save_profile(profile: FarmerProfile) -> str:
    profile.touch_updated_at()
    path = profile_path(profile.farmer_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile.__dict__, f, ensure_ascii=False, indent=2)
    return path


def list_profiles() -> Dict[str, str]:
    ensure_profile_dir()
    items = {}
    for name in os.listdir(PROFILE_DIR):
        if name.endswith(".json"):
            fid = name[:-5]
            items[fid] = os.path.join(PROFILE_DIR, name)
    return items


def compute_profile_hash(profile: Optional[FarmerProfile] | Optional[dict]) -> Optional[str]:
    if not profile:
        return None
    if isinstance(profile, dict):
        raw_dict = profile
    else:
        raw_dict = profile.__dict__
    raw = json.dumps(raw_dict, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def default_active_base(profile: Optional[FarmerProfile]) -> Optional[str]:
    if not profile:
        return None
    return profile.active_base_id or profile.base_id
