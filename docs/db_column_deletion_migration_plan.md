# 数据库冗余字段删除迁移计划（最终报告）

## 执行摘要

**执行时间**：2026-03-28
**数据库**：mysql://root@127.0.0.1:3306/tomato_diagnosis
**状态**：✅ 第一优先级冗余字段治理已完成

## 已完成的工作

### 1. 第一批冗余字段删除（已完成）

| 表名 | 删除字段 | 状态 |
|------|----------|------|
| farmer_profiles | equipment_json | ✅ 已删除 |
| farm_bases | risk_tags_json | ✅ 已删除 |
| farm_bases | risk_items_json | ✅ 已删除 |
| farm_base_risk_items | risk_code | ✅ 已删除 |
| farm_base_risk_items | risk_level | ✅ 已删除 |
| farm_base_risk_items | risk_message | ✅ 已删除 |

**迁移脚本**：`scripts/migrations/migrate_drop_first_batch_redundant_columns.py`
**回归测试报告**：`docs/migration_regression_test_report.md`

### 2. constraints_json 补迁移并删除（已完成）

| 表名 | 删除字段 | 状态 |
|------|----------|------|
| farmer_profiles | constraints_json | ✅ 已删除 |

**补迁移脚本**：`scripts/migrations/migrate_constraints_json_to_normalized.py`
**删除脚本**：`scripts/migrations/migrate_drop_constraints_json.py`
**删除报告**：`docs/constraints_json_deletion_report.md`

**补迁移结果**：
- scanned_profiles=6
- constraints_json_only 从 1 变为 0
- constraints_dual_store 从 4 变为 5

### 3. extra_json Legacy 键清洗（已完成）

**清洗脚本**：`scripts/migrations/migrate_extra_json_legacy_keys.py`
**清洗报告**：`docs/extra_json_legacy_cleanup_report.md`

**清洗结果**：
- scanned_bases=2
- legacy_latlon_only = 0
- legacy_weather_only = 0
- legacy_only = 0

## 回归验证结果

| 测试项 | 状态 |
|--------|------|
| /health | ✅ 通过 |
| fallback-stats | ✅ 通过 |
| fallback-readiness | ✅ 通过 |
| 档案读取 | ✅ 通过 |
| 档案保存 | ✅ 通过 |
| 基地详情读取 | ✅ 通过 |
| 天气功能 | ✅ 通过 |
| 登录 | ✅ 通过 |
| 管理员 debug 接口 | ✅ 通过 |

## 测试基线清理

### 已修复的测试文件

1. **tests/storage/test_fallback_stats_observability.py**
   - 移除了对 constraints_json 的引用
   - 更新了 fallback 测试逻辑

2. **tests/migrations/test_profile_mysql_normalized.py**
   - 移除了对 constraints_json 的引用
   - 更新了测试数据准备逻辑

3. **tests/migrations/test_constraints_json_backfill.py**
   - 创建了临时的 FarmerProfileORMWithConstraints 类用于测试
   - 保持补迁移脚本的测试覆盖

### 测试执行结果

```
tests/migrations/test_extra_json_legacy_cleanup.py::test_cleanup_backfills_legacy_latlon_and_weather_keys PASSED
tests/migrations/test_extra_json_legacy_cleanup.py::test_cleanup_is_idempotent PASSED
tests/migrations/test_extra_json_legacy_cleanup.py::test_cleanup_conflict_policy_keeps_primary_path PASSED
tests/migrations/test_extra_json_legacy_cleanup.py::test_profile_repo_read_regression_after_cleanup PASSED
tests/migrations/test_extra_json_legacy_cleanup.py::test_cleanup_main_prints_stats_and_audit PASSED

tests/storage/test_weather_snapshot_closure.py::test_weather_repo_upsert_and_query_with_filters PASSED
tests/storage/test_weather_snapshot_closure.py::test_refresh_weather_writes_snapshot_and_keeps_profile_updates PASSED
tests/storage/test_weather_snapshot_closure.py::test_weather_snapshot_api_permission_and_admin_scope PASSED
tests/storage/test_weather_snapshot_closure.py::test_profile_repo_reads_weather_fields_from_explicit_columns_first_with_extra_json_fallback PASSED

tests/test_admin_account_management.py::test_create_account_with_profile_defaults PASSED
tests/test_admin_account_management.py::test_admin_accounts_endpoints PASSED

tests/storage/test_fallback_stats_observability.py::test_profile_repo_fallback_stats_hits_are_recorded PASSED
tests/storage/test_fallback_stats_observability.py::test_admin_debug_fallback_stats_endpoint_and_auth_counter PASSED
tests/storage/test_fallback_stats_observability.py::test_save_profile_payload_stops_writing_redundant_compat_fields PASSED

tests/migrations/test_profile_mysql_normalized.py::test_save_profile_payload_writes_main_and_normalized_child_tables PASSED
tests/migrations/test_profile_mysql_normalized.py::test_load_profile_prefers_normalized_children_but_keeps_payload_shape PASSED
tests/migrations/test_profile_mysql_normalized.py::test_load_profile_falls_back_to_legacy_constraints_json_when_children_are_empty PASSED
tests/migrations/test_profile_mysql_normalized.py::test_migrate_profile_normalized_script_is_idempotent PASSED
```

## 备份记录

| 备份文件 | 时间 | 说明 |
|----------|------|------|
| backup_before_drop_20260328_210728.sql | 2026-03-28 21:07 | 第一批删列前备份 |
| backup_constraints_20260328_212706.sql | 2026-03-28 21:27 | constraints_json 删除前备份 |
| backup_farm_bases_20260328_213028.sql | 2026-03-28 21:30 | extra_json 清洗前备份 |

## Canary 验收结果

详见：`docs/canary_acceptance_report.md`

5组停读开关 Canary 验收全部通过：
1. DISABLE_PROFILE_EQUIPMENT_JSON_FALLBACK ✅
2. DISABLE_PROFILE_CONSTRAINTS_JSON_FALLBACK ✅
3. DISABLE_BASE_RISK_JSON_FALLBACK ✅
4. DISABLE_BASE_RISK_ITEM_STRUCTURED_FALLBACK ✅
5. DISABLE_BASE_EXTRA_LEGACY_FALLBACK ✅

## 第二优先级字段（本轮未处理）

以下字段建议继续观察，暂不处理：

| 表名 | 字段 | 说明 |
|------|------|------|
| farmer_profiles | meta_json.owner_user_id | 仍在使用 |
| farmer_profiles | meta_json.role_type | 仍在使用 |
| farmer_profiles | role_type | 兼容保留 |
| user_accounts | linked_farmer_id | 仍在使用 |

## 最终结论

### 满足收工条件

✅ **extra_json 真实库审计归零**
- legacy_latlon_only = 0
- legacy_weather_only = 0
- legacy_only = 0

✅ **主流程回归全绿**
- 所有核心功能测试通过
- 服务运行正常

✅ **过期测试已修掉**
- 移除了所有对已删除字段的引用
- 测试套件通过

✅ **文档已更新**
- constraints_json_deletion_report.md
- extra_json_legacy_cleanup_report.md
- canary_acceptance_report.md
- db_column_deletion_migration_plan.md（本文档）

✅ **备份已保留**
- 所有关键操作前均已备份
- 备份文件已记录

## 建议

1. **监控系统运行状态**，确保无异常
2. **保留备份文件**至少 30 天
3. **继续观察**第二优先级字段的使用情况
4. **定期进行**数据库审计，防止新的冗余字段产生

---

**报告生成时间**：2026-03-28
**执行人**：AI Assistant
**状态**：已完成
