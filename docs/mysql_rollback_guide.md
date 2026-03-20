# MySQL 迁移后的短期回滚指南

## 1. 文档目的

本文档用于说明系统在默认运行形态切到 MySQL 持久化后，如何在**短期窗口内**安全回滚到 `dual` 或 `file` 模式。

适用范围：
- `PROFILE_STORE_MODE`
- `EVENT_STORE_MODE`
- `TRACE_STORE_MODE`
- `KB_STORE_MODE`

本文档强调：
1. 当前仓库仍保留 `file / dual / mysql` 三模式支持；
2. 旧 JSON / JSONL 文件逻辑仍保留，具备短期回滚基础；
3. 已有迁移脚本与 KB parity 校验脚本需要继续保留，不能删除；
4. 回滚是**运行配置切换**，不是代码回退。

---

## 2. 当前默认运行形态

当前推荐默认部署方式为：

```env
PROFILE_STORE_MODE=mysql
EVENT_STORE_MODE=mysql
TRACE_STORE_MODE=mysql
KB_STORE_MODE=mysql
```

应用启动后会输出：

```text
[StorageResolved] DATABASE_URL=... PROFILE_STORE_MODE=... EVENT_STORE_MODE=... TRACE_STORE_MODE=... KB_STORE_MODE=...
```

回滚时应首先确认该日志，避免误判当前实际运行模式。

---

## 3. 回滚触发条件

建议满足以下任一条件时，启动短期回滚评估：

### 3.1 Profile 层
- `/api/profiles`、`/api/profiles/{farmer_id}`、`/api/profiles/base-ids` 返回异常或数据缺失；
- 农户档案新增/编辑后无法读取；
- 活跃基地解析失败，导致个性化上下文缺失。

### 3.2 Event 层
- `/api/events`、`/api/stats/disease`、`/api/stats/timeseries` 等统计接口明显异常；
- 新诊断事件写入成功率下降；
- 事件查询结果与已知业务事实明显不符。

### 3.3 Trace 层
- `/api/traces/{trace_id}` 或 trace stream 无法返回完整链路；
- 新 trace 事件无法追加，或序号连续性异常；
- 诊断链路在观测上出现“无 trace / trace 不全”。

### 3.4 KB 层
- KB 管理接口新增/编辑后数据无法读取；
- `normalize_symptoms`、`rule_diagnosis`、`get_treatment_plan` 等核心结果出现明显偏差；
- KB parity 校验失败；
- MySQL 中的 KB payload 与 `data/kb/*.json` 不一致。

### 3.5 基础设施层
- MySQL 实例连接不稳定、频繁超时；
- 数据库只读、锁等待、DDL/DML 异常影响主链路；
- 部署后发现数据库权限、字符集、索引或表结构未准备好。

---

## 4. 回滚原则

1. **优先回滚到 `dual`，而不是立即回到 `file`。**
   - `dual` 仍保留文件读路径，可以快速规避 MySQL 读问题；
   - 同时继续向 MySQL 双写，便于问题定位后再恢复切读。
2. **仅当 MySQL 写入也不可信时，再回滚到 `file`。**
   - `file` 模式是更保守的兜底方案；
   - 但回到 `file` 后，新的写入默认不再同步到 MySQL。
3. **回滚仅切配置，不删除旧文件，也不删除数据库数据。**
4. **回滚后必须做接口与链路验证，不能只看启动成功。**

---

## 5. 回滚方式 A：回滚到 dual

### 5.1 适用场景
- MySQL 写入大体正常，但读取结果异常；
- 需要快速恢复“文件读为准”的稳定行为；
- 希望保留 MySQL 双写，继续收集问题现场。

### 5.2 配置方式

将部署环境变量调整为：

```env
PROFILE_STORE_MODE=dual
EVENT_STORE_MODE=dual
TRACE_STORE_MODE=dual
KB_STORE_MODE=dual
```

如果只怀疑某一层，可按层局部回滚，例如仅 KB：

```env
KB_STORE_MODE=dual
```

### 5.3 dual 回滚后的读写语义
- **Profile**：优先读文件，必要时可回退查 MySQL；写入 file + MySQL。 
- **Event**：读文件，写 file + MySQL。 
- **Trace**：读文件，写 file + MySQL。 
- **KB**：读文件，写 file + MySQL。 

### 5.4 适用优先级
推荐优先顺序：
1. 先局部回滚单层；
2. 若影响面扩大，再整体回滚到 `dual`；
3. 继续观察并定位具体异常点。

