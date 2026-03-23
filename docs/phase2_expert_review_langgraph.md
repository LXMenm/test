# Phase2 设计说明：将专家复核并回同一 LangGraph（本次不实现）

> 本文仅作为后续扩展说明，不包含本次代码落地。

## 目标

将当前“专家复核后直接写病例快照结束”的模式，演进为“图内暂停-回填-恢复执行”模式：

1. `manual_review` 节点不再直接 `END`；
2. 当进入专家复核时，图进入暂停态（持久化 `trace_id` + state 快照）；
3. 专家提交后，将 `expert_review_result / expert_review_notes` 回填到 state；
4. 从恢复点继续执行 `kb_retrieval -> treatment -> verification`；
5. 最终再写终态病例事件，保证单一业务闭环。

## 建议状态流

- `pending_expert_review`：等待专家处理（图暂停）
- `completed`：专家回填后恢复执行并完成
- `cancelled`：管理员关闭，图终止不再恢复

## 兼容建议

- 保持现有 `event_store` 病例快照事件结构，新增恢复标志字段即可；
- 继续保留当前管理端“任务状态 + 管理标签”分离语义；
- 对外接口优先保持兼容，只新增可选字段。
