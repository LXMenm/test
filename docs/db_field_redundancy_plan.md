# 数据库字段冗余清理预案（第一轮，限定范围）

## 1. 文档定位

- 本文是**第一轮、限定字段范围**的冗余清理预案，只覆盖本轮点名字段。
- 本文**不代表全库字段冗余审计已完成**，不能外推为“全库可删结论”。
- 本轮目标是：
  1) 盘点真实读写路径；
  2) 做风险分级；
  3) 规划迁移顺序；
  而不是直接执行删列。

## 2. 审计方法

本次判定依据仅来自当前代码中可验证路径：

1. ORM 模型定义（字段存在性、注释语义、索引/约束）；
2. 仓储层读写逻辑（`repositories/*.py` 的组装、回退、落库）；
3. API 返回路径（`app.py` 中登录/管理/档案相关接口）；
4. 个性化与风险标签链路（`personalization/profile_store.py` 与 `personalization/risk_tags.py`）；
5. 字段是否仅作为兼容回退（如“列为空回退 JSON / 子表为空回退主表 JSON”）。

> 注意：本文不基于“推测未来会用到”，仅基于当前代码已实现路径判定。

## 3. 本轮覆盖范围

本轮仅覆盖以下字段：

- `farmer_profiles.role_type`
- `farmer_profiles.display_name`
- `farmer_profiles.equipment_json`
- `farmer_profiles.constraints_json`
- `farmer_profiles.meta_json` 内：`display_name` / `owner_user_id` / `role_type`
- `farm_bases.risk_tags_json` / `risk_items_json` / `risk_reasons_json`
- `farm_bases.extra_json` 内天气/坐标兼容键（`temperature_2m` / `wind_speed_10m` / `weather_refreshed_at` / `lat` / `lon`）
- `farm_base_risk_items.risk_code` / `risk_level` / `risk_message`
- `weather_snapshots.raw_json`
- `kb_treatment_actions.payload_json`
- `kb_treatment_ingredients.ingredient_type` / `payload_json`
- `user_accounts.linked_farmer_id`

## 4. 字段级审计明细

判定值说明：

- **核心字段**：当前业务主路径直接依赖；
- **兼容冗余**：主路径已有替代，字段主要承担回退/兼容返回；
- **迁移后可删**：当前仍有回退依赖，需先迁移读写再删；
- **弱使用/预留**：当前几乎不读（或仅读空值），偏预留。

