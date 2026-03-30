"""农户档案统一存储入口，支持 file / dual / mysql 三种模式。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from config import PROFILE_STORE_MODE

from .profile_constants import estimate_harvest_window_days
from .profile_models import BaseProfile, FarmerProfile, RiskItem, TreatmentConstraint
from .risk_tags import build_base_risk_tags


PROFILE_DIR = Path("data/profiles")


def _ensure_dir() -> None:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)


def get_profile_path(farmer_id: str) -> Path:
    """返回档案文件路径。"""
    _ensure_dir()
    return PROFILE_DIR / f"{farmer_id}.json"


def _log_store_action(message: str) -> None:
    print(f"[ProfileStore:{PROFILE_STORE_MODE}] {message}")


def _get_mysql_repo():
    from repositories.profile_repo_mysql import (
        delete_profile as delete_profile_mysql,
        get_profile as get_profile_mysql,
        list_all_base_ids as list_all_base_ids_mysql,
        list_profile_ids as list_profile_ids_mysql,
        save_profile_payload,
    )

    return {
        "get_profile_mysql": get_profile_mysql,
        "list_profile_ids_mysql": list_profile_ids_mysql,
        "list_all_base_ids_mysql": list_all_base_ids_mysql,
        "save_profile_payload": save_profile_payload,
        "delete_profile_mysql": delete_profile_mysql,
    }


def _list_profile_ids_from_file() -> List[str]:
    """列出文件中的 farmer_id 列表。"""
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

    # 采收窗口优先级：
    # 1) manual 模式：使用手工值；
    # 2) auto 模式：优先播种日期估算，估算不到再回退手工值。
    active_base = profile.bases.get(profile.active_base_id or "") if profile.active_base_id else None
    harvest_mode = str(getattr(profile.constraints, "harvest_window_mode", "auto") or "auto").strip().lower()
    if harvest_mode != "manual" and active_base and active_base.sowing_date:
        estimated_days = estimate_harvest_window_days(active_base.sowing_date)
        if estimated_days is not None:
            profile.constraints.harvest_window_days = estimated_days

    harvest_hint = profile.constraints.harvest_window_days
    for base_id, base in list(profile.bases.items()):
        risk_payload = build_base_risk_tags(base, harvest_window_days=harvest_hint if profile.active_base_id == base_id else None)
        base.risk_tags = [str(item).strip() for item in (risk_payload.get("risk_tags") or []) if str(item).strip()]
        base.risk_reasons = [str(item).strip() for item in (risk_payload.get("risk_reasons") or []) if str(item).strip()]
        base.risk_updated_at = risk_payload.get("risk_updated_at")
        base.risk_items = [RiskItem.model_validate(item) for item in (risk_payload.get("risk_items") or [])]
        profile.bases[base_id] = BaseProfile.model_validate(base.model_dump())

    profile.ensure_timestamp()
    return profile


def _load_profile_from_file(farmer_id: str) -> Optional[FarmerProfile]:
    """从 JSON 文件读取指定农户档案。"""
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


def _load_profile_from_mysql(farmer_id: str) -> Optional[FarmerProfile]:
    repo = _get_mysql_repo()
    payload = repo["get_profile_mysql"](farmer_id)
    if payload is None:
        return None
    try:
        profile = FarmerProfile.model_validate(payload)
    except Exception:
        return None
    return _ensure_profile_compatibility(profile)


def _save_profile_to_file(profile: FarmerProfile) -> Path:
    """保存农户档案到 JSON 文件。"""
    path = get_profile_path(profile.farmer_id)
    with path.open("w", encoding="utf-8") as f:
        json.dump(profile.model_dump(), f, ensure_ascii=False, indent=2)
    return path


def _save_profile_to_mysql(profile: FarmerProfile) -> None:
    repo = _get_mysql_repo()
    repo["save_profile_payload"](profile.model_dump())


def _delete_profile_from_file(farmer_id: str) -> None:
    path = get_profile_path(farmer_id)
    if path.exists():
        path.unlink()


def _delete_profile_from_mysql(farmer_id: str) -> None:
    repo = _get_mysql_repo()
    repo["delete_profile_mysql"](farmer_id)


def load_profile(farmer_id: str) -> Optional[FarmerProfile]:
    """读取指定农户档案。"""
    mode = (PROFILE_STORE_MODE or "file").lower()
    if mode == "mysql":
        _log_store_action(f"load_profile farmer_id={farmer_id} via mysql")
        return _load_profile_from_mysql(farmer_id)

    profile = _load_profile_from_file(farmer_id)
    if profile is not None:
        if mode == "dual":
            _log_store_action(f"load_profile farmer_id={farmer_id} via file")
        return profile

    if mode == "dual":
        _log_store_action(f"load_profile farmer_id={farmer_id} fallback to mysql")
        return _load_profile_from_mysql(farmer_id)

    return None


def list_profile_ids() -> List[str]:
    """列出已有的 farmer_id 列表。"""
    mode = (PROFILE_STORE_MODE or "file").lower()
    if mode == "mysql":
        _log_store_action("list_profile_ids via mysql")
        repo = _get_mysql_repo()
        return repo["list_profile_ids_mysql"]()

    file_ids = _list_profile_ids_from_file()
    if mode == "dual":
        _log_store_action("list_profile_ids merge file + mysql")
        repo = _get_mysql_repo()
        mysql_ids = repo["list_profile_ids_mysql"]()
        return sorted(set(file_ids) | set(mysql_ids))

    return file_ids


def list_all_base_ids() -> dict[str, str]:
    """列出 base_id 到 farmer_id 的映射。"""
    mode = (PROFILE_STORE_MODE or "file").lower()
    mapping: dict[str, str] = {}

    if mode in {"file", "dual"}:
        for farmer_id in _list_profile_ids_from_file():
            profile = _load_profile_from_file(farmer_id)
            if profile is None:
                continue
            for base_id in profile.bases.keys():
                mapping[base_id] = farmer_id

    if mode in {"dual", "mysql"}:
        repo = _get_mysql_repo()
        mapping.update(repo["list_all_base_ids_mysql"]())

    return dict(sorted(mapping.items()))


def save_profile(profile: FarmerProfile) -> Path:
    """按当前模式保存农户档案。"""
    normalized = _ensure_profile_compatibility(profile)
    mode = (PROFILE_STORE_MODE or "file").lower()

    if mode == "mysql":
        _log_store_action(f"save_profile farmer_id={normalized.farmer_id} via mysql")
        _save_profile_to_mysql(normalized)
        return get_profile_path(normalized.farmer_id)

    _log_store_action(f"save_profile farmer_id={normalized.farmer_id} via file")
    path = _save_profile_to_file(normalized)
    if mode == "dual":
        _log_store_action(f"save_profile farmer_id={normalized.farmer_id} dual-write mysql")
        _save_profile_to_mysql(normalized)
    return path


def delete_profile(farmer_id: str) -> None:
    """按当前模式删除农户档案。"""
    mode = (PROFILE_STORE_MODE or "file").lower()

    if mode == "mysql":
        _log_store_action(f"delete_profile farmer_id={farmer_id} via mysql")
        _delete_profile_from_mysql(farmer_id)
        return

    _log_store_action(f"delete_profile farmer_id={farmer_id} via file")
    _delete_profile_from_file(farmer_id)
    if mode == "dual":
        _log_store_action(f"delete_profile farmer_id={farmer_id} dual-delete mysql")
        _delete_profile_from_mysql(farmer_id)


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
