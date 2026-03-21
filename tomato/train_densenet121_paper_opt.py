# -*- coding: utf-8 -*-
"""论文融合版 DenseNet121 番茄病害训练脚本。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import sys
import tensorflow as tf
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint, ReduceLROnPlateau
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.preprocessing.image import ImageDataGenerator

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tomato.densenet121_paper_opt import (
    DEFAULT_LABEL_MAP_CN,
    FocalLoss,
    build_paper_optimized_densenet121,
    compute_class_alpha,
)

BASE_DIR = Path(__file__).resolve().parent
TRAIN_DIR = BASE_DIR / "train"
VAL_DIR = BASE_DIR / "val"
MODEL_DIR = REPO_ROOT / "models"
CLASS_NAMES_PATH = BASE_DIR / "tomato_disease_classes.txt"
CLASS_INDICES_PATH = BASE_DIR / "tomato_disease_class_indices.json"
LABEL_MAP_CN_PATH = BASE_DIR / "label_map_cn.json"
HISTORY_PATH = BASE_DIR / "densenet121_paper_opt_history.json"


def parse_args():
    parser = argparse.ArgumentParser(description="论文融合版 DenseNet121 番茄病害训练")
    parser.add_argument("--image_size", type=int, default=224)
    parser.add_argument("--batch_size", type=int, default=16)
    parser.add_argument("--head_epochs", type=int, default=8, help="冻结骨干阶段训练轮数")
    parser.add_argument("--fine_tune_epochs", type=int, default=20, help="解冻末端阶段训练轮数")
    parser.add_argument("--head_lr", type=float, default=1e-4)
    parser.add_argument("--fine_tune_lr", type=float, default=1e-5)
    parser.add_argument("--dropout", type=float, default=0.30)
    parser.add_argument("--transition_dim", type=int, default=512)
    parser.add_argument("--loss", type=str, default="focal", choices=["focal", "ce"])
    parser.add_argument("--focal_gamma", type=float, default=1.0)
    parser.add_argument(
        "--output_name",
        type=str,
        default="densenet121_tomato_disease_model_fine_tuned_paper_opt.h5",
        help="输出到 models/ 目录的模型文件名",
    )
    parser.add_argument(
        "--overwrite_default",
        action="store_true",
        help="额外覆盖系统默认模型名 models/densenet121_tomato_disease_model_fine_tuned.h5",
    )
    return parser.parse_args()


def build_generators(image_size: int, batch_size: int):
    train_datagen = ImageDataGenerator(
        rescale=1.0 / 255.0,
        rotation_range=20,
        width_shift_range=0.10,
        height_shift_range=0.10,
        shear_range=0.10,
        zoom_range=0.20,
        brightness_range=(0.85, 1.15),
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


def compile_model(model: tf.keras.Model, loss_name: str, lr: float, gamma: float, alpha: list[float]):
    if loss_name == "focal":
        loss = FocalLoss(gamma=gamma, alpha=alpha)
    else:
        loss = "categorical_crossentropy"
    model.compile(
        optimizer=Adam(learning_rate=lr),
        loss=loss,
        metrics=["accuracy", tf.keras.metrics.TopKCategoricalAccuracy(k=3, name="top3_acc")],
    )


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
    alpha = compute_class_alpha(class_indices, class_counts)

    wrapper = build_paper_optimized_densenet121(
        num_classes=len(class_indices),
        image_size=args.image_size,
        transition_dim=args.transition_dim,
        dropout=args.dropout,
        backbone_trainable=False,
    )
    model = wrapper.model

    output_path = MODEL_DIR / args.output_name
    best_tmp_path = MODEL_DIR / (output_path.stem + "_best.h5")
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    callbacks = [
        EarlyStopping(monitor="val_accuracy", patience=8, restore_best_weights=True, mode="max"),
        ReduceLROnPlateau(monitor="val_loss", factor=0.3, patience=3, verbose=1, min_lr=1e-7),
        ModelCheckpoint(str(best_tmp_path), monitor="val_accuracy", save_best_only=True, mode="max", verbose=1),
    ]

    histories: list[tf.keras.callbacks.History] = []

    print("\n[Stage 1] 冻结骨干，仅训练注意力与分类头")
    wrapper.freeze_backbone()
    compile_model(model, args.loss, args.head_lr, args.focal_gamma, alpha)
    history_head = model.fit(
        train_generator,
        epochs=args.head_epochs,
        validation_data=val_generator,
        callbacks=callbacks,
        verbose=1,
    )
    histories.append(history_head)

    print("\n[Stage 2] 解冻最后 Dense Block 微调")
    wrapper.unfreeze_last_dense_block(train_batch_norm=False)
    compile_model(model, args.loss, args.fine_tune_lr, args.focal_gamma, alpha)
    history_ft = model.fit(
        train_generator,
        epochs=args.fine_tune_epochs,
        validation_data=val_generator,
        callbacks=callbacks,
        verbose=1,
    )
    histories.append(history_ft)

    if best_tmp_path.exists():
        model = tf.keras.models.load_model(str(best_tmp_path), custom_objects={"FocalLoss": FocalLoss}, compile=False)

    model.save(str(output_path), include_optimizer=False)
    print(f"\n优化模型已保存到: {output_path}")

    if args.overwrite_default:
        default_path = MODEL_DIR / "densenet121_tomato_disease_model_fine_tuned.h5"
        model.save(str(default_path), include_optimizer=False)
        print(f"已额外覆盖默认系统模型: {default_path}")

    eval_result = model.evaluate(val_generator, verbose=1)
    metrics = dict(zip(model.metrics_names, [float(v) for v in eval_result]))
    merged_history = history_to_dict(histories)
    payload = {
        "class_indices": class_indices,
        "class_counts": class_counts,
        "loss": args.loss,
        "focal_gamma": args.focal_gamma,
        "head_epochs": args.head_epochs,
        "fine_tune_epochs": args.fine_tune_epochs,
        "output_path": str(output_path),
        "metrics": metrics,
        "history": merged_history,
    }
    HISTORY_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"训练历史与指标已保存到: {HISTORY_PATH}")


if __name__ == "__main__":
    main()
