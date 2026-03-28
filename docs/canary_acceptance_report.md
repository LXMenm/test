# 停读开关 Canary 验收结论

## 验收概述

本文档记录了 5 组停读开关的 Canary 验收结果，用于后续"默认停读"评估的证据链。

---

## 第一组：DISABLE_PROFILE_EQUIPMENT_JSON_FALLBACK

### 基本信息
- **开关名**：DISABLE_PROFILE_EQUIPMENT_JSON_FALLBACK
- **开启时间**：2026-03-28 11:00
- **环境**：Windows PowerShell
- **版本**：当前代码库

### 验收结论
✅ **通过**

### fallback-stats 前后对比
- **开启前**：profile.equipment_json_fallback 计数增长
- **开启后**：profile.equipment_json_fallback 计数为 0，多次访问后不再增长

### fallback-readiness 结果
```json
{
  "name": "profile.equipment_json_fallback",
  "hits": 0,
  "category": "profile_json_fallback",
  "candidate_field": "farmer_profiles.equipment_json",
  "phase": "candidate_for_canary",
  "notes": "process-local counters since last restart; use only as readiness hint"
}
```

### 是否出现回归
❌ 否

### 是否已验证历史样本不再回退
✅ 是
- 测试样本：F0005（equipment_json 有旧数据，但 farmer_profile_equipment 子表为空）
- 验证结果：开关开启后，旧设备不再显示

---

## 第二组：DISABLE_PROFILE_CONSTRAINTS_JSON_FALLBACK

### 基本信息
- **开关名**：DISABLE_PROFILE_CONSTRAINTS_JSON_FALLBACK
- **开启时间**：2026-03-28 11:13
- **环境**：Windows PowerShell
- **版本**：当前代码库

### 验收结论
✅ **通过**

### fallback-stats 前后对比
- **开启前**：profile.constraints_json_fallback 计数增长
- **开启后**：profile.constraints_json_fallback 计数为 0，多次访问后不再增长

### fallback-readiness 结果
```json
{
  "name": "profile.constraints_json_fallback",
  "hits": 0,
  "category": "profile_json_fallback",
  "candidate_field": "farmer_profiles.constraints_json",
  "phase": "candidate_for_canary",
  "notes": "process-local counters since last restart; use only as readiness hint"
}
```

### 是否出现回归
❌ 否

### 是否已验证历史样本不再回退
✅ 是
- 测试样本：F0005（constraints_json 有旧数据，但 prefer_organic/harvest_window_days 显式列为空）
- 验证结果：开关开启后，旧约束不再显示

---

## 第三组：DISABLE_BASE_RISK_JSON_FALLBACK

### 基本信息
- **开关名**：DISABLE_BASE_RISK_JSON_FALLBACK
- **开启时间**：2026-03-28 11:23
- **环境**：Windows PowerShell
- **版本**：当前代码库

### 验收结论
✅ **通过**

### fallback-stats 前后对比
- **开启前**：base.risk_tags_json_fallback 和 base.risk_items_json_fallback 计数增长
- **开启后**：两个计数均为 0，多次访问后不再增长

### fallback-readiness 结果
```json
{
  "name": "base.risk_tags_json_fallback",
  "hits": 0,
  "category": "base_risk_json_fallback",
  "candidate_field": "farm_bases.risk_tags_json",
  "phase": "candidate_for_canary"
},
{
  "name": "base.risk_items_json_fallback",
  "hits": 0,
  "category": "base_risk_json_fallback",
  "candidate_field": "farm_bases.risk_items_json",
  "phase": "candidate_for_canary"
}
```

### 是否出现回归
❌ 否

### 是否已验证历史样本不再回退
✅ 是
- 测试样本：TEST_BASE（risk_tags_json/risk_items_json 有旧数据，但 farm_base_risk_tags/farm_base_risk_items 子表为空）
- 验证结果：开关开启后，旧风险标签/风险项不再显示

---

## 第四组：DISABLE_BASE_RISK_ITEM_STRUCTURED_FALLBACK

### 基本信息
- **开关名**：DISABLE_BASE_RISK_ITEM_STRUCTURED_FALLBACK
- **开启时间**：2026-03-28 11:29
- **环境**：Windows PowerShell
- **版本**：当前代码库

### 验收结论
✅ **通过**

### fallback-stats 前后对比
- **开启前**：base.risk_item_structured_fallback 计数增长
- **开启后**：base.risk_item_structured_fallback 计数为 0，多次访问后不再增长

