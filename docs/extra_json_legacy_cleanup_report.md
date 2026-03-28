# farm_bases.extra_json legacy 键清洗报告（第二批治理第二步）

## 1) 本轮目标与边界

本轮是 **extra_json 内容清洗轮**，不是删列执行轮：

- 仅处理 `farm_bases.extra_json` 里的 legacy 键残留。
- 将有效 legacy 数据保守回填到当前主路径（显式列 + 新 key）。
- 不删除 `farm_bases.extra_json` 列。
- 不扩展到第二优先级字段。
- 不改动第一批已完成删列字段。
- 不处理 `linked_farmer_id`、`role_type`、`meta_json.owner_user_id`。

对应脚本：`scripts/migrations/migrate_extra_json_legacy_keys.py`。

## 2) legacy 键与主路径映射

- 坐标：
  - `extra_json.lat` -> `farm_bases.latitude`
  - `extra_json.lon` -> `farm_bases.longitude`

- 天气：
  - `extra_json.temperature_2m` -> `extra_json.weather_temperature_2m`
  - `extra_json.wind_speed_10m` -> `extra_json.weather_wind_speed_10m`
  - `extra_json.weather_refreshed_at` -> `extra_json.last_weather_refresh_at`

## 3) 回填规则（保守）

### 坐标

- 当 `latitude` 为空且 legacy `lat` 可解析为数值时，回填 `latitude`。
- 当 `longitude` 为空且 legacy `lon` 可解析为数值时，回填 `longitude`。
- legacy 值非法（不可转 float）则跳过并计入 `invalid_or_skipped`。

### 天气

- 当新键为空且 legacy 键有值时，回填到新键。
- 新键已有值时不覆盖。

### 旧键移除策略

默认启用旧键移除（可 `--keep-legacy-keys` 关闭）：

- 仅在主路径已落位时移除对应 legacy 键。
- 例如 `lat` 仅在 `latitude` 已有值时才删。

## 4) 冲突策略（不强覆盖）

- 坐标冲突：`latitude/longitude` 已有值且与 `lat/lon` 不一致 -> 不覆盖，记录冲突与 `(farmer_id, base_id)`。
- 天气冲突：新键已有值且与 legacy 键不一致 -> 不覆盖，记录冲突与 `(farmer_id, base_id)`。
- 主路径永远优先，legacy 只作补齐。

## 5) 幂等性

脚本幂等：

- 已回填的值不会在第二次执行中重复写入。
- 已删除的 legacy 键不会重复删除。
- 主路径已有值时不覆盖。

建议执行方式：连续执行两次，确认第二次统计项回落到 0（除扫描数/命中数外）。

## 6) 执行方式（正向）

> 建议先做库表备份，再执行。

```bash
python scripts/migrations/migrate_extra_json_legacy_keys.py
```

如果需要极保守模式（仅回填，不删旧键）：

```bash
python scripts/migrations/migrate_extra_json_legacy_keys.py --keep-legacy-keys
```

脚本会输出：扫描数、命中数、回填数、冲突数、非法值、移除旧键数量、受影响 `(farmer_id, base_id)`、迁移前后审计摘要。

## 7) 审计复核

脚本内置 `audit_extra_json_legacy_dependency`，可用于迁移前后比对：

- `legacy_keys_present`
- `legacy_latlon_only`
- `legacy_weather_only`
- `legacy_only`

理想目标：`legacy_only = 0`。

## 8) 回滚方案

当前仓库未提供自动化“逐行反向回放”回滚脚本，建议如下：

1. **首选**：用清洗前数据库快照整表回滚 `farm_bases`（最稳妥）。
2. **手动回滚（应急）**：
   - 用备份将 `latitude/longitude` 恢复到清洗前值；
   - 将 `extra_json.weather_*` / `last_weather_refresh_at` 恢复到清洗前值；
   - 必要时将 `lat/lon/temperature_2m/wind_speed_10m/weather_refreshed_at` legacy 键按备份恢复。

> 若线上执行，强烈建议在执行前导出 `farm_bases` 全量快照（含 `extra_json`、`latitude`、`longitude`）。

## 9) 下一步建议

当多轮审计稳定满足 `legacy_only=0` 且观测窗口内无 fallback 命中后，可进入“进一步收缩 extra_json 结构”的评估阶段。

但该阶段与本轮解耦，不应在本轮直接推进删列或大规模结构收缩。
