# 数据库表结构与项目代码一致性审计报告（基于当前代码，重新核查）

> 审计时间：2026-03-26（UTC）
> 
> 审计目标：
> 1) 校验 ORM/初始化/仓储/业务入口一致性；
> 2) 识别闭环、弱闭环、预留表；
> 3) 判断是否需要新增主表。

---

## 1. 审计范围

本次逐项核查了以下文件（按“模型 → 建库 → 仓储 → 业务入口/存储模式”链路）：

- ORM 与表定义：`mysql_models.py`
- 初始化脚本：`scripts/db/init_db.py`
- 业务入口：`app.py`
- MySQL 仓储：
  - `repositories/profile_repo_mysql.py`
  - `repositories/event_repo_mysql.py`
  - `repositories/trace_repo_mysql.py`
  - `repositories/kb_repo_mysql.py`
- 存储模式/迁移兼容：
  - `config.py`
  - `personalization/profile_store.py`
  - `event_store.py`
  - `trace_store.py`
  - `knowledge_base/kb_store.py`
  - `README.md`

---

## 2. ORM 基线清单（按模块分组）

### 2.1 Profile 模块

1. `farmer_profiles`
   - 主键：`id`
   - 关键唯一约束：`farmer_id`（unique），`owner_user_id`（`uq_farmer_profiles_owner_user_id`）
   - 关键索引：`farmer_id`、`owner_user_id`、`role_type`、`active_base_id`、`idx_farmer_profiles_name`
   - 主要用途：农户档案主表（身份绑定、个性化参数、基地引用等）

2. `farmer_profile_equipment`
   - 主键：`id`
   - 关键唯一约束：`(farmer_id, seq)`
   - 关键索引：`idx_farmer_profile_equipment_farmer(farmer_id, seq)`
   - 主要用途：档案设备列表归一化子表

3. `farmer_profile_banned_ingredients`
   - 主键：`id`
   - 关键唯一约束：`(farmer_id, seq)`
   - 关键索引：`idx_farmer_profile_banned_ingredients_farmer(farmer_id, seq)`
   - 主要用途：禁限用成分归一化子表

4. `farm_bases`
   - 主键：`id`
   - 关键唯一约束：`(farmer_id, base_id)`
   - 关键索引：`idx_farm_bases_farmer_base`、`idx_farm_bases_geo`、`growth_stage`
   - 主要用途：基地主数据（地理信息、生长阶段、天气快照字段、风险聚合字段）

5. `farm_base_risk_tags`
   - 主键：`id`
   - 关键唯一约束：`(farmer_id, base_id, risk_tag)`
   - 关键索引：`idx_farm_base_risk_tags_farmer_base`
   - 主要用途：基地风险标签归一化子表

6. `farm_base_risk_items`
   - 主键：`id`
   - 关键唯一约束：无
   - 关键索引：`idx_farm_base_risk_items_farmer_base`
   - 主要用途：基地风险项归一化子表（含 payload）

### 2.2 Weather 模块

7. `weather_snapshots`
   - 主键：`id`
   - 关键唯一约束：无
   - 关键索引：`base_id`、`farmer_id`、`snapshot_time`、`idx_weather_snapshots_base_time`
   - 主要用途：天气快照独立存储（当前代码中定义完整，但未形成仓储/业务闭环）

### 2.3 Event 模块

8. `diagnosis_events`
   - 主键：`id`
   - 关键唯一约束：`event_id`（unique）
   - 关键索引：`trace_id`、`ts`，以及 disease/farmer/base + ts 组合索引
   - 主要用途：诊断事件宽表（核心事实 + JSON payload）

### 2.4 Trace 模块

9. `trace_events`
   - 主键：`id`
   - 关键唯一约束：`(trace_id, seq)`
   - 关键索引：`idx_trace_events_trace_ts(trace_id, ts)`，`node`，`status`
   - 主要用途：多智能体 trace 事件宽表（时间序列）

### 2.5 KB 模块

10. `kb_diseases`
    - 主键：`id`
    - 关键唯一约束：`disease_name`（unique）
    - 关键索引：`disease_name`
    - 主要用途：疾病主知识

11. `kb_treatments`
    - 主键：`id`
    - 关键唯一约束：`disease_name`（unique）
    - 关键索引：`disease_name`
    - 主要用途：治疗/预防主知识

12. `kb_treatment_actions`
    - 主键：`id`
    - 关键唯一约束：`(disease_name, action_section, seq)`
    - 关键索引：`idx_kb_treatment_actions_disease_section`
    - 主要用途：治疗动作归一化子表

13. `kb_treatment_ingredients`
    - 主键：`id`
    - 关键唯一约束：`(disease_name, ingredient_name, seq)`
    - 关键索引：`idx_kb_treatment_ingredients_disease_seq`、`ingredient_name`
    - 主要用途：用药成分归一化子表

