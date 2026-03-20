# MySQL 迁移完成后的清理与性能优化计划

## 1. 文档目标

本文档用于盘点 MySQL 迁移完成后，哪些旧逻辑**暂时不能删除**，哪些内容可在后续逐步清理，以及 Event / Trace / KB 三层可以进入 backlog 的性能优化项。

注意：
- 本文档只做盘点与规划；
- 本轮**不删除旧逻辑**；
- 本轮**不做性能重构**；
- 内容基于当前仓库的真实实现状态，而不是理想化架构。

---

## 2. 当前不建议立刻删除的内容

## 2.1 file / dual / mysql 三模式支持
原因：
- 这是当前短期回滚能力的核心；
- 默认值虽然已切到 mysql，但仍需要 `dual` 和 `file` 作为排障与回滚手段；
- 在经过一个稳定运行窗口前，不应移除。

涉及层：
- `personalization/profile_store.py`
- `event_store.py`
- `trace_store.py`
- `knowledge_base/kb_store.py`

### 2.2 旧 JSON / JSONL 文件
不建议立刻删除：
- `data/profiles/*.json`
- `diagnosis_events.jsonl` / `.cache/events/diagnosis_events.jsonl` / 兼容位置的历史文件
- `trace_events.jsonl` / `.cache/events/trace_events.jsonl` / 兼容位置的历史文件
- `data/kb/*.json`

原因：
- 它们是 `file` / `dual` 模式的真实数据基础；
- 同时也是短期回滚和历史对账依据；
- KB parity 验证仍依赖 `data/kb/*.json` 作为 file 基准。

### 2.3 迁移与校验脚本
不建议删除：
- `scripts/migrate_json_to_mysql.py`
- `scripts/migrate_kb_json_to_mysql.py`
- `scripts/verify_kb_file_mysql_parity.py`

原因：
- 它们是迁移补导、回滚后再切读、以及验收复核的重要工具；
- 在完成一个较长稳定运行周期前，应视为运维资产而非一次性脚本。

---

## 3. 后续可以逐步清理的旧逻辑

## 3.1 Profile 层
未来可逐步清理：
- 部分仅为文件枚举服务的辅助方法；
- 仅为 JSON 兼容保留的目录扫描逻辑。

前提条件：
1. `PROFILE_STORE_MODE=mysql` 连续稳定运行；
2. profile 回滚窗口结束；
3. 所有部署环境不再依赖 `data/profiles/*.json` 作为权威数据源。

### 3.2 Event 层
未来可逐步清理：
- 读取 JSONL 的聚合统计逻辑；
- 基于文件的 timeseries / geo_points / model_usage 计算代码；
- 旧事件文件兼容位置的查找逻辑。

前提条件：
1. event 的 mysql 查询与统计结果稳定；
2. 已确认不再需要从 JSONL 回放历史数据；
3. 已具备数据库侧数据备份与恢复能力。

### 3.3 Trace 层
未来可逐步清理：
- 文件 trace 的事件顺序恢复逻辑；
- `.cache/events/trace_events.jsonl` 的兼容写入逻辑；
- 仅服务于 file/dual 模式的 seq 恢复路径。

前提条件：
1. trace mysql 路径在真实使用中稳定；
2. SSE / trace replay 已验证无回归；
3. 需要时可直接从数据库恢复链路。

### 3.4 KB 层
未来可逐步清理：
- `data/kb/*.json` 作为线上权威读源的角色；
- `kb_store.py` 中 dual/file 的文件写路径；
- 某些仅服务于旧 payload 兼容的冗余适配。

前提条件：
1. `KB_STORE_MODE=mysql` 长期稳定；
2. KB 管理操作都已在 mysql-only 模式下验证通过；
3. `verify_kb_file_mysql_parity.py` 在最终一轮校验后不再发现差异；
4. 已明确是否保留 JSON 作为离线导出备份格式。

---

## 4. Event / Trace / KB 三层的性能优化候选项

## 4.1 Event 层优化候选

### 候选 A：数据库端聚合替换 Python 侧全量遍历
当前现状：
- file 模式下很多统计依赖读取 JSONL 后在 Python 中聚合；
- mysql 模式下已接入 repo，但仍应持续审视是否全部走数据库端过滤与聚合。

优化目标：
- `stats_by_disease`
- `timeseries`
- `geo_points`
- `model_usage_range`

