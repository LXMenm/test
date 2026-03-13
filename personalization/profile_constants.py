"""Profile-related constants and compatibility helpers."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

# 经验值：番茄从播种到采收常见在 110~140 天，这里取中位保守常量。
# 用于系统估算 harvest_window_days（论文中可解释为规则基线而非精准农业模型）。
TOMATO_TOTAL_GROW_DAYS = 120

TOMATO_GROWTH_STAGE_LABELS = {
    "SEEDLING": "育苗期",
    "VEGETATIVE": "营养生长期",
    "FLOWERING": "开花期",
    "FRUIT_SET": "坐果期",
    "FRUIT_EXPANSION": "膨果期",
    "RIPENING": "转色成熟期",
    "HARVEST": "采收期",
}

_TOMATO_STAGE_ALIASES = {
    "育苗": "SEEDLING",
    "育苗期": "SEEDLING",
    "苗期": "SEEDLING",
    "seedling": "SEEDLING",
    "营养生长期": "VEGETATIVE",
    "营养期": "VEGETATIVE",
    "生长期": "VEGETATIVE",
    "vegetative": "VEGETATIVE",
    "开花": "FLOWERING",
    "开花期": "FLOWERING",
    "flowering": "FLOWERING",
    "坐果": "FRUIT_SET",
    "坐果期": "FRUIT_SET",
    "fruit_set": "FRUIT_SET",
    "fruitting": "FRUIT_SET",
    "膨果": "FRUIT_EXPANSION",
    "膨果期": "FRUIT_EXPANSION",
    "果实膨大期": "FRUIT_EXPANSION",
    "fruit_expansion": "FRUIT_EXPANSION",
    "转色": "RIPENING",
    "成熟": "RIPENING",
    "转色成熟期": "RIPENING",
    "ripening": "RIPENING",
    "采收": "HARVEST",
    "采收期": "HARVEST",
    "harvest": "HARVEST",
}


def normalize_growth_stage(value: str | None) -> Optional[str]:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    upper = raw.upper()
    if upper in TOMATO_GROWTH_STAGE_LABELS:
        return upper
    alias = _TOMATO_STAGE_ALIASES.get(raw) or _TOMATO_STAGE_ALIASES.get(raw.lower())
    return alias


def growth_stage_label(value: str | None) -> str:
    normalized = normalize_growth_stage(value)
    if not normalized:
        return "未设置"
    return TOMATO_GROWTH_STAGE_LABELS.get(normalized, normalized)


def normalize_sowing_date(value: str | None) -> Optional[str]:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None
    return parsed.isoformat()


def estimate_harvest_window_days(sowing_date: str | None, *, today: date | None = None) -> Optional[int]:
    normalized = normalize_sowing_date(sowing_date)
    if not normalized:
        return None
    sow = datetime.strptime(normalized, "%Y-%m-%d").date()
    ref_today = today or datetime.now(timezone.utc).date()
    passed_days = (ref_today - sow).days
    if passed_days < 0:
        passed_days = 0
    return max(TOMATO_TOTAL_GROW_DAYS - passed_days, 0)