14. `kb_rules`
    - 主键：`id`
    - 关键唯一约束：`rule_id`（可空 unique）
    - 关键索引：`rule_id`、`crop_type`、`disease_name`
    - 主要用途：规则推理知识

15. `kb_symptom_maps`
    - 主键：`id`
    - 关键唯一约束：`symptom_key`（unique）
    - 关键索引：`symptom_key`
    - 主要用途：症状映射主表（含 payload 保留）

16. `kb_symptom_aliases`
    - 主键：`id`
    - 关键唯一约束：`(symptom_key, alias)`
    - 关键索引：`idx_kb_symptom_aliases_symptom_alias`
    - 主要用途：症状别名归一化子表

17. `kb_symptom_candidate_diseases`
    - 主键：`id`
    - 关键唯一约束：`(symptom_key, disease_name)`
    - 关键索引：`idx_kb_symptom_candidate_diseases_symptom_rank`
    - 主要用途：症状候选病害归一化子表

### 2.6 Account 模块

18. `user_accounts`
    - 主键：`id`
    - 关键唯一约束：`user_id`（unique）、`username`（unique）
    - 关键索引：`role`、`status`、`linked_farmer_id`、`idx_user_accounts_role_status(role,status)`
    - 主要用途：登录与权限主体（USER/EXPERT/ADMIN）

---

## 3. 初始化脚本与 ORM 一致性检查

结论：**初始化脚本与 ORM 定义一致**。

核查要点：

1. `scripts/db/init_db.py` 显式 `import mysql_models`，确保 ORM 类注册至 `Base.metadata`。
2. 随后调用 `Base.metadata.create_all(bind=db_engine)`，会创建 metadata 中所有缺失表。
3. 未发现“ORM 已定义但 init 不会建出”的表。
4. 需注意：该脚本说明仅“新表创建”，不负责老库改列/改约束（这是预期，不属于不一致）。

---

## 4. 表—代码对账结果（闭环审计）

> 说明：
> - “运行时使用”以 `app.py` + 各 store/repo 的真实调用链判断；
> - 项目支持 file/dual/mysql 三模式，`mysql` 才是纯 DB 路径；`dual`/`file` 可能导致 DB 路径被旁路，这属于迁移策略，不是 schema 错误。

| 表名 | ORM | 读路径 | 写路径 | 运行时使用 | 状态 | 说明 |
|---|---|---|---|---|---|---|
| farmer_profiles | 有 | `profile_repo_mysql.get_profile` | `save_profile_payload`/账户创建 | 是 | 已闭环 | 档案主表，API 读写都在用 |
| farmer_profile_equipment | 有 | `get_profile` 聚合读取 | `save_profile_payload` 重建写入 | 是 | 已闭环 | 与主档案同事务维护 |
| farmer_profile_banned_ingredients | 有 | `get_profile` 聚合读取 | `save_profile_payload` 重建写入 | 是 | 已闭环 | 与主档案同事务维护 |
| farm_bases | 有 | `get_profile`/`list_all_base_ids` | `save_profile_payload` | 是 | 已闭环 | 基地核心表 |
| farm_base_risk_tags | 有 | `get_profile` 聚合读取 | `_replace_base_risk_children` | 是 | 已闭环 | 归一化标签子表已接入 |
| farm_base_risk_items | 有 | `get_profile` 聚合读取 | `_replace_base_risk_children` | 是 | 已闭环 | 归一化风险项子表已接入 |
| weather_snapshots | 有 | 未发现 | 未发现 | 否 | 弱闭环/预留 | 天气刷新当前写回 profile/base，不落该表 |
| diagnosis_events | 有 | `event_repo_mysql` 系列查询 | `append_event_mysql` | 是（经 `event_store`） | 已闭环 | 宽表+JSON 与当前查询模式一致 |
| trace_events | 有 | `trace_repo_mysql.list_trace_events_mysql` | `append/emit_trace_event_mysql` | 是（经 `trace_store`） | 已闭环 | trace 主链路稳定 |
| kb_diseases | 有 | `load_diseases_mysql` | `save_diseases_mysql` | 是（经 `kb_store`） | 已闭环 | |
| kb_treatments | 有 | `load_treatments_mysql` | `save_treatments_mysql` | 是（经 `kb_store`） | 已闭环 | |
| kb_treatment_actions | 有 | `load_treatments_mysql` 子表读取 | `_replace_treatment_children` | 是 | 已闭环 | 归一化子表已实际读写 |
| kb_treatment_ingredients | 有 | `load_treatments_mysql` 子表读取 | `_replace_treatment_children` | 是 | 已闭环 | 归一化子表已实际读写 |
| kb_rules | 有 | `load_rules_mysql` | `save_rules_mysql` | 是 | 已闭环 | |
| kb_symptom_maps | 有 | `load_symptom_map_mysql` | `save_symptom_map_mysql` | 是 | 已闭环 | |
| kb_symptom_aliases | 有 | `load_symptom_map_mysql` 子表读取 | `_replace_symptom_map_children` | 是 | 已闭环 | |
| kb_symptom_candidate_diseases | 有 | `load_symptom_map_mysql` 子表读取 | `_replace_symptom_map_children` | 是 | 已闭环 | |
| user_accounts | 有 | 登录/管理接口直接 SQLAlchemy 查询 | seed/创建账号/角色变更/删除 | 是 | 已闭环 | 非仅 demo；登录与权限链路强依赖 |

