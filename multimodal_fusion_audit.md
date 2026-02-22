# 多模态融合审计笔记

本文件由自动审计生成，用于记录图像+症状融合逻辑、置信度策略与回退路径。

- 图像优先：若有 `image_path`，先调用 `diagnose_from_image`，设置 `final_source=image`。
- 低置信度/低margin：通过 `make_confidence_flags` 设置 `need_confirm` 与 `fallback_reason`。
- 融合回退：当 `need_confirm=true` 且症状存在时，执行 `diagnose_from_symptoms`，并可覆盖 `final_disease`。
- 纯文本路径：无图像或图像失败时，走规则诊断（KB rule + symptom mapping）。
- 关键输出：`final_disease/final_confidence/final_source/image_confidence`。

