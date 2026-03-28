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
from mysql_models import FarmerProfileBannedIngredientORM, FarmerProfileORM  # noqa: E402


@dataclass
class BackfillStats:
    scanned_profiles: int = 0
    constraints_profiles: int = 0
    prefer_organic_backfilled: int = 0
    harvest_window_backfilled: int = 0
    banned_ingredients_inserted: int = 0
    conflict_profiles: int = 0
    invalid_profiles: int = 0
    updated_farmer_ids: list[str] = field(default_factory=list)
    conflict_farmer_ids: list[str] = field(default_factory=list)
    invalid_farmer_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scanned_profiles": self.scanned_profiles,
            "constraints_profiles": self.constraints_profiles,
            "prefer_organic_backfilled": self.prefer_organic_backfilled,
            "harvest_window_backfilled": self.harvest_window_backfilled,
            "banned_ingredients_inserted": self.banned_ingredients_inserted,
            "conflict_profiles": self.conflict_profiles,
            "invalid_profiles": self.invalid_profiles,
            "updated_farmer_ids": self.updated_farmer_ids,
            "conflict_farmer_ids": self.conflict_farmer_ids,
            "invalid_farmer_ids": self.invalid_farmer_ids,
        }


def _safe_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _normalize_ingredient(value: Any) -> str:
    return str(value or "").strip()


def _is_constraints_json_non_empty(value: Any) -> bool:
    data = _safe_dict(value)
    return bool(data)


def audit_constraints_json_dependency(session: Any) -> dict[str, int]:
    profiles = session.execute(select(FarmerProfileORM)).scalars().all()
    constraints_profiles = 0
    constraints_json_only = 0
    constraints_dual_store = 0

    for profile in profiles:
        constraints = _safe_dict(profile.constraints_json)
        if not constraints:
            continue
        constraints_profiles += 1
        has_banned_rows = session.execute(
            select(FarmerProfileBannedIngredientORM.id).where(
                FarmerProfileBannedIngredientORM.farmer_id == profile.farmer_id
            )
        ).first() is not None
        has_primary = bool(profile.prefer_organic) or profile.harvest_window_days is not None or has_banned_rows
        if has_primary:
            constraints_dual_store += 1
        else:
            constraints_json_only += 1

    return {
        "constraints_profiles": constraints_profiles,
        "constraints_json_only": constraints_json_only,
        "constraints_dual_store": constraints_dual_store,
    }


def _backfill_one_profile(session: Any, profile: FarmerProfileORM, stats: BackfillStats) -> None:
    farmer_id = str(profile.farmer_id or "").strip()
    constraints = _safe_dict(profile.constraints_json)
    if not constraints:
        return

    stats.constraints_profiles += 1
    profile_conflict = False
    profile_invalid = False
    profile_changed = False

    prefer_organic_raw = constraints.get("prefer_organic")
    if isinstance(prefer_organic_raw, bool):
        if prefer_organic_raw and not bool(profile.prefer_organic):
            profile.prefer_organic = True
            stats.prefer_organic_backfilled += 1
            profile_changed = True
        elif (not prefer_organic_raw) and bool(profile.prefer_organic):
            profile_conflict = True
    elif prefer_organic_raw is not None:
        profile_invalid = True

    harvest_raw = constraints.get("harvest_window_days")
    harvest_value: int | None = None
    if harvest_raw in (None, ""):
        harvest_value = None
    else:
        try:
            harvest_value = int(harvest_raw)
        except (TypeError, ValueError):
            profile_invalid = True

    if harvest_value is not None:
        if profile.harvest_window_days is None:
            profile.harvest_window_days = harvest_value
            stats.harvest_window_backfilled += 1
            profile_changed = True
        elif int(profile.harvest_window_days) != harvest_value:
            profile_conflict = True

    banned_raw = constraints.get("banned_ingredients")
    normalized_banned: list[str] = []
    if banned_raw is None:
        normalized_banned = []
    elif isinstance(banned_raw, list):
        seen: set[str] = set()
        for item in banned_raw:
            ingredient = _normalize_ingredient(item)
            if not ingredient or ingredient in seen:
                continue
            seen.add(ingredient)
            normalized_banned.append(ingredient)
    else:
        profile_invalid = True

    existing_rows = session.execute(
        select(FarmerProfileBannedIngredientORM).where(
            FarmerProfileBannedIngredientORM.farmer_id == farmer_id
        )
    ).scalars().all()
    existing_names = {_normalize_ingredient(row.ingredient_name) for row in existing_rows}
    max_seq = max([int(row.seq or 0) for row in existing_rows], default=0)

    for ingredient in normalized_banned:
        if ingredient in existing_names:
            continue
        max_seq += 1
        session.add(
            FarmerProfileBannedIngredientORM(
                farmer_id=farmer_id,
                ingredient_name=ingredient,
                seq=max_seq,
            )
        )
        existing_names.add(ingredient)
        stats.banned_ingredients_inserted += 1
        profile_changed = True

    if profile_conflict:
        stats.conflict_profiles += 1
        stats.conflict_farmer_ids.append(farmer_id)
    if profile_invalid:
        stats.invalid_profiles += 1
        stats.invalid_farmer_ids.append(farmer_id)
    if profile_changed:
        stats.updated_farmer_ids.append(farmer_id)


def backfill_constraints_json_to_normalized() -> dict[str, Any]:
    stats = BackfillStats()

    with get_db_session() as session:
        try:
            profiles = session.execute(select(FarmerProfileORM)).scalars().all()
            stats.scanned_profiles = len(profiles)

            for profile in profiles:
                if not _is_constraints_json_non_empty(profile.constraints_json):
                    continue
                _backfill_one_profile(session, profile, stats)

            session.commit()
            return stats.to_dict()
        except Exception:
            session.rollback()
            raise


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill legacy farmer_profiles.constraints_json into normalized constraints fields"
    )
    parser.parse_known_args()

    mysql_models.FarmerProfileORM.__table__.create(bind=engine, checkfirst=True)
    mysql_models.FarmerProfileBannedIngredientORM.__table__.create(bind=engine, checkfirst=True)

    with get_db_session() as session:
        before = audit_constraints_json_dependency(session)

    stats = backfill_constraints_json_to_normalized()

    with get_db_session() as session:
        after = audit_constraints_json_dependency(session)

    print("[constraints-backfill] migration completed")
    print(f"[constraints-backfill] scanned_profiles={stats['scanned_profiles']}")
    print(f"[constraints-backfill] constraints_profiles={stats['constraints_profiles']}")
    print(f"[constraints-backfill] prefer_organic_backfilled={stats['prefer_organic_backfilled']}")
    print(f"[constraints-backfill] harvest_window_backfilled={stats['harvest_window_backfilled']}")
    print(f"[constraints-backfill] banned_ingredients_inserted={stats['banned_ingredients_inserted']}")
    print(f"[constraints-backfill] conflict_profiles={stats['conflict_profiles']}")
    print(f"[constraints-backfill] invalid_profiles={stats['invalid_profiles']}")
    print(f"[constraints-backfill] updated_farmer_ids={stats['updated_farmer_ids']}")
    print(f"[constraints-backfill] conflict_farmer_ids={stats['conflict_farmer_ids']}")
    print(f"[constraints-backfill] invalid_farmer_ids={stats['invalid_farmer_ids']}")
    print(f"[constraints-backfill] audit_before={before}")
    print(f"[constraints-backfill] audit_after={after}")


if __name__ == "__main__":
    main()
