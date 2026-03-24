# 诊断阈值离线调优工具

## 概述

本工具用于在不重新训练图像/文本模型的前提下，复用现有诊断规则，对一批样本做离线回放、阈值搜索和指标评估。

## 核心特性

- ✅ **线上/离线逻辑一致**：通过抽取纯函数 `evaluate_confirmation_decision()` 确保线上和离线使用相同的确认决策逻辑
- ✅ **批量阈值搜索**：支持网格搜索，自动评估所有阈值组合
- ✅ **多维度指标评估**：包括整体准确率、自动完成精度、确认率、分桶准确率等
- ✅ **最小侵入性**：不修改数据库结构，不影响现有在线 API 行为

## 文件结构

```
test/
├── diagnosis_model.py              # 核心诊断模型（新增 evaluate_confirmation_decision 纯函数）
├── agents.py                       # 智能体逻辑（使用新的纯函数）
├── configs/
│   └── threshold_grid.yaml         # 阈值网格配置
├── scripts/
│   ├── tune_thresholds.py          # 离线调优主脚本
│   └── sample_eval_data.jsonl      # 示例评估数据（5 条）
├── tests/
│   └── test_threshold_tuning.py    # 单元测试
└── results/
    └── threshold_search.csv        # 输出结果（运行后生成）
```

## 快速开始

### 1. 运行单元测试

```bash
python tests/test_threshold_tuning.py
```

**预期输出**：
```
================================================================================
诊断阈值离线调优功能单元测试
================================================================================

✓ test_conflict_sample_should_need_confirm 通过
✓ test_image_strong_text_weak_high_confidence_should_clear 通过
✓ test_both_weak_sample_should_need_confirm 通过
✓ test_low_confidence_should_need_confirm 通过
✓ test_low_margin_should_need_confirm 通过
✓ test_high_confidence_consistent_should_clear 通过
✓ test_weak_conflict_flag 通过
✓ test_image_weak_text_strong_high_confidence 通过

================================================================================
所有测试通过！✓
================================================================================
```

### 2. 运行阈值搜索

```bash
python scripts/tune_thresholds.py \
  --data scripts/sample_eval_data.jsonl \
  --grid configs/threshold_grid.yaml \
  --output results/threshold_search.csv \
  --topk 20
```

**命令行参数**：
- `--data`：JSONL 格式的评估数据路径（必需）
- `--grid`：YAML 格式的阈值网格配置路径（必需）
- `--output`：CSV 输出路径（必需）
- `--topk`：显示前 K 个最佳配置（可选，默认：20）

### 3. 查看结果

结果将保存至 `results/threshold_search.csv`，包含以下列：

| 列名 | 说明 |
|------|------|
| version | 配置版本号 |
| overall_accuracy | 整体准确率 |
| auto_complete_precision | 自动完成精度（need_confirm 预测准确率） |
| confirm_rate | 确认率 |
| conflict_bucket_accuracy | conflict 桶的准确率 |
| consistent_bucket_accuracy | consistent 桶的准确率 |
| image_strong_text_weak_bucket_accuracy | image_strong_text_weak 桶的准确率 |
| image_weak_text_strong_bucket_accuracy | image_weak_text_strong 桶的准确率 |
| both_weak_bucket_accuracy | both_weak 桶的准确率 |
| 各种 threshold 列 | 对应的阈值参数值 |

## 配置说明

### threshold_grid.yaml

```yaml
# 搜索策略：grid | random
search_strategy: grid

# 随机搜索次数（仅在 random 策略下使用）
random_search_iterations: 50

# 阈值网格配置
grid:
  image_top1_threshold: [0.60, 0.65, 0.70, 0.75, 0.80]
  image_margin_threshold: [0.10, 0.15, 0.20, 0.25]
  text_top1_threshold: [0.40, 0.45, 0.50, 0.55]
  text_margin_threshold: [0.08, 0.10, 0.12, 0.15]
  weak_conflict_min_image_top1: [0.45, 0.50, 0.55, 0.60]
  weak_conflict_min_text_top1: [0.35, 0.40, 0.45, 0.50]
  diagnosis_conf_threshold: [0.50, 0.55, 0.60, 0.65]
  low_margin_threshold: [0.03, 0.05, 0.08, 0.10]

# 默认配置（用于单条评估）
default:
  image_top1_threshold: 0.70
  image_margin_threshold: 0.15
  text_top1_threshold: 0.45
  text_margin_threshold: 0.10
  weak_conflict_min_image_top1: 0.50
  weak_conflict_min_text_top1: 0.40
  diagnosis_conf_threshold: 0.60
  low_margin_threshold: 0.05
```

### sample_eval_data.jsonl

每行一个样本，格式如下：

```json
{
  "sample_id": "sample_001",
  "ground_truth": "早疫病",
  "image_probs": {"早疫病": 0.78, "细菌性斑点病": 0.11, "晚疫病": 0.07},
  "text_probs": {"细菌性斑点病": 0.48, "叶斑病": 0.13, "晚疫病": 0.11},
  "prior_probs": {},
  "round_type": "initial",
  "symptom_count": 2,
  "expected_need_confirm": true,
  "expected_fusion_case": "conflict"
}
```

