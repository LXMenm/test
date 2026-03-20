# 文件存储迁移到 MySQL 的迁移完成说明 / 验收记录

## 1. 迁移背景与目标

本项目为基于 FastAPI + LangGraph 的番茄病害诊治系统。随着个性化档案、事件统计、trace 追踪、KB 管理能力逐步完善，原有 JSON / JSONL 文件存储在以下方面存在局限：

- 多类数据分散在不同文件中，部署一致性与运维性较弱；
- 事件与 trace 的查询、统计、回溯能力受限；
- KB 在多来源读写场景下需要更稳定的持久化后端；
- 默认部署形态希望统一到 MySQL，以便后续答辩展示、运维管理和功能扩展。

本次迁移的核心目标不是重写业务，而是：
1. 在尽量不改变主链路行为的前提下，引入 MySQL 持久化；
2. 通过 `file / dual / mysql` 三模式 rollout 降低切换风险；
3. 为 Profile / Event / Trace / KB 提供可迁移、可回滚、可验证的统一持久化方案；
4. 将当前推荐默认部署方式固化为 MySQL。

---

## 2. 迁移范围（Profile / Event / Trace / KB）

### 2.1 Profile
- 农户档案（FarmerProfile）
- 基地信息（FarmBase）
- 相关 base_id 映射

### 2.2 Event
- 诊断事件主记录
- 事件查询、聚合统计、地理点位、模型使用情况等接口依赖的数据

### 2.3 Trace
- 多智能体执行过程 trace 事件
- trace 列表、按 trace_id 回放、SSE stream 依赖的数据

### 2.4 KB
- `diseases.json`
- `treatments.json`
- `rules.json`
- `symptom_map.json`

---

## 3. 已完成的代码改造

### 3.1 Profile / Event / Trace 三层
已完成统一 store 入口和 MySQL 仓储：
- Profile：支持 `file / dual / mysql`
- Event：支持 `file / dual / mysql`
- Trace：支持 `file / dual / mysql`

实现效果：
- `mysql`：读写均走 MySQL；
- `dual`：保留旧文件读路径，同时把写入同步到 MySQL；
- `file`：继续走旧文件逻辑，作为回滚兜底。

### 3.2 KB 层
已完成以下内容：
- `knowledge_base/kb_store.py` 支持 `file / dual / mysql` 三模式；
- 新增 `repositories/kb_repo_mysql.py`，提供与文件 payload 等价的 MySQL 读写；
- 新增 `scripts/migrate_kb_json_to_mysql.py`；
- 新增 `scripts/verify_kb_file_mysql_parity.py`；
- 新增 `tests/test_stage13_kb_read_rollout.py`，验证 KB rollout 与 parity。

### 3.3 默认部署形态
当前默认运行形态已固化为：

```env
PROFILE_STORE_MODE=mysql
EVENT_STORE_MODE=mysql
TRACE_STORE_MODE=mysql
KB_STORE_MODE=mysql
```

同时仍保留环境变量覆盖能力，因此可以按层切回 `dual` 或 `file`。

### 3.4 启动日志与可观测性
应用启动时会打印：

```text
[StorageResolved] DATABASE_URL=... PROFILE_STORE_MODE=... EVENT_STORE_MODE=... TRACE_STORE_MODE=... KB_STORE_MODE=...
```

用于确认当前实际运行形态。

---

## 4. 切换顺序与 rollout 策略（file / dual / mysql）

本次迁移遵循渐进式 rollout：

### 阶段 A：保留 file，补 MySQL 写入能力
- 先建立 ORM、仓储层和迁移脚本；
- 不改主业务接口；
- 确保 MySQL 可承接现有 payload。

### 阶段 B：切到 dual
- 读仍以旧文件为主；
- 写入同步到 file + MySQL；
- 用于收集线上一致性问题、减少切换风险。

### 阶段 C：专项验证 mysql 读路径
- 对 KB 做 file vs mysql parity 验证；
- 核查 manager 层关键行为是否一致；
- 对 Profile / Event / Trace 做读路径 rollout 测试。

### 阶段 D：默认值切到 mysql
- 将四类 store mode 默认值改为 `mysql`；
- 保留环境变量覆盖与旧文件逻辑，确保短期可回滚。

