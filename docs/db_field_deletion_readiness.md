# 数据库冗余字段删列前评估（第四轮：默认停读）

> 本文目标：记录“第一优先级 fallback 已默认停读”的当前状态、恢复方式与删列前条件。本文不是删列执行脚本。

## 1. 阶段状态

- 已停写（完成）
- 可观测（完成）
- Canary 停读验证（完成）
- 默认停读（本轮完成，仅第一优先级 5 组）
- 待删列评估（未开始）

## 2. 第一优先级 5 组当前状态

### 2.1 profile JSON fallback 组
- 字段：`farmer_profiles.equipment_json`、`farmer_profiles.constraints_json`
- 当前主路径：设备子表 + 约束显式列/禁用成分子表
- 当前默认：**停读**
- 恢复方式：
  - `ENABLE_PROFILE_EQUIPMENT_JSON_FALLBACK=true`
  - `ENABLE_PROFILE_CONSTRAINTS_JSON_FALLBACK=true`
- 观测点：`profile.equipment_json_fallback`、`profile.constraints_json_fallback`

### 2.2 base risk JSON fallback 组
- 字段：`farm_bases.risk_tags_json`、`farm_bases.risk_items_json`
- 当前主路径：`farm_base_risk_tags` + `farm_base_risk_items`
- 当前默认：**停读**
- 恢复方式：`ENABLE_BASE_RISK_JSON_FALLBACK=true`
- 观测点：`base.risk_tags_json_fallback`、`base.risk_items_json_fallback`

### 2.3 base extra legacy fallback 组
- 字段：`lat/lon/temperature_2m/wind_speed_10m/weather_refreshed_at`
- 当前主路径：显式列 + `extra_json` 新键
- 当前默认：**停读**
- 恢复方式：`ENABLE_BASE_EXTRA_LEGACY_FALLBACK=true`
- 观测点：`base.extra.latlon_fallback`、`base.extra.weather_legacy_key_fallback`

### 2.4 risk item structured fallback 组
- 字段：`farm_base_risk_items.risk_code/risk_level/risk_message`
- 当前主路径：`payload_json`
- 当前默认：**停读**
- 恢复方式：`ENABLE_BASE_RISK_ITEM_STRUCTURED_FALLBACK=true`
- 观测点：`base.risk_item_structured_fallback`

## 3. 第二优先级（本轮不推进）

仅观察，不做默认停读推进：
- `farmer_profiles.meta_json.owner_user_id`
- `farmer_profiles.meta_json.role_type`
- `farmer_profiles.role_type`
- `user_accounts.linked_farmer_id`

## 4. 管理端评估接口

- `GET /api/admin/debug/fallback-stats`
- `GET /api/admin/debug/fallback-readiness`

说明：
- readiness 仅基于“当前进程累计命中”，重启后会清零；
- 仅用于辅助判断，不作为删列自动门槛。

## 5. 删列前仍需满足

1. 离线全量数据审计（确认历史值分布与可回填性）；
2. 明确 migration 执行方案（含灰度与回滚）；
3. 完整回归（档案/基地风险/天气/登录/管理员接口）；
4. 线上观测窗口内 fallback 命中稳定低位。
