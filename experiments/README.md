# Experiments

本目录提供两个离线评测脚本，用于论文中的“规则版 vs BERT 版文本诊断器”和“图文融合方案”对比。

## 1) 文本分支对比

脚本：`experiments/run_text_vs_bert_eval.py`

功能：
- 读取 `data/text_cls/test.csv`
- 逐条调用：
  - `predict_text_proba_rule_based()`
  - `predict_text_proba_bert()`
- 取 top1 作为预测标签
- 输出 accuracy、macro-f1、confusion matrix
- 保存预测明细和混淆矩阵到 CSV

运行示例：

```bash
python experiments/run_text_vs_bert_eval.py \
  --input data/text_cls/test.csv \
  --output outputs/text_eval_results.csv \
  --cm_output outputs/text_eval_confusion_matrix.csv \
  --text_backend both
```

输出文件：
- `outputs/text_eval_results.csv`：逐样本预测明细（含 rule/bert 概率分布）
- `outputs/text_eval_confusion_matrix.csv`：rule 与 bert 的混淆矩阵（按 10 类顺序）

## 2) 图文融合对比

脚本：`experiments/run_multimodal_eval.py`

功能：
- 读取图文联合评测文件（默认 `data/multimodal_eval.csv`）
- 评估三种策略：
  - image only
  - image + rule text fusion
  - image + bert text fusion
- 输出 accuracy、macro-f1
- 保存逐样本预测明细 CSV

运行示例：

```bash
python experiments/run_multimodal_eval.py \
  --input data/multimodal_eval.csv \
  --output outputs/multimodal_eval_results.csv \
  --text_backend both
```

输出文件：
- `outputs/multimodal_eval_results.csv`：三种策略的逐样本预测和概率明细

## 推荐的图文联合数据格式

若仓库暂无统一图文评测数据，建议先使用如下 CSV 字段：

- `image_path`：图像路径（可相对项目根目录）
- `label`：真实病害标签（10 类之一）
- `text`：用户自然语言描述
- `symptoms`：症状关键词（空格分隔，便于规则版使用）
- `growth_stage`：生育期（可选）
- `environment`：环境描述（可选）
- `facility`：设施信息（可选）
- `province`：地区信息（可选）

示例：

```csv
image_path,label,text,symptoms,growth_stage,environment,facility,province
samples/a1.jpg,细菌性斑点病,叶片很多小黑点还有黄边,小黑点 黄边,VEGETATIVE,高湿,露地,山东
samples/a2.jpg,黄化曲叶病毒病,叶片卷曲发黄植株长不高,卷曲 黄化,SEEDLING,高温,温室,海南
```


补充参数：
- `--text_backend both|rule|bert`：用于临时只跑规则版或只跑 BERT 版，默认 `both`。
