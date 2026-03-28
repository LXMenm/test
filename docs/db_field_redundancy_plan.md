# 数据库字段冗余清理预案（第一轮：仅做安全准备）

> 目标：先完成“读写依赖盘点 + 分级清单 + 清理顺序”，避免直接删字段导致历史数据不可读。

## 范围

本预案只覆盖以下字段：

- `farmer_profiles.role_type`
- `farmer_profiles.display_name`
- `farmer_profiles.equipment_json`
- `farmer_profiles.constraints_json`
- `farmer_profiles.meta_json` 中的 `display_name` / `owner_user_id` / `role_type`
- `farm_bases.risk_tags_json` / `risk_items_json` / `risk_reasons_json`
- `farm_bases.extra_json` 中天气/坐标兼容键
- `farm_base_risk_items.risk_code` / `risk_level` / `risk_message`
- `weather_snapshots.raw_json`
- `kb_treatment_actions.payload_json`
- `kb_treatment_ingredients.ingredient_type` / `payload_json`
- `user_accounts.linked_farmer_id`

---

## 逐字段盘点（读/写/标签构造/兼容兜底）

| 字段 | 当前是否被读 | 当前是否被写 | 是否参与标签构造 | 是否只是兼容兜底 | 说明 |
|---|---|---|---|---|---|
| `farmer_profiles.role_type` | 是（返回 profile 时读取） | 是（保存 profile 时固定写 `FARMER`） | 否 | 是 | 身份语义已迁移到 `user_accounts.role`，此字段仅兼容返回。 |
| `farmer_profiles.display_name` | 否（profile 主读路径不读该列） | 是（创建账号档案时会写） | 否 | 是（历史遗留） | 当前读取走 `meta_json.display_name` -> `name`。 |
| `farmer_profiles.equipment_json` | 是（无子表时回退读取） | 是（保存 profile 时写） | 否 | 是 | 已有归一化子表 `farmer_profile_equipment`，该列是回退桥接。 |
| `farmer_profiles.constraints_json` | 是（无子表时回退读取） | 是（保存 profile 时写） | 间接（影响风险/约束相关流程） | 是 | 已有归一化子表 `farmer_profile_banned_ingredients` + 明细列，该列是回退桥接。 |
| `farmer_profiles.meta_json.display_name` | 是（优先于 `name`） | 是 | 否 | 部分是 | 实际承担显示名读取主路径。 |
| `farmer_profiles.meta_json.owner_user_id` | 是（`owner_user_id` 列为空时回退） | 是 | 否 | 是 | 主列已有唯一约束，JSON 仅兜底。 |
| `farmer_profiles.meta_json.role_type` | 是（列为空时回退） | 是（固定写 `FARMER`） | 否 | 是 | 兼容保留值。 |
| `farm_bases.risk_tags_json` | 是（无风险标签子表时回退） | 是 | 是 | 是 | 归一化子表 `farm_base_risk_tags` 已接入，JSON 为兼容。 |
| `farm_bases.risk_items_json` | 是（无风险项子表时回退） | 是 | 是 | 是 | 归一化子表 `farm_base_risk_items` 已接入，JSON 为兼容。 |
| `farm_bases.risk_reasons_json` | 是（直接读取） | 是 | 否（不直接构造标签） | 否（当前仍主读） | 目前无替代子表字段承接。 |
| `farm_bases.extra_json` 天气兼容键（`temperature_2m`,`wind_speed_10m`,`weather_refreshed_at`） | 是（显式回退） | 是（写新键） | 否 | 是 | 典型历史兼容键，主键已切到新命名。 |
| `farm_bases.extra_json` 坐标兼容键（`lat`,`lon`） | 是（当列为空时回退） | 间接（透传 `extra_json`） | 否 | 是 | 仅历史数据兜底。 |
| `farm_base_risk_items.risk_code` | 是（`payload_json.code` 缺失时回退） | 是（写入时同步冗余） | 是 | 是 | 与 `payload_json` 重复。 |
| `farm_base_risk_items.risk_level` | 是（`payload_json.level` 缺失时回退） | 是（写入时同步冗余） | 是 | 是 | 与 `payload_json` 重复。 |
| `farm_base_risk_items.risk_message` | 是（`payload_json.reason/label` 缺失时回退） | 是（写入时同步冗余） | 是 | 是 | 与 `payload_json` 重复。 |
| `weather_snapshots.raw_json` | 是（列表/详情 API 均返回） | 是（upsert 时写） | 否 | 否 | 用于保留原始天气载荷。 |
| `kb_treatment_actions.payload_json` | 否（读取未使用） | 是（当前固定写 `None`） | 否 | 是 | 明显冗余预留。 |
| `kb_treatment_ingredients.ingredient_type` | 否（读取未使用） | 是（当前固定写 `None`） | 否 | 是 | 明显冗余预留。 |
| `kb_treatment_ingredients.payload_json` | 否（读取未使用） | 是（当前固定写 `None`） | 否 | 是 | 明显冗余预留。 |
| `user_accounts.linked_farmer_id` | 是（登录返回、同步接口返回） | 是（seed/建号/一致性修复写） | 否 | 是 | 已不再用于切换他人档案，仅兼容返回。 |

