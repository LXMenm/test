from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

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


def _resolve_light_model_alphas() -> list[float]:
    candidates: list[float] = []
    history_path = PROJECT_ROOT / "tomato" / "mobilenetv3_light_v1_history.json"
    if history_path.exists():
        try:
            payload = json.loads(history_path.read_text(encoding="utf-8"))
            alpha = float(payload.get("alpha", 0.75))
            if alpha not in candidates:
                candidates.append(alpha)
        except Exception:
            pass
    for alpha in [0.75, 1.0, 0.5]:
        if alpha not in candidates:
            candidates.append(alpha)
    return candidates


def _load_weights_with_name_matching(model, model_path: str) -> str:
    try:
        model.load_weights(model_path, by_name=True, skip_mismatch=False)
        return "by_name"
    except Exception as exc:
        try:
            model.load_weights(model_path, by_name=True, skip_mismatch=True)
            return f"by_name_skip_mismatch({exc})"
        except Exception as exc2:
            raise RuntimeError(f"by_name_error={exc}; skip_mismatch_error={exc2}") from exc2


def _load_manual_tf_model(model_path: str, class_names: list[str]):
    lower_name = Path(model_path).name.lower()

    if "light_v1" in lower_name or "mobilenet" in lower_name:
        from tomato.mobilenetv3_light_v1 import build_mobilenetv3_light_v1

        errors: list[str] = []
        for alpha in _resolve_light_model_alphas():
            try:
                wrapper = build_mobilenetv3_light_v1(
                    num_classes=len(class_names),
                    image_size=224,
                    alpha=alpha,
                    backbone_trainable=False,
                )
                model = wrapper.model
                weight_mode = _load_weights_with_name_matching(model, model_path)
                return model, f"manual_tf_loader_light_v1(alpha={alpha},{weight_mode})"
            except Exception as exc:
                errors.append(f"alpha={alpha}: {exc}")
        raise RuntimeError("; ".join(errors))

    if "paper_opt" in lower_name or "cbam" in lower_name:
        from tomato.densenet121_paper_opt import build_paper_optimized_densenet121

        wrapper = build_paper_optimized_densenet121(
            num_classes=len(class_names),
            image_size=224,
            backbone_trainable=False,
        )
        model = wrapper.model
        weight_mode = _load_weights_with_name_matching(model, model_path)
        return model, f"manual_tf_loader_paper_opt({weight_mode})"

    raise RuntimeError(f"没有可用的手工TF加载器: {model_path}")


def _predict_with_manual_tf_model(model, image_path: str, class_names: list[str], label_map: dict[str, str]):
    from tensorflow.keras.preprocessing.image import img_to_array, load_img

    img = load_img(image_path, target_size=(224, 224))
    img_array = img_to_array(img).astype("float32") / 255.0
    img_array = np.expand_dims(img_array, axis=0)
    probs = model.predict(img_array, verbose=0)[0]
    pred_idx = int(np.argmax(probs))
    confidence = float(probs[pred_idx])
    raw_label = class_names[pred_idx]
    pred_label = label_map.get(raw_label, raw_label)
    probs_dict = {label_map.get(label, label): float(prob) for label, prob in zip(class_names, probs)}
    if confidence < DIAGNOSIS_CONFIDENCE_THRESHOLD:
        pred_label = "疑似病害（置信度不足）"
    return pred_label, confidence, probs_dict


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

    class_names = _load_class_names()
    label_map = _load_label_map()
    engine = None
    manual_model = None
    load_mode = "diagnosis_engine"

    try:
        engine = get_diagnosis_engine(
            model_path=resolved_model.model_path,
            backend=resolved_model.backend,
            allow_torch=allow_torch,
        )
    except Exception as exc:
        if resolved_model.backend == "tf":
            try:
                manual_model, load_mode = _load_manual_tf_model(resolved_model.model_path, class_names)
            except Exception as manual_exc:
                return {
                    "model_id": model_id,
                    "resolved_model_id": resolved_model.model_id,
                    "backend": resolved_model.backend,
                    "resolved_model_path": resolved_model.model_path,
                    "fallback_reason": fallback_reasons,
                    "skipped": True,
                    "reason": "model_load_error",
                    "load_error": f"engine_error={exc}; manual_error={manual_exc}",
                }
        else:
            return {
                "model_id": model_id,
                "resolved_model_id": resolved_model.model_id,
                "backend": resolved_model.backend,
                "resolved_model_path": resolved_model.model_path,
                "fallback_reason": fallback_reasons,
                "skipped": True,
                "reason": "model_load_error",
                "load_error": str(exc),
            }

    if engine is not None and engine.tf_backend and engine.tf_model is not None:
        output_dim = engine.tf_model.output_shape[-1]
        if output_dim != len(class_names):
            return {
                "model_id": model_id,
                "resolved_model_id": resolved_model.model_id,
                "backend": resolved_model.backend,
                "resolved_model_path": resolved_model.model_path,
                "fallback_reason": fallback_reasons,
                "skipped": True,
                "reason": "class_count_mismatch",
                "load_error": f"output_dim({output_dim}) != len(class_names)({len(class_names)})",
            }

    if manual_model is not None:
        output_dim = manual_model.output_shape[-1]
        if output_dim != len(class_names):
            return {
                "model_id": model_id,
                "resolved_model_id": resolved_model.model_id,
                "backend": resolved_model.backend,
                "resolved_model_path": resolved_model.model_path,
                "fallback_reason": fallback_reasons,
                "skipped": True,
                "reason": "class_count_mismatch",
                "load_error": f"output_dim({output_dim}) != len(class_names)({len(class_names)})",
            }

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
            if manual_model is not None:
                pred_label, confidence, _ = _predict_with_manual_tf_model(
                    manual_model,
                    str(image_path),
                    class_names,
                    label_map,
                )
            else:
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
        "load_mode": load_mode,
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
            extra = f": {item.get('load_error')}" if item.get("load_error") else ""
            print(f"- {item['model_id']}: skipped ({item['reason']}){extra}")
            continue
        load_mode = f", load_mode={item['load_mode']}" if item.get("load_mode") else ""
        print(
            f"- {item['model_id']} ({item['backend']}): "
            f"acc={item['accuracy']}, avg_conf={item['avg_confidence']}, "
            f"low_conf={item['low_confidence_ratio']}, failed={item['failed']}{load_mode}"
        )


if __name__ == "__main__":
    main()
