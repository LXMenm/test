# -*- coding: utf-8 -*-
"""论文融合版 DenseNet121 番茄病害推理脚本。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import sys
import tensorflow as tf
from tensorflow.keras.preprocessing.image import img_to_array, load_img

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tomato.densenet121_paper_opt import get_custom_objects

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_MODEL_PATH = REPO_ROOT / "models" / "densenet121_tomato_disease_model_fine_tuned_paper_opt.h5"
CLASS_NAMES_PATH = BASE_DIR / "tomato_disease_classes.txt"
LABEL_MAP_CN_PATH = BASE_DIR / "label_map_cn.json"
IMAGE_SIZE = 224


def parse_args():
    parser = argparse.ArgumentParser(description="论文融合版 DenseNet121 推理")
    parser.add_argument("--image", type=str, default=None, help="单张图片路径")
    parser.add_argument("--dir", type=str, default=None, help="批量预测目录")
    parser.add_argument("--model_path", type=str, default=str(DEFAULT_MODEL_PATH))
    parser.add_argument("--topk", type=int, default=3)
    parser.add_argument("--show", action="store_true", help="显示图像")
    return parser.parse_args()


def load_class_names() -> list[str]:
    if CLASS_NAMES_PATH.exists():
        return [line.strip() for line in CLASS_NAMES_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    return []


def load_label_map() -> dict[str, str]:
    if not LABEL_MAP_CN_PATH.exists():
        return {}
    return json.loads(LABEL_MAP_CN_PATH.read_text(encoding="utf-8"))


def load_trained_model(model_path: str):
    model_file = Path(model_path)
    if not model_file.exists():
        raise FileNotFoundError(f"模型文件不存在: {model_file}")
    model = tf.keras.models.load_model(str(model_file), custom_objects=get_custom_objects(), compile=False)
    print(f"已加载模型: {model_file}")
    return model


def preprocess_image(image_path: str):
    img = load_img(image_path, target_size=(IMAGE_SIZE, IMAGE_SIZE))
    img_array = img_to_array(img).astype("float32") / 255.0
    img_array = np.expand_dims(img_array, axis=0)
    return img, img_array


def predict_image(model, image_path: str, class_names: list[str], label_map: dict[str, str], topk: int = 3):
    img, img_array = preprocess_image(image_path)
    probs = model.predict(img_array, verbose=0)[0]
    indices = np.argsort(probs)[::-1][:topk]
    predictions = []
    for idx in indices:
        raw = class_names[idx] if idx < len(class_names) else str(idx)
        predictions.append({
            "label": label_map.get(raw, raw),
            "raw_label": raw,
            "confidence": float(probs[idx]),
        })
    return img, predictions


def display_result(img, predictions, image_path: str):
    top1 = predictions[0] if predictions else {"label": "未知", "confidence": 0.0}
    plt.figure(figsize=(8, 6))
    plt.imshow(img)
    plt.title(f"预测结果: {top1['label']}\n置信度: {top1['confidence'] * 100:.2f}%")
    plt.axis("off")
    plt.tight_layout()
    plt.show()
    print(f"图像路径: {image_path}")
    for item in predictions:
        print(f"- {item['label']}: {item['confidence'] * 100:.2f}%")


def batch_predict(model, image_dir: str, class_names: list[str], label_map: dict[str, str], topk: int):
    results = []
    for filename in sorted(os.listdir(image_dir)):
        if not filename.lower().endswith((".jpg", ".jpeg", ".png", ".bmp", ".webp")):
            continue
        image_path = os.path.join(image_dir, filename)
        try:
            _, predictions = predict_image(model, image_path, class_names, label_map, topk=topk)
            top1 = predictions[0] if predictions else {"label": "未知", "confidence": 0.0}
            results.append({
                "filename": filename,
                "label": top1["label"],
                "confidence": top1["confidence"],
                "topk": predictions,
            })
            print(f"{filename}: {top1['label']} ({top1['confidence'] * 100:.2f}%)")
        except Exception as exc:
            print(f"处理 {filename} 时出错: {exc}")
    return results


def main():
    args = parse_args()
    model = load_trained_model(args.model_path)
    class_names = load_class_names()
    label_map = load_label_map()

    if args.image:
        img, predictions = predict_image(model, args.image, class_names, label_map, topk=args.topk)
        if args.show:
            display_result(img, predictions, args.image)
        else:
            print(json.dumps({"image": args.image, "predictions": predictions}, ensure_ascii=False, indent=2))
        return

    if args.dir:
        results = batch_predict(model, args.dir, class_names, label_map, topk=args.topk)
        print(json.dumps({"results": results}, ensure_ascii=False, indent=2))
        return

    print("请通过 --image 或 --dir 指定预测输入。")


if __name__ == "__main__":
    main()