---

## 6. 回滚方式 B：回滚到 file

### 6.1 适用场景
- MySQL 读写都不稳定；
- 数据库实例不可用，短时间内无法恢复；
- 需要完全依赖旧文件链路保证演示/答辩/临时运行。

### 6.2 配置方式

将部署环境变量调整为：

```env
PROFILE_STORE_MODE=file
EVENT_STORE_MODE=file
TRACE_STORE_MODE=file
KB_STORE_MODE=file
```

也可以按层回退，例如：

```env
EVENT_STORE_MODE=file
TRACE_STORE_MODE=file
```

### 6.3 file 回滚后的影响
- 系统重新以旧 JSON / JSONL 文件作为唯一权威读写路径；
- 运行时写入不会自动补到 MySQL；
- 回滚窗口结束后，如需重新切回 mysql，需要重新评估增量数据同步方式。

---

## 7. 回滚后必须验证的接口与链路

> 建议按“接口层 → 主链路 → 数据对账”三步走。

### 7.1 启动日志确认
- 确认启动日志中 `[StorageResolved] ...` 已反映目标回滚模式；
- 若日志仍显示 `mysql`，说明环境变量未生效。

### 7.2 Profile 相关接口
- `GET /api/profiles`
- `GET /api/profiles/{farmer_id}`
- `GET /api/profiles/base-ids`
- 新建/编辑/删除 profile 的完整链路

### 7.3 Event 相关接口
- `GET /api/events`
- `GET /api/stats/disease`
- `GET /api/stats/timeseries`
- 至少发起一次新的诊断请求，确认事件写入正常

### 7.4 Trace 相关接口
- `GET /api/traces/{trace_id}`
- `GET /api/traces/{trace_id}/stream`
- 检查 trace 事件顺序、节点数、结束节点是否完整

### 7.5 KB 相关接口与能力
- `GET /api/kb/diseases`
- `GET /api/kb/treatments`
- `GET /api/kb/rules`
- `GET /api/kb/symptom-map`
- 至少验证以下能力：
  - `normalize_symptoms`
  - `get_candidate_diseases_from_symptoms`
  - `rule_diagnosis`
  - `get_treatment_plan`

### 7.6 主诊断链路
建议最少验证以下场景：
1. 文本症状诊断（无图）；
2. 图像 + 文本联合诊断；
3. 带 `farmer_id/base_id` 的个性化诊断；
4. 低置信度追问场景；
5. 最终治疗方案输出链路。

---

## 8. 与迁移/校验脚本的关系

回滚方案依赖以下脚本继续保留：

### 8.1 Profile / Event / Trace 迁移脚本
```bash
python scripts/migrate_json_to_mysql.py
```
用途：
- 在重新切回 mysql 前，补导旧文件数据；
- 复盘文件侧是否仍保留完整历史。

### 8.2 KB 迁移脚本
```bash
python scripts/migrate_kb_json_to_mysql.py
```
用途：
- 在 KB 从 file/dual 重新切回 mysql-only 之前，重新同步 `data/kb/*.json`。

### 8.3 KB parity 校验脚本
```bash
python scripts/verify_kb_file_mysql_parity.py --reset-schema
```
用途：
- 验证 KB file 与 mysql 的 payload 及关键行为是否一致；
- 是 KB 层恢复 mysql-only 前的推荐验收动作。

---

## 9. 建议的回滚决策流程

### 9.1 轻度异常
- 单层局部异常；
- 业务可继续；
- 建议：**单层切 `dual`**，保留更多排障信息。

### 9.2 中度异常
- 多层读取不稳定；
- 但 MySQL 写入仍可接受；
- 建议：**整体切 `dual`**，恢复文件读稳定性。

### 9.3 重度异常
- MySQL 实例不可用或写入失败；
- 主链路已受影响；
- 建议：**整体切 `file`**，先恢复业务，再单独处理数据库问题。

---

## 10. 为什么当前仍具备安全回滚能力

1. 仓库未删除 `file / dual / mysql` 三模式；
2. Profile / Event / Trace / KB 的旧文件逻辑仍保留；
3. 当前默认值虽然是 mysql，但可通过环境变量即时切回；
4. 已有迁移脚本和 parity 校验脚本可用于重新同步与复核；
5. 各层读写入口已经统一到 store 层，回滚主要是**配置切换**，不是大规模代码回退。

因此，当前系统仍具备**短期、低成本、低风险**的运行态回滚能力。
