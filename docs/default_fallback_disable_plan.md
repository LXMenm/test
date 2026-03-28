# 默认停读落地说明（第一优先级）

## 1. 目标
将第一优先级 5 组 fallback 从“默认兼容读取”切换为“默认停读”，保留按需恢复能力。

## 2. 默认停读组
- profile equipment JSON fallback
- profile constraints JSON fallback
- base risk JSON fallback
- base extra legacy fallback
- base risk item structured fallback

## 3. 恢复开关（按需开启）
- `ENABLE_PROFILE_EQUIPMENT_JSON_FALLBACK=true`
- `ENABLE_PROFILE_CONSTRAINTS_JSON_FALLBACK=true`
- `ENABLE_BASE_RISK_JSON_FALLBACK=true`
- `ENABLE_BASE_EXTRA_LEGACY_FALLBACK=true`
- `ENABLE_BASE_RISK_ITEM_STRUCTURED_FALLBACK=true`

## 4. 回滚策略
- 不改 schema、不删 ORM；
- 仅通过环境变量恢复 fallback；
- 保留 stats/readiness 观察恢复后的命中变化。

## 5. 非目标
- 本阶段不做删列；
- 不推进第二优先级字段默认停读；
- 不触碰 `linked_farmer_id`。
