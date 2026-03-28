# extra_json Legacy 键清洗报告

## 执行信息

- **清洗时间**：2026-03-28 21:30
- **数据库**：mysql://root@127.0.0.1:3306/tomato_diagnosis
- **备份文件**：backup_farm_bases_20260328_213028.sql

## 执行步骤

### 1. 备份表
```bash
mysqldump -h 127.0.0.1 -u root -p123456 tomato_diagnosis farm_bases > backup_farm_bases_20260328_213028.sql
```

### 2. 执行清洗脚本
```bash
python scripts/migrations/migrate_extra_json_legacy_keys.py
```

#### 清洗结果
```
[extra-json-legacy-cleanup] migration completed
[extra-json-legacy-cleanup] scanned_bases=2
[extra-json-legacy-cleanup] legacy_hit_bases=0
[extra-json-legacy-cleanup] latitude_backfilled=0
[extra-json-legacy-cleanup] longitude_backfilled=0
[extra-json-legacy-cleanup] weather_temperature_2m_backfilled=0
[extra-json-legacy-cleanup] weather_wind_speed_10m_backfilled=0
[extra-json-legacy-cleanup] last_weather_refresh_at_backfilled=0
[extra-json-legacy-cleanup] legacy_keys_removed=0
[extra-json-legacy-cleanup] coordinate_conflicts=0
[extra-json-legacy-cleanup] weather_conflicts=0
[extra-json-legacy-cleanup] invalid_or_skipped=0
[extra-json-legacy-cleanup] affected_base_pairs=[]
[extra-json-legacy-cleanup] conflict_base_pairs=[]
[extra-json-legacy-cleanup] audit_before={'scanned_bases': 2, 'legacy_keys_present': 0, 'legacy_latlon_only': 0, 'legacy_weather_only': 0, 'legacy_only': 0}
[extra-json-legacy-cleanup] audit_after={'scanned_bases': 2, 'legacy_keys_present': 0, 'legacy_latlon_only': 0, 'legacy_weather_only': 0, 'legacy_only': 0}
```

### 3. 审计复核

清洗前后审计结果：
- `legacy_latlon_only` = 0
- `legacy_weather_only` = 0
- `legacy_only` = 0

✅ **所有 legacy 键审计指标已归零**

## 回归验证

| 测试项 | 状态 | 说明 |
|--------|------|------|
| /health | ✅ 通过 | 返回 {"status":"ok"} |
| fallback-stats | ✅ 通过 | 返回空对象 |
| fallback-readiness | ✅ 通过 | 所有 hits=0 |
| 基地详情读取 | ✅ 通过 | 数据正常加载 |
| 档案读取 | ✅ 通过 | 数据正常加载 |
| 档案保存 | ✅ 通过 | 保存成功 |

## 关键验证点

1. **清洗成功**：所有 legacy 键审计指标已归零
2. **无脏数据**：scanned_bases=2，legacy_hit_bases=0，说明没有遗留的 legacy 数据
3. **功能正常**：服务运行正常，基地和档案功能正常
4. **无回归**：系统无功能回归

## 结论

✅ **extra_json legacy 键清洗成功完成**

### 完成的工作
- [x] 备份 farm_bases 表
- [x] 执行 extra_json legacy 键清洗脚本
- [x] 验证 legacy_latlon_only = 0
- [x] 验证 legacy_weather_only = 0
- [x] 验证 legacy_only = 0
- [x] 回归测试通过

### 说明
当前数据库中 farm_bases 表的 extra_json 字段已经没有 legacy 键（lat/lon/temperature_2m/wind_speed_10m/weather_refreshed_at），所有数据都已迁移到显式列（latitude/longitude/weather_temperature_2m/weather_wind_speed_10m/last_weather_refresh_at）。

系统现在完全依赖显式列存储坐标和天气数据，不再使用 extra_json 中的 legacy 键。
