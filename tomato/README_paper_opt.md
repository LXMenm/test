# DenseNet121 论文融合优化版说明

这套脚本是在现有 `tomato/train_densenet121.py` 和 `tomato/infer_densenet121.py` 之外新增的一条优化训练链路，目标是尽量不破坏你当前项目结构，同时把论文里最值得落地的改动接进去。

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

如果你想直接覆盖系统默认模型路径：

```bash
python -m tomato.train_densenet121_paper_opt \
  --overwrite_default
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

## 和现有脚本的关系

- 原脚本保留，方便你回退。
- 新脚本单独命名为 `*_paper_opt.py`，不会直接覆盖你当前训练流程。
- 当你确认优化模型效果更好后，可以再把输出模型覆盖到系统默认路径。

## 现阶段我为什么没有直接替换原有系统加载逻辑

因为仓库当前诊断主流程已经在使用现有 `diagnosis_model.py` 和默认模型路径，为了避免一次性改太多导致诊断主链路不可用，这次先把“优化版训练/推理链路”独立出来，方便你先做 A/B 对比。

如果你验证新模型效果更好，再把默认模型路径切到新产物即可.