这种 rollout 方式的优点是：
1. 允许分层验证；
2. 避免一次性全量切换；
3. 在发生异常时可快速回到 `dual` 或 `file`。

---

## 5. 验收项与验收结果

## 5.1 配置验收
- [x] `config.py` 默认值已切到 mysql；
- [x] `.env.example` 已提供 MySQL 推荐默认配置；
- [x] README / USAGE 已更新默认部署说明；
- [x] 应用启动日志可显示四类存储模式。

### 5.2 Profile / Event / Trace 验收
- [x] 已存在面向 rollout 的测试，覆盖 `file / dual / mysql` 读路径行为；
- [x] 导入 `app` 时不会因为默认 mysql 而在模块初始化阶段立即强连 KB；
- [x] 相关测试通过，说明默认 mysql 不会破坏现有兼容性。

### 5.3 KB 验收
- [x] `kb_store.py` 已支持三模式；
- [x] MySQL repo 已提供 4 类 payload 的等价读写；
- [x] KB 迁移脚本存在；
- [x] KB parity 校验脚本存在；
- [x] `normalize_symptoms / get_candidate_diseases_from_symptoms / score_diseases_from_text / rule_diagnosis / get_treatment_plan` 已完成 file vs mysql 一致性验证；
- [x] treatment 的 `actions / ingredients` 已在专项验证中覆盖。

### 5.4 保守结论
从当前仓库实现状态看：
- 迁移工作已完成到“**默认 MySQL 部署 + 保留回滚能力**”阶段；
- 适合继续作为工程实现留档；
- 也适合整理进入毕业设计中的“系统工程化落地与数据迁移策略”章节。

---

## 6. 当前推荐默认部署方式

当前推荐默认部署方式如下：

```env
DATABASE_URL=mysql+pymysql://root:123456@127.0.0.1:3306/tomato_diagnosis?charset=utf8mb4
PROFILE_STORE_MODE=mysql
EVENT_STORE_MODE=mysql
TRACE_STORE_MODE=mysql
KB_STORE_MODE=mysql
```

启动服务后，建议检查启动日志中是否出现：

```text
[StorageResolved] DATABASE_URL=... PROFILE_STORE_MODE=mysql EVENT_STORE_MODE=mysql TRACE_STORE_MODE=mysql KB_STORE_MODE=mysql
```

如果需要演示或排障，仍可临时覆盖：
- `dual`：保留文件读/双写能力；
- `file`：完全回退旧文件链路。

---

## 7. 回滚能力说明

当前仍保留短期安全回滚能力，原因如下：

1. `file / dual / mysql` 三模式支持仍在；
2. 旧 JSON / JSONL 文件逻辑未删除；
3. Profile / Event / Trace / KB 都有统一 store 层作为切换入口；
4. 已有迁移脚本与 KB parity 校验脚本可辅助重新同步与复核；
5. 回滚主要通过环境变量切换完成，不需要代码回退。

推荐参考文档：
- `docs/mysql_rollback_guide.md`

短期回滚建议：
- 优先回滚到 `dual`；
- 仅在 MySQL 读写都不可信时回滚到 `file`。

---

## 8. 遗留风险与后续优化方向

### 8.1 当前仍存在但不阻塞验收的风险
1. 某些仓储层仍采用全量重写或内存聚合方式，后续可优化；
2. 真实生产 MySQL 环境下的容量、索引与慢查询表现，仍需在更长时间窗口内观察；
3. 回滚窗口结束后，是否清理旧文件逻辑，需要在确认稳定运行后再决策。

### 8.2 后续优化方向
1. Event / Trace 统计与查询逐步转为更明确的数据库端聚合；
2. KB repo 逐步从“全量覆盖式写入”演进到更精细的 upsert；
3. 根据运行数据，决定是否下线部分旧文件回滚逻辑；
4. 增加更完整的迁移后监控指标与异常告警。

---

## 9. 留档结论

综合当前实现与测试状态，可以给出如下工程结论：

> 本项目已经完成从文件存储到 MySQL 持久化的核心迁移工作，并通过分阶段 rollout、迁移脚本、parity 校验和保守回滚设计，达到了“可部署、可验证、可回滚”的工程目标。

对开发者而言，这份记录可作为部署与运维依据；
对导师或毕业设计整理而言，这份记录可作为“系统工程实现与数据迁移验收”的直接素材。
