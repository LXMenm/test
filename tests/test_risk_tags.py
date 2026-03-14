from datetime import date, timedelta

from personalization.profile_models import BaseProfile
from personalization.risk_tags import build_base_risk_tags


def test_scenario_a_greenhouse_high_humidity_rain_fruiting():
    base = BaseProfile(
        base_id="B1",
        facility="温室大棚",
        environment="湿度 88%，连阴雨，叶面结露，通风差",
        growth_stage="FRUIT_SET",
        location="山东寿光",
    )
    result = build_base_risk_tags(base)
    tags = set(result["risk_tags"])
    assert "HIGH_HUMIDITY" in tags
    assert "GREENHOUSE_PRESSURE" in tags
    assert "FLOWERING_FRUITING_SENSITIVE" in tags


def test_scenario_b_near_harvest_by_sowing_date_estimate():
    sowing = (date.today() - timedelta(days=117)).isoformat()
    base = BaseProfile(base_id="B1", sowing_date=sowing)
    result = build_base_risk_tags(base)
    tags = set(result["risk_tags"])
    assert "NEAR_HARVEST" in tags


def test_scenario_c_minimal_fields_no_crash_with_missing_context():
    base = BaseProfile(base_id="B1", name="仅名称")
    result = build_base_risk_tags(base)
    tags = set(result["risk_tags"])
    assert "MISSING_CONTEXT" in tags


def test_scenario_d_low_risk_plain_soil_not_near_harvest():
    sowing = (date.today() - timedelta(days=30)).isoformat()
    base = BaseProfile(
        base_id="B1",
        facility="露地",
        environment="湿度 45%，晴朗，通风良好",
        growth_stage="VEGETATIVE",
        sowing_date=sowing,
        location="云南昆明",
    )
    result = build_base_risk_tags(base)
    tags = set(result["risk_tags"])
    assert "HIGH_HUMIDITY" not in tags
    assert "NEAR_HARVEST" not in tags
