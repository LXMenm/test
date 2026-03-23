# 文件存储迁移到 MySQL 的迁移完成说明 / 验收记录

## 1. 文档目的

本文档用于记录当前仓库从 JSON / JSONL 到 MySQL 的迁移完成状态、关键设计取舍、验收结果与当前遗留边界。

需要特别说明：
- 本文档描述的是**当前真实实现状态**；
- 当前数据库设计基调是：**工程兼容优先、平滑迁移优先的半规范化设计**；
- 本文档不把当前实现包装为完全高范式数据库；
- `diagnosis_events` / `trace_events` 保留宽表与 `payload_json`，这是阶段性有意设计，不视为缺陷。

---

## 2. 当前已完成的迁移范围

## 2.1 Profile
已完成迁移内容：
- `FarmerProfileORM` 主档案；
- `FarmBaseORM` 基地主表；
- `FarmerProfileEquipmentORM` 设备子表；
- `FarmerProfileBannedIngredientORM` 禁用成分子表；
- `FarmBaseRiskTagORM` 基地风险标签子表；
- `FarmBaseRiskItemORM` 基地风险项子表；
- `repositories/profile_repo_mysql.py` 中对旧 JSON 兼容结构的聚合恢复。

当前特点：
- Profile 组已进入“主表 + 子表 + 兼容 JSON 列”的半规范化状态；
- `profile_store.py` 与 `app.py` 仍继续依赖兼容 payload，因此 repo 层负责恢复旧结构；
- 旧 JSON 列尚未删除，以支持双写、回滚与兼容读取。

## 2.2 Event
已完成迁移内容：
- `DiagnosisEventORM` 宽表持久化；
- event 的写入、查询、过滤与部分聚合已接入 MySQL repo；
- 事件宽表中保留关键结构化字段与 JSON 扩展字段并存。

当前特点：
- `diagnosis_events` 继续保留宽表；
- `payload_json` 继续保留全量兼容事件载荷；
- 当前阶段**不继续推进 diagnosis_events 的进一步拆表**。

## 2.3 Trace
已完成迁移内容：
- `TraceEventORM` 宽表持久化；
- trace 读写与回放支持 MySQL；
- `trace_id + seq` 顺序恢复与查询已接入 repo；
- MySQL trace 时间列已采用毫秒精度处理。

当前特点：
- `trace_events` 继续保留宽表与 `payload_json`；
- 当前阶段**不继续推进 trace_events 的进一步拆表**；
- trace 设计优先服务于链路回放、SSE 观测与调试，而非高度报表化分析。

## 2.4 KB
已完成迁移内容：
- `KBDiseaseORM`
- `KBTreatmentORM`
- `KBRuleORM`
- `KBSymptomMapORM`
- `repositories/kb_repo_mysql.py` 对 4 类 KB payload 的 MySQL 读写；
- treatment actions / ingredients 子表；
- symptom_map aliases / candidate diseases 子表；
- KB 迁移脚本与 parity 校验脚本。

---

## 3. rollout 策略（file / dual / mysql）

当前四类 store 统一支持三种模式：
- `PROFILE_STORE_MODE`
- `EVENT_STORE_MODE`
- `TRACE_STORE_MODE`
- `KB_STORE_MODE`

## 3.1 file
- 完全沿用旧 JSON / JSONL 文件读写；
- 作为最保守兜底和最终回滚路径。

## 3.2 dual
- 保留旧文件读路径或兼容兜底；
- 写入同步到 file + MySQL；
- 适合切换观察期和一致性排查。

## 3.3 mysql
- 读写以 MySQL 为主；
- 但旧文件和迁移脚本仍保留，便于短期回滚。

## 3.4 当前结论
当前 rollout 已完成到：
- **默认值切到 mysql**；
- **保留 dual / file 回滚能力**；
- **保留迁移脚本与旧文件数据作为运维资产**。

---

## 4. 当前默认推荐运行方式

当前推荐默认部署配置为：

```env
DATABASE_URL=mysql+pymysql://root:123456@127.0.0.1:3306/tomato_diagnosis?charset=utf8mb4
PROFILE_STORE_MODE=mysql
EVENT_STORE_MODE=mysql
TRACE_STORE_MODE=mysql
KB_STORE_MODE=mysql
```

应用启动后会打印：

```text
[StorageResolved] DATABASE_URL=... PROFILE_STORE_MODE=... EVENT_STORE_MODE=... TRACE_STORE_MODE=... KB_STORE_MODE=...
```

