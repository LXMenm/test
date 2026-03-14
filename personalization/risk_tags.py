"""农业风险标签规则引擎（规则版，可解释，可测试）。"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

from .profile_constants import estimate_harvest_window_days, growth_stage_label
from .profile_models import BaseProfile

TOMATO_HARVEST_CYCLE_DAYS = 120

_RISK_LABELS = {
    "HIGH_HUMIDITY": "高湿风险",
    "RAIN_RISK": "降雨风险",
    "POOR_VENTILATION": "通风不良风险",
    "NEAR_HARVEST": "临近采收风险",
    "SEEDLING_VULNERABLE": "苗期脆弱风险",
    "FLOWERING_FRUITING_SENSITIVE": "开花结果期敏感风险",
    "GREENHOUSE_PRESSURE": "温室环境风险",
    "MISSING_CONTEXT": "信息不完整",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return ""
    return str(value).strip()


def _parse_metrics_from_text(text: str) -> dict[str, float | None]:
    source = text.lower()
    humidity = None
    rain_risk = None
    precipitation = None

    hm = re.search(r"湿度\s*[:：]?\s*(\d{1,3}(?:\.\d+)?)\s*%", source)
    if hm:
        humidity = float(hm.group(1))
    rr = re.search(r"降雨概率\s*[:：]?\s*(\d{1,3}(?:\.\d+)?)\s*%", source)
    if rr:
        rain_risk = float(rr.group(1))
    pm = re.search(r"降水\s*[:：]?\s*(\d{1,3}(?:\.\d+)?)\s*mm", source)
    if pm:
        precipitation = float(pm.group(1))

    return {
        "humidity": humidity,
        "rain_risk": rain_risk,
        "precipitation": precipitation,
    }


def _is_greenhouse(facility: str) -> bool:
    text = facility.lower()
    return any(keyword in text for keyword in ["温室", "大棚", "greenhouse", "棚"])


def _contains_any(text: str, keywords: list[str]) -> bool:
    source = text.lower()
    return any(keyword.lower() in source for keyword in keywords)


def build_base_risk_tags(
    base: BaseProfile,
    *,
    harvest_window_days: Optional[int] = None,
) -> dict[str, Any]:
    """根据基地档案构建风险标签（纯函数，不依赖 FastAPI）。"""
    facility = _to_text(base.facility)
    environment = _to_text(base.environment)
    weather_snapshot = _to_text(base.weather_snapshot)
    growth_stage = _to_text(base.growth_stage)

    location_fields = [
        _to_text(base.location),
        _to_text(base.province),
        _to_text(base.city),
        _to_text(base.district),
    ]
    location_missing = not any(location_fields) and (base.latitude is None or base.longitude is None)

    merged_text = "\n".join([environment, weather_snapshot]).strip()
    metrics = _parse_metrics_from_text(merged_text)

    risk_items: list[dict[str, str]] = []

    def add_item(code: str, level: str, reason: str) -> None:
        if any(item["code"] == code for item in risk_items):
            return
        risk_items.append(
            {
                "code": code,
                "label": _RISK_LABELS[code],
                "level": level,
                "reason": reason,
            }
        )

    humidity = metrics["humidity"]
    rain_risk = metrics["rain_risk"]
    precipitation = metrics["precipitation"]
    greenhouse = _is_greenhouse(facility)

    high_humidity = (humidity is not None and humidity >= 80) or _contains_any(
        merged_text, ["高湿", "连阴雨", "叶面结露", "湿度大", "潮湿"]
    )
    if high_humidity:
        add_item("HIGH_HUMIDITY", "medium", "环境湿度偏高，真菌性病害传播风险上升。")

    has_rain = (
        (rain_risk is not None and rain_risk >= 60)
        or (precipitation is not None and precipitation > 0)
        or _contains_any(merged_text, ["降雨", "有雨", "降水", "雷阵雨", "连阴雨"])
    )
    if has_rain:
        add_item("RAIN_RISK", "medium", "存在降雨/降水信号，田间湿度与传播压力增加。")

    if greenhouse and ((humidity is not None and humidity >= 75) or _contains_any(merged_text, ["闷", "结露", "通风差", "不通风", "高湿"])):
        add_item("POOR_VENTILATION", "high", "温室/大棚内湿热且通风不足，需加强通风排湿。")

    if greenhouse:
        add_item("GREENHOUSE_PRESSURE", "low", "设施栽培环境下病害压力更易累积，需强化巡检。")

    effective_harvest_window_days = harvest_window_days
    if effective_harvest_window_days is None:
        effective_harvest_window_days = estimate_harvest_window_days(base.sowing_date)
    if effective_harvest_window_days is not None and effective_harvest_window_days <= 7:
        add_item(
            "NEAR_HARVEST",
            "high",
            f"预计距采收约 {effective_harvest_window_days} 天，需严格关注安全间隔与低残留。",
        )

    stage = growth_stage.upper()
    if stage == "SEEDLING":
        add_item("SEEDLING_VULNERABLE", "medium", "当前为苗期，植株抗逆性较弱，需温湿度精细管理。")
    if stage in {"FLOWERING", "FRUIT_SET", "FRUIT_EXPANSION"}:
        add_item("FLOWERING_FRUITING_SENSITIVE", "medium", f"当前处于{growth_stage_label(stage)}，需兼顾病害控制与产量品质。")

    missing_fields = []
    if not growth_stage:
        missing_fields.append("growth_stage")
    if not _to_text(base.sowing_date):
        missing_fields.append("sowing_date")
    if location_missing:
        missing_fields.append("location")
    if not merged_text:
        missing_fields.append("weather")
    if missing_fields:
        add_item("MISSING_CONTEXT", "low", f"关键上下文缺失：{', '.join(missing_fields)}。")

    return {
        "risk_tags": [item["code"] for item in risk_items],
        "risk_items": risk_items,
        "risk_reasons": [item["reason"] for item in risk_items],
        "risk_updated_at": _utc_now_iso(),
        "estimated_harvest_window_days": estimate_harvest_window_days(base.sowing_date),
        "harvest_cycle_days": TOMATO_HARVEST_CYCLE_DAYS,
    }