预期收益：
- 减少内存占用；
- 降低大时间窗口统计的延迟；
- 让统计接口更适合长期运行。

### 候选 B：补充必要索引与查询画像
优化方向：
- 结合真实查询频次复核 disease/time、trace/time、farmer/time 等索引是否足够；
- 记录慢查询样本再做定向优化。

---

## 4.2 Trace 层优化候选

### 候选 A：减少 seq 计算中的额外读取
当前现状：
- 为兼容 file/dual/mysql，不同模式下会做不同的 seq 恢复与最大序号判断。

优化方向：
- mysql-only 稳定后，可将 seq 计算进一步收敛到数据库侧；
- 减少 dual 兼容逻辑带来的额外读取判断。

### 候选 B：trace stream 与历史回放分离优化
优化方向：
- 区分“实时流式写入场景”和“历史查询场景”；
- 针对 trace replay 设计更直接的分页或顺序读取方案。

---

## 4.3 KB 层优化候选

### 候选 A：从全量覆盖写入改为增量 upsert
当前现状：
- `repositories/kb_repo_mysql.py` 以 payload 等价优先，采用 delete + 全量重写策略。

优化方向：
- diseases / treatments / rules / symptom_map 按实体或键粒度做 upsert；
- 仅在必要时更新变更项，而不是重写整表。

预期收益：
- 降低写放大；
- 降低后台管理操作对数据库的瞬时压力；
- 更适合后续 KB 管理功能扩展。

### 候选 B：减少 payload 兼容冗余
当前现状：
- 为保证与 JSON payload 等价，repo 中保留了较多 `meta_json` 回填逻辑。

优化方向：
- 在 mysql-only 完全稳定后，重新评估哪些字段可改为更明确的数据结构；
- 但这属于后续迭代，不建议在回滚窗口内推进。

---

## 5. 建议的执行时机与前置条件

## 5.1 第一阶段：稳定运行观察期
建议时机：
- 默认 mysql 部署上线后，先经过一个稳定观察窗口。

前置条件：
- 关键接口无明显异常；
- 回滚演练路径明确；
- 日志与监控能判断当前运行模式和错误来源。

本阶段只做：
- 观测；
- 数据对账；
- 问题清单整理；
- 不做大规模删改。

### 5.2 第二阶段：局部清理与 SQL 优化
建议时机：
- 已确认某一层几乎不会再回滚到 file；
- 对该层已有足够真实运行数据。

可做事项：
- 局部清理某一层的旧文件聚合逻辑；
- 补索引、优化查询；
- 在不改变对外行为的前提下做小步重构。

### 5.3 第三阶段：结束回滚窗口后的结构收敛
建议时机：
- 明确不再需要 file/dual 作为短期运行态回滚工具；
- 已形成数据库备份、恢复、监控和演练闭环。

可做事项：
- 评估是否下线部分旧文件逻辑；
- 评估是否将某些 payload 结构进一步数据库化；
- 评估是否把迁移脚本从“常用工具”转为“归档工具”。

---

## 6. 风险说明

### 风险 1：过早删除 file/dual 逻辑会丢失短期回滚能力
说明：
- 当前默认 mysql 虽已稳定，但仍处于刚完成迁移的阶段；
- 一旦删除 file/dual 逻辑，再出现数据库层异常时，恢复成本会显著上升。

### 风险 2：在没有真实运行画像时做性能优化，容易偏离瓶颈
说明：
- 当前可以列出优化候选，但不应假设所有瓶颈都已明确；
- 应先基于真实接口访问模式、慢查询、数据量级来排序优化优先级。

### 风险 3：过早做数据库深度规范化会增加不必要变更面
说明：
- 当前迁移目标是“平滑切换并可回滚”；
- 大规模 schema 重构应放在回滚窗口结束后再评估。

---

## 7. 建议的后续执行结论

结合当前仓库状态，建议采用以下策略：

1. **短期内保留全部 file / dual / mysql 三模式与旧文件数据**；
2. **优先保留迁移脚本、KB parity 校验脚本和旧文件样本**；
3. **先做运行观察，再做局部性能优化，最后再考虑清理旧逻辑**；
4. **Event / Trace / KB 三层的优化优先级高于大规模代码清理**；
5. **真正删除旧逻辑前，应先确认回滚窗口结束并完成一次正式回滚演练复盘**。

这份计划适合继续作为后续开发 backlog、运维协作清单，以及毕业设计中的“迁移后运维与演进计划”材料。
