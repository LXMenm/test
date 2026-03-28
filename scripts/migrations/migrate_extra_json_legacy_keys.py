from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
import sys
from typing import Any

from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from db import engine, get_db_session  # noqa: E402
import mysql_models  # noqa: F401,E402
from mysql_models import FarmBaseORM  # noqa: E402

LEGACY_COORD_KEYS = ("lat", "lon")
LEGACY_WEATHER_KEYS = ("temperature_2m", "wind_speed_10m", "weather_refreshed_at")
TARGET_WEATHER_KEYS = {
    "temperature_2m": "weather_temperature_2m",
    "wind_speed_10m": "weather_wind_speed_10m",
    "weather_refreshed_at": "last_weather_refresh_at",
}


@dataclass
class CleanupStats:
    scanned_bases: int = 0
    legacy_hit_bases: int = 0
    latitude_backfilled: int = 0
    longitude_backfilled: int = 0
    weather_temperature_2m_backfilled: int = 0
    weather_wind_speed_10m_backfilled: int = 0
    last_weather_refresh_at_backfilled: int = 0
    legacy_keys_removed: int = 0
    coordinate_conflicts: int = 0
    weather_conflicts: int = 0
    invalid_or_skipped: int = 0
    affected_base_pairs: list[str] = field(default_factory=list)
    conflict_base_pairs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scanned_bases": self.scanned_bases,
            "legacy_hit_bases": self.legacy_hit_bases,
            "latitude_backfilled": self.latitude_backfilled,
            "longitude_backfilled": self.longitude_backfilled,
            "weather_temperature_2m_backfilled": self.weather_temperature_2m_backfilled,
            "weather_wind_speed_10m_backfilled": self.weather_wind_speed_10m_backfilled,
            "last_weather_refresh_at_backfilled": self.last_weather_refresh_at_backfilled,
            "legacy_keys_removed": self.legacy_keys_removed,
            "coordinate_conflicts": self.coordinate_conflicts,
            "weather_conflicts": self.weather_conflicts,
            "invalid_or_skipped": self.invalid_or_skipped,
            "affected_base_pairs": self.affected_base_pairs,
            "conflict_base_pairs": self.conflict_base_pairs,
        }


def _safe_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _to_float(value: Any) -> float | None:
    if _is_empty(value):
        return None
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_pair(farmer_id: Any, base_id: Any) -> str:
    return f"({str(farmer_id or '').strip()},{str(base_id or '').strip()})"


def audit_extra_json_legacy_dependency(session: Any) -> dict[str, int]:
    rows = session.execute(select(FarmBaseORM)).scalars().all()
    legacy_keys_present = 0
    legacy_latlon_only = 0
    legacy_weather_only = 0
    legacy_only = 0

    for row in rows:
        extra_json = _safe_dict(row.extra_json)
        has_legacy_coord = any(not _is_empty(extra_json.get(key)) for key in LEGACY_COORD_KEYS)
        has_legacy_weather = any(not _is_empty(extra_json.get(key)) for key in LEGACY_WEATHER_KEYS)
        if has_legacy_coord or has_legacy_weather:
            legacy_keys_present += 1

        lat_only = not _is_empty(extra_json.get("lat")) and row.latitude is None
        lon_only = not _is_empty(extra_json.get("lon")) and row.longitude is None
        is_legacy_latlon_only = lat_only or lon_only

        temp_only = (
            not _is_empty(extra_json.get("temperature_2m"))
            and _is_empty(extra_json.get("weather_temperature_2m"))
        )
        wind_only = (
            not _is_empty(extra_json.get("wind_speed_10m"))
            and _is_empty(extra_json.get("weather_wind_speed_10m"))
        )
        refreshed_only = (
            not _is_empty(extra_json.get("weather_refreshed_at"))
            and _is_empty(extra_json.get("last_weather_refresh_at"))
        )
        is_legacy_weather_only = temp_only or wind_only or refreshed_only

        if is_legacy_latlon_only:
            legacy_latlon_only += 1
        if is_legacy_weather_only:
            legacy_weather_only += 1
        if is_legacy_latlon_only or is_legacy_weather_only:
            legacy_only += 1

    return {
        "scanned_bases": len(rows),
        "legacy_keys_present": legacy_keys_present,
        "legacy_latlon_only": legacy_latlon_only,
        "legacy_weather_only": legacy_weather_only,
        "legacy_only": legacy_only,
    }