**必填字段**：
- `sample_id`：样本唯一标识
- `ground_truth`：真实标签
- `image_probs`：图像模型概率分布
- `text_probs`：文本模型概率分布

**可选字段**：
- `prior_probs`：先验概率分布
- `round_type`：轮次类型（initial/supplement）
- `symptom_count`：症状数量
- `expected_need_confirm`：期望的 need_confirm 值（用于评估）
- `expected_fusion_case`：期望的 fusion_case（用于验证）

## 核心 API

### evaluate_confirmation_decision()

```python
from diagnosis_model import evaluate_confirmation_decision

result = evaluate_confirmation_decision(
    fusion_top3=[("早疫病", 0.75), ("晚疫病": 0.15)],
    fusion_meta={
        "fusion_case": "consistent",
        "image_reliable": True,
        "text_reliable": True,
        "modality_conflict_flag": False,
        "weak_conflict_candidate": False,
        "supplement_mode": "none",
    },
    image_top3=[("早疫病", 0.78)],
    text_top3=[("早疫病", 0.72)],
    final_confidence=0.75,
    diagnosis_conf_threshold=0.60,
    low_margin_threshold=0.05,
    need_confirm_threshold=0.60,
)

# 返回：
# {
#     "need_confirm": False,
#     "reasons": [],
#     "weak_conflict_flag": False,
#     "modality_conflict_flag": False,
#     "fusion_case": "consistent",
#     "image_reliable": True,
#     "text_reliable": True,
#     "supplement_mode": "none",
#     "should_clear_confirm": True,
# }
```

## 评估指标说明

### 整体指标

- **overall_accuracy**：诊断正确的样本比例
- **auto_complete_precision**：need_confirm 预测的准确率
- **confirm_rate**：需要确认的样本比例
- **false_clear_rate**：错误清除确认的比例（暂未实现）

### 分桶指标

根据 `fusion_case` 分桶统计准确率：

- **conflict_bucket_accuracy**：图文冲突场景的准确率
- **consistent_bucket_accuracy**：图文一致场景的准确率
- **image_strong_text_weak_bucket_accuracy**：图强文弱场景的准确率
- **image_weak_text_strong_bucket_accuracy**：图弱文强场景的准确率
- **both_weak_bucket_accuracy**：双弱场景的准确率

## 实现细节

### 纯函数设计

`evaluate_confirmation_decision()` 是一个纯函数，具有以下特点：

1. **无副作用**：不修改任何外部状态
2. **确定性**：相同输入总是产生相同输出
3. **可测试**：易于编写单元测试
4. **可复用**：线上/离线共用同一逻辑

### 确认决策逻辑

```python
if fusion_case == "conflict":
    need_confirm = True
elif weak_conflict_flag:
    need_confirm = True
elif fusion_case == "both_weak":
    need_confirm = True
elif fusion_case in {"image_strong_text_weak", "image_weak_text_strong", "consistent", "image_only", "text_only"}:
    if final_confidence < diagnosis_conf_threshold:
        need_confirm = True
        reasons.append("low_confidence")
    if margin < low_margin_threshold:
        need_confirm = True
        reasons.append("low_margin")
```

## 扩展建议

### 未来可以增强的功能

1. **随机搜索模式**：支持 `search_strategy: random`，在大规模网格时更高效
2. **贝叶斯优化**：使用贝叶斯优化替代网格搜索
3. **多目标优化**：同时优化准确率和确认率
4. **可视化**：生成阈值 - 指标曲线图
5. **交叉验证**：支持 K 折交叉验证

### 自定义评估指标

在 `compute_metrics()` 函数中添加新的评估指标：

```python
def compute_metrics(results: List[Dict[str, Any]]) -> Dict[str, float]:
    # ... 现有代码 ...
    
    # 新增指标
    new_metric = compute_your_metric(results)
    
    return {
        # ... 现有指标 ...
        "new_metric": new_metric,
    }
```

## 常见问题

### Q: 为什么需要离线调优？

A: 阈值参数对诊断系统的行为影响很大，但不需要重新训练模型。通过离线调优，可以快速找到最优阈值组合，提升系统性能。

### Q: 如何准备自己的评估数据？

A: 参考 `scripts/sample_eval_data.jsonl` 格式，准备 JSONL 文件。每条样本至少包含 `sample_id`、`ground_truth`、`image_probs`、`text_probs`。

### Q: 网格搜索太慢怎么办？

A: 可以：
1. 减少每个阈值的候选值数量
2. 使用随机搜索模式（待实现）
3. 只搜索关键阈值（如 `diagnosis_conf_threshold`）

### Q: 如何验证线上/离线逻辑一致性？

A: 运行 `tests/test_threshold_tuning.py`，所有测试通过即表示逻辑一致。

## 版本历史

- **v1.0**（2026-03-24）：初始版本
  - 实现 `evaluate_confirmation_decision()` 纯函数
  - 实现离线调优脚本
  - 实现单元测试
  - 支持网格搜索

## 联系方式

如有问题或建议，请提交 Issue 或 Pull Request。
