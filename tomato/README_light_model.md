# 轻量模型 V1 说明

这套轻量模型是针对你当前项目 `tf_light_v1` 槽位新增的一条训练/推理链路，目标是在 **不改系统主流程** 的前提下，把论文里适合移动端部署的思路落到现有 TensorFlow / Keras 工程中。

## 方案选择

综合几篇论文后，这里把轻量模型定为：

- 主干：`MobileNetV3-Large`
- 工程轻量化：`alpha=0.75` 缩窄宽度，减少参数量与推理开销
- 训练技巧：借鉴 DM-MobileNetV3 的思路，加入
  - 空洞深度卷积头部
  - 小型 MLP 分类头
  - Focal Loss
  - 更强的数据增强

> 说明：郑超杰论文里最强部署形态是 `MobileNetV3-Prune`。为了兼容你当前仓库的 TensorFlow/Keras 栈并避免额外依赖，这里先实现一个 **免额外依赖的工程版轻量模型**：`MobileNetV3-Large-0.75 + 轻量头 + Focal Loss`。这比直接引入完整剪枝流水线更容易在你当前项目中稳定落地。

## 新增文件

- `tomato/mobilenetv3_light_v1.py`
- `tomato/train_mobilenetv3_light_v1.py`
- `tomato/infer_mobilenetv3_light_v1.py`

## 默认输出位置

训练脚本默认直接输出到系统当前 `tf_light_v1` 的模型槽位：

```text
models/densenet121_tomato_disease_model_light_v1.h5
```

虽然文件名里沿用了历史命名中的 `densenet121`，但其中实际保存的是新的 MobileNetV3 轻量模型。这样做的目的是 **不改现有 model_registry，就能直接接入系统轻量模型选项**。

## 推荐训练命令

```bash
python -m tomato.train_mobilenetv3_light_v1 \
  --head_epochs 8 \
  --fine_tune_epochs 18 \
  --alpha 0.75 \
  --loss focal \
  --focal_gamma 1.5
```

## 推荐推理命令

单图：

```bash
python -m tomato.infer_mobilenetv3_light_v1 --image path/to/image.jpg --topk 3
```

批量：

```bash
python -m tomato.infer_mobilenetv3_light_v1 --dir tomato/val/Tomato_healthy --topk 3
```

## 和现有系统的关系

- 新模型默认保存到 `tf_light_v1` 现有槽位路径。
- 后端模型选择仍可继续使用 `tf_default` 与 `tf_light_v1` 做 A/B 对比。
- 类别文件和中文标签映射仍复用 `tomato/` 下同一套文件。

## 建议的验证顺序

1. 先训练轻量模型。
2. 用 `tools/eval_models.py` 对比 `tf_default` 和 `tf_light_v1`。
3. 如果轻量模型在速度、体积和精度上达到预期，再将前端默认模型切到 `tf_light_v1`。
