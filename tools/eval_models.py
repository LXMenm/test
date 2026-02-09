from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from config import DIAGNOSIS_ALLOW_TORCH, DIAGNOSIS_CONFIDENCE_THRESHOLD
from diagnosis_model import get_diagnosis_engine
from model_registry import list_all_models, resolve_model


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def _load_class_names() -> list[str]:
    path = PROJECT_ROOT / "tomato" / "tomato_disease_classes.txt"
    if not path.exists():
        raise FileNotFoundError(f"缺少类别文件: {path}")
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _load_label_map() -> dict[str, str]:
    path = PROJECT_ROOT / "tomato" / "label_map_cn.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_images(data_dir: Path, limit: int) -> list[tuple[str, Path]]:
    samples: list[tuple[str, Path]] = []
    for class_dir in sorted(data_dir.iterdir()):
        if not class_dir.is_dir():
            continue
        label = class_dir.name
        count = 0
        for image_path in sorted(class_dir.iterdir()):
            if image_path.suffix.lower() not in IMAGE_EXTS:
                continue
            samples.append((label, image_path))
            count += 1
            if count >= limit:
                break
    return samples


def evaluate_model(model_id: str, data_dir: Path, limit: int) -> dict[str, object]:
    allow_torch = str(DIAGNOSIS_ALLOW_TORCH).lower() in {"1", "true", "yes"}
    resolved_model, fallback_reasons = resolve_model(model_id, allow_torch=allow_torch)
    if resolved_model.model_id != model_id and "model_disabled" in fallback_reasons:
        return {
            "model_id": model_id,
            "skipped": True,
            "reason": "model_disabled",
            "fallback_reason": fallback_reasons,
        }
    if resolved_model.backend == "torch" and not allow_torch:
        return {
            "model_id": model_id,
            "skipped": True,
            "reason": "torch_disabled",
            "fallback_reason": fallback_reasons,
        }

    engine = get_diagnosis_engine(
        model_path=resolved_model.model_path,
        backend=resolved_model.backend,
        allow_torch=allow_torch,
    )

    class_names = _load_class_names()
    label_map = _load_label_map()
    if engine.tf_backend and engine.tf_model is not None:
        output_dim = engine.tf_model.output_shape[-1]
        if output_dim != len(class_names):
            raise ValueError(
                f"output_dim({output_dim}) != len(class_names)({len(class_names)})"
            )

    samples = _iter_images(data_dir, limit)
    total = 0
    correct = 0
    low_conf = 0
    total_conf = 0.0
    failed = 0

    for true_label, image_path in samples:
        total += 1
        mapped_true = label_map.get(true_label, true_label)
        try:
            pred_label, confidence, _ = engine.diagnose_from_image(str(image_path))
        except Exception:
            failed += 1
            continue
        if pred_label == "模型未部署":
            failed += 1
            continue
        total_conf += float(confidence or 0.0)
        if float(confidence or 0.0) < DIAGNOSIS_CONFIDENCE_THRESHOLD:
            low_conf += 1
        if pred_label == mapped_true:
            correct += 1

    avg_conf = (total_conf / total) if total else 0.0
    accuracy = (correct / total) if total else 0.0
    low_conf_ratio = (low_conf / total) if total else 0.0
    return {
        "model_id": model_id,
        "resolved_model_id": resolved_model.model_id,
        "backend": resolved_model.backend,
        "resolved_model_path": resolved_model.model_path,
        "fallback_reason": fallback_reasons,
        "total": total,
        "accuracy": round(accuracy, 4),
        "avg_confidence": round(avg_conf, 4),
        "low_confidence_ratio": round(low_conf_ratio, 4),
        "failed": failed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate diagnosis models.")
    parser.add_argument("--data_dir", required=True, help="目录结构按类别子目录组织")
    parser.add_argument("--limit", type=int, default=20, help="每类最多抽样数量")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        raise SystemExit(f"data_dir 不存在: {data_dir}")

    results = []
    for model in list_all_models():
        results.append(evaluate_model(model.model_id, data_dir, args.limit))

    payload = {"results": results}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print("\nSummary")
    for item in results:
        if item.get("skipped"):
            print(f"- {item['model_id']}: skipped ({item['reason']})")
            continue
        print(
            f"- {item['model_id']} ({item['backend']}): "
            f"acc={item['accuracy']}, avg_conf={item['avg_confidence']}, "
            f"low_conf={item['low_confidence_ratio']}, failed={item['failed']}"
        )


if __name__ == "__main__":
    main()
