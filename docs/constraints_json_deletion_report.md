# constraints_json 字段删除迁移报告

## 迁移执行信息

- **迁移时间**：2026-03-28 21:27
- **数据库**：mysql://root@127.0.0.1:3306/tomato_diagnosis
- **备份文件**：backup_constraints_20260328_212706.sql

## 执行步骤

### 1. 备份表
```bash
mysqldump -h 127.0.0.1 -u root -p123456 tomato_diagnosis farmer_profiles farmer_profile_banned_ingredients > backup_constraints_20260328_212706.sql
```

### 2. 执行补迁移脚本
```bash
python scripts/migrations/migrate_constraints_json_to_normalized.py
```

#### 补迁移结果
```
[constraints-backfill] migration completed
[constraints-backfill] scanned_profiles=6
[constraints-backfill] constraints_profiles=5
[constraints-backfill] prefer_organic_backfilled=1
[constraints-backfill] harvest_window_backfilled=1
[constraints-backfill] banned_ingredients_inserted=0
[constraints-backfill] conflict_profiles=0
[constraints-backfill] invalid_profiles=0
[constraints-backfill] updated_farmer_ids=['F0001']
[constraints-backfill] conflict_farmer_ids=[]
[constraints-backfill] invalid_farmer_ids=[]
[constraints-backfill] audit_before={'constraints_profiles': 5, 'constraints_json_only': 1, 'constraints_dual_store': 4}
[constraints-backfill] audit_after={'constraints_profiles': 5, 'constraints_json_only': 0, 'constraints_dual_store': 5}
```

### 3. 重跑审计
```bash
python audit_constraints.py
```

#### 审计结果
```
=== constraints_json 审计结果 ===
database: mysql+pymysql://root:***@127.0.0.1:3306/tomato_diagnosis?charset=utf8mb4

只靠 constraints_json 表达约束的档案数: 0
双存档案数: 5

✅ 可以进入删列执行轮
建议：删除 farmer_profiles.constraints_json 字段
```

### 4. 执行删除迁移
```bash
python scripts/migrations/migrate_drop_constraints_json.py
```

#### 删除结果
```
[drop-constraints-json] migration completed
[drop-constraints-json] dropped=1
  - dropped: farmer_profiles.constraints_json
```

### 5. 修改代码

#### 5.1 修改 profile_repo_mysql.py
- 移除了 `_build_constraints_payload` 函数中对 `constraints_json` 的引用
- 简化了函数逻辑，直接从显式列和子表读取数据

#### 5.2 修改 mysql_models.py
- 从 `FarmerProfileORM` 中移除了 `constraints_json` 字段定义

## 回归测试结果

| 测试项 | 状态 | 说明 |
|--------|------|------|
| 服务启动 | ✅ 通过 | 正常启动 |
| /health | ✅ 通过 | 返回 {"status":"ok"} |
| 档案读取 | ✅ 通过 | 数据正常加载 |
| 档案保存 | ✅ 通过 | 保存成功，响应 {"ok":true,"farmer_id":"F0001"} |
| 约束字段 | ✅ 通过 | prefer_organic 和 harvest_window_days 正常 |

## 关键验证点

1. **补迁移成功**：constraints_json_only 从 1 变为 0
2. **字段删除成功**：成功删除 farmer_profiles.constraints_json 字段
3. **代码更新成功**：移除了所有对 constraints_json 的引用
4. **功能正常**：服务运行正常，档案读写功能正常
5. **无回归**：系统无功能回归

## 结论

✅ **constraints_json 字段删除迁移成功完成**

### 完成的工作
- [x] 执行补迁移，将所有 constraints_json 数据迁移到显式列和子表
- [x] 验证 constraints_json_only = 0
- [x] 删除 farmer_profiles.constraints_json 字段
- [x] 更新相关代码，移除对 constraints_json 的引用
- [x] 验证系统功能正常，无回归

### 后续建议
- 监控系统运行状态
- 保留备份文件至少 30 天
- 继续处理 extra_json legacy 键的清洗工作
