# 数据库冗余字段删列前评估（第三轮：停读准备）

> 结论边界：本文用于“删列前评估 + 停读准备”，**不是**直接删列执行单。

## 1. 当前阶段定义

- **已停写**：新写路径不再写入冗余字段，但保留兼容读取。
- **可观测**：已纳入 fallback stats，可通过 admin debug 接口查看命中。
- **待停读验证**：可通过停读开关进行 canary 级验证（默认关闭）。
- **待删列评估**：停读验证通过后，结合离线数据审计进入删列评估。
- **不建议近期处理**：仍有接口契约/权限链路强依赖。

## 2. 分组评估

### 2.1 profile JSON fallback 组

字段：
- `farmer_profiles.equipment_json`
- `farmer_profiles.constraints_json`

- 主数据源：
  - `farmer_profile_equipment` 子表
  - `farmer_profile_banned_ingredients` 子表 + `prefer_organic` / `harvest_window_days`
- fallback 来源：对应 JSON 列。
- 观测点：
  - `profile.equipment_json_fallback`
  - `profile.constraints_json_fallback`
- 停读前提：新数据停写后，fallback 命中长期低位（建议至少一个完整发布周期观察）。
- 风险等级：中（影响旧档案兼容读取）。
- 当前状态：**已停写 + 可观测 + 已具备停读开关（默认关闭）**。

### 2.2 base risk JSON fallback 组

字段：
- `farm_bases.risk_tags_json`
- `farm_bases.risk_items_json`

- 主数据源：
  - `farm_base_risk_tags`
  - `farm_base_risk_items`
- fallback 来源：`farm_bases` 主表 JSON 列。
- 观测点：
  - `base.risk_tags_json_fallback`
  - `base.risk_items_json_fallback`
- 停读前提：子表覆盖率稳定、fallback 长期低位。
- 风险等级：中（影响历史基地风险结果读取）。
- 当前状态：**已停写 + 可观测 + 已具备停读开关（默认关闭）**。

### 2.3 base extra legacy fallback 组

字段（legacy 键）：
- `lat` / `lon`
- `temperature_2m` / `wind_speed_10m` / `weather_refreshed_at`

- 主数据源：
  - 显式列 `latitude/longitude`
  - 新键 `weather_temperature_2m/weather_wind_speed_10m/last_weather_refresh_at`
- fallback 来源：`extra_json` legacy 键。
- 观测点：
  - `base.extra.latlon_fallback`
  - `base.extra.weather_legacy_key_fallback`
- 停读前提：历史库中 legacy 键已完成迁移或命中趋近 0。
- 风险等级：中高（影响历史天气/坐标兼容）。
- 当前状态：**已停写 + 可观测 + 已具备停读开关（默认关闭）**。

### 2.4 risk item structured fallback 组

字段：
- `farm_base_risk_items.risk_code`
- `farm_base_risk_items.risk_level`
- `farm_base_risk_items.risk_message`

- 主数据源：`farm_base_risk_items.payload_json`
- fallback 来源：结构化列。
- 观测点：`base.risk_item_structured_fallback`
- 停读前提：旧数据结构化列回退命中长期低位，且回放验证通过。
- 风险等级：中（影响老 risk item 兼容）。
- 当前状态：**已停写 + 可观测 + 已具备停读开关（默认关闭）**。

### 2.5 profile meta compatibility 组（第二优先级）

字段：
- `farmer_profiles.meta_json.owner_user_id`
- `farmer_profiles.meta_json.role_type`
- `farmer_profiles.role_type`

- 主数据源：`owner_user_id` / `role_type` 显式列（`role_type` 仍有兼容返回语义）。
- fallback 来源：`meta_json`。
- 观测点：
  - `profile.meta.owner_user_id_fallback`
  - `profile.meta.role_type_fallback`
- 风险等级：中高（身份/兼容返回语义相关）。
- 当前状态：**已停写 + 可观测；本轮不推进停读开关**。

### 2.6 auth/account compatibility 组（只观察）

字段：
- `user_accounts.linked_farmer_id`

- 当前用途：一致性修复 + 登录/管理接口兼容返回。
- 观测点：`auth.linked_farmer_id_returned`
- 风险等级：高（接口契约影响）。
- 当前状态：**仅观察，不建议近期停写/停读**。

## 3. 本轮代码级停读准备

### 3.1 新增停读开关（默认 false）

- `DISABLE_PROFILE_EQUIPMENT_JSON_FALLBACK`
- `DISABLE_PROFILE_CONSTRAINTS_JSON_FALLBACK`
- `DISABLE_BASE_RISK_JSON_FALLBACK`
- `DISABLE_BASE_EXTRA_LEGACY_FALLBACK`
- `DISABLE_BASE_RISK_ITEM_STRUCTURED_FALLBACK`

说明：
- 开关默认关闭，当前默认行为保持兼容读取。
- 仅用于 canary 级停读验证，不作为删列自动触发条件。

### 3.2 readiness 视图

- `GET /api/admin/debug/fallback-readiness`
- 输出每个 fallback 的：
  - `hits`
  - `category`
  - `candidate_field`
  - `phase`
  - `notes`

注意：
- readiness 仅基于进程内计数，重启清零；
- 仅作辅助判断，不能直接作为删列决策依据。

## 4. 本轮结论

### 4.1 可进入下一轮 canary 停读验证（默认仍关闭）

- `equipment_json` fallback
- `constraints_json` fallback
- `risk_tags_json` / `risk_items_json` fallback
- `extra_json` legacy 键 fallback
- `risk_item` structured fallback

### 4.2 本轮仅继续观察，不建议推进停读

- `meta_json.owner_user_id`
- `meta_json.role_type`
- `farmer_profiles.role_type`
- `user_accounts.linked_farmer_id`

## 5. 下一轮建议

1. 在灰度环境按开关逐项启用（一次只开一组）；
2. 对照 fallback readiness + 回归测试结果评估风险；
3. 通过后再进入“停读默认化评估”；
4. 最后才进入删列迁移设计（仍需离线数据审计 + 回滚方案）。
