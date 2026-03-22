# DenseNet121 论文融合优化版说明

这套脚本是在现有 `tomato/train_densenet121.py` 和 `tomato/infer_densenet121.py` 之外新增的一条高精度训练链路，当前在项目中的定位已经明确为：

- 默认上线模型：`tf_default` → 默认轻量上线模型
- 高精度备选模型：`tf_paper_opt` → DenseNet 论文融合优化版

也就是说，这套 DenseNet 优化版现在不再作为系统默认模型，而是作为**高精度备选模型**保留，适合复核、对照和高精度场景。

## 这次新增了什么

- `tomato/densenet121_paper_opt.py`
  - DenseNet121 + CBAM 注意力
  - 1x1 Conv + GAP 过渡头
  - 512/256 MLP 分类头
  - Focal Loss
  - 两阶段微调辅助函数

- `tomato/train_densenet121_paper_opt.py`
  - 更强的数据增强
  - 先冻结主干，再解冻最后 Dense Block
  - EarlyStopping + ReduceLROnPlateau + ModelCheckpoint
  - 自动输出类别映射、中文标签映射、训练历史

- `tomato/infer_densenet121_paper_opt.py`
  - 支持单图/目录预测
  - 支持 Top-K 输出

## 推荐训练命令

```bash
python -m tomato.train_densenet121_paper_opt \
  --head_epochs 8 \
  --fine_tune_epochs 20 \
  --loss focal \
  --focal_gamma 1.0
```

## 推荐推理命令

单图：

```bash
python -m tomato.infer_densenet121_paper_opt --image path/to/image.jpg --topk 3
```

批量：

```bash
python -m tomato.infer_densenet121_paper_opt --dir tomato/val/Tomato_healthy --topk 3
```

## 和现有系统的关系

- 原始 DenseNet 训练脚本保留，方便你回退。
- `tf_paper_opt` 当前在系统中作为 **高精度备选模型** 暴露。
- 当你需要更高平均置信度或做结果复核时，可以手动切换到该模型。
- 日常默认上线与主流程诊断则走轻量模型 `tf_default`。

## 建议的使用方式

1. 日常默认诊断：使用 `tf_default`
2. 高精度复核或 A/B 对照：使用 `tf_paper_opt`
3. 如需继续优化 DenseNet 方向，再基于这条链路迭代
