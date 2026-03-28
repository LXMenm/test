# 数据库冗余字段删列迁移方案（第一批执行轮）

> 文档状态：**执行稿**（对应第一批可删字段）。

## 1. 本轮范围（只删已审计通过字段）

本轮仅删除以下 6 个字段：

1. `farmer_profiles.equipment_json`
2. `farm_bases.risk_tags_json`
3. `farm_bases.risk_items_json`
4. `farm_base_risk_items.risk_code`
5. `farm_base_risk_items.risk_level`
6. `farm_base_risk_items.risk_message`

审计依据：以上字段已满足“无 JSON-only/旧兜底依赖、主数据源接管、默认停读完成、Canary 通过”的执行条件。

## 2. 迁移实现

本仓库当前采用 `scripts/migrations/*.py` 脚本迁移方式（非 Alembic）。

- 新增执行脚本：`scripts/migrations/migrate_drop_first_batch_redundant_columns.py`
- 执行方式：

```bash
python scripts/migrations/migrate_drop_first_batch_redundant_columns.py
```

脚本行为：
- 逐列检查是否存在（`information_schema.columns`）；
- 存在则执行 `ALTER TABLE ... DROP COLUMN ...`；
- 不存在则跳过（幂等可重复执行）。

## 3. 新库基线与旧库迁移

- 新库基线：`mysql_models.py` 已移除本轮 6 个字段，`init_db.py` 的 `create_all` 不会再创建这些列。
- 旧库迁移：对既有库执行上述 migration 脚本完成删列。

## 4. 正向执行建议

1. 先备份目标表（至少结构 + 行级快照）：
   - `farmer_profiles`
   - `farm_bases`
   - `farm_base_risk_items`
2. 在维护窗口执行 migration 脚本。
3. 执行回归测试与管理员 debug 检查。

## 5. 手动回滚建议（仓库无自动回滚机制）

若需回滚，请手工执行：

1. 通过 `ALTER TABLE ... ADD COLUMN ...` 恢复 6 列（类型需与删列前一致）；
2. 从删列前快照回填数据；
3. 回退到删列前代码版本（恢复旧 ORM/repository/fallback 元数据）；
4. 重新执行回归验证。

> 注意：本轮已移除对应 fallback 逻辑，不支持“仅开关恢复”完成业务兜底。

## 6. 本轮明确不处理项

仍保留待后续处理：

- `farmer_profiles.constraints_json`
- `farm_bases.extra_json` legacy 键清洗（`lat/lon/temperature_2m/wind_speed_10m/weather_refreshed_at`）
- 第二优先级字段：
  - `farmer_profiles.meta_json.owner_user_id`
  - `farmer_profiles.meta_json.role_type`
  - `farmer_profiles.role_type`
  - `user_accounts.linked_farmer_id`

## 7. 第二批第一步（constraints_json 补迁移）

`constraints_json` 当前仍存在历史残留，不能直接删列。已新增补迁移脚本：

```bash
python scripts/migrations/migrate_constraints_json_to_normalized.py
```

该脚本仅做保守回填（不删列）：补 `prefer_organic` / `harvest_window_days` / `farmer_profile_banned_ingredients`，
并输出迁移前后审计摘要，用于判断是否可进入下一轮删列评估。
