# -*- coding: utf-8 -*-
"""
基于论文改进思路的 DenseNet121 番茄病害识别模块。

设计目标：
1. 保持与现有 TensorFlow/Keras 工作流兼容。
2. 在 DenseNet121 主干后加入 CBAM 注意力。
3. 使用 1x1 Conv + GAP + MLP 分类头。
4. 支持 Focal Loss 和两阶段微调。
"""

from __future__ import annotations

from typing import Dict, Iterable, List

import tensorflow as tf
from tensorflow.keras import backend as K
from tensorflow.keras.applications import DenseNet121
from tensorflow.keras.layers import (
    Activation,
    BatchNormalization,
    Concatenate,
    Conv2D,
    Dense,
    Dropout,
    GlobalAveragePooling2D,
    GlobalMaxPooling2D,
    Input,
    Layer,
    Multiply,
    ReLU,
    Reshape,
)
from tensorflow.keras.models import Model
from tensorflow.keras.regularizers import l2


@tf.keras.utils.register_keras_serializable(package="tomato")
class ChannelAttention(Layer):
    def __init__(self, reduction: int = 16, **kwargs):
        super().__init__(**kwargs)
        self.reduction = reduction
        self.avg_pool = GlobalAveragePooling2D(keepdims=True)
        self.max_pool = GlobalMaxPooling2D(keepdims=True)
        self.fc1 = None
        self.fc2 = None
        self.reshape = None
        self.multiply = Multiply()

    def build(self, input_shape):
        channels = int(input_shape[-1])
        hidden = max(channels // self.reduction, 8)
        self.fc1 = Dense(hidden, activation="relu", use_bias=False, name=f"{self.name}_fc1")
        self.fc2 = Dense(channels, activation=None, use_bias=False, name=f"{self.name}_fc2")
        self.reshape = Reshape((1, 1, channels))
        super().build(input_shape)

    def call(self, inputs, **kwargs):
        avg = self.fc2(self.fc1(self.avg_pool(inputs)))
        mx = self.fc2(self.fc1(self.max_pool(inputs)))
        scale = tf.nn.sigmoid(avg + mx)
        scale = self.reshape(scale)
        return self.multiply([inputs, scale])

    def get_config(self):
        config = super().get_config()
        config.update({"reduction": self.reduction})
        return config


@tf.keras.utils.register_keras_serializable(package="tomato")
class SpatialAttention(Layer):
    def __init__(self, kernel_size: int = 7, **kwargs):
        super().__init__(**kwargs)
        self.kernel_size = kernel_size
        self.conv = Conv2D(
            1,
            kernel_size=kernel_size,
            padding="same",
            activation="sigmoid",
            use_bias=False,
            name=f"{self.name}_conv",
        )
        self.concat = Concatenate(axis=-1)
        self.multiply = Multiply()

    def call(self, inputs, **kwargs):
        avg = tf.reduce_mean(inputs, axis=-1, keepdims=True)
        mx = tf.reduce_max(inputs, axis=-1, keepdims=True)
        attention = self.conv(self.concat([avg, mx]))
        return self.multiply([inputs, attention])

    def get_config(self):
        config = super().get_config()
        config.update({"kernel_size": self.kernel_size})
        return config


@tf.keras.utils.register_keras_serializable(package="tomato")
class CBAMBlock(Layer):
    def __init__(self, reduction: int = 16, spatial_kernel: int = 7, **kwargs):
        super().__init__(**kwargs)
        self.reduction = reduction
        self.spatial_kernel = spatial_kernel
        self.channel_attention = ChannelAttention(reduction=reduction, name=f"{self.name}_channel")
        self.spatial_attention = SpatialAttention(kernel_size=spatial_kernel, name=f"{self.name}_spatial")

    def call(self, inputs, **kwargs):
        x = self.channel_attention(inputs)
        x = self.spatial_attention(x)
        return x

    def get_config(self):
        config = super().get_config()
        config.update({"reduction": self.reduction, "spatial_kernel": self.spatial_kernel})
        return config


@tf.keras.utils.register_keras_serializable(package="tomato")
class FocalLoss(tf.keras.losses.Loss):
    def __init__(self, gamma: float = 1.0, alpha: list[float] | None = None, name: str = "focal_loss"):
        super().__init__(name=name)
        self.gamma = float(gamma)
        self.alpha = alpha

    def call(self, y_true, y_pred):
        y_true = tf.cast(y_true, tf.float32)
        y_pred = tf.clip_by_value(tf.cast(y_pred, tf.float32), K.epsilon(), 1.0 - K.epsilon())
        ce = -y_true * tf.math.log(y_pred)
        modulating = tf.pow(1.0 - y_pred, self.gamma)
        loss = modulating * ce
        if self.alpha is not None:
            alpha = tf.constant(self.alpha, dtype=tf.float32)
            loss = loss * alpha
        return tf.reduce_mean(tf.reduce_sum(loss, axis=-1))

    def get_config(self):
        config = super().get_config()
        config.update({"gamma": self.gamma, "alpha": self.alpha})
        return config


def _dense_block_layer_names() -> tuple[str, ...]:
    return ("conv5_", "pool5", "bn")


class PaperOptimizedDenseNet121:
    """用于封装模型与微调策略。"""

    def __init__(
        self,
        num_classes: int,
        image_size: int = 224,
        transition_dim: int = 512,
        dropout: float = 0.30,
        l2_weight: float = 1e-4,
        backbone_trainable: bool = False,
    ):
        self.num_classes = int(num_classes)
        self.image_size = int(image_size)
        self.transition_dim = int(transition_dim)
        self.dropout = float(dropout)
        self.l2_weight = float(l2_weight)
        self.backbone_trainable = bool(backbone_trainable)
        self.base_model: Model | None = None
        self.model: Model = self._build_model()

    def _build_model(self) -> Model:
        inputs = Input(shape=(self.image_size, self.image_size, 3), name="image")
        base_model = DenseNet121(
            weights="imagenet",
            include_top=False,
            input_shape=(self.image_size, self.image_size, 3),
        )
        base_model.trainable = self.backbone_trainable
        self.base_model = base_model

        x = base_model(inputs)
        x = CBAMBlock(name="cbam_block")(x)
        x = Conv2D(
            self.transition_dim,
            kernel_size=1,
            padding="same",
            use_bias=False,
            kernel_regularizer=l2(self.l2_weight),
            name="transition_conv",
        )(x)
        x = BatchNormalization(name="transition_bn")(x)
        x = ReLU(name="transition_relu")(x)
        x = GlobalAveragePooling2D(name="global_avg_pool")(x)

        x = Dense(512, kernel_regularizer=l2(self.l2_weight), name="fc1")(x)
        x = BatchNormalization(name="fc1_bn")(x)
        x = Activation("relu", name="fc1_relu")(x)
        x = Dropout(self.dropout, name="fc1_dropout")(x)

        x = Dense(256, kernel_regularizer=l2(self.l2_weight), name="fc2")(x)
        x = BatchNormalization(name="fc2_bn")(x)
        x = Activation("relu", name="fc2_relu")(x)
        x = Dropout(self.dropout, name="fc2_dropout")(x)

        outputs = Dense(self.num_classes, activation="softmax", name="predictions")(x)
        return Model(inputs=inputs, outputs=outputs, name="paper_optimized_densenet121")

    def freeze_backbone(self) -> None:
        if self.base_model is None:
            return
        self.base_model.trainable = False
        for layer in self.base_model.layers:
            layer.trainable = False

    def unfreeze_last_dense_block(self, train_batch_norm: bool = False) -> None:
        if self.base_model is None:
            return
        self.base_model.trainable = True
        prefixes = _dense_block_layer_names()
        for layer in self.base_model.layers:
            name = layer.name or ""
            if any(name.startswith(prefix) for prefix in prefixes):
                if isinstance(layer, BatchNormalization) and not train_batch_norm:
                    layer.trainable = False
                else:
                    layer.trainable = True
            else:
                layer.trainable = False

    def unfreeze_all(self, train_batch_norm: bool = False) -> None:
        if self.base_model is None:
            return
        self.base_model.trainable = True
        for layer in self.base_model.layers:
            if isinstance(layer, BatchNormalization) and not train_batch_norm:
                layer.trainable = False
            else:
                layer.trainable = True


def build_paper_optimized_densenet121(
    num_classes: int,
    image_size: int = 224,
    transition_dim: int = 512,
    dropout: float = 0.30,
    l2_weight: float = 1e-4,
    backbone_trainable: bool = False,
) -> PaperOptimizedDenseNet121:
    return PaperOptimizedDenseNet121(
        num_classes=num_classes,
        image_size=image_size,
        transition_dim=transition_dim,
        dropout=dropout,
        l2_weight=l2_weight,
        backbone_trainable=backbone_trainable,
    )


def compute_class_alpha(class_indices: Dict[str, int], class_counts: Iterable[int]) -> List[float]:
    counts = list(class_counts)
    if not counts:
        return []
    total = float(sum(counts))
    weights = [total / max(float(count), 1.0) for count in counts]
    mean_weight = sum(weights) / len(weights)
    return [weight / mean_weight for weight in weights]


DEFAULT_LABEL_MAP_CN = {
    "Tomato_Bacterial_spot": "细菌性斑点病",
    "Tomato_Early_blight": "早疫病",
    "Tomato_healthy": "健康",
    "Tomato_Late_blight": "晚疫病",
    "Tomato_Leaf_Mold": "叶霉病",
    "Tomato_Septoria_leaf_spot": "叶斑病",
    "Tomato_Spider_mites_Two_spotted_spider_mite": "蜘蛛螨",
    "Tomato_Target_Spot": "靶斑病",
    "Tomato_Tomato_mosaic_virus": "花叶病毒病",
    "Tomato_Tomato_Yellow_Leaf_Curl_Virus": "黄化曲叶病毒病",
}


def get_custom_objects() -> Dict[str, object]:
    return {
        "ChannelAttention": ChannelAttention,
        "SpatialAttention": SpatialAttention,
        "CBAMBlock": CBAMBlock,
        "FocalLoss": FocalLoss,
    }
