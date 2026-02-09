from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from config import DIAGNOSIS_ALLOW_TORCH
from model_registry import list_all_models


def main() -> None:
    allow_torch = str(DIAGNOSIS_ALLOW_TORCH).lower() in {"1", "true", "yes"}
    rows = []
    for model in list_all_models():
        exists = Path(model.model_path).exists()
        visible = model.enabled and (model.backend != "torch" or allow_torch)
        rows.append(
            {
                "model_id": model.model_id,
                "backend": model.backend,
                "model_path": model.model_path,
                "enabled": model.enabled,
                "exists": exists,
                "visible": visible,
            }
        )

    headers = ["model_id", "backend", "model_path", "enabled", "exists", "visible"]
    print("DIAGNOSIS_ALLOW_TORCH:", DIAGNOSIS_ALLOW_TORCH)
    print("visible 表示：enabled 且 (backend!=torch 或 allow_torch=1)")
    print(" | ".join(headers))
    print("-" * 120)
    for row in rows:
        print(
            " | ".join(str(row[h]) for h in headers)
        )


if __name__ == "__main__":
    main()
