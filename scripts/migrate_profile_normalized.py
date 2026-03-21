from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from sqlalchemy import inspect

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from db import engine  # noqa: E402
import mysql_models  # noqa: F401,E402
from repositories.profile_repo_mysql import backfill_profile_normalized_mysql, list_profile_ids, get_profile  # noqa: E402


def _load_payloads_from_profile_table() -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for farmer_id in list_profile_ids():
        payload = get_profile(farmer_id)
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def _load_payloads_from_files(profile_dir: Path) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    if not profile_dir.exists():
        return payloads
    for path in sorted(profile_dir.glob('*.json')):
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def main() -> None:
    parser = argparse.ArgumentParser(description='Backfill normalized profile child tables from existing profile data')
    parser.add_argument('--profile-dir', default='data/profiles', help='Fallback JSON profile directory when profile tables are empty')
    args = parser.parse_args()

    mysql_models.FarmerProfileORM.__table__.create(bind=engine, checkfirst=True)
    mysql_models.FarmerProfileEquipmentORM.__table__.create(bind=engine, checkfirst=True)
    mysql_models.FarmerProfileBannedIngredientORM.__table__.create(bind=engine, checkfirst=True)
    mysql_models.FarmBaseORM.__table__.create(bind=engine, checkfirst=True)

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    use_profile_table = 'farmer_profiles' in tables

    payloads = _load_payloads_from_profile_table() if use_profile_table else []
    if not payloads:
        payloads = _load_payloads_from_files(Path(args.profile_dir))

    profile_count = 0
    equipment_count = 0
    banned_count = 0
    base_count = 0

    for payload in payloads:
        stats = backfill_profile_normalized_mysql(payload)
        profile_count += 1
        equipment_count += stats['equipment_count']
        banned_count += stats['banned_ingredient_count']
        base_count += stats['base_count']

    print('[profile-normalize] migration completed')
    print(f'[profile-normalize] profiles={profile_count}')
    print(f'[profile-normalize] equipment_rows={equipment_count}')
    print(f'[profile-normalize] banned_ingredient_rows={banned_count}')
    print(f'[profile-normalize] base_rows={base_count}')


if __name__ == '__main__':
    main()
