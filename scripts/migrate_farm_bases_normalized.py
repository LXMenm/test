from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from db import engine  # noqa: E402
import mysql_models  # noqa: F401,E402
from repositories.profile_repo_mysql import backfill_farm_bases_normalized_mysql  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill normalized farm-base risk child tables from existing farm_bases JSON columns"
    )
    parser.parse_args()

    mysql_models.FarmBaseORM.__table__.create(bind=engine, checkfirst=True)
    mysql_models.FarmBaseRiskTagORM.__table__.create(bind=engine, checkfirst=True)
    mysql_models.FarmBaseRiskItemORM.__table__.create(bind=engine, checkfirst=True)

    stats = backfill_farm_bases_normalized_mysql()

    print("[farm-bases-normalize] migration completed")
    print(f"[farm-bases-normalize] bases={stats['base_count']}")
    print(f"[farm-bases-normalize] risk_tags={stats['risk_tag_count']}")
    print(f"[farm-bases-normalize] risk_items={stats['risk_item_count']}")


if __name__ == "__main__":
    main()
