# 第一批删列执行报告

## 执行日期

- 2026-03-28

## 一、已实际删除字段（共 6 个）

- `farmer_profiles.equipment_json`
- `farm_bases.risk_tags_json`
- `farm_bases.risk_items_json`
- `farm_base_risk_items.risk_code`
- `farm_base_risk_items.risk_level`
- `farm_base_risk_items.risk_message`

删除原因：
- 无 JSON-only / 旧兜底依赖；
- 主数据源已完全接管；
- 默认停读已完成；
- Canary 已通过；
- 审计确认可进入删列执行轮。

## 二、本轮未处理字段

### 2.1 仍需先清洗/补迁移

- `farmer_profiles.constraints_json`
- `farm_bases.extra_json` legacy 键（`lat/lon/temperature_2m/wind_speed_10m/weather_refreshed_at`）

### 2.2 第二优先级字段

- `farmer_profiles.meta_json.owner_user_id`
- `farmer_profiles.meta_json.role_type`
- `farmer_profiles.role_type`
- `user_accounts.linked_farmer_id`

## 三、代码影响面

- Schema：新增第一批删列 migration；
- ORM：移除 6 个字段映射；
- Repository：移除上述字段相关 fallback 读逻辑 / 停读开关 / 统计命中；
- Fallback stats/readiness：移除 4 项已删列元数据；
- Test：补充删列脚本与新基线 schema 测试，更新兼容测试断言。

## 四、执行与回滚说明

### 4.1 正向执行

```bash
python scripts/migrations/migrate_drop_first_batch_redundant_columns.py
```

建议先备份：
- `farmer_profiles`
- `farm_bases`
- `farm_base_risk_items`

### 4.2 回滚

仓库当前无自动回滚机制，需手工：
1. `ALTER TABLE ... ADD COLUMN ...` 恢复 6 列；
2. 从删列前快照回填；
3. 回退到删列前代码版本（恢复 ORM/repository/fallback 元数据）。

## 五、下一轮建议

1. 优先推进 `constraints_json` 清洗与删列准备；
2. 其次推进 `extra_json` legacy 键内容清洗；
3. 暂不推进第二优先级字段。