| 表名 | 字段名 | 当前是否被读 | 当前是否被写 | 是否作为标签/规则引擎输入 | 是否作为标签结果存储或下游消费 | 是否只是兼容/回退用途 | 当前判定 | 说明 |
|---|---|---|---|---|---|---|---|---|
| farmer_profiles | role_type | 是 | 是（固定写 `FARMER`） | 否 | 否 | 是 | 兼容冗余 | 身份语义已由 `user_accounts.role` 承载，保留用于兼容返回。 |
| farmer_profiles | display_name | 否（档案主读路径不读该列） | 是（创建账号档案时写） | 否 | 否 | 是 | 迁移后可删 | 当前显示名主读为 `meta_json.display_name`→`name`。 |
| farmer_profiles | equipment_json | 是（子表为空时回退） | 是 | 否 | 否 | 是 | 迁移后可删 | 与 `farmer_profile_equipment` 子表并存。 |
| farmer_profiles | constraints_json | 是（子表为空时回退） | 是 | 间接（影响约束上下文） | 间接（约束结果进入后续上下文） | 是 | 迁移后可删 | 与 `prefer_organic`/`harvest_window_days` + 禁用成分子表并存。 |
| farmer_profiles.meta_json | display_name | 是（优先于 `name`） | 是 | 否 | 是（用于档案展示） | 否（当前主读） | 核心字段（本范围内） | 当前显示名输出优先取该键。 |
| farmer_profiles.meta_json | owner_user_id | 是（列空时回退） | 是 | 否 | 否 | 是 | 兼容冗余 | 主列 `owner_user_id` 已是约束字段，JSON 为兜底。 |
| farmer_profiles.meta_json | role_type | 是（列空时回退） | 是（固定写 `FARMER`） | 否 | 否 | 是 | 兼容冗余 | 与 `farmer_profiles.role_type` 同属兼容层。 |
| farm_bases | risk_tags_json | 是（风险标签子表为空时回退） | 是 | 否 | 是 | 是 | 迁移后可删 | 结果列，与 `farm_base_risk_tags` 子表并存。 |
| farm_bases | risk_items_json | 是（风险项子表为空时回退） | 是 | 否 | 是 | 是 | 迁移后可删 | 结果列，与 `farm_base_risk_items` 子表并存。 |
| farm_bases | risk_reasons_json | 是 | 是 | 否 | 是 | 否（当前直接使用） | 核心字段（本范围内） | 当前无对应子表承接 reasons。 |
| farm_bases.extra_json | temperature_2m / wind_speed_10m / weather_refreshed_at | 是（有显式回退） | 是（写新键同时保留 extra） | 否 | 否 | 是 | 迁移后可删 | 兼容旧键；新键为 `weather_temperature_2m` / `weather_wind_speed_10m` / `last_weather_refresh_at`。 |
| farm_bases.extra_json | lat / lon | 是（列空时回退） | 间接（透传 extra） | 是（缺失检查会影响 `MISSING_CONTEXT`） | 否 | 是 | 迁移后可删 | 仅历史兼容坐标键。 |
| farm_base_risk_items | risk_code | 是（`payload_json.code` 缺失时回退） | 是 | 否 | 是 | 是 | 迁移后可删 | 与 `payload_json` 重复存储。 |
| farm_base_risk_items | risk_level | 是（`payload_json.level` 缺失时回退） | 是 | 否 | 是 | 是 | 迁移后可删 | 与 `payload_json` 重复存储。 |
| farm_base_risk_items | risk_message | 是（`payload_json.reason/label` 缺失时回退） | 是 | 否 | 是 | 是 | 迁移后可删 | 与 `payload_json` 重复存储。 |
| weather_snapshots | raw_json | 是 | 是 | 否 | 是（天气快照详情回传） | 否 | 核心字段（本范围内） | 用于保留原始天气载荷，当前 API 返回该字段。 |
| kb_treatment_actions | payload_json | 否（读取未使用） | 是（固定写 `None`） | 否 | 否 | 是 | 弱使用/预留 | 归一化读取只看 `action_section/seq/action_text`。 |
| kb_treatment_ingredients | ingredient_type | 否（读取未使用） | 是（固定写 `None`） | 否 | 否 | 是 | 弱使用/预留 | 当前只消费 `ingredient_name`。 |
| kb_treatment_ingredients | payload_json | 否（读取未使用） | 是（固定写 `None`） | 否 | 否 | 是 | 弱使用/预留 | 当前读取路径未消费。 |
| user_accounts | linked_farmer_id | 是（登录返回/同步返回） | 是（seed/建号/一致性修复） | 否 | 是（接口兼容回传） | 是 | 兼容冗余 | 已不用于跨账号切换，仅保留兼容字段。 |

## 5. 三色清单

### 🟢 可优先清理

1. `kb_treatment_actions.payload_json`
2. `kb_treatment_ingredients.ingredient_type`
3. `kb_treatment_ingredients.payload_json`

原因：当前读取路径不消费，写入恒为 `None`，属于弱使用/预留字段；在补齐 migration 与回归测试后可优先处理。

### 🟡 需迁移后再删

1. `farmer_profiles.role_type`
2. `farmer_profiles.display_name`
3. `farmer_profiles.equipment_json`
4. `farmer_profiles.constraints_json`
5. `farmer_profiles.meta_json.owner_user_id`
6. `farmer_profiles.meta_json.role_type`
7. `farm_bases.risk_tags_json`
8. `farm_bases.risk_items_json`
9. `farm_bases.extra_json` 兼容键（`temperature_2m` / `wind_speed_10m` / `weather_refreshed_at` / `lat` / `lon`）
10. `farm_base_risk_items.risk_code`
11. `farm_base_risk_items.risk_level`
12. `farm_base_risk_items.risk_message`
13. `user_accounts.linked_farmer_id`

