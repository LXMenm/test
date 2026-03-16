"""农业风险标签规则引擎（规则版，可解释，可测试）。"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
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
    "CONTEXT_CONFLICT": "档案信息冲突",
}

_NEGATIVE_WEATHER_HINTS = [
    "降雨概率较低",
    "降水概率较小",
    "暂无明显降雨风险",
    "当前无降水",
    "短时无雨",
    "降雨可能性不高",
    "无明显降雨",
    "降水较少",
    "无雨",
    "不明显",
    "较低",
    "较小",
    "不高",
]

_POSITIVE_WEATHER_HINTS_HIGH = ["暴雨", "大雨", "强降雨", "持续降雨", "雷阵雨", "明显降雨", "降水较大", "正在降雨"]
_POSITIVE_WEATHER_HINTS_MEDIUM = ["有雨", "有降雨", "有降水", "小雨", "中雨", "阵雨", "未来有雨"]


class WeatherTextSignal(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


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


def _normalize_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = _to_text(value)
    if not text:
        return None
    matched = re.search(r"-?\d+(?:\.\d+)?", text)
    if not matched:
        return None
    try:
        return float(matched.group(0))
    except ValueError:
        return None


def _get_structured_weather(base: BaseProfile) -> dict[str, float | None]:
    return {
        "humidity": _normalize_number(base.relative_humidity_2m),
        "precipitation": _normalize_number(base.precipitation),
        "rain_risk": _normalize_number(base.rain_risk),
    }


def _interpret_weather_text_signal(text: str) -> WeatherTextSignal:
    source = _to_text(text).lower()
    if not source:
        return WeatherTextSignal.UNKNOWN

    if _contains_any(source, _NEGATIVE_WEATHER_HINTS):
        return WeatherTextSignal.LOW
    if _contains_any(source, _POSITIVE_WEATHER_HINTS_HIGH):
        return WeatherTextSignal.HIGH
    if _contains_any(source, _POSITIVE_WEATHER_HINTS_MEDIUM):
        return WeatherTextSignal.MEDIUM
    return WeatherTextSignal.UNKNOWN


def _validate_agri_context_consistency(
    *,
    stage: str,
    explicit_harvest_window_days: Optional[int],
    estimated_harvest_window_days: Optional[int],
) -> list[str]:
    conflicts: list[str] = []

    if stage == "SEEDLING":
        if explicit_harvest_window_days is not None and explicit_harvest_window_days <= 7:
            conflicts.append(f"生长阶段为苗期，但采收窗口仅剩 {explicit_harvest_window_days} 天")
        if estimated_harvest_window_days is not None and estimated_harvest_window_days <= 7:
            conflicts.append(f"生长阶段为苗期，但按播种日期估算已临近采收（约 {estimated_harvest_window_days} 天）")

    if stage in {"FLOWERING", "FRUIT_SET", "FRUIT_EXPANSION", "FRUITING"}:
        if estimated_harvest_window_days is not None and estimated_harvest_window_days >= 90:
            conflicts.append(f"生长阶段为{growth_stage_label(stage)}，但按播种日期估算距采收仍约 {estimated_harvest_window_days} 天")

    if explicit_harvest_window_days is not None and estimated_harvest_window_days is not None:
        if abs(explicit_harvest_window_days - estimated_harvest_window_days) >= 45:
            conflicts.append(
                f"手动采收窗口（{explicit_harvest_window_days} 天）与播种日期估算（{estimated_harvest_window_days} 天）差异过大"
            )
    return conflicts


def build_base_risk_tags(
    base: BaseProfile,
    *,
    harvest_window_days: Optional[int] = None,
) -> dict[str, Any]:
    """根据基地档案构建风险标签（纯函数，不依赖 FastAPI）。"""
    facility = _to_text(base.facility)
    environment_text = _to_text(base.environment)
    weather_snapshot = _to_text(base.weather_snapshot)
    growth_stage = _to_text(base.growth_stage)

    location_fields = [
        _to_text(base.location),
        _to_text(base.province),
        _to_text(base.city),
        _to_text(base.district),
    ]
    location_missing = not any(location_fields) and (base.latitude is None or base.longitude is None)

    merged_text = "\n".join([environment_text, weather_snapshot]).strip()
    text_metrics = _parse_metrics_from_text(merged_text)
    structured_metrics = _get_structured_weather(base)

    risk_items: list[dict[str, str]] = []

    def add_item(code: str, level: str, reason: str, source: str) -> None:
        if any(item["code"] == code for item in risk_items):
            return
        risk_items.append(
            {
                "code": code,
                "label": _RISK_LABELS[code],
                "level": level,
                "reason": reason,
                "source": source,
            }
        )

    humidity = structured_metrics["humidity"] if structured_metrics["humidity"] is not None else text_metrics["humidity"]
    rain_risk = structured_metrics["rain_risk"]
    precipitation = structured_metrics["precipitation"]
    weather_source = "structured_weather" if (rain_risk is not None or precipitation is not None) else "weather_text"
    greenhouse = _is_greenhouse(facility)

    high_humidity = (humidity is not None and humidity >= 80) or _contains_any(
        merged_text, ["高湿", "连阴雨", "叶面结露", "湿度大", "潮湿"]
    )
    if high_humidity:
        add_item("HIGH_HUMIDITY", "medium", "环境湿度偏高，真菌性病害传播风险上升。", "structured_weather" if humidity is not None else "weather_text")

    rain_level: str | None = None
    rain_reason: str | None = None
    if precipitation is not None and precipitation > 0:
        rain_level = "high" if precipitation >= 10 else "medium"
        rain_reason = f"预报降水量约 {precipitation:g} mm，降雨条件已满足。"
    elif rain_risk is not None:
        if rain_risk >= 60:
            rain_level = "high"
            rain_reason = f"未来24小时降雨概率约 {rain_risk:g}%（高风险）。"
        elif rain_risk >= 30:
            rain_level = "medium"
            rain_reason = f"未来24小时降雨概率约 {rain_risk:g}%（中等风险）。"
    else:
        weather_signal = _interpret_weather_text_signal(merged_text)
        if weather_signal == WeatherTextSignal.HIGH:
            rain_level = "high"
            rain_reason = "天气文本显示存在明显降雨信号（如强降雨/持续降雨）。"
        elif weather_signal == WeatherTextSignal.MEDIUM:
            rain_level = "medium"
            rain_reason = "天气文本显示存在降雨可能，需关注田间湿度变化。"

    if rain_level and rain_reason:
        add_item("RAIN_RISK", rain_level, rain_reason, weather_source)

    if greenhouse and ((humidity is not None and humidity >= 75) or _contains_any(merged_text, ["闷", "结露", "通风差", "不通风", "高湿"])):
        add_item("POOR_VENTILATION", "high", "温室/大棚内湿热且通风不足，需加强通风排湿。", "weather_text")

    if greenhouse:
        add_item("GREENHOUSE_PRESSURE", "low", "设施栽培环境下病害压力更易累积，需强化巡检。", "context_check")

    estimated_harvest_days = estimate_harvest_window_days(base.sowing_date)
    effective_harvest_window_days = harvest_window_days if harvest_window_days is not None else estimated_harvest_days

    stage = growth_stage.upper()
    conflicts = _validate_agri_context_consistency(
        stage=stage,
        explicit_harvest_window_days=harvest_window_days,
        estimated_harvest_window_days=estimated_harvest_days,
    )

    near_harvest_blocked = stage == "SEEDLING" and bool(conflicts)

    if effective_harvest_window_days is not None and effective_harvest_window_days <= 7 and not near_harvest_blocked:
        add_item(
            "NEAR_HARVEST",
            "high",
            f"预计距采收约 {effective_harvest_window_days} 天，需严格关注安全间隔与低残留。",
            "harvest_window" if harvest_window_days is not None else "sowing_date_estimate",
        )

    if stage == "SEEDLING":
        add_item("SEEDLING_VULNERABLE", "medium", "当前为苗期，植株抗逆性较弱，需温湿度精细管理。", "growth_stage")
    if stage in {"FLOWERING", "FRUIT_SET", "FRUIT_EXPANSION", "FRUITING"}:
        add_item("FLOWERING_FRUITING_SENSITIVE", "medium", f"当前处于{growth_stage_label(stage)}，需兼顾病害控制与产量品质。", "growth_stage")

    if conflicts:
        add_item(
            "CONTEXT_CONFLICT",
            "warning",
            f"{conflicts[0]}，请核对播种日期、生长阶段或采收窗口设置。",
            "conflict_check",
        )

    missing_fields = []
    if not growth_stage:
        missing_fields.append("growth_stage")
    if not _to_text(base.sowing_date):
        missing_fields.append("sowing_date")
    if location_missing:
        missing_fields.append("location")
    if not merged_text and rain_risk is None and precipitation is None and humidity is None:
        missing_fields.append("weather")
    if missing_fields:
        add_item("MISSING_CONTEXT", "low", f"关键上下文缺失：{', '.join(missing_fields)}。", "context_check")

    return {
        "risk_tags": [item["code"] for item in risk_items],
        "risk_items": risk_items,
        "risk_reasons": [item["reason"] for item in risk_items],
        "risk_updated_at": _utc_now_iso(),
        "estimated_harvest_window_days": estimated_harvest_days,
        "harvest_cycle_days": TOMATO_HARVEST_CYCLE_DAYS,
    }