---

## 5. 迁移策略核查（避免误判 schema）

### 5.1 当前是否仍支持 file / dual / mysql

是。当前代码明确保留三模式并存：

- Profile：`personalization/profile_store.py`
- Event：`event_store.py`
- Trace：`trace_store.py`
- KB：`knowledge_base/kb_store.py`
- 配置：`config.py` + README“存储模式说明”

### 5.2 这如何影响一致性判断

- 不能用“某表在某次运行没写入”直接判定 schema 有误；可能只是当前 mode= `file`/`dual` 的行为。
- 需要看“代码是否存在 MySQL 读写路径并被业务入口调用”——本次除 `weather_snapshots` 外，其余目标表均有清晰路径。

### 5.3 哪些现象属于迁移兼容，不应误判

- Event/Trace/KB/Profile 在 `dual` 下出现文件读 + MySQL 写（或 dual-read file）的分流。
- 部分 API 调用的是 store 抽象，而不是直接 repo；这是架构层兼容策略。

---

## 6. 是否需要新增表（核心结论）

### 6.1 必须新增（Must-have）

**结论：当前无“必须新增”的业务主表。**

理由：

1. 核心业务对象（档案、基地、事件、trace、KB、账号）均已有合理 schema 落点。
2. 核心流程可跑通，且绝大多数表已形成“ORM + 读 + 写 + 入口调用”的闭环。

### 6.2 可选增强（Nice-to-have）

可选考虑新增**治理/审计类表**，但不作为当前主流程阻塞项，例如：

- `admin_config_audit`：记录管理端配置变更历史；
- `expert_review_flow_history`：记录专家复核流状态迁移。

这些属于治理增强，不是当前 schema 缺口。

### 6.3 不建议新增（当前更优先）

**不建议当前新增新的业务主表。**

更优先方向：

1. 先补齐 `weather_snapshots` 的闭环（若决定保留该表）；
2. 先做索引与查询层优化；
3. 先减少 Python 端全量拉取后统计的开销。

> 特别说明：基于当前证据，不建议继续拆 `diagnosis_events` / `trace_events` 主体结构。

---

## 7. 推荐优化顺序（基于当前代码）

### P0（立即）

1. **核实 `weather_snapshots` 真实定位**：
   - 若要保留：补仓储读写与调用闭环；
   - 若短期不用：文档中明确“预留表”，避免误读。
2. **检查高频查询索引有效性**：
   - `diagnosis_events`（按 `ts`/`trace_id`/`farmer_id`/`base_id` 的组合检索）；
   - `trace_events`（`trace_id+seq/ts`）；
   - Profile 组（`farmer_id/base_id` 主链路）。

### P1（次优先）

1. 将事件统计（按病害、时间序列、模型使用）尽量下推数据库聚合，减少 Python 全表遍历。
2. 评估 `event_repo_mysql` 中“先全量取再过滤”的路径，替换为 SQL 条件过滤 + 限流分页。

### P2（增强）

1. 如需更强合规/治理，再新增审计类历史表（`admin_config_audit`、`expert_review_flow_history` 等）。
2. 依据审计需求再决定是否做更细粒度归档，不作为当前必需。

---

## 8. 一致性总结

### 8.1 总体判断

- **当前表结构与当前代码整体相符（在三模式兼容架构前提下）**。
- 绝大多数表已形成真实闭环。

### 8.2 主要风险点与待复核项

1. `weather_snapshots`：当前为**弱闭环/预留**（有 ORM、无仓储/入口读写闭环）。
2. `event_repo_mysql` 部分统计路径存在 Python 端聚合，可用 SQL 聚合优化性能。
3. 三模式并存期需持续维护“文件与数据库语义一致”，避免双写分歧。

---

## 9. 可落地结论（供后续开发直接采用）

1. 现阶段**不新增业务主表**。
2. 将 `weather_snapshots` 定位作为第一优先级决策项（补闭环 or 明确预留）。
3. 性能优化优先于 schema 扩张：先索引、再 SQL 聚合、再治理审计增强。
4. 保持 `diagnosis_events` / `trace_events` 宽表策略不变，避免无证据拆表。

