-- 冗余字段离线审计 SQL（第一优先级）
-- 说明：本文件仅包含只读 SELECT，不包含 UPDATE/DELETE/ALTER。

-- A) farmer_profiles.equipment_json
-- A1: 仅 equipment_json 有值、equipment 子表为空
SELECT
  COUNT(*) AS profile_count_only_equipment_json
FROM farmer_profiles fp
WHERE JSON_VALID(fp.equipment_json)
  AND JSON_LENGTH(fp.equipment_json) > 0
  AND NOT EXISTS (
    SELECT 1 FROM farmer_profile_equipment pe WHERE pe.farmer_id = fp.farmer_id
  );

-- A2: equipment_json 与子表双存
SELECT
  COUNT(*) AS profile_count_equipment_dual_store
FROM farmer_profiles fp
WHERE JSON_VALID(fp.equipment_json)
  AND JSON_LENGTH(fp.equipment_json) > 0
  AND EXISTS (
    SELECT 1 FROM farmer_profile_equipment pe WHERE pe.farmer_id = fp.farmer_id
  );

-- B) farmer_profiles.constraints_json
-- B1: constraints_json 有值但显式列+子表不足（示意：显式列为空且禁用成分子表为空）
SELECT
  COUNT(*) AS profile_count_constraints_json_only
FROM farmer_profiles fp
WHERE JSON_VALID(fp.constraints_json)
  AND JSON_LENGTH(fp.constraints_json) > 0
  AND fp.prefer_organic = 0
  AND fp.harvest_window_days IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM farmer_profile_banned_ingredients bi WHERE bi.farmer_id = fp.farmer_id
  );

-- B2: constraints_json 与规范化路径双存
SELECT
  COUNT(*) AS profile_count_constraints_dual_store
FROM farmer_profiles fp
WHERE JSON_VALID(fp.constraints_json)
  AND JSON_LENGTH(fp.constraints_json) > 0
  AND (
    fp.prefer_organic = 1
    OR fp.harvest_window_days IS NOT NULL
    OR EXISTS (SELECT 1 FROM farmer_profile_banned_ingredients bi WHERE bi.farmer_id = fp.farmer_id)
  );

-- C) farm_bases.risk_tags_json / risk_items_json
-- C1: risk_tags_json 仅主表有值，子表为空
SELECT
  COUNT(*) AS base_count_only_risk_tags_json
FROM farm_bases fb
WHERE JSON_VALID(fb.risk_tags_json)
  AND JSON_LENGTH(fb.risk_tags_json) > 0
  AND NOT EXISTS (
    SELECT 1 FROM farm_base_risk_tags rt
    WHERE rt.farmer_id = fb.farmer_id AND rt.base_id = fb.base_id
  );

-- C2: risk_items_json 仅主表有值，子表为空
SELECT
  COUNT(*) AS base_count_only_risk_items_json
FROM farm_bases fb
WHERE JSON_VALID(fb.risk_items_json)
  AND JSON_LENGTH(fb.risk_items_json) > 0
  AND NOT EXISTS (
    SELECT 1 FROM farm_base_risk_items ri
    WHERE ri.farmer_id = fb.farmer_id AND ri.base_id = fb.base_id
  );

-- C3: risk_tags/risk_items 双存
SELECT
  COUNT(*) AS base_count_risk_json_dual_store
FROM farm_bases fb
WHERE (
    (JSON_VALID(fb.risk_tags_json) AND JSON_LENGTH(fb.risk_tags_json) > 0)
    OR (JSON_VALID(fb.risk_items_json) AND JSON_LENGTH(fb.risk_items_json) > 0)
  )
  AND (
    EXISTS (SELECT 1 FROM farm_base_risk_tags rt WHERE rt.farmer_id = fb.farmer_id AND rt.base_id = fb.base_id)
    OR EXISTS (SELECT 1 FROM farm_base_risk_items ri WHERE ri.farmer_id = fb.farmer_id AND ri.base_id = fb.base_id)
  );

-- D) farm_base_risk_items.risk_code/risk_level/risk_message
-- D1: payload 不完整但结构化列有值（仍依赖结构化兜底）
SELECT
  COUNT(*) AS risk_item_count_payload_incomplete_structured_present
FROM farm_base_risk_items ri
WHERE (
    JSON_EXTRACT(ri.payload_json, '$.code') IS NULL
    OR JSON_EXTRACT(ri.payload_json, '$.level') IS NULL
    OR JSON_EXTRACT(ri.payload_json, '$.reason') IS NULL
  )
  AND (
    NULLIF(TRIM(COALESCE(ri.risk_code, '')), '') IS NOT NULL
    OR NULLIF(TRIM(COALESCE(ri.risk_level, '')), '') IS NOT NULL
    OR NULLIF(TRIM(COALESCE(ri.risk_message, '')), '') IS NOT NULL
  );

-- D2: 结构化列仍有残留值（用于评估清洗规模）
SELECT
  COUNT(*) AS risk_item_count_structured_non_null
FROM farm_base_risk_items ri
WHERE
  NULLIF(TRIM(COALESCE(ri.risk_code, '')), '') IS NOT NULL
  OR NULLIF(TRIM(COALESCE(ri.risk_level, '')), '') IS NOT NULL
  OR NULLIF(TRIM(COALESCE(ri.risk_message, '')), '') IS NOT NULL;

-- E) farm_bases.extra_json legacy 键残留
-- E1: 仅 legacy lat/lon 有值，显式列为空
SELECT
  COUNT(*) AS base_count_only_legacy_latlon
FROM farm_bases fb
WHERE fb.latitude IS NULL
  AND fb.longitude IS NULL
  AND (
    JSON_EXTRACT(fb.extra_json, '$.lat') IS NOT NULL
    OR JSON_EXTRACT(fb.extra_json, '$.lon') IS NOT NULL
  );

-- E2: 仅 legacy weather 键有值，新键为空
SELECT
  COUNT(*) AS base_count_only_legacy_weather_keys
FROM farm_bases fb
WHERE
  JSON_EXTRACT(fb.extra_json, '$.weather_temperature_2m') IS NULL
  AND JSON_EXTRACT(fb.extra_json, '$.weather_wind_speed_10m') IS NULL
  AND JSON_EXTRACT(fb.extra_json, '$.last_weather_refresh_at') IS NULL
  AND (
    JSON_EXTRACT(fb.extra_json, '$.temperature_2m') IS NOT NULL
    OR JSON_EXTRACT(fb.extra_json, '$.wind_speed_10m') IS NOT NULL
    OR JSON_EXTRACT(fb.extra_json, '$.weather_refreshed_at') IS NOT NULL
  );

-- E3: legacy 键残留总量
SELECT
  COUNT(*) AS base_count_legacy_keys_present
FROM farm_bases fb
WHERE
  JSON_EXTRACT(fb.extra_json, '$.lat') IS NOT NULL
  OR JSON_EXTRACT(fb.extra_json, '$.lon') IS NOT NULL
  OR JSON_EXTRACT(fb.extra_json, '$.temperature_2m') IS NOT NULL
  OR JSON_EXTRACT(fb.extra_json, '$.wind_speed_10m') IS NOT NULL
  OR JSON_EXTRACT(fb.extra_json, '$.weather_refreshed_at') IS NOT NULL;
