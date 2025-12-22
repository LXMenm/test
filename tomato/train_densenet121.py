# -*- coding: utf-8 -*-
"""
基于DenseNet121的番茄病害识别模型训练脚本
使用PlantVillage番茄数据集进行训练
"""

import os
import tensorflow as tf
from tensorflow.keras.applications import DenseNet121
from tensorflow.keras.layers import Dense, GlobalAveragePooling2D
from tensorflow.keras.models import Model
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.preprocessing.image import ImageDataGenerator
import numpy as np

# 配置参数
IMAGE_SIZE = 224  # DenseNet121默认输入大小
BATCH_SIZE = 32
EPOCHS = 50
LEARNING_RATE = 1e-4
TRAIN_DIR = 'train'
VAL_DIR = 'val'
SAVE_PATH = 'densenet121_tomato_disease_model.h5'

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

# 创建类别名称文件
with open('tomato_disease_classes.txt', 'w') as f:
    for class_name in class_names:
        f.write(f"{class_name}\n")

# 加载预训练的DenseNet121模型（不包括顶层）
base_model = DenseNet121(weights='imagenet', include_top=False, input_shape=(IMAGE_SIZE, IMAGE_SIZE, 3))

# 冻结基础模型的层
for layer in base_model.layers:
    layer.trainable = False

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
model.save(SAVE_PATH)
print(f"模型已保存到: {SAVE_PATH}")

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
model.save(f"{SAVE_PATH.replace('.h5', '_fine_tuned.h5')}")
print(f"微调后的模型已保存到: {SAVE_PATH.replace('.h5', '_fine_tuned.h5')}")

# 最终评估
loss, accuracy = model.evaluate(val_generator)
print(f"微调后验证集准确率: {accuracy * 100:.2f}%")