def cleanup_extra_json_legacy_keys(*, remove_legacy_keys: bool = True) -> dict[str, Any]:
    stats = CleanupStats()

    with get_db_session() as session:
        try:
            rows = session.execute(select(FarmBaseORM)).scalars().all()
            stats.scanned_bases = len(rows)

            for row in rows:
                extra_json = _safe_dict(row.extra_json)
                if not extra_json:
                    continue

                has_legacy_hit = any(key in extra_json for key in (*LEGACY_COORD_KEYS, *LEGACY_WEATHER_KEYS))
                if not has_legacy_hit:
                    continue
                stats.legacy_hit_bases += 1

                pair = _normalize_pair(row.farmer_id, row.base_id)
                changed = False
                conflict = False

                legacy_lat = extra_json.get("lat")
                legacy_lon = extra_json.get("lon")
                lat_value = _to_float(legacy_lat)
                lon_value = _to_float(legacy_lon)
                if legacy_lat is not None and lat_value is None:
                    stats.invalid_or_skipped += 1
                if legacy_lon is not None and lon_value is None:
                    stats.invalid_or_skipped += 1

                if lat_value is not None:
                    if row.latitude is None:
                        row.latitude = lat_value
                        stats.latitude_backfilled += 1
                        changed = True
                    elif float(row.latitude) != lat_value:
                        stats.coordinate_conflicts += 1
                        conflict = True

                if lon_value is not None:
                    if row.longitude is None:
                        row.longitude = lon_value
                        stats.longitude_backfilled += 1
                        changed = True
                    elif float(row.longitude) != lon_value:
                        stats.coordinate_conflicts += 1
                        conflict = True

                for legacy_key, target_key in TARGET_WEATHER_KEYS.items():
                    legacy_value = extra_json.get(legacy_key)
                    if _is_empty(legacy_value):
                        continue
                    target_value = extra_json.get(target_key)
                    if _is_empty(target_value):
                        extra_json[target_key] = legacy_value
                        changed = True
                        if target_key == "weather_temperature_2m":
                            stats.weather_temperature_2m_backfilled += 1
                        elif target_key == "weather_wind_speed_10m":
                            stats.weather_wind_speed_10m_backfilled += 1
                        elif target_key == "last_weather_refresh_at":
                            stats.last_weather_refresh_at_backfilled += 1
                    elif target_value != legacy_value:
                        stats.weather_conflicts += 1
                        conflict = True

                if remove_legacy_keys:
                    removable = {
                        "lat": row.latitude is not None,
                        "lon": row.longitude is not None,
                        "temperature_2m": not _is_empty(extra_json.get("weather_temperature_2m")),
                        "wind_speed_10m": not _is_empty(extra_json.get("weather_wind_speed_10m")),
                        "weather_refreshed_at": not _is_empty(extra_json.get("last_weather_refresh_at")),
                    }
                    for key, can_remove in removable.items():
                        if can_remove and key in extra_json:
                            extra_json.pop(key, None)
                            stats.legacy_keys_removed += 1
                            changed = True

                if changed:
                    row.extra_json = extra_json
                    if pair not in stats.affected_base_pairs:
                        stats.affected_base_pairs.append(pair)

                if conflict and pair not in stats.conflict_base_pairs:
                    stats.conflict_base_pairs.append(pair)

            session.commit()
            return stats.to_dict()
        except Exception:
            session.rollback()
            raise


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cleanup farm_bases.extra_json legacy keys by conservative backfill to primary fields"
    )
    parser.add_argument(
        "--keep-legacy-keys",
        action="store_true",
        help="Only backfill; do not remove legacy keys.",
    )
    args, _ = parser.parse_known_args()

    mysql_models.FarmBaseORM.__table__.create(bind=engine, checkfirst=True)

    with get_db_session() as session:
        before = audit_extra_json_legacy_dependency(session)

    stats = cleanup_extra_json_legacy_keys(remove_legacy_keys=not args.keep_legacy_keys)

    with get_db_session() as session:
        after = audit_extra_json_legacy_dependency(session)

    print("[extra-json-legacy-cleanup] migration completed")
    for key in (
        "scanned_bases",
        "legacy_hit_bases",
        "latitude_backfilled",
        "longitude_backfilled",
        "weather_temperature_2m_backfilled",
        "weather_wind_speed_10m_backfilled",
        "last_weather_refresh_at_backfilled",
        "legacy_keys_removed",
        "coordinate_conflicts",
        "weather_conflicts",
        "invalid_or_skipped",
    ):
        print(f"[extra-json-legacy-cleanup] {key}={stats[key]}")
    print(f"[extra-json-legacy-cleanup] affected_base_pairs={stats['affected_base_pairs']}")
    print(f"[extra-json-legacy-cleanup] conflict_base_pairs={stats['conflict_base_pairs']}")
    print(f"[extra-json-legacy-cleanup] audit_before={before}")
    print(f"[extra-json-legacy-cleanup] audit_after={after}")


if __name__ == "__main__":
    main()
