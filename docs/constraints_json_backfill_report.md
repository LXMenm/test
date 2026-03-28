# constraints_json 补迁移执行说明（第二批第一步）

## 1. 为什么当前不能直接删 `constraints_json`

最新审计显示：
- 仍存在 `constraints_json` only 档案（主路径表达不完整）；
- 仍存在双存档案（JSON + 规范化并存）；

因此当前阶段必须先做历史补迁移，再进入删列评估。

## 2. 本轮范围与边界

本轮仅处理：`farmer_profiles.constraints_json` 历史残留回填。

- ✅ 回填到主路径：
  - `farmer_profiles.prefer_organic`
  - `farmer_profiles.harvest_window_days`
  - `farmer_profile_banned_ingredients`
- ❌ 不删 `constraints_json` 列。
- ❌ 不处理 `extra_json` legacy 键。
- ❌ 不处理第二优先级字段。

## 3. 迁移策略（保守补迁移）

脚本：`scripts/migrations/migrate_constraints_json_to_normalized.py`

### 3.1 prefer_organic
- 仅在 `constraints_json.prefer_organic = true` 且显式列当前为 `false` 时回填为 `true`。
- 若显式列已是 `true` 且 JSON 为 `false`，视为冲突，记录并跳过覆盖。

### 3.2 harvest_window_days
- 仅在显式列为空（`NULL`）时，从 JSON 回填。
- 若显式列已有值且与 JSON 不一致，记录冲突并跳过覆盖。

### 3.3 banned_ingredients
- 从 JSON 列表逐项规范化（去空、去重）后补写子表。
- 若子表中已存在同名 ingredient，跳过。
- 新增记录的 `seq` 从当前该 farmer 的最大 `seq` 递增，保证稳定且幂等。

## 4. 统计输出

脚本执行会输出：
- 扫描档案数
- 命中 `constraints_json` 的档案数
- 回填 `prefer_organic` 数量
- 回填 `harvest_window_days` 数量
- 新增 banned_ingredients 数量
- 冲突档案数
- 非法数据档案数
- 更新/冲突/非法的 farmer_id 列表
- 迁移前后审计摘要（`constraints_json_only`、`constraints_dual_store`）

## 5. 执行方式

```bash
python scripts/migrations/migrate_constraints_json_to_normalized.py
```

建议先备份：
- `farmer_profiles`
- `farmer_profile_banned_ingredients`

## 6. 回滚方式

仓库暂无自动回滚机制。建议：
1. 使用迁移前快照恢复 `farmer_profiles.prefer_organic/harvest_window_days`；
2. 删除本轮新增的 `farmer_profile_banned_ingredients` 行（可按迁移日志 farmer_id + ingredient 定位）；
3. 或直接回滚到迁移前数据库快照。

## 7. 下一步

补迁移后重新执行约束审计，确认 `constraints_json` only 数量下降（理想为 0），再评估是否进入后续删列轮。
