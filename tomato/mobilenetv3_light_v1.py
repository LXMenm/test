# -*- coding: utf-8 -*-
"""轻量模型 V1: MobileNetV3-Large + 轻量头 + Focal Loss 辅助组件。"""

from __future__ import annotations

from typing import Dict

import tensorflow as tf
from tensorflow.keras import layers, models
from tensorflow.keras.applications import MobileNetV3Large
from tensorflow.keras.regularizers import l2

from tomato.densenet121_paper_opt import DEFAULT_LABEL_MAP_CN, FocalLoss, compute_class_alpha


class MobileNetV3LightV1:
    def __init__(
        self,
        num_classes: int,
        image_size: int = 224,
        alpha: float = 0.75,
        dropout: float = 0.25,
        l2_weight: float = 1e-4,
        backbone_trainable: bool = False,
    ):
        self.num_classes = int(num_classes)
        self.image_size = int(image_size)
        self.alpha = float(alpha)
        self.dropout = float(dropout)
        self.l2_weight = float(l2_weight)
        self.backbone_trainable = bool(backbone_trainable)
        self.base_model: tf.keras.Model | None = None
        self.model: tf.keras.Model = self._build_model()

    def _build_model(self) -> tf.keras.Model:
        inputs = layers.Input(shape=(self.image_size, self.image_size, 3), name="image")
        base_model = MobileNetV3Large(
            input_shape=(self.image_size, self.image_size, 3),
            alpha=self.alpha,
            include_top=False,
            weights="imagenet",
            include_preprocessing=False,
            pooling=None,
        )
        base_model.trainable = self.backbone_trainable
        self.base_model = base_model

        x = base_model(inputs)
        x = layers.Conv2D(160, kernel_size=1, padding="same", use_bias=False, name="light_proj_conv")(x)
        x = layers.BatchNormalization(name="light_proj_bn")(x)
        x = layers.Activation("swish", name="light_proj_swish")(x)
        x = layers.DepthwiseConv2D(
            kernel_size=3,
            padding="same",
            dilation_rate=2,
            use_bias=False,
            name="light_dilated_dwconv",
        )(x)
        x = layers.BatchNormalization(name="light_dilated_bn")(x)
        x = layers.Activation("swish", name="light_dilated_swish")(x)
        x = layers.GlobalAveragePooling2D(name="global_avg_pool")(x)
        x = layers.Dense(256, activation="swish", kernel_regularizer=l2(self.l2_weight), name="mlp_fc1")(x)
        x = layers.Dropout(self.dropout, name="mlp_dropout1")(x)
        x = layers.Dense(128, activation="swish", kernel_regularizer=l2(self.l2_weight), name="mlp_fc2")(x)
        x = layers.Dropout(self.dropout * 0.8, name="mlp_dropout2")(x)
        outputs = layers.Dense(self.num_classes, activation="softmax", name="predictions")(x)
        return models.Model(inputs=inputs, outputs=outputs, name="mobilenetv3_light_v1")

    def freeze_backbone(self) -> None:
        if self.base_model is None:
            return
        self.base_model.trainable = False
        for layer in self.base_model.layers:
            layer.trainable = False

    def unfreeze_top_layers(self, last_n: int = 40, train_batch_norm: bool = False) -> None:
        if self.base_model is None:
            return
        self.base_model.trainable = True
        split_idx = max(len(self.base_model.layers) - int(last_n), 0)
        for i, layer in enumerate(self.base_model.layers):
            should_train = i >= split_idx
            if isinstance(layer, layers.BatchNormalization) and not train_batch_norm:
                layer.trainable = False
            else:
                layer.trainable = should_train


def build_mobilenetv3_light_v1(
    num_classes: int,
    image_size: int = 224,
    alpha: float = 0.75,
    dropout: float = 0.25,
    l2_weight: float = 1e-4,
    backbone_trainable: bool = False,
) -> MobileNetV3LightV1:
    return MobileNetV3LightV1(
        num_classes=num_classes,
        image_size=image_size,
        alpha=alpha,
        dropout=dropout,
        l2_weight=l2_weight,
        backbone_trainable=backbone_trainable,
    )


def compile_light_model(
    model: tf.keras.Model,
    *,
    loss_name: str,
    learning_rate: float,
    focal_gamma: float,
    alpha_weights: list[float],
) -> None:
    if loss_name == "focal":
        loss = FocalLoss(gamma=focal_gamma, alpha=alpha_weights)
    else:
        loss = "categorical_crossentropy"
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=learning_rate),
        loss=loss,
        metrics=["accuracy", tf.keras.metrics.TopKCategoricalAccuracy(k=3, name="top3_acc")],
    )


def get_custom_objects() -> Dict[str, object]:
    return {"FocalLoss": FocalLoss}
