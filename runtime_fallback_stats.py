"""轻量级兼容回退命中统计（进程内）。"""

from __future__ import annotations

from collections import Counter
from threading import Lock
from typing import Any, Dict

_LOCK = Lock()
_COUNTER: Counter[str] = Counter()
_FALLBACK_META: dict[str, dict[str, str]] = {
    "profile.equipment_json_fallback": {
        "category": "profile_json_fallback",
        "candidate_field": "farmer_profiles.equipment_json",
        "default_behavior": "fallback_disabled",
    },
    "profile.constraints_json_fallback": {
        "category": "profile_json_fallback",
        "candidate_field": "farmer_profiles.constraints_json",
        "default_behavior": "fallback_disabled",
    },
    "profile.meta.owner_user_id_fallback": {
        "category": "profile_meta_fallback",
        "candidate_field": "farmer_profiles.meta_json.owner_user_id",
        "default_behavior": "fallback_enabled",
    },
    "profile.meta.role_type_fallback": {
        "category": "profile_meta_fallback",
        "candidate_field": "farmer_profiles.meta_json.role_type",
        "default_behavior": "fallback_enabled",
    },
    "base.risk_tags_json_fallback": {
        "category": "base_risk_json_fallback",
        "candidate_field": "farm_bases.risk_tags_json",
        "default_behavior": "fallback_disabled",
    },
    "base.risk_items_json_fallback": {
        "category": "base_risk_json_fallback",
        "candidate_field": "farm_bases.risk_items_json",
        "default_behavior": "fallback_disabled",
    },
    "base.extra.latlon_fallback": {
        "category": "base_extra_legacy_fallback",
        "candidate_field": "farm_bases.extra_json.lat/lon",
        "default_behavior": "fallback_disabled",
    },
    "base.extra.weather_legacy_key_fallback": {
        "category": "base_extra_legacy_fallback",
        "candidate_field": "farm_bases.extra_json.temperature_2m/wind_speed_10m/weather_refreshed_at",
        "default_behavior": "fallback_disabled",
    },
    "base.risk_item_structured_fallback": {
        "category": "risk_item_structured_fallback",
        "candidate_field": "farm_base_risk_items.risk_code/risk_level/risk_message",
        "default_behavior": "fallback_disabled",
    },
    "auth.linked_farmer_id_returned": {
        "category": "auth_compatibility",
        "candidate_field": "user_accounts.linked_farmer_id",
        "default_behavior": "fallback_enabled",
    },
}


def record_fallback_hit(name: str) -> None:
    key = str(name or "").strip()
    if not key:
        return
    with _LOCK:
        _COUNTER[key] += 1


def get_fallback_stats() -> Dict[str, int]:
    with _LOCK:
        return dict(sorted(_COUNTER.items(), key=lambda item: item[0]))


def reset_fallback_stats() -> None:
    with _LOCK:
        _COUNTER.clear()


def get_fallback_readiness() -> dict[str, Any]:
    """
    仅用于删列前辅助判断（进程内统计，非全局结论）。
    phase 规则（保守）:
    - hits == 0: candidate_for_canary
    - hits > 0: observe
    """
    stats = get_fallback_stats()
    items: list[dict[str, Any]] = []
    for name, meta in sorted(_FALLBACK_META.items(), key=lambda pair: pair[0]):
        hits = int(stats.get(name, 0))
        phase = "candidate_for_canary" if hits == 0 else "observe"
        items.append(
            {
                "name": name,
                "hits": hits,
                "category": meta["category"],
                "candidate_field": meta["candidate_field"],
                "default_behavior": meta["default_behavior"],
                "phase": phase,
                "notes": "process-local counters since last restart; use only as readiness hint",
            }
        )
    return {
        "items": items,
        "notes": "Readiness does not auto-approve column deletion; combine with offline data audit.",
    }
