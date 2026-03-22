# -*- coding: utf-8 -*-
"""轻量模型 V1 推理脚本。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

import numpy as np
import tensorflow as tf
from tensorflow.keras.preprocessing.image import img_to_array, load_img

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tomato.mobilenetv3_light_v1 import build_mobilenetv3_light_v1, get_custom_objects

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_MODEL_PATH = REPO_ROOT / "models" / "mobilenetv3_light_v1.keras"
DEFAULT_WEIGHTS_PATH = REPO_ROOT / "models" / "mobilenetv3_light_v1.weights.h5"
ARTIFACTS_PATH = REPO_ROOT / "models" / "mobilenetv3_light_v1_artifacts.json"
CLASS_NAMES_PATH = BASE_DIR / "tomato_disease_classes.txt"
LABEL_MAP_CN_PATH = BASE_DIR / "label_map_cn.json"
IMAGE_SIZE = 224


def parse_args():
    parser = argparse.ArgumentParser(description="轻量模型 V1 推理")
    parser.add_argument("--image", type=str, default=None, help="单张图片路径")
    parser.add_argument("--dir", type=str, default=None, help="批量预测目录")
    parser.add_argument("--model_path", type=str, default=str(DEFAULT_MODEL_PATH))
    parser.add_argument("--weights_path", type=str, default=str(DEFAULT_WEIGHTS_PATH))
    parser.add_argument("--topk", type=int, default=3)
    return parser.parse_args()


def load_class_names() -> list[str]:
    if CLASS_NAMES_PATH.exists():
        return [line.strip() for line in CLASS_NAMES_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    return []


def load_label_map() -> dict[str, str]:
    if not LABEL_MAP_CN_PATH.exists():
        return {}
    return json.loads(LABEL_MAP_CN_PATH.read_text(encoding="utf-8"))


def _load_artifacts() -> dict[str, object]:
    if not ARTIFACTS_PATH.exists():
        return {}
    try:
        return json.loads(ARTIFACTS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _build_model_from_artifacts(class_names: list[str], weights_path: str):
    artifacts = _load_artifacts()
    alpha = float(artifacts.get("alpha", 0.75))
    dropout = float(artifacts.get("dropout", 0.25))
    image_size = int(artifacts.get("image_size", IMAGE_SIZE))
    wrapper = build_mobilenetv3_light_v1(
        num_classes=max(len(class_names), int(artifacts.get("num_classes", len(class_names) or 10))),
        image_size=image_size,
        alpha=alpha,
        dropout=dropout,
        backbone_trainable=False,
    )
    model = wrapper.model
    model.load_weights(weights_path)
    return model


def load_trained_model(model_path: str, class_names: list[str], weights_path: str):
    model_file = Path(model_path)
    if model_file.exists():
        model = tf.keras.models.load_model(str(model_file), custom_objects=get_custom_objects(), compile=False)
        print(f"已加载模型: {model_file}")
        return model

    weights_file = Path(weights_path)
    if weights_file.exists():
        model = _build_model_from_artifacts(class_names, str(weights_file))
        print(f"已通过权重重建模型: {weights_file}")
        return model

    raise FileNotFoundError(f"模型文件不存在: {model_file}; 权重文件不存在: {weights_file}")


def preprocess_image(image_path: str):
    img = load_img(image_path, target_size=(IMAGE_SIZE, IMAGE_SIZE))
    img_array = img_to_array(img).astype("float32") / 255.0
    img_array = np.expand_dims(img_array, axis=0)
    return img_array


def predict_image(model, image_path: str, class_names: list[str], label_map: dict[str, str], topk: int = 3):
    img_array = preprocess_image(image_path)
    probs = model.predict(img_array, verbose=0)[0]
    indices = np.argsort(probs)[::-1][:topk]
    predictions = []
    for idx in indices:
        raw = class_names[idx] if idx < len(class_names) else str(idx)
        predictions.append(
            {
                "label": label_map.get(raw, raw),
                "raw_label": raw,
                "confidence": float(probs[idx]),
            }
        )
    return predictions


def batch_predict(model, image_dir: str, class_names: list[str], label_map: dict[str, str], topk: int):
    results = []
    for filename in sorted(os.listdir(image_dir)):
        if not filename.lower().endswith((".jpg", ".jpeg", ".png", ".bmp", ".webp")):
            continue
        image_path = os.path.join(image_dir, filename)
        try:
            predictions = predict_image(model, image_path, class_names, label_map, topk=topk)
            top1 = predictions[0] if predictions else {"label": "未知", "confidence": 0.0}
            results.append(
                {
                    "filename": filename,
                    "label": top1["label"],
                    "confidence": top1["confidence"],
                    "topk": predictions,
                }
            )
            print(f"{filename}: {top1['label']} ({top1['confidence'] * 100:.2f}%)")
        except Exception as exc:
            print(f"处理 {filename} 时出错: {exc}")
    return results


def main():
    args = parse_args()
    class_names = load_class_names()
    label_map = load_label_map()
    model = load_trained_model(args.model_path, class_names, args.weights_path)

    if args.image:
        predictions = predict_image(model, args.image, class_names, label_map, topk=args.topk)
        print(json.dumps({"image": args.image, "predictions": predictions}, ensure_ascii=False, indent=2))
        return

    if args.dir:
        results = batch_predict(model, args.dir, class_names, label_map, topk=args.topk)
        print(json.dumps({"results": results}, ensure_ascii=False, indent=2))
        return

    print("请通过 --image 或 --dir 指定预测输入。")


if __name__ == "__main__":
    main()
