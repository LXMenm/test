from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from db import engine  # noqa: E402
from mysql_models import KBTreatmentActionORM, KBTreatmentIngredientORM, KBTreatmentORM  # noqa: E402
from repositories.kb_repo_mysql import backfill_treatments_normalized_mysql, load_treatments_mysql  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill normalized KB treatment child tables from existing treatment data")
    _ = parser.parse_args()

    KBTreatmentORM.__table__.create(bind=engine, checkfirst=True)
    KBTreatmentActionORM.__table__.create(bind=engine, checkfirst=True)
    KBTreatmentIngredientORM.__table__.create(bind=engine, checkfirst=True)

    payload = load_treatments_mysql()
    stats = backfill_treatments_normalized_mysql(payload)

    print("[kb-treatments-normalize] migration completed")
    print(f"[kb-treatments-normalize] diseases={stats['disease_count']}")
    print(f"[kb-treatments-normalize] action_rows={stats['action_count']}")
    print(f"[kb-treatments-normalize] ingredient_rows={stats['ingredient_count']}")


if __name__ == "__main__":
    main()
