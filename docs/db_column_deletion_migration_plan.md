# 数据库列删除迁移方案（设计稿，非执行稿）

> 本文是“删列前离线审计 + migration 设计”文档，不直接执行删列。

## 1. 当前阶段

- 第一优先级 5 组已完成：停写 + 默认停读 + 可观测。
- 当前仍保留：fallback 代码、恢复开关、stats/readiness、管理员调试接口。
- 本阶段目标：给出删列前提、阻塞项、迁移顺序、回滚方案。

## 2. 分组设计

### 组 1：`farmer_profiles.equipment_json`

- 主数据源：`farmer_profile_equipment`。
- 删列前提：
  1. 离线审计确认“仅 equipment_json 有值且子表为空”数量可控；
  2. 必要时先离线回填到子表；
  3. 默认停读观察窗口内无异常。
- 风险：历史档案可能只在 JSON 列存设备。
- 审计方法：见 `scripts/db/audit_redundant_fields.sql` 的 A1/A2。
- 回滚：删列前导出 JSON 快照；若异常，回滚迁移并恢复 `ENABLE_PROFILE_EQUIPMENT_JSON_FALLBACK=true`。

### 组 2：`farmer_profiles.constraints_json`

- 主数据源：显式列 + `farmer_profile_banned_ingredients`。
- 删列前提：
  1. 离线审计确认 JSON-only 约束残留；
  2. 回填缺失的禁用成分/显式列；
  3. 停读观察窗口稳定。
- 风险：旧数据可能仅在 JSON 保留完整约束。
- 审计方法：见 B1/B2。
- 回滚：保留回填前快照，必要时回滚迁移并恢复 `ENABLE_PROFILE_CONSTRAINTS_JSON_FALLBACK=true`。

### 组 3：`farm_bases.risk_tags_json` / `farm_bases.risk_items_json`

- 主数据源：`farm_base_risk_tags` + `farm_base_risk_items`。
- 删列前提：
  1. 离线审计确认 JSON-only 残留；
  2. 回填到子表；
  3. 停读观察窗口稳定。
- 风险：历史基地风险结果缺子表行。
- 审计方法：见 C1/C2/C3。
- 回滚：删列前导出列数据；必要时回滚迁移并恢复 `ENABLE_BASE_RISK_JSON_FALLBACK=true`。

### 组 4：`farm_base_risk_items.risk_code/risk_level/risk_message`

- 主数据源：`payload_json`。
- 删列前提：
  1. 审计确认 payload 不完整但结构化列有值的记录量（D1）；
  2. 补齐 payload 后再删列；
  3. 停读观察窗口稳定。
- 风险：老记录 payload 缺字段。
- 审计方法：见 D1/D2。
- 回滚：删列前导出结构化列快照；必要时回滚并恢复 `ENABLE_BASE_RISK_ITEM_STRUCTURED_FALLBACK=true`。

### 组 5：`farm_bases.extra_json` legacy 键（内容清洗，不是删列）

- 目标对象：`lat/lon/temperature_2m/wind_speed_10m/weather_refreshed_at`。
- 主数据源：显式列 + 新键。
- 前提：
  1. 审计 legacy-only 残留量（E1/E2/E3）；
  2. 先做离线内容清洗（回填主字段/新键）；
  3. 观察窗口稳定后，再评估是否需要结构收敛。
- 结论：本组本轮不属于“直接删列”，属于 JSON 内容治理。

## 3. 推荐迁移顺序

1. 运行离线审计（只读）；
2. 输出分组残留统计，定义回填批次；
3. 执行离线回填/清洗（小批次 + 校验）；
4. 进入只读观察窗口（stats/readiness + 业务回归）；
5. 对真正列字段执行删列 migration（分组推进，禁止一把梭）；
6. 删列稳定后再做 ORM/代码收缩。

## 4. 回滚方案

- 删列前必须导出目标列快照（含主键定位）；
- 迁移脚本需具备可逆或补偿脚本；
- 发现线上问题时：
  1. 先恢复 `ENABLE_*_FALLBACK=true`；
  2. 回滚 migration；
  3. 从快照恢复数据；
  4. 重新进入观察窗口。

## 5. 本轮不进入删列设计的字段

- `farmer_profiles.meta_json.owner_user_id`
- `farmer_profiles.meta_json.role_type`
- `farmer_profiles.role_type`
- `user_accounts.linked_farmer_id`

这些字段本轮继续观察，不进入删列执行排期。