### fallback-readiness 结果
```json
{
  "name": "base.risk_item_structured_fallback",
  "hits": 0,
  "category": "risk_item_structured_fallback",
  "candidate_field": "farm_base_risk_items.risk_code/risk_level/risk_message",
  "phase": "candidate_for_canary",
  "notes": "process-local counters since last restart; use only as readiness hint"
}
```

### 是否出现回归
❌ 否

### 是否已验证历史样本不再回退
✅ 是
- 测试样本：LEGACY_RISK（payload_json 不完整，但 risk_code/risk_level/risk_message 结构化列有值）
- 验证结果：开关开启后，不再从结构化列回退补全

---

## 第五组：DISABLE_BASE_EXTRA_LEGACY_FALLBACK

### 基本信息
- **开关名**：DISABLE_BASE_EXTRA_LEGACY_FALLBACK
- **开启时间**：2026-03-28 11:31
- **环境**：Windows PowerShell
- **版本**：当前代码库

### 验收结论
✅ **通过**

### fallback-stats 前后对比
- **开启前**：base.extra.latlon_fallback 和 base.extra.weather_legacy_key_fallback 计数增长
- **开启后**：两个计数均为 0，多次访问后不再增长

### fallback-readiness 结果
```json
{
  "name": "base.extra.latlon_fallback",
  "hits": 0,
  "category": "base_extra_legacy_fallback",
  "candidate_field": "farm_bases.extra_json.lat/lon",
  "phase": "candidate_for_canary"
},
{
  "name": "base.extra.weather_legacy_key_fallback",
  "hits": 0,
  "category": "base_extra_legacy_fallback",
  "candidate_field": "farm_bases.extra_json.temperature_2m/wind_speed_10m/weather_refreshed_at",
  "phase": "candidate_for_canary"
}
```

### 是否出现回归
❌ 否

### 是否已验证历史样本不再回退
✅ 是
- 测试样本：WEATHER_TEST（extra_json 包含 legacy 键 lat/lon/temperature_2m/wind_speed_10m/weather_refreshed_at，但显式列为空）
- 验证结果：开关开启后，不再从 extra_json legacy 键回退读取

---

## 总体验收总结

### 验收完成情况

| 组别 | 开关名 | 状态 | 开启时间 |
|------|---------|------|---------|
| 第一组 | DISABLE_PROFILE_EQUIPMENT_JSON_FALLBACK | ✅ 通过 | 2026-03-28 11:00 |
| 第二组 | DISABLE_PROFILE_CONSTRAINTS_JSON_FALLBACK | ✅ 通过 | 2026-03-28 11:13 |
| 第三组 | DISABLE_BASE_RISK_JSON_FALLBACK | ✅ 通过 | 2026-03-28 11:23 |
| 第四组 | DISABLE_BASE_RISK_ITEM_STRUCTURED_FALLBACK | ✅ 通过 | 2026-03-28 11:29 |
| 第五组 | DISABLE_BASE_EXTRA_LEGACY_FALLBACK | ✅ 通过 | 2026-03-28 11:31 |

### 关键发现

1. **所有开关均有效**
   - 5 组开关全部通过验收
   - 开关开启后，目标 fallback 计数均为 0 且不再增长

2. **无功能回归**
   - 新数据主路径完全正常
   - 页面和接口无明显报错
   - 核心功能不受影响

3. **历史样本停读验证成功**
   - 所有历史样本在开关开启后不再通过旧 JSON 回退
   - 系统已完全依赖新主路径读取数据

4. **管理员接口正常**
   - fallback-stats 接口正常访问
   - fallback-readiness 接口正常访问
   - 所有 fallback 项 phase 均为 "candidate_for_canary"

### 后续建议

1. **进入"默认停读评估"阶段**
   - 评估是否可以将这些开关默认开启
   - 分析开启后的系统稳定性
   - 评估删列的可行性和风险

2. **按照文档建议，逐步推进**
   - 先完成默认停读评估
   - 再考虑删列工作
   - 保持谨慎，逐步推进

3. **监控指标**
   - 持续监控 fallback-stats
   - 关注用户反馈
   - 评估性能影响

---

## 证据链完整性

本文档提供了完整的证据链，包括：
- ✅ 每组开关的开启时间和环境
- ✅ fallback-stats 前后对比数据
- ✅ fallback-readiness 接口结果
- ✅ 回归验证结果
- ✅ 历史样本停读验证结果

所有证据表明，5 组停读开关已准备好进入"默认停读评估"阶段。
