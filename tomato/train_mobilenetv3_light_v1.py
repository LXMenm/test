# -*- coding: utf-8 -*-
"""轻量模型 V1 训练脚本。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import tensorflow as tf
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint, ReduceLROnPlateau
from tensorflow.keras.preprocessing.image import ImageDataGenerator

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tomato.densenet121_paper_opt import DEFAULT_LABEL_MAP_CN, compute_class_alpha
from tomato.mobilenetv3_light_v1 import compile_light_model, build_mobilenetv3_light_v1

BASE_DIR = Path(__file__).resolve().parent
TRAIN_DIR = BASE_DIR / "train"
VAL_DIR = BASE_DIR / "val"
MODEL_DIR = REPO_ROOT / "models"
CLASS_NAMES_PATH = BASE_DIR / "tomato_disease_classes.txt"
CLASS_INDICES_PATH = BASE_DIR / "tomato_disease_class_indices.json"
LABEL_MAP_CN_PATH = BASE_DIR / "label_map_cn.json"
HISTORY_PATH = BASE_DIR / "mobilenetv3_light_v1_history.json"
DEFAULT_OUTPUT = MODEL_DIR / "densenet121_tomato_disease_model_light_v1.h5"
BEST_OUTPUT = MODEL_DIR / "densenet121_tomato_disease_model_light_v1_best.h5"


def parse_args():
    parser = argparse.ArgumentParser(description="训练轻量模型 V1")
    parser.add_argument("--image_size", type=int, default=224)
    parser.add_argument("--batch_size", type=int, default=24)
    parser.add_argument("--alpha", type=float, default=0.75)
    parser.add_argument("--dropout", type=float, default=0.25)
    parser.add_argument("--head_epochs", type=int, default=8)
    parser.add_argument("--fine_tune_epochs", type=int, default=18)
    parser.add_argument("--head_lr", type=float, default=1e-4)
    parser.add_argument("--fine_tune_lr", type=float, default=1e-5)
    parser.add_argument("--loss", choices=["focal", "ce"], default="focal")
    parser.add_argument("--focal_gamma", type=float, default=1.5)
    parser.add_argument("--output_path", type=str, default=str(DEFAULT_OUTPUT))
    return parser.parse_args()


def build_generators(image_size: int, batch_size: int):
    train_datagen = ImageDataGenerator(
        rescale=1.0 / 255.0,
        rotation_range=25,
        width_shift_range=0.10,
        height_shift_range=0.10,
        zoom_range=0.20,
        shear_range=0.10,
        brightness_range=(0.8, 1.2),
        horizontal_flip=True,
        fill_mode="nearest",
    )
    val_datagen = ImageDataGenerator(rescale=1.0 / 255.0)

    train_generator = train_datagen.flow_from_directory(
        str(TRAIN_DIR),
        target_size=(image_size, image_size),
        batch_size=batch_size,
        class_mode="categorical",
        shuffle=True,
    )
    val_generator = val_datagen.flow_from_directory(
        str(VAL_DIR),
        target_size=(image_size, image_size),
        batch_size=batch_size,
        class_mode="categorical",
        shuffle=False,
    )
    return train_generator, val_generator


def save_metadata(class_indices: dict[str, int]) -> None:
    class_names = [name for name, _ in sorted(class_indices.items(), key=lambda item: item[1])]
    CLASS_NAMES_PATH.write_text("\n".join(class_names) + "\n", encoding="utf-8")
    CLASS_INDICES_PATH.write_text(json.dumps(class_indices, ensure_ascii=False, indent=2), encoding="utf-8")
    label_map = {name: DEFAULT_LABEL_MAP_CN.get(name, name.replace("Tomato_", "").replace("_", " ")) for name in class_names}
    LABEL_MAP_CN_PATH.write_text(json.dumps(label_map, ensure_ascii=False, indent=2), encoding="utf-8")


def history_to_dict(history_list: list[tf.keras.callbacks.History]) -> dict[str, list[float]]:
    merged: dict[str, list[float]] = {}
    for history in history_list:
        for key, values in history.history.items():
            merged.setdefault(key, []).extend([float(v) for v in values])
    return merged


def main():
    args = parse_args()
    if not TRAIN_DIR.is_dir():
        raise SystemExit(f"训练目录不存在: {TRAIN_DIR}")
    if not VAL_DIR.is_dir():
        raise SystemExit(f"验证目录不存在: {VAL_DIR}")

    train_generator, val_generator = build_generators(args.image_size, args.batch_size)
    class_indices = dict(train_generator.class_indices)
    save_metadata(class_indices)
    class_counts = np.bincount(train_generator.classes, minlength=len(class_indices)).tolist()
    alpha_weights = compute_class_alpha(class_indices, class_counts)

    wrapper = build_mobilenetv3_light_v1(
        num_classes=len(class_indices),
        image_size=args.image_size,
        alpha=args.alpha,
        dropout=args.dropout,
        backbone_trainable=False,
    )
    model = wrapper.model

    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    callbacks = [
        EarlyStopping(monitor="val_accuracy", patience=6, restore_best_weights=True, mode="max"),
        ReduceLROnPlateau(monitor="val_loss", factor=0.3, patience=3, verbose=1, min_lr=1e-7),
        ModelCheckpoint(str(BEST_OUTPUT), monitor="val_accuracy", save_best_only=True, mode="max", verbose=1),
    ]

    histories = []

    print("\n[Stage 1] 冻结主干，训练轻量头")
    wrapper.freeze_backbone()
    compile_light_model(
        model,
        loss_name=args.loss,
        learning_rate=args.head_lr,
        focal_gamma=args.focal_gamma,
        alpha_weights=alpha_weights,
    )
    history_head = model.fit(
        train_generator,
        epochs=args.head_epochs,
        validation_data=val_generator,
        callbacks=callbacks,
        verbose=1,
    )
    histories.append(history_head)

    print("\n[Stage 2] 解冻顶部层微调")
    wrapper.unfreeze_top_layers(last_n=40, train_batch_norm=False)
    compile_light_model(
        model,
        loss_name=args.loss,
        learning_rate=args.fine_tune_lr,
        focal_gamma=args.focal_gamma,
        alpha_weights=alpha_weights,
    )
    history_ft = model.fit(
        train_generator,
        epochs=args.fine_tune_epochs,
        validation_data=val_generator,
        callbacks=callbacks,
        verbose=1,
    )
    histories.append(history_ft)

    model.save(str(output_path), include_optimizer=False)
    print(f"轻量模型已保存到: {output_path}")

    metrics = dict(zip(model.metrics_names, [float(v) for v in model.evaluate(val_generator, verbose=1)]))
    payload = {
        "class_indices": class_indices,
        "class_counts": class_counts,
        "alpha": args.alpha,
        "loss": args.loss,
        "focal_gamma": args.focal_gamma,
        "metrics": metrics,
        "output_path": str(output_path),
        "history": history_to_dict(histories),
    }
    HISTORY_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"训练历史已保存到: {HISTORY_PATH}")


if __name__ == "__main__":
    main()
