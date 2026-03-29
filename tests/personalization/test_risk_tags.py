from datetime import date, timedelta

from personalization.profile_models import BaseProfile
from personalization.risk_tags import build_base_risk_tags


def _tags(result: dict) -> set[str]:
    return set(result["risk_tags"])


def test_sample_1_no_rain_risk_and_conflict_resolution_seedling_vs_harvest_window():
    base = BaseProfile(
        base_id="B1",
        weather_snapshot="未来24小时降雨概率较低",
        relative_humidity_2m=45,
        precipitation=0,
        rain_risk=20,
        growth_stage="SEEDLING",
    )
    result = build_base_risk_tags(base, harvest_window_days=2)
    tags = _tags(result)

    assert "RAIN_RISK" not in tags
    assert "SEEDLING_VULNERABLE" in tags
    assert "NEAR_HARVEST" not in tags
    assert "CONTEXT_CONFLICT" in tags


def test_sample_2_structured_weather_and_greenhouse_near_harvest():
    base = BaseProfile(
        base_id="B1",
        facility="温室",
        relative_humidity_2m=88,
        precipitation=3.2,
        rain_risk=75,
        growth_stage="FRUITING",
        weather_snapshot="通风一般",
    )
    result = build_base_risk_tags(base, harvest_window_days=5)
    tags = _tags(result)

    assert "RAIN_RISK" in tags
    assert "HIGH_HUMIDITY" in tags
    assert "GREENHOUSE_PRESSURE" in tags
    assert "NEAR_HARVEST" in tags

    rain_item = next(item for item in result["risk_items"] if item["code"] == "RAIN_RISK")
    assert rain_item["source"] == "structured_weather"


def test_sample_3_text_fallback_low_rain_probability_should_not_trigger():
    base = BaseProfile(
        base_id="B1",
        weather_snapshot="降雨概率较低，短时无雨",
    )
    result = build_base_risk_tags(base)
    assert "RAIN_RISK" not in _tags(result)


def test_sample_4_seedling_with_long_harvest_estimate_no_near_harvest():
    sowing = (date.today() - timedelta(days=30)).isoformat()
    base = BaseProfile(base_id="B1", growth_stage="SEEDLING", sowing_date=sowing)
    result = build_base_risk_tags(base)
    tags = _tags(result)

    assert "SEEDLING_VULNERABLE" in tags
    assert "NEAR_HARVEST" not in tags


def test_sample_5_fruiting_with_sowing_estimate_near_harvest():
    sowing = (date.today() - timedelta(days=116)).isoformat()
    base = BaseProfile(base_id="B1", growth_stage="FRUITING", sowing_date=sowing)
    result = build_base_risk_tags(base)
    tags = _tags(result)

    assert "NEAR_HARVEST" in tags
    assert "SEEDLING_VULNERABLE" not in tags


def test_typical_risk_tags_keep_semantics_for_weather_stage_and_context():
    near_harvest_sowing = (date.today() - timedelta(days=116)).isoformat()
    base = BaseProfile(
        base_id="B2",
        facility="温室",
        growth_stage="FLOWERING",
        sowing_date=near_harvest_sowing,
        weather_snapshot="通风差，近期有持续降雨",
        relative_humidity_2m=86,
        rain_risk=78,
        precipitation=12,
        notes="测试典型风险标签组合",
    )
    result = build_base_risk_tags(base)
    tags = _tags(result)

    assert "HIGH_HUMIDITY" in tags
    assert "RAIN_RISK" in tags
    assert "NEAR_HARVEST" in tags
    assert "FLOWERING_FRUITING_SENSITIVE" in tags


def test_missing_context_and_context_conflict_tags_are_still_generated():
    base = BaseProfile(
        base_id="B3",
        growth_stage="SEEDLING",
        sowing_date=None,
    )
    result = build_base_risk_tags(base, harvest_window_days=2)
    tags = _tags(result)

    assert "MISSING_CONTEXT" in tags
    assert "CONTEXT_CONFLICT" in tags
