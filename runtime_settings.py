from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from config import LLM_PROVIDER, OPENAI_MODEL, QWEN_MODEL, WENXIN_MODEL

RUNTIME_CONFIG_PATH = Path("data/system/admin_runtime_config.json")

RUNTIME_THRESHOLD_DEFAULTS: dict[str, float] = {
    "image_top1_threshold": 0.65,
    "image_margin_threshold": 0.15,
    "text_top1_threshold": 0.40,
    "text_margin_threshold": 0.10,
    "weak_conflict_min_image_top1": 0.50,
    "weak_conflict_min_text_top1": 0.40,
    "diagnosis_conf_threshold": 0.50,
    "low_margin_threshold": 0.03,
}

DEFAULT_ADMIN_CONFIG: dict[str, Any] = {
    "workflow": {
        "confirm_round_limit": 1,
        "validator_rewrite_limit": 1,
        "enable_validator_agent": True,
        "enable_personalization_agent": True,
    },
    "model_fusion": {
        "enable_image_model": True,
        "enable_text_model": True,
        "text_backend": "auto",
        **RUNTIME_THRESHOLD_DEFAULTS,
    },
    "llm": {
        "enable_llm": True,
        "enable_treatment_generation": True,
        "enable_constraint_validation": True,
    },
}


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _as_float(value: Any, default: float, *, min_value: float = 0.0, max_value: float = 1.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(max_value, parsed))


def _as_int(value: Any, default: int, *, min_value: int = 0, max_value: int = 99) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(max_value, parsed))


def _normalize_text_backend(value: Any, default: str) -> str:
    text = str(value or "").strip().lower()
    if text in {"auto", "bert", "rule"}:
        return text
    return default


def _coalesce_threshold(model_input: dict[str, Any], new_key: str, default_value: float) -> float:
    # 兼容迁移：旧字段仅用于一次性读取并迁移，运行时真值统一收口到新字段。
    legacy_alias_map = {
        "image_top1_threshold": ("image_reliable_threshold",),
        "text_top1_threshold": ("text_reliable_threshold",),
        # 旧 conflict_margin 历史上用于文本弱冲突兜底，迁移到 weak_conflict_min_text_top1。
        "weak_conflict_min_text_top1": ("conflict_margin",),
        # need_confirm_threshold 已弃用：在线逻辑统一使用 diagnosis_conf_threshold + low_margin_threshold。
        "diagnosis_conf_threshold": (),
    }
    raw_value = model_input.get(new_key)
    if raw_value is None:
        for old_key in legacy_alias_map.get(new_key, ()):  # pragma: no cover - simple fallback path
            if model_input.get(old_key) is not None:
                raw_value = model_input.get(old_key)
                break
    return _as_float(raw_value, default_value)


