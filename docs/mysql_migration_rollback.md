# MySQL 迁移回滚说明

## 1. 文档目的

本文档用于说明：在当前默认运行形态切到 MySQL 后，何时应触发回滚、如何回滚到 `dual` 或 `file`、以及回滚后应完成哪些验证。

本文档强调：
1. 当前仓库仍保留 `file / dual / mysql` 三模式；
2. 旧 JSON / JSONL 文件与迁移脚本仍保留；
3. 回滚是**运行配置切换**，不是代码回退；
4. 回滚后必须验证主链路与关键接口，而不是只确认服务能启动。

---

## 2. 何时触发回滚

建议满足以下任一条件时，启动回滚评估。

## 2.1 Profile 相关触发条件
- `/api/profiles`、`/api/profiles/{farmer_id}`、`/api/profiles/base-ids` 明显异常；
- 个性化档案新增/编辑后无法读取；
- `_resolve_profile_and_base()` 失败，导致个性化上下文缺失；
- 基地信息、风险标签或禁用约束恢复异常，影响诊断链路。

## 2.2 Event 相关触发条件
- `/api/events`、`/api/stats/disease`、`/api/stats/timeseries` 明显异常；
- 新诊断事件写入成功率下降；
- 事件统计与已知业务事实明显不符。

## 2.3 Trace 相关触发条件
- `/api/traces/{trace_id}` 或 trace stream 无法返回完整链路；
- trace 顺序异常、事件缺失、时间精度异常；
- confirm 轮或等待补充场景的 trace 观测出现明显异常。

## 2.4 KB 相关触发条件
- KB 管理接口新增/编辑后数据无法读取；
- `normalize_symptoms`、`rule_diagnosis`、`get_treatment_plan` 结果出现明显偏差；
- KB parity 校验失败；
- MySQL 与 `data/kb/*.json` 行为不一致。

## 2.5 基础设施触发条件
- MySQL 实例连接不稳定、频繁超时；
- 数据库只读、权限异常、锁等待严重；
- 目标表缺失、字符集错误、索引缺失影响主链路；
- 迁移后发现环境准备不完整，短期内无法修复。

---

## 3. 回滚原则

1. **优先回滚到 `dual`**，先恢复文件读稳定性；
2. **仅当 MySQL 写入也不可信时再回滚到 `file`**；
3. **回滚时不删除数据库数据，也不删除旧文件**；
4. **保留迁移脚本与 parity 校验脚本**，便于后续重新切回 mysql；
5. **回滚后必须执行验证清单**。

---

## 4. dual 回滚方式

## 4.1 适用场景
- MySQL 写入总体可接受，但读取结果不稳定；
- 需要快速恢复文件读为准的行为；
- 希望继续双写 MySQL，为后续问题定位保留现场。

## 4.2 配置方式

整体回滚到 `dual`：

```env
PROFILE_STORE_MODE=dual
EVENT_STORE_MODE=dual
TRACE_STORE_MODE=dual
KB_STORE_MODE=dual
```

也可以按层局部回滚，例如仅 KB：

```env
KB_STORE_MODE=dual
```

## 4.3 dual 回滚后的语义
- **Profile**：优先使用文件读路径，写入 file + MySQL；
- **Event**：读文件，写 file + MySQL；
- **Trace**：读文件，写 file + MySQL；
- **KB**：读文件，写 file + MySQL。

## 4.4 建议顺序
1. 先局部回滚单层；
2. 若影响面扩大，再整体切 `dual`；
3. 待问题定位清楚后，再评估是否切回 `mysql`。

---

## 5. file 回滚方式

## 5.1 适用场景
- MySQL 读写都不稳定；
- 数据库实例不可用，短时间内无法恢复；
- 需要完全依赖旧文件链路保障演示、答辩或临时运行。

## 5.2 配置方式

整体回滚到 `file`：

```env
PROFILE_STORE_MODE=file
EVENT_STORE_MODE=file
TRACE_STORE_MODE=file
KB_STORE_MODE=file
```

也可以按层局部回退，例如：

```env
EVENT_STORE_MODE=file
TRACE_STORE_MODE=file
```

## 5.3 file 回滚后的影响
- 旧 JSON / JSONL 文件重新成为唯一权威读写路径；
- 新写入默认不再自动同步到 MySQL；
- 需要重新切回 mysql 时，应先考虑增量补导与校验。

---

## 6. 回滚后验证清单

## 6.1 启动日志验证
- 确认启动日志中的 `[StorageResolved] ...` 已反映目标模式；
- 若日志仍显示 `mysql`，说明环境变量未生效。

## 6.2 Profile 验证
- `GET /api/profiles`
- `GET /api/profiles/{farmer_id}`
- `GET /api/profiles/base-ids`
- 新建 / 编辑 / 删除 profile
- 带 `farmer_id/base_id` 的个性化诊断

## 6.3 Event 验证
- `GET /api/events`
- `GET /api/stats/disease`
- `GET /api/stats/timeseries`
- 至少发起一次新的诊断请求，确认事件写入正常

## 6.4 Trace 验证
- `GET /api/traces/{trace_id}`
- `GET /api/traces/{trace_id}/stream`
- 检查 trace 事件顺序、毫秒时间精度、结束节点是否完整
- 检查 confirm 轮与等待补充场景的 trace 表现是否正常

## 6.5 KB 验证
- `GET /api/kb/diseases`
- `GET /api/kb/treatments`
- `GET /api/kb/rules`
- `GET /api/kb/symptom-map`
- 关键能力：
  - `normalize_symptoms`
  - `get_candidate_diseases_from_symptoms`
  - `rule_diagnosis`
  - `get_treatment_plan`

## 6.6 主诊断链路验证
至少验证以下场景：
1. 文本症状诊断；
2. 图像 + 文本联合诊断；
3. 带 `farmer_id/base_id` 的个性化诊断；
4. 低置信度追问；
5. confirm 轮补充诊断；
6. 最终治疗方案输出链路。

---

## 7. 当前仍保留的旧 JSON / JSONL 与脚本说明

## 7.1 仍保留的旧文件
- `data/profiles/*.json`
- `diagnosis_events.jsonl`
- `.cache/events/diagnosis_events.jsonl`
- `trace_events.jsonl`
- `.cache/events/trace_events.jsonl`
- `data/kb/*.json`

保留原因：
- 支撑 `file` / `dual` 模式；
- 短期回滚依据；
- 历史对账依据；
- KB parity 基准。

## 7.2 仍保留的迁移 / 校验脚本
- `scripts/migrations/migrate_json_to_mysql.py`
- `scripts/migrations/migrate_kb_json_to_mysql.py`
- `scripts/migrations/migrate_profile_normalized.py`
- `scripts/migrations/migrate_farm_bases_normalized.py`
- `scripts/migrations/migrate_kb_symptom_map_normalized.py`
- `scripts/migrations/migrate_kb_treatments_normalized.py`
- `scripts/verify/verify_kb_file_mysql_parity.py`

说明：
- 这些脚本当前应视为运维资产，而不是一次性脚本；
- 在回滚窗口结束前，不建议删除。

---

## 8. 为什么当前仍具备安全回滚能力

1. 四类 store 都保留 `file / dual / mysql` 三模式；
2. 旧 JSON / JSONL 文件逻辑仍保留；
3. 统一 store 入口已把切换点集中；
4. 迁移脚本与 parity 校验脚本仍可用于补导和复核；
5. 当前回滚主要是**配置切换**，而不是大规模代码回退。

因此，当前系统仍具备**短期、低成本、低风险**的运行态回滚能力。