这条日志用于确认：
- 当前实际数据库连接；
- 四类 store 的真实运行模式；
- 环境变量覆盖是否生效。

---

## 5. 关键设计取舍

## 5.1 当前不是完全规范化数据库
当前设计更适合表述为：
- **半规范化**；
- **工程兼容优先**；
- **面向平滑迁移与可回滚**。

## 5.2 为什么保留 JSON / payload 字段
### Profile / FarmBase
- 用于兼容旧 JSON payload；
- 用于部分字段仍未进一步拆分时的兜底；
- 用于迁移脚本与兼容读取。

### DiagnosisEventORM
- 保留关键筛选列 + 多个 JSON 列 + `payload_json`；
- 目的是兼顾审计、统计、历史兼容与字段演进；
- 当前阶段不继续拆表。

### TraceEventORM
- 保留核心 trace 字段 + `payload_json`；
- 目的是支持 trace replay、SSE、链路排障与跨节点兼容；
- 当前阶段不继续拆表。

## 5.3 当前为什么不继续推进 diagnosis_events / trace_events 拆表
原因包括：
1. 结构变化频繁；
2. payload 差异较大；
3. 当前迁移目标是“先稳定切换、再观察运行”；
4. 进一步拆表会显著扩大代码与迁移风险；
5. 当前收益不如继续完善验证、回滚与观测能力明确。

---

## 6. 关键验证结果

## 6.1 配置与启动验收
- [x] `config.py` 默认 store mode 已切到 `mysql`；
- [x] 启动日志已能输出 `[StorageResolved] ...`；
- [x] 仍可通过环境变量覆盖切回 `dual` / `file`。

## 6.2 Profile / Event / Trace rollout 验收
- [x] Profile / Event / Trace 均已具备 MySQL repo；
- [x] 已存在对应 stage13 rollout 测试，覆盖 `file / dual / mysql` 读路径；
- [x] `_resolve_profile_and_base()`、档案页读取、个性化上下文、诊断链路等关键路径已有回归测试支撑；
- [x] 导入 `app` 时不会因为默认 mysql 而在模块初始化阶段立即强连 KB。

## 6.3 Profile / FarmBase 半规范化验收
- [x] equipment / banned ingredients 已有子表；
- [x] farm base risk tags / risk items 已有子表；
- [x] repo 已支持双写与兼容读取；
- [x] 对应迁移脚本与 idempotent 测试已存在。

## 6.4 Trace 毫秒精度验收
- [x] trace MySQL repo 对 ISO 时间输出保留毫秒；
- [x] trace MySQL 行记录 payload 保留毫秒级时间；
- [x] MySQL trace 时间列已采用毫秒精度变体。

## 6.5 confirm 轮 supervisor 计时修复验收
- [x] 前端 trace timing helper 已做 confirm 轮切片；
- [x] confirm 轮场景下不会把 supervisor 时间跨轮累加；
- [x] 相关回归测试已覆盖该行为。

## 6.6 KB parity 验收
- [x] `scripts/verify/verify_kb_file_mysql_parity.py` 已存在；
- [x] payload parity 与 `KnowledgeBaseManager` parity 均有测试支撑；
- [x] symptom_map / treatments 的规范化子表与迁移脚本已有专项测试。

---

## 7. 当前遗留但不阻塞上线的问题

以下内容属于真实存在但目前**不阻塞 mysql 默认上线**的边界：

1. 部分 repo 仍采用 delete + 全量重写策略，优先保证幂等与兼容；
2. 旧 JSON / JSONL 文件仍需继续保留，用于 dual/file 与短期回滚；
3. `diagnosis_events` / `trace_events` 仍是宽表设计，不继续拆表；
4. 更深入的数据库端聚合与索引优化仍需结合真实运行画像推进；
5. 是否最终下线 file/dual 逻辑，需要在稳定运行窗口结束后再决策。

---

## 8. 当前留档结论

结合当前仓库实现状态，可以给出如下结论：

> 本项目已经完成 JSON / JSONL 到 MySQL 的主体迁移开发，并在 Profile、Event、Trace、KB 四类数据上形成了统一 store 入口、分阶段 rollout、半规范化 schema、专项迁移脚本、parity 校验与短期回滚机制。当前实现已达到“默认 MySQL 运行 + 保留回滚能力 + 文档可留档”的工程目标。

该结论可用于：
- 部署说明；
- 项目留档；
- 论文“系统工程实现 / 数据迁移验收”章节。
