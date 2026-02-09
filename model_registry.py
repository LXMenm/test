from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from config import DEFAULT_TF_MODEL_PATH, PROJECT_ROOT


@dataclass(frozen=True)
class ModelConfig:
    model_id: str
    display_name: str
    backend: str
    model_path: str
    enabled: bool = True


DEFAULT_MODEL_ID = "tf_default"


def _resolve_path(path: str) -> str:
    path_obj = Path(path)
    if path_obj.is_absolute():
        return str(path_obj)
    return str((PROJECT_ROOT / path_obj).resolve())


_MODEL_REGISTRY: list[ModelConfig] = [
    ModelConfig(
        model_id="tf_default",
        display_name="默认高精度模型",
        backend="tf",
        model_path=str(DEFAULT_TF_MODEL_PATH),
        enabled=True,
    ),
    ModelConfig(
        model_id="torch_debug",
        display_name="Torch对比模型",
        backend="torch",
        model_path=_resolve_path("models/diagnosis_model.pth"),
        enabled=False,
    ),
]


def _iter_registry() -> Iterable[ModelConfig]:
    for model in _MODEL_REGISTRY:
        yield model


def list_models(*, allow_torch: bool) -> list[dict[str, object]]:
    models: list[dict[str, object]] = []
    for model in _iter_registry():
        if not model.enabled:
            continue
        if model.backend == "torch" and not allow_torch:
            continue
        models.append(
            {
                "model_id": model.model_id,
                "display_name": model.display_name,
                "backend": model.backend,
                "model_path": model.model_path,
                "enabled": model.enabled,
            }
        )
    return models


def resolve_model(model_id: str | None, *, allow_torch: bool) -> tuple[ModelConfig, list[str]]:
    fallback_reasons: list[str] = []
    registry = {model.model_id: model for model in _iter_registry()}
    default_model = registry.get(DEFAULT_MODEL_ID)
    if not default_model:
        raise RuntimeError("默认模型未配置")

    requested = registry.get(model_id) if model_id else default_model
    if model_id and requested is None:
        fallback_reasons.append("model_not_found")
        requested = default_model
    if requested.backend == "torch" and not allow_torch:
        fallback_reasons.append("torch_disabled")
        requested = default_model
    if not requested.enabled:
        fallback_reasons.append("model_disabled")
        requested = default_model
    if requested.model_path and not Path(requested.model_path).exists():
        fallback_reasons.append("model_path_missing")
        if requested.model_id != default_model.model_id:
            requested = default_model
            fallback_reasons.append("fallback_to_default")
    if requested.model_id != (model_id or default_model.model_id):
        fallback_reasons.append("fallback_to_default")
    return requested, fallback_reasons