---

## 三色清单

### 🟢 可删候选（优先）

> 原则：当前读取路径不依赖，且写入值恒为空/无业务意义。

1. `kb_treatment_actions.payload_json`
2. `kb_treatment_ingredients.ingredient_type`
3. `kb_treatment_ingredients.payload_json`

说明：当前仅在写入时固定写 `None`，读取逻辑完全不使用。

### 🟡 需迁移后再删

1. `farmer_profiles.role_type`
2. `farmer_profiles.display_name`
3. `farmer_profiles.equipment_json`
4. `farmer_profiles.constraints_json`
5. `farmer_profiles.meta_json.role_type`
6. `farmer_profiles.meta_json.owner_user_id`
7. `farm_bases.risk_tags_json`
8. `farm_bases.risk_items_json`
9. `farm_bases.extra_json` 兼容天气/坐标键（`temperature_2m`/`wind_speed_10m`/`weather_refreshed_at`/`lat`/`lon`）
10. `farm_base_risk_items.risk_code`
11. `farm_base_risk_items.risk_level`
12. `farm_base_risk_items.risk_message`
13. `user_accounts.linked_farmer_id`

原因：这些字段都被“读取回退逻辑”覆盖，直接删会影响历史数据可读或兼容返回。

### 🔵 先保留

1. `farmer_profiles.meta_json.display_name`
2. `farm_bases.risk_reasons_json`
3. `weather_snapshots.raw_json`

原因：目前仍在有效读取链路中承担主职责或承载原始信息，不建议第一轮动。

---

## 不能直接删的字段及回退依赖

- `farmer_profiles.equipment_json`：依赖 `_build_equipment_payload` 的“子表为空则回退 JSON”。
- `farmer_profiles.constraints_json`：依赖 `_build_constraints_payload` 的“子表为空则回退 JSON”。
- `farmer_profiles.meta_json.owner_user_id`：依赖 `_profile_row_to_dict` 中 `owner_user_id` 的多级回退。
- `farmer_profiles.meta_json.role_type` / `farmer_profiles.role_type`：依赖 `_profile_row_to_dict` 的兼容返回逻辑。
- `farm_bases.risk_tags_json` / `risk_items_json`：依赖 `_base_row_to_dict` 中“子表优先、JSON 回退”。
- `farm_bases.extra_json` 兼容键：依赖 `_base_row_to_dict` 中天气字段与经纬度字段回退。
- `farm_base_risk_items.risk_code` / `risk_level` / `risk_message`：依赖 `_risk_item_row_to_dict` 回退。
- `user_accounts.linked_farmer_id`：依赖登录与同步返回兼容字段（虽不再用于权限切换）。

---

## 建议清理顺序（避免一次性大删）

1. **第 0 步（本轮）**：完成盘点与分级，冻结“直接删列”动作。
2. **第 1 步**：先删“写空且不读”字段（KB 三字段），配套 migration + ORM + 测试。
3. **第 2 步**：将回退读取改为“可观测”模式（打点统计 fallback 命中率）。
4. **第 3 步**：对 fallback 命中率为 0 的字段，先停止写入冗余，再观察一个发布周期。
5. **第 4 步**：确认历史数据完成回填后，再执行删列 migration。

---

## 本轮可执行的“最安全小清理”

本轮**不做删列**，仅做准备动作：

- 输出本预案文档，明确三色分级与迁移顺序；
- 保持现有读回退逻辑不变，确保历史数据读取零风险；
- 后续第一批建议从 KB 三字段入手（它们当前“只写 None 且不读”）。

> 结论：本轮“可安全移除”的是 **候选级别**（KB 三字段），但建议在下一轮通过 migration + 回归测试正式落地；当前提交先做预案，不直接改表结构。
