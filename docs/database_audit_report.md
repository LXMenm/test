# 数据库冗余字段审计报告

## 审计概述

本文档记录了对第一优先级字段的数据库审计结果，用于判断哪些字段已满足删列前提，哪些需要先清洗数据。

## 数据库信息

- **数据库类型**：MySQL
- **实例地址**：127.0.0.1:3306
- **数据库名**：tomato_diagnosis
- **账号**：root
- **环境类型**：测试库
- **审计时间**：2026-03-28

## 审计结果总览

### 字段分组审计结果

| 组别 | 字段 | JSON-only / legacy-only 数量 | 双存数量 | 是否可进入删列执行轮 | 备注 |
|------|------|------------------------------|----------|----------------------|------|
| A | equipment_json | 0 | 1 | 是 | 双存可后续清洗 |
| B | constraints_json | 1 | 4 | 否 | 先补迁移 |
| C | risk_tags_json / risk_items_json | 0 | 0 | 是 | 可设计删列 |
| D | risk_code / risk_level / risk_message | 0 | 0 | 是 | 可设计删列 |
| E | extra_json legacy 键 | 1 | 0 | 否（先清洗） | 不是删列，先回填 |

### 详细审计结果

#### A 组：equipment_json
- **只在 equipment_json 有值的档案数**：0
- **双存档案数**：1
- **判定**：可以进入删列执行轮
- **说明**：所有档案的设备数据已迁移到 farmer_profile_equipment 子表，仅有 1 个档案存在双存情况，可后续清洗

#### B 组：constraints_json
- **只靠 constraints_json 表达约束的档案数**：1
- **双存档案数**：4
- **判定**：还不能删，存在只依赖 constraints_json 的档案
- **说明**：仍有 1 个档案完全依赖 constraints_json，需要先补迁移

#### C 组：risk_tags_json / risk_items_json
- **只在 risk_tags_json 有值的基地数**：0
- **只在 risk_items_json 有值的基地数**：0
- **双存基地数**：0
- **判定**：可以进入删列执行轮
- **说明**：所有风险标签和风险项已完全迁移到子表，主表 JSON 字段无依赖

#### D 组：risk_code / risk_level / risk_message
- **仍依赖结构化列兜底的 risk item 数量**：0
- **结构化列非空的 risk item 数量**：0
- **判定**：可以进入删列执行轮
- **说明**：所有风险项已完全迁移到 payload_json，结构化列无依赖

#### E 组：extra_json legacy 键
- **只依赖 legacy lat/lon 的基地数**：0
- **只依赖 legacy 天气键的基地数**：1
- **包含任何 legacy 键的基地数**：1
- **判定**：需先清洗数据
- **说明**：仍有 1 个基地依赖 legacy 天气键，需要先回填到新字段

## 分流结论

### 可直接进入删列执行轮

| 字段 | 理由 |
|------|------|
| equipment_json | JSON-only 数量为 0，所有数据已迁移到子表 |
| risk_tags_json | JSON-only 数量为 0，所有数据已迁移到子表 |
| risk_items_json | JSON-only 数量为 0，所有数据已迁移到子表 |
| risk_code | 无依赖，所有数据已迁移到 payload_json |
| risk_level | 无依赖，所有数据已迁移到 payload_json |
| risk_message | 无依赖，所有数据已迁移到 payload_json |

### 需先做离线清洗/补迁移

| 字段 | 理由 | 清洗建议 |
|------|------|----------|
| constraints_json | 仍有 1 个档案只依赖此字段 | 补填 prefer_organic、harvest_window_days 和 banned_ingredients |
| extra_json legacy 键 | 仍有 1 个基地依赖 legacy 天气键 | 回填 temperature_2m/wind_speed_10m/weather_refreshed_at 到新字段 |

### 暂不推进

| 字段 | 理由 | 后续建议 |
|------|------|----------|
| 无 | 所有字段已分类 | - |

## 迁移执行顺序建议

1. **第一阶段**：删除最干净的字段
   - equipment_json
   - risk_tags_json
   - risk_items_json

2. **第二阶段**：删除结构化列
   - risk_code
   - risk_level
   - risk_message

3. **第三阶段**：清洗并处理剩余字段
   - constraints_json（补迁移后删除）
   - extra_json legacy 键（清洗后收缩）

## 下一轮执行目标

### 建议执行任务

1. **执行删列**：
   - 删除 equipment_json 字段
   - 删除 risk_tags_json 和 risk_items_json 字段
   - 删除 risk_code、risk_level、risk_message 字段

2. **执行数据清洗**：
   - 对 constraints_json 进行补迁移
   - 对 extra_json legacy 键进行回填

3. **验证**：
   - 验证删列后系统正常运行
   - 验证清洗后数据完整性

### 注意事项

- 删列前确保所有相关代码已不再使用这些字段
- 删列后监控系统运行状态
- 保留回滚方案，如遇问题及时回滚

## 证据链

本次审计基于真实数据库执行，所有结果均来自实际查询。审计过程遵循只读原则，未对数据进行任何修改。

---

**审计结论**：大部分第一优先级字段已满足删列条件，可按建议顺序推进删列工作。