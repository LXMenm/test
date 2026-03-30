from __future__ import annotations

from app import _normalize_profile_payload_for_save
from personalization.profile_constants import estimate_harvest_window_days
from personalization.profile_context import build_personalization_flags
from personalization.profile_models import BaseProfile, FarmerProfile, TreatmentConstraint
from personalization.policy_engine import build_policy


def test_harvest_window_auto_estimation_from_sowing_date() -> None:
    profile = FarmerProfile(
        farmer_id="F9001",
        active_base_id="B1",
        constraints=TreatmentConstraint(harvest_window_mode="auto", harvest_window_days=3),
        bases={"B1": BaseProfile(base_id="B1", sowing_date="2026-03-01")},
    )
    base = profile.bases["B1"]
    expected = estimate_harvest_window_days(base.sowing_date)
    flags = build_personalization_flags(profile, base)
    assert flags["harvest_window_days"] == expected
    assert flags["harvest_window_source"] == "auto"


def test_harvest_window_manual_override_has_higher_priority() -> None:
    profile = FarmerProfile(
        farmer_id="F9002",
        active_base_id="B1",
        constraints=TreatmentConstraint(harvest_window_mode="manual", harvest_window_days=5),
        bases={"B1": BaseProfile(base_id="B1", sowing_date="2026-03-01")},
    )
    base = profile.bases["B1"]
    flags = build_personalization_flags(profile, base)
    policy = build_policy(profile, base)
    assert flags["harvest_window_days"] == 5
    assert flags["harvest_window_source"] == "manual"
    assert policy.hard_constraints["harvest_window_days"] == 5


def test_harvest_window_manual_value_used_when_sowing_date_missing() -> None:
    profile = FarmerProfile(
        farmer_id="F9003",
        active_base_id="B1",
        constraints=TreatmentConstraint(harvest_window_mode="auto", harvest_window_days=11),
        bases={"B1": BaseProfile(base_id="B1", sowing_date=None)},
    )
    base = profile.bases["B1"]
    flags = build_personalization_flags(profile, base)
    assert flags["harvest_window_days"] == 11
    assert flags["harvest_window_source"] == "manual_fallback"


def test_save_and_read_back_keeps_manual_mode_value() -> None:
    payload = {
        "farmer_id": "F9004",
        "active_base_id": "B1",
        "constraints": {"harvest_window_mode": "manual", "harvest_window_days": 9},
        "bases": {
            "B1": {
                "base_id": "B1",
                "sowing_date": "2026-03-01",
            }
        },
    }
    profile = _normalize_profile_payload_for_save("F9004", payload)
    assert profile.constraints.harvest_window_mode == "manual"
    assert profile.constraints.harvest_window_days == 9
