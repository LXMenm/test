# 数据库冗余字段删列 Readiness（第一批执行后）

## 1. 第一批已执行删列字段

已完成删列：

- `farmer_profiles.equipment_json`
- `farm_bases.risk_tags_json`
- `farm_bases.risk_items_json`
- `farm_base_risk_items.risk_code`
- `farm_base_risk_items.risk_level`
- `farm_base_risk_items.risk_message`

对应影响：
- ORM 列定义已移除；
- repository fallback 读路径与开关逻辑已移除；
- fallback stats/readiness 元数据项已移除。

## 2. 当前仍保留的 fallback 观测项

以下项仍在 `runtime_fallback_stats` 中保留：

- `profile.constraints_json_fallback`
- `profile.meta.owner_user_id_fallback`
- `profile.meta.role_type_fallback`
- `base.extra.latlon_fallback`
- `base.extra.weather_legacy_key_fallback`
- `auth.linked_farmer_id_returned`

## 3. 本轮明确不推进字段

### 3.1 仍需先清洗/补迁移

- `farmer_profiles.constraints_json`
- `farm_bases.extra_json` legacy 键：
  - `lat`
  - `lon`
  - `temperature_2m`
  - `wind_speed_10m`
  - `weather_refreshed_at`

### 3.2 第二优先级（继续观察）

- `farmer_profiles.meta_json.owner_user_id`
- `farmer_profiles.meta_json.role_type`
- `farmer_profiles.role_type`
- `user_accounts.linked_farmer_id`

## 4. 下一轮建议

1. 先推进 `constraints_json` 数据清洗与删列准备；
2. 再推进 `extra_json` legacy 内容清洗；
3. 第二优先级字段继续保持观测，不在下一轮直接删列。
