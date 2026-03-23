from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

RUNTIME_CONFIG_PATH = Path("data/system/admin_runtime_config.json")

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
        "image_reliable_threshold": 0.70,
        "text_reliable_threshold": 0.45,
        "conflict_margin": 0.10,
        "need_confirm_threshold": 0.60,
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


def _sanitize_config(raw: dict[str, Any] | None) -> dict[str, Any]:
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
        "image_reliable_threshold": _as_float(model_input.get("image_reliable_threshold"), float(default_model["image_reliable_threshold"])),
        "text_reliable_threshold": _as_float(model_input.get("text_reliable_threshold"), float(default_model["text_reliable_threshold"])),
        "conflict_margin": _as_float(model_input.get("conflict_margin"), float(default_model["conflict_margin"])),
        "need_confirm_threshold": _as_float(model_input.get("need_confirm_threshold"), float(default_model["need_confirm_threshold"])),
    }

    default_llm = DEFAULT_ADMIN_CONFIG["llm"]
    llm_input = source.get("llm") if isinstance(source.get("llm"), dict) else {}
    llm = {
        "enable_llm": _as_bool(llm_input.get("enable_llm"), bool(default_llm["enable_llm"])),
        "enable_treatment_generation": _as_bool(llm_input.get("enable_treatment_generation"), bool(default_llm["enable_treatment_generation"])),
        "enable_constraint_validation": _as_bool(llm_input.get("enable_constraint_validation"), bool(default_llm["enable_constraint_validation"])),
    }

    return {
        "workflow": workflow,
        "model_fusion": model_fusion,
        "llm": llm,
    }


def load_admin_runtime_config() -> dict[str, Any]:
    if not RUNTIME_CONFIG_PATH.exists():
        return deepcopy(DEFAULT_ADMIN_CONFIG)
    try:
        raw = json.loads(RUNTIME_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return deepcopy(DEFAULT_ADMIN_CONFIG)
    return _sanitize_config(raw if isinstance(raw, dict) else None)


def save_admin_runtime_config(raw: dict[str, Any]) -> dict[str, Any]:
    normalized = _sanitize_config(raw)
    RUNTIME_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_CONFIG_PATH.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return normalized


def get_admin_flag(path: str, default: Any = None) -> Any:
    cursor: Any = load_admin_runtime_config()
    for key in path.split("."):
        if not isinstance(cursor, dict) or key not in cursor:
            return default
        cursor = cursor[key]
    return cursor
