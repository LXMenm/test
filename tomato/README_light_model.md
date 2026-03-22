# 轻量模型 V1 说明

这套轻量模型是当前项目的**默认上线模型**，对应系统默认模型 ID：`tf_default`。

它基于 MobileNetV3 轻量化路线实现，目标是在保持精度的同时，获得更小模型体积和更快推理速度，适合作为生产默认模型。

## 当前定位

在当前项目中，模型分工已经明确：

- 默认上线模型：`tf_default`
  - 实际对应：`mobilenetv3_light_v1.keras`
  - 展示名称：**默认轻量上线模型**
- 高精度备选模型：`tf_paper_opt`
  - 实际对应：`densenet121_tomato_disease_model_fine_tuned_paper_opt.h5`
  - 展示名称：**高精度备选模型**

> 说明：`tf_light_v1` 现在保留为兼容历史命名的别名，不再作为前台主选项暴露。

## 方案选择

综合几篇论文后，这里把默认上线轻量模型定为：

- 主干：`MobileNetV3-Large`
- 工程轻量化：`alpha=0.75`
- 训练技巧：
  - 空洞深度卷积头部
  - 小型 MLP 分类头
  - Focal Loss
  - 更强的数据增强

## 默认产物

训练脚本默认输出三类产物：

```text
models/mobilenetv3_light_v1.keras
models/mobilenetv3_light_v1.weights.h5
models/mobilenetv3_light_v1_artifacts.json
```

其中：

- `.keras`：系统默认加载文件
- `.weights.h5`：用于按代码重建结构后再加载权重
- `artifacts.json`：记录 `alpha`、`dropout`、`image_size`、类别数等关键参数

如需兼容旧流程，还可以额外导出 legacy h5：

```bash
python -m tomato.train_mobilenetv3_light_v1 --export_legacy_h5
```

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

- `config.py` 中默认 TF 模型路径指向 `models/mobilenetv3_light_v1.keras`
- `model_registry.py` 中 `tf_default` 表示默认轻量上线模型
- `tf_paper_opt` 表示高精度备选模型
- 推理时如果 `.keras` 不存在，还可以退回 `.weights.h5 + artifacts.json` 方式重建模型

## 建议验证顺序

1. 训练轻量模型
2. 用 `tools/eval_models.py` 对比 `tf_default` 和 `tf_paper_opt`
3. 用 `python -m tomato.infer_mobilenetv3_light_v1` 抽查单图/批量预测
4. 若需复核高精度场景，再切换到 `tf_paper_opt`