def _sanitize_config(raw: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
    source = raw if isinstance(raw, dict) else {}

    default_workflow = DEFAULT_ADMIN_CONFIG["workflow"]
    workflow_input = source.get("workflow") if isinstance(source.get("workflow"), dict) else {}
    workflow = {
        "confirm_round_limit": _as_int(workflow_input.get("confirm_round_limit"), int(default_workflow["confirm_round_limit"]), min_value=0, max_value=10),
        "validator_rewrite_limit": _as_int(workflow_input.get("validator_rewrite_limit"), int(default_workflow["validator_rewrite_limit"]), min_value=0, max_value=10),
        "enable_validator_agent": _as_bool(workflow_input.get("enable_validator_agent"), bool(default_workflow["enable_validator_agent"])),
        "enable_personalization_agent": _as_bool(workflow_input.get("enable_personalization_agent"), bool(default_workflow["enable_personalization_agent"])),
    }

    default_model = DEFAULT_ADMIN_CONFIG["model_fusion"]
    model_input = source.get("model_fusion") if isinstance(source.get("model_fusion"), dict) else {}
    model_fusion = {
        "enable_image_model": _as_bool(model_input.get("enable_image_model"), bool(default_model["enable_image_model"])),
        "enable_text_model": _as_bool(model_input.get("enable_text_model"), bool(default_model["enable_text_model"])),
        "text_backend": _normalize_text_backend(model_input.get("text_backend"), str(default_model["text_backend"])),
        "image_top1_threshold": _coalesce_threshold(model_input, "image_top1_threshold", float(default_model["image_top1_threshold"])),
        "image_margin_threshold": _coalesce_threshold(model_input, "image_margin_threshold", float(default_model["image_margin_threshold"])),
        "text_top1_threshold": _coalesce_threshold(model_input, "text_top1_threshold", float(default_model["text_top1_threshold"])),
        "text_margin_threshold": _coalesce_threshold(model_input, "text_margin_threshold", float(default_model["text_margin_threshold"])),
        "weak_conflict_min_image_top1": _coalesce_threshold(model_input, "weak_conflict_min_image_top1", float(default_model["weak_conflict_min_image_top1"])),
        "weak_conflict_min_text_top1": _coalesce_threshold(model_input, "weak_conflict_min_text_top1", float(default_model["weak_conflict_min_text_top1"])),
        "diagnosis_conf_threshold": _coalesce_threshold(model_input, "diagnosis_conf_threshold", float(default_model["diagnosis_conf_threshold"])),
        "low_margin_threshold": _coalesce_threshold(model_input, "low_margin_threshold", float(default_model["low_margin_threshold"])),
    }

    default_llm = DEFAULT_ADMIN_CONFIG["llm"]
    llm_input = source.get("llm") if isinstance(source.get("llm"), dict) else {}
    llm = {
        "enable_llm": _as_bool(llm_input.get("enable_llm"), bool(default_llm["enable_llm"])),
        "enable_treatment_generation": _as_bool(llm_input.get("enable_treatment_generation"), bool(default_llm["enable_treatment_generation"])),
        "enable_constraint_validation": _as_bool(llm_input.get("enable_constraint_validation"), bool(default_llm["enable_constraint_validation"])),
    }

    normalized = {
        "workflow": workflow,
        "model_fusion": model_fusion,
        "llm": llm,
    }
    was_migrated = normalized != (source if isinstance(source, dict) else {})
    return normalized, was_migrated


def load_admin_runtime_config() -> dict[str, Any]:
    if not RUNTIME_CONFIG_PATH.exists():
        return deepcopy(DEFAULT_ADMIN_CONFIG)
    try:
        raw = json.loads(RUNTIME_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return deepcopy(DEFAULT_ADMIN_CONFIG)
    normalized, was_migrated = _sanitize_config(raw if isinstance(raw, dict) else None)
    if was_migrated:
        save_admin_runtime_config(normalized)
    return normalized


def save_admin_runtime_config(raw: dict[str, Any]) -> dict[str, Any]:
    normalized, _ = _sanitize_config(raw)
    RUNTIME_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_CONFIG_PATH.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return normalized


def get_runtime_thresholds(config: dict[str, Any] | None = None) -> dict[str, float]:
    current = config if isinstance(config, dict) else load_admin_runtime_config()
    model_fusion = current.get("model_fusion") if isinstance(current.get("model_fusion"), dict) else {}
    return {
        key: _as_float(model_fusion.get(key), default)
        for key, default in RUNTIME_THRESHOLD_DEFAULTS.items()
    }


def get_admin_flag(path: str, default: Any = None) -> Any:
    cursor: Any = load_admin_runtime_config()
    for key in path.split("."):
        if not isinstance(cursor, dict) or key not in cursor:
            return default
        cursor = cursor[key]
    return cursor


def get_admin_llm_runtime_snapshot(config: dict[str, Any] | None = None) -> dict[str, Any]:
    current_config = config if isinstance(config, dict) else load_admin_runtime_config()
    llm_config = current_config.get("llm") if isinstance(current_config.get("llm"), dict) else {}
    constraint_global_enabled = _as_bool(
        llm_config.get("enable_constraint_validation"),
        bool(DEFAULT_ADMIN_CONFIG["llm"]["enable_constraint_validation"]),
    )

    provider = str(LLM_PROVIDER or "openai").strip().lower() or "openai"
    provider_meta = {
        "openai": {"label": "OpenAI", "model_id": OPENAI_MODEL},
        "qwen": {"label": "通义千问", "model_id": QWEN_MODEL},
        "wenxin": {"label": "文心一言", "model_id": WENXIN_MODEL},
    }
    selected_provider_meta = provider_meta.get(provider, {"label": provider.upper(), "model_id": "unknown"})
    model_id = str(selected_provider_meta.get("model_id") or "unknown")
    model_display_name = f'{selected_provider_meta["label"]} · {model_id}'

    template_mode = "llm_dynamic_generation" if bool(llm_config.get("enable_treatment_generation", True)) else "kb_fallback_only"
    template_scene = "家庭/中等规模/企业分档 + 专家复核后可再生成"
    if template_mode == "kb_fallback_only":
        template_scene = "仅知识库后备方案（可用于禁用生成或失败降级）"

    constraint_summary_items = [
        {"key": "banned_ingredients", "label": "禁用成分", "enabled": constraint_global_enabled, "description": "校验并剔除禁用成分建议"},
        {"key": "harvest_window", "label": "采收窗口", "enabled": constraint_global_enabled, "description": "采收临近时补充窗口与时机提醒"},
        {"key": "safety_interval", "label": "安全间隔", "enabled": constraint_global_enabled, "description": "提示施药后采收安全间隔"},
        {"key": "equipment_capability", "label": "设备能力", "enabled": constraint_global_enabled, "description": "结合设备条件约束执行流程"},
        {"key": "organic_preference", "label": "有机偏好", "enabled": constraint_global_enabled, "description": "偏好低残留/有机友好方案"},
        {"key": "risk_preference", "label": "风险偏好", "enabled": constraint_global_enabled, "description": "按风险偏好控制建议激进程度"},
    ]

    return {
        "model": {
            "provider": provider,
            "provider_display_name": selected_provider_meta["label"],
            "model_id": model_id,
            "model_display_name": model_display_name,
        },
        "template": {
            "name": template_mode,
            "purpose": "生成可执行、可审计的番茄病害治疗建议，并结合个性化档案约束。",
            "scenes": template_scene,
        },
        "constraint_validation": {
            "mode": "runtime_default_summary",
            "global_enabled": constraint_global_enabled,
            "items": constraint_summary_items,
        },
    }
