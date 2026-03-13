from __future__ import annotations

import json
from datetime import date

import pytest

from app import _normalize_profile_payload_for_save
from personalization.profile_constants import estimate_harvest_window_days, normalize_growth_stage
from personalization.profile_store import load_profile


def test_duplicate_base_id_same_farmer_should_fail() -> None:
    payload = {
        "name": "测试农户",
        "bases": [
            {"base_id": "B001", "name": "一号地"},
            {"base_id": "B001", "name": "二号地"},
        ],
    }
    with pytest.raises(ValueError, match="基地ID重复"):
        _normalize_profile_payload_for_save("F0999", payload)


def test_edit_existing_base_not_false_duplicate() -> None:
    payload = {
        "name": "测试农户",
        "active_base_id": "B001",
        "bases": {
            "B001": {
                "base_id": "B001",
                "name": "一号基地",
                "growth_stage": "开花期",
            }
        },
    }
    profile = _normalize_profile_payload_for_save("F0998", payload)
    assert profile.bases["B001"].base_id == "B001"
    assert profile.bases["B001"].growth_stage == "FLOWERING"


def test_sowing_date_estimate_harvest_window_days() -> None:
    # 默认120天周期，播种后30天 => 距采收约90天
    estimated = estimate_harvest_window_days("2026-01-01", today=date(2026, 1, 31))
    assert estimated == 90


def test_growth_stage_enum_mapping_is_stable() -> None:
    assert normalize_growth_stage("开花期") == "FLOWERING"
    assert normalize_growth_stage("FLOWERING") == "FLOWERING"
    assert normalize_growth_stage("未知阶段") is None


def test_legacy_profile_without_uid_or_sowing_date_is_compatible(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from personalization import profile_store

    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(profile_store, "PROFILE_DIR", profile_dir)

    legacy_profile = {
        "farmer_id": "F0001",
        "name": "旧档案",
        "schema_version": "1.1",
        "bases": {
            "B001": {
                "base_id": "B001",
                "name": "旧基地",
                "growth_stage": "开花期",
            }
        },
        "constraints": {"prefer_organic": False, "harvest_window_days": 15, "banned_ingredients": []},
    }

    path = profile_dir / "F0001.json"
    path.write_text(json.dumps(legacy_profile, ensure_ascii=False), encoding="utf-8")

    loaded = load_profile("F0001")
    assert loaded is not None
    assert loaded.schema_version == "1.2"
    assert loaded.bases["B001"].internal_base_uid
    assert loaded.bases["B001"].sowing_date is None