原因：以上字段仍被当前回退读取或接口兼容返回链路依赖，直接删会影响历史数据可读性或返回结构稳定性。

### 🔵 当前先保留

1. `farmer_profiles.meta_json.display_name`
2. `farm_bases.risk_reasons_json`
3. `weather_snapshots.raw_json`

原因：当前在主读取/回传链路中仍有明确作用，且尚无等价替代路径可立即接管。

## 6. 不能直接删除的原因

按依赖类型归纳如下：

1. **子表为空时回退 JSON**
   - `farmer_profiles.equipment_json`
   - `farmer_profiles.constraints_json`
   - `farm_bases.risk_tags_json`
   - `farm_bases.risk_items_json`

2. **显式列为空时回退 `meta_json` / `extra_json`**
   - `farmer_profiles.meta_json.owner_user_id`
   - `farmer_profiles.meta_json.role_type`
   - `farm_bases.extra_json` 兼容天气/坐标键

3. **结果子表内“结构化列 ↔ payload_json”互相回退**
   - `farm_base_risk_items.risk_code` / `risk_level` / `risk_message`

4. **登录/接口兼容返回仍依赖旧字段**
   - `user_accounts.linked_farmer_id`

5. **当前主返回链路仍直接依赖**
   - `farmer_profiles.meta_json.display_name`
   - `farm_bases.risk_reasons_json`
   - `weather_snapshots.raw_json`

## 7. 标签相关字段特别说明

为避免“输入字段”和“结果字段”混淆，单独澄清如下：

### 7.1 风险标签构造输入（`build_base_risk_tags()`）

当前规则判断实际输入包括：

- `facility`
- `environment`
- `weather_snapshot`
- `relative_humidity_2m`
- `precipitation`
- `rain_risk`
- `growth_stage`
- `sowing_date`
- `location` / `province` / `city` / `district`
- `latitude` / `longitude`

这些字段参与湿度/降雨/生育期/上下文完整性等判断。

### 7.2 风险标签结果存储与下游消费（非规则输入）

以下字段属于“标签结果存储、回传或兼容持久化”，不是规则引擎输入：

- `farm_bases.risk_tags_json`
- `farm_bases.risk_items_json`
- `farm_bases.risk_reasons_json`
- `farm_base_risk_items.risk_code`
- `farm_base_risk_items.risk_level`
- `farm_base_risk_items.risk_message`

## 8. 建议清理顺序

1. **第 0 步**：冻结删列动作，先补文档与观测口径；
2. **第 1 步**：优先处理最安全弱使用字段（KB 三字段）；
3. **第 2 步**：给兼容回退字段增加命中统计（区分新老路径）；
4. **第 3 步**：对命中趋近 0 的字段先“停写冗余”，观察一个发布周期；
5. **第 4 步**：确认历史数据迁移完成后，再执行删列 migration。

## 9. 本轮最安全的小清理建议

本轮建议仍为“只做预案，不做 schema 变更”。

下一轮最先落地的一批建议：

- `kb_treatment_actions.payload_json`
- `kb_treatment_ingredients.ingredient_type`
- `kb_treatment_ingredients.payload_json`

落地方式：migration + ORM 同步 + 回归测试，不直接扩展为全量 schema 改造。

## 10. 未覆盖但必须继续审计的高冗余区域

以下区域本轮**未展开**，但后续必须进入正式审计：

1. `diagnosis_events`：结构化列 + `payload_json` + `meta_json` 的并存与回填策略；
2. `trace_events`：投影列 + `payload_json` 的双轨存储边界；
3. `kb_diseases`：主字段与 `meta_json` 的重复承载；
4. `kb_treatments`：主表字段与子表/JSON 的并存策略；
5. `kb_rules`：结构化规则列与 `meta_json` 共存冗余；
6. `kb_symptom_maps`：主表 JSON 与归一化子表并存关系；
7. `farm_bases.internal_base_uid`：真实读写路径与唯一性/业务必要性需单独核实。

> 结论边界：本预案只给出“第一轮、限定范围”的冗余清理建议，不构成全库删列结论。
