"""
MySQL 农户档案仓储层
负责 FarmerProfileORM / FarmBaseORM 的读写与当前 JSON 结构之间的转换。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, Optional

from sqlalchemy import delete, select

from db import get_db_session
from mysql_models import (
    FarmBaseORM,
    FarmBaseRiskItemORM,
    FarmBaseRiskTagORM,
    FarmerProfileBannedIngredientORM,
    FarmerProfileEquipmentORM,
    FarmerProfileORM,
)


def _datetime_to_iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat() + "Z"
    if isinstance(value, str):
        return value
    return str(value)


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            return None
    return None


def _safe_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _safe_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _safe_bool(value: Any) -> bool:
    return bool(value)


def _safe_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _iter_base_payloads(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        for base_id in sorted(value.keys()):
            item = value.get(base_id)
            if not isinstance(item, dict):
                continue
            base_payload = dict(item)
            if not base_payload.get("base_id"):
                base_payload["base_id"] = str(base_id)
            yield base_payload
        return

    if isinstance(value, list):
        normalized = [item for item in value if isinstance(item, dict)]
        normalized.sort(key=lambda item: str(item.get("base_id") or ""))
        for item in normalized:
            yield dict(item)


def _normalize_risk_tags(value: Any) -> list[str]:
    return [
        str(item).strip()
        for item in _safe_list(value)
        if str(item).strip()
    ]


def _normalize_risk_items(value: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in _safe_list(value):
        if isinstance(item, dict):
            normalized.append(dict(item))
    return normalized


def _extract_constraints(payload: dict[str, Any]) -> dict[str, Any]:
    constraints = _safe_dict(payload.get("constraints"))
    return {
        "prefer_organic": _safe_bool(constraints.get("prefer_organic")),
        "harvest_window_days": _safe_int(constraints.get("harvest_window_days")),
        "banned_ingredients": [
            str(item).strip()
            for item in _safe_list(constraints.get("banned_ingredients"))
            if str(item).strip()
        ],
    }


def _build_constraints_payload(
    profile_row: FarmerProfileORM,
    ingredient_rows: Iterable[FarmerProfileBannedIngredientORM],
) -> dict[str, Any]:
    ingredient_values = [
        str(row.ingredient_name).strip()
        for row in sorted(ingredient_rows, key=lambda item: (item.seq or 0, item.id or 0))
        if str(row.ingredient_name or "").strip()
    ]
    if ingredient_values:
        return {
            "prefer_organic": bool(profile_row.prefer_organic),
            "harvest_window_days": profile_row.harvest_window_days,
            "banned_ingredients": ingredient_values,
        }

    legacy = _safe_dict(profile_row.constraints_json)
    return {
        "prefer_organic": _safe_bool(legacy.get("prefer_organic")),
        "harvest_window_days": _safe_int(legacy.get("harvest_window_days")),
        "banned_ingredients": [
            str(item).strip()
            for item in _safe_list(legacy.get("banned_ingredients"))
            if str(item).strip()
        ],
    }


def _build_equipment_payload(
    profile_row: FarmerProfileORM,
    equipment_rows: Iterable[FarmerProfileEquipmentORM],
) -> list[str]:
    equipment_values = [
        str(row.equipment_code).strip()
        for row in sorted(equipment_rows, key=lambda item: (item.seq or 0, item.id or 0))
        if str(row.equipment_code or "").strip()
    ]
    if equipment_values:
        return equipment_values
    return [str(item).strip() for item in _safe_list(profile_row.equipment_json) if str(item).strip()]


def _risk_item_row_to_dict(row: FarmBaseRiskItemORM) -> dict[str, Any]:
    payload = _safe_dict(row.payload_json)
    code = str(payload.get("code") or row.risk_code or payload.get("label") or "").strip()
    label = str(payload.get("label") or row.risk_code or row.risk_message or "风险项").strip()
    reason = str(payload.get("reason") or row.risk_message or label).strip()
    normalized = dict(payload)
    normalized["code"] = code or label or "RISK_ITEM"
    normalized["label"] = label or normalized["code"]
    normalized["level"] = str(payload.get("level") or row.risk_level or "low").strip() or "low"
    normalized["reason"] = reason or normalized["label"]
    return normalized


def _base_row_to_dict(
    base_row: FarmBaseORM,
    risk_tag_rows: Iterable[FarmBaseRiskTagORM] | None = None,
    risk_item_rows: Iterable[FarmBaseRiskItemORM] | None = None,
) -> dict[str, Any]:
    extra_json = _safe_dict(base_row.extra_json)
    normalized_risk_tags = [
        str(row.risk_tag).strip()
        for row in sorted(risk_tag_rows or [], key=lambda item: (item.risk_tag or "", item.id or 0))
        if str(row.risk_tag or "").strip()
    ]
    normalized_risk_items = [
        _risk_item_row_to_dict(row)
        for row in sorted(risk_item_rows or [], key=lambda item: item.id or 0)
    ]
    return {
        "base_id": base_row.base_id,
        "internal_base_uid": base_row.internal_base_uid,
        "name": base_row.name,
        "location": base_row.location,
        "province": base_row.province,
        "city": base_row.city,
        "district": base_row.district,
        "latitude": base_row.latitude,
        "longitude": base_row.longitude,
        "facility": base_row.facility,
        "environment": base_row.environment,
        "growth_stage": base_row.growth_stage,
        "sowing_date": base_row.sowing_date,
        "weather_snapshot": base_row.weather_snapshot,
        "last_weather_refresh_at": _datetime_to_iso(extra_json.get("last_weather_refresh_at")),
        "weather_temperature_2m": extra_json.get("weather_temperature_2m"),
        "weather_wind_speed_10m": extra_json.get("weather_wind_speed_10m"),
        "relative_humidity_2m": base_row.relative_humidity_2m,
        "precipitation": base_row.precipitation,
        "rain_risk": base_row.rain_risk,
        "risk_tags": normalized_risk_tags or _normalize_risk_tags(base_row.risk_tags_json),
        "risk_reasons": _safe_list(base_row.risk_reasons_json),
        "risk_items": normalized_risk_items or _normalize_risk_items(base_row.risk_items_json),
        "risk_updated_at": _datetime_to_iso(base_row.risk_updated_at),
        "notes": base_row.notes,
    }


def _profile_row_to_dict(
    profile_row: FarmerProfileORM,
    base_rows: Iterable[FarmBaseORM],
    equipment_rows: Iterable[FarmerProfileEquipmentORM],
    ingredient_rows: Iterable[FarmerProfileBannedIngredientORM],
    base_risk_tag_rows: Iterable[FarmBaseRiskTagORM] | None = None,
    base_risk_item_rows: Iterable[FarmBaseRiskItemORM] | None = None,
) -> dict[str, Any]:
    ordered_base_rows = sorted(base_rows, key=lambda item: item.base_id or "")
    risk_tag_map: dict[str, list[FarmBaseRiskTagORM]] = {}
    for row in base_risk_tag_rows or []:
        risk_tag_map.setdefault(str(row.base_id or ""), []).append(row)
    risk_item_map: dict[str, list[FarmBaseRiskItemORM]] = {}
    for row in base_risk_item_rows or []:
        risk_item_map.setdefault(str(row.base_id or ""), []).append(row)
    bases = {
        base_row.base_id: _base_row_to_dict(
            base_row,
            risk_tag_map.get(base_row.base_id or "", []),
            risk_item_map.get(base_row.base_id or "", []),
        )
        for base_row in ordered_base_rows
        if base_row.base_id
    }
    meta_json = _safe_dict(profile_row.meta_json)
    owner_user_id = str(profile_row.owner_user_id or "").strip() or str(meta_json.get("owner_user_id") or "").strip() or profile_row.farmer_id
    return {
        "farmer_id": profile_row.farmer_id,
        "name": profile_row.name,
        "display_name": meta_json.get("display_name") or profile_row.name,
        # 兼容返回字段：role_type 已废弃，不再承载身份语义。
        "role_type": str(profile_row.role_type or meta_json.get("role_type") or "FARMER").strip().upper() or "FARMER",
        "owner_user_id": owner_user_id,
        "schema_version": profile_row.schema_version,
        "updated_at": _datetime_to_iso(profile_row.profile_updated_at),
        "active_base_id": profile_row.active_base_id,
        "confirm_when_low_confidence": profile_row.confirm_when_low_confidence,
        "farm_scale": profile_row.farm_scale,
        "pesticide_access_level": profile_row.pesticide_access_level,
        "equipment": _build_equipment_payload(profile_row, equipment_rows),
        "cultivation_mode": profile_row.cultivation_mode,
        "experience_level": profile_row.experience_level,
        "risk_preference": profile_row.risk_preference,
        "constraints": _build_constraints_payload(profile_row, ingredient_rows),
        "bases": bases,
    }


def get_profile(farmer_id: str) -> Optional[dict[str, Any]]:
    with get_db_session() as session:
        profile_row = session.execute(
            select(FarmerProfileORM).where(FarmerProfileORM.farmer_id == farmer_id)
        ).scalar_one_or_none()
        if profile_row is None:
            return None

        base_rows = session.execute(
            select(FarmBaseORM).where(FarmBaseORM.farmer_id == farmer_id)
        ).scalars().all()
        equipment_rows = session.execute(
            select(FarmerProfileEquipmentORM).where(FarmerProfileEquipmentORM.farmer_id == farmer_id)
        ).scalars().all()
        ingredient_rows = session.execute(
            select(FarmerProfileBannedIngredientORM).where(
                FarmerProfileBannedIngredientORM.farmer_id == farmer_id
            )
        ).scalars().all()
        base_risk_tag_rows = session.execute(
            select(FarmBaseRiskTagORM).where(FarmBaseRiskTagORM.farmer_id == farmer_id)
        ).scalars().all()
        base_risk_item_rows = session.execute(
            select(FarmBaseRiskItemORM).where(FarmBaseRiskItemORM.farmer_id == farmer_id)
        ).scalars().all()
        return _profile_row_to_dict(
            profile_row,
            base_rows,
            equipment_rows,
            ingredient_rows,
            base_risk_tag_rows,
            base_risk_item_rows,
        )


def list_profile_ids() -> list[str]:
    with get_db_session() as session:
        rows = session.execute(
            select(FarmerProfileORM.farmer_id).order_by(FarmerProfileORM.farmer_id.asc())
        ).all()
        return [row[0] for row in rows if row[0]]


def list_all_base_ids() -> dict[str, str]:
    with get_db_session() as session:
        rows = session.execute(
            select(FarmBaseORM.base_id, FarmBaseORM.farmer_id).order_by(FarmBaseORM.base_id.asc())
        ).all()
        return {base_id: farmer_id for base_id, farmer_id in rows if base_id and farmer_id}


def _replace_base_risk_children(
    *,
    session: Any,
    farmer_id: str,
    base_id: str,
    risk_tags: Iterable[str],
    risk_items: Iterable[dict[str, Any]],
) -> tuple[int, int]:
    session.execute(
        delete(FarmBaseRiskTagORM).where(
            FarmBaseRiskTagORM.farmer_id == farmer_id,
            FarmBaseRiskTagORM.base_id == base_id,
        )
    )
    session.execute(
        delete(FarmBaseRiskItemORM).where(
            FarmBaseRiskItemORM.farmer_id == farmer_id,
            FarmBaseRiskItemORM.base_id == base_id,
        )
    )

    tag_count = 0
    for risk_tag in _normalize_risk_tags(list(risk_tags)):
        session.add(
            FarmBaseRiskTagORM(
                farmer_id=farmer_id,
                base_id=base_id,
                risk_tag=risk_tag,
            )
        )
        tag_count += 1

    item_count = 0
    for risk_item in _normalize_risk_items(list(risk_items)):
        payload = dict(risk_item)
        session.add(
            FarmBaseRiskItemORM(
                farmer_id=farmer_id,
                base_id=base_id,
                risk_code=str(payload.get("code") or "").strip() or None,
                risk_level=str(payload.get("level") or "").strip() or None,
                risk_message=str(payload.get("reason") or payload.get("label") or "").strip() or None,
                payload_json=payload,
            )
        )
        item_count += 1

    return tag_count, item_count


def save_profile_payload(payload: dict[str, Any]) -> dict[str, Any]:
    farmer_id = str(payload.get("farmer_id") or "").strip()
    if not farmer_id:
        raise ValueError("payload.farmer_id is required")

    bases_payload = list(_iter_base_payloads(payload.get("bases") or {}))
    constraints_payload = _extract_constraints(payload)
    equipment_payload = [
        str(item).strip()
        for item in _safe_list(payload.get("equipment"))
        if str(item).strip()
    ]

    with get_db_session() as session:
        try:
            profile_row = session.execute(
                select(FarmerProfileORM).where(FarmerProfileORM.farmer_id == farmer_id)
            ).scalar_one_or_none()
            if profile_row is None:
                profile_row = FarmerProfileORM(farmer_id=farmer_id)
                session.add(profile_row)

            profile_row.name = payload.get("name")
            profile_row.schema_version = str(payload.get("schema_version") or "1.2")
            profile_row.profile_updated_at = _parse_datetime(payload.get("updated_at"))
            profile_row.active_base_id = payload.get("active_base_id")
            profile_row.confirm_when_low_confidence = bool(
                payload.get("confirm_when_low_confidence", True)
            )
            profile_row.farm_scale = payload.get("farm_scale")
            profile_row.pesticide_access_level = payload.get("pesticide_access_level")
            profile_row.equipment_json = equipment_payload
            profile_row.cultivation_mode = payload.get("cultivation_mode")
            profile_row.experience_level = payload.get("experience_level")
            profile_row.risk_preference = payload.get("risk_preference")
            meta_json = _safe_dict(profile_row.meta_json)
            meta_json["display_name"] = payload.get("display_name") or payload.get("name") or farmer_id
            # role_type 兼容落库：已废弃，不再参与主业务逻辑。
            role_type = "FARMER"
            owner_user_id = str(payload.get("owner_user_id") or farmer_id).strip() or farmer_id
            profile_row.role_type = role_type
            profile_row.owner_user_id = owner_user_id
            meta_json["role_type"] = role_type
            meta_json["owner_user_id"] = owner_user_id
            profile_row.meta_json = meta_json
            profile_row.constraints_json = {
                "prefer_organic": constraints_payload["prefer_organic"],
                "harvest_window_days": constraints_payload["harvest_window_days"],
                "banned_ingredients": list(constraints_payload["banned_ingredients"]),
            }
            profile_row.prefer_organic = constraints_payload["prefer_organic"]
            profile_row.harvest_window_days = constraints_payload["harvest_window_days"]

            session.execute(delete(FarmBaseORM).where(FarmBaseORM.farmer_id == farmer_id))
            session.execute(delete(FarmBaseRiskTagORM).where(FarmBaseRiskTagORM.farmer_id == farmer_id))
            session.execute(delete(FarmBaseRiskItemORM).where(FarmBaseRiskItemORM.farmer_id == farmer_id))
            session.execute(
                delete(FarmerProfileEquipmentORM).where(FarmerProfileEquipmentORM.farmer_id == farmer_id)
            )
            session.execute(
                delete(FarmerProfileBannedIngredientORM).where(
                    FarmerProfileBannedIngredientORM.farmer_id == farmer_id
                )
            )

            for seq, equipment_code in enumerate(equipment_payload, start=1):
                session.add(
                    FarmerProfileEquipmentORM(
                        farmer_id=farmer_id,
                        equipment_code=equipment_code,
                        seq=seq,
                    )
                )

            for seq, ingredient_name in enumerate(constraints_payload["banned_ingredients"], start=1):
                session.add(
                    FarmerProfileBannedIngredientORM(
                        farmer_id=farmer_id,
                        ingredient_name=ingredient_name,
                        seq=seq,
                    )
                )

            for base_payload in bases_payload:
                base_id = str(base_payload.get("base_id") or "").strip()
                if not base_id:
                    continue
                normalized_risk_tags = _normalize_risk_tags(base_payload.get("risk_tags"))
                normalized_risk_items = _normalize_risk_items(base_payload.get("risk_items"))
                extra_json = _safe_dict(base_payload.get("extra_json"))
                extra_json["last_weather_refresh_at"] = _datetime_to_iso(
                    _parse_datetime(base_payload.get("last_weather_refresh_at"))
                )
                extra_json["weather_temperature_2m"] = base_payload.get("weather_temperature_2m")
                extra_json["weather_wind_speed_10m"] = base_payload.get("weather_wind_speed_10m")
                session.add(
                    FarmBaseORM(
                        farmer_id=farmer_id,
                        base_id=base_id,
                        internal_base_uid=base_payload.get("internal_base_uid"),
                        name=base_payload.get("name"),
                        location=base_payload.get("location"),
                        province=base_payload.get("province"),
                        city=base_payload.get("city"),
                        district=base_payload.get("district"),
                        latitude=base_payload.get("latitude"),
                        longitude=base_payload.get("longitude"),
                        facility=base_payload.get("facility"),
                        environment=base_payload.get("environment"),
                        growth_stage=base_payload.get("growth_stage"),
                        sowing_date=base_payload.get("sowing_date"),
                        weather_snapshot=base_payload.get("weather_snapshot"),
                        relative_humidity_2m=base_payload.get("relative_humidity_2m"),
                        precipitation=base_payload.get("precipitation"),
                        rain_risk=base_payload.get("rain_risk"),
                        risk_tags_json=normalized_risk_tags,
                        risk_reasons_json=_safe_list(base_payload.get("risk_reasons")),
                        risk_items_json=normalized_risk_items,
                        risk_updated_at=_parse_datetime(base_payload.get("risk_updated_at")),
                        notes=base_payload.get("notes"),
                        extra_json=extra_json,
                    )
                )
                _replace_base_risk_children(
                    session=session,
                    farmer_id=farmer_id,
                    base_id=base_id,
                    risk_tags=normalized_risk_tags,
                    risk_items=normalized_risk_items,
                )

            session.commit()

            base_rows = session.execute(
                select(FarmBaseORM).where(FarmBaseORM.farmer_id == farmer_id)
            ).scalars().all()
            equipment_rows = session.execute(
                select(FarmerProfileEquipmentORM).where(FarmerProfileEquipmentORM.farmer_id == farmer_id)
            ).scalars().all()
            ingredient_rows = session.execute(
                select(FarmerProfileBannedIngredientORM).where(
                    FarmerProfileBannedIngredientORM.farmer_id == farmer_id
                )
            ).scalars().all()
            base_risk_tag_rows = session.execute(
                select(FarmBaseRiskTagORM).where(FarmBaseRiskTagORM.farmer_id == farmer_id)
            ).scalars().all()
            base_risk_item_rows = session.execute(
                select(FarmBaseRiskItemORM).where(FarmBaseRiskItemORM.farmer_id == farmer_id)
            ).scalars().all()
            session.refresh(profile_row)
            return _profile_row_to_dict(
                profile_row,
                base_rows,
                equipment_rows,
                ingredient_rows,
                base_risk_tag_rows,
                base_risk_item_rows,
            )
        except Exception:
            session.rollback()
            raise


def backfill_farm_bases_normalized_mysql() -> dict[str, int]:
    with get_db_session() as session:
        try:
            base_rows = session.execute(
                select(FarmBaseORM).order_by(FarmBaseORM.farmer_id.asc(), FarmBaseORM.base_id.asc())
            ).scalars().all()
            session.execute(delete(FarmBaseRiskTagORM))
            session.execute(delete(FarmBaseRiskItemORM))

            risk_tag_count = 0
            risk_item_count = 0
            for base_row in base_rows:
                one_tag_count, one_item_count = _replace_base_risk_children(
                    session=session,
                    farmer_id=str(base_row.farmer_id or "").strip(),
                    base_id=str(base_row.base_id or "").strip(),
                    risk_tags=_normalize_risk_tags(base_row.risk_tags_json),
                    risk_items=_normalize_risk_items(base_row.risk_items_json),
                )
                risk_tag_count += one_tag_count
                risk_item_count += one_item_count

            session.commit()
            return {
                "base_count": len(base_rows),
                "risk_tag_count": risk_tag_count,
                "risk_item_count": risk_item_count,
            }
        except Exception:
            session.rollback()
            raise


def backfill_profile_normalized_mysql(payload: dict[str, Any]) -> dict[str, int]:
    saved = save_profile_payload(payload)
    constraints = _safe_dict(saved.get("constraints"))
    return {
        "equipment_count": len(_safe_list(saved.get("equipment"))),
        "banned_ingredient_count": len(_safe_list(constraints.get("banned_ingredients"))),
        "base_count": len(_safe_dict(saved.get("bases"))),
    }


def delete_profile(farmer_id: str) -> None:
    with get_db_session() as session:
        try:
            session.execute(
                delete(FarmBaseORM).where(FarmBaseORM.farmer_id == farmer_id)
            )
            session.execute(
                delete(FarmBaseRiskTagORM).where(FarmBaseRiskTagORM.farmer_id == farmer_id)
            )
            session.execute(
                delete(FarmBaseRiskItemORM).where(FarmBaseRiskItemORM.farmer_id == farmer_id)
            )
            session.execute(
                delete(FarmerProfileEquipmentORM).where(FarmerProfileEquipmentORM.farmer_id == farmer_id)
            )
            session.execute(
                delete(FarmerProfileBannedIngredientORM).where(
                    FarmerProfileBannedIngredientORM.farmer_id == farmer_id
                )
            )
            session.execute(
                delete(FarmerProfileORM).where(FarmerProfileORM.farmer_id == farmer_id)
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
