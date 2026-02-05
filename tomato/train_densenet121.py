# -*- coding: utf-8 -*-
"""
基于DenseNet121的番茄病害识别模型训练脚本
使用PlantVillage番茄数据集进行训练
"""

import argparse
import json
import os
from pathlib import Path
import tensorflow as tf
from tensorflow.keras.applications import DenseNet121
from tensorflow.keras.layers import Dense, GlobalAveragePooling2D
from tensorflow.keras.models import Model
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.preprocessing.image import ImageDataGenerator
import numpy as np

def parse_args():
    parser = argparse.ArgumentParser(description="DenseNet121番茄病害识别模型训练")
    parser.add_argument("--epochs", type=int, default=None, help="覆盖训练轮数")
    parser.add_argument(
        "--trainable",
        type=str,
        default=None,
        help="是否解冻骨干网络 (true/false)，默认保持原逻辑",
    )
    return parser.parse_args()


# 配置参数
IMAGE_SIZE = 224  # DenseNet121默认输入大小
BATCH_SIZE = 32
EPOCHS = 50
LEARNING_RATE = 1e-4
REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TRAIN_DIR = os.path.join(BASE_DIR, "train")
VAL_DIR = os.path.join(BASE_DIR, "val")
MODEL_DIR = REPO_ROOT / "models"
BASE_MODEL_PATH = MODEL_DIR / "densenet121_tomato_disease_model.h5"
FINE_TUNED_MODEL_PATH = MODEL_DIR / "densenet121_tomato_disease_model_fine_tuned.h5"
CLASS_NAMES_PATH = REPO_ROOT / "tomato" / "tomato_disease_classes.txt"
CLASS_INDICES_PATH = REPO_ROOT / "tomato" / "tomato_disease_class_indices.json"

# 数据增强和预处理
train_datagen = ImageDataGenerator(
    rescale=1./255,
    shear_range=0.2,
    zoom_range=0.2,
    rotation_range=30,
    horizontal_flip=True,
    vertical_flip=True,
    fill_mode='nearest'
)

val_datagen = ImageDataGenerator(rescale=1./255)

args = parse_args()
if args.epochs is not None:
    EPOCHS = args.epochs

if args.trainable is not None:
    trainable_flag = args.trainable.strip().lower()
    if trainable_flag not in {"true", "false"}:
        raise ValueError("--trainable 只接受 true 或 false")
    backbone_trainable = trainable_flag == "true"
else:
    backbone_trainable = False

print("CWD:", os.getcwd())
print("TRAIN_DIR:", TRAIN_DIR)
print("VAL_DIR:", VAL_DIR)

if not os.path.isdir(TRAIN_DIR):
    print(f"训练数据目录不存在: {TRAIN_DIR}")
    raise SystemExit(1)
if not os.path.isdir(VAL_DIR):
    print(f"验证数据目录不存在: {VAL_DIR}")

# 创建数据生成器
train_generator = train_datagen.flow_from_directory(
    TRAIN_DIR,
    target_size=(IMAGE_SIZE, IMAGE_SIZE),
    batch_size=BATCH_SIZE,
    class_mode='categorical'
)

val_generator = val_datagen.flow_from_directory(
    VAL_DIR,
    target_size=(IMAGE_SIZE, IMAGE_SIZE),
    batch_size=BATCH_SIZE,
    class_mode='categorical'
)

# 保存类别映射
class_indices = train_generator.class_indices
print("类别映射:", class_indices)

# 保存类别名称
class_names = list(class_indices.keys())
print("类别名称:", class_names)

CLASS_NAMES_PATH.parent.mkdir(parents=True, exist_ok=True)
with open(CLASS_NAMES_PATH, "w", encoding="utf-8") as f:
    for class_name in class_names:
        f.write(f"{class_name}\n")

with open(CLASS_INDICES_PATH, "w", encoding="utf-8") as f:
    json.dump(class_indices, f, ensure_ascii=False, indent=2)

# 加载预训练的DenseNet121模型（不包括顶层）
base_model = DenseNet121(weights='imagenet', include_top=False, input_shape=(IMAGE_SIZE, IMAGE_SIZE, 3))

# 冻结基础模型的层
for layer in base_model.layers:
    layer.trainable = backbone_trainable

# 添加自定义顶层
x = base_model.output
x = GlobalAveragePooling2D()(x)

# 全连接层
x = Dense(1024, activation='relu')(x)
x = Dense(512, activation='relu')(x)

# 输出层（10个番茄病害类别）
predictions = Dense(len(class_indices), activation='softmax')(x)

# 创建完整模型
model = Model(inputs=base_model.input, outputs=predictions)

# 编译模型
model.compile(optimizer=Adam(learning_rate=LEARNING_RATE),
              loss='categorical_crossentropy',
              metrics=['accuracy'])

# 打印模型结构
model.summary()

# 训练模型
history = model.fit(
    train_generator,
    steps_per_epoch=train_generator.samples // BATCH_SIZE,
    epochs=EPOCHS,
    validation_data=val_generator,
    validation_steps=val_generator.samples // BATCH_SIZE
)

# 保存模型
MODEL_DIR.mkdir(parents=True, exist_ok=True)
model.save(BASE_MODEL_PATH)
print(f"模型已保存到: {BASE_MODEL_PATH}")

# 评估模型
loss, accuracy = model.evaluate(val_generator)
print(f"验证集准确率: {accuracy * 100:.2f}%")

# 可选：解冻部分顶层并进行微调
print("\n开始模型微调...")

# 解冻基础模型的最后几个密集块
for layer in base_model.layers[-24:]:  # 解冻最后8个卷积块（24层）
    layer.trainable = True

# 重新编译模型（使用更小的学习率）
model.compile(optimizer=Adam(learning_rate=LEARNING_RATE / 10),
              loss='categorical_crossentropy',
              metrics=['accuracy'])

# 继续训练
history_fine = model.fit(
    train_generator,
    steps_per_epoch=train_generator.samples // BATCH_SIZE,
    epochs=EPOCHS // 2,  # 微调轮数减半
    validation_data=val_generator,
    validation_steps=val_generator.samples // BATCH_SIZE
)

# 保存微调后的模型
model.save(FINE_TUNED_MODEL_PATH)
print(f"微调后的模型已保存到: {FINE_TUNED_MODEL_PATH}")

# 最终评估
loss, accuracy = model.evaluate(val_generator)
print(f"微调后验证集准确率: {accuracy * 100:.2f}%")

print("\n训练完成总结:")
print(f"- 模型路径: {BASE_MODEL_PATH}")
print(f"- 类别文件路径: {CLASS_NAMES_PATH}")
print(f"- 类别前3项: {class_names[:3]}")
