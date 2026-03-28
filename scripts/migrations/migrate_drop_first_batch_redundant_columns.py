from __future__ import annotations

from pathlib import Path
import sys

from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from db import engine  # noqa: E402


DROP_PLAN: dict[str, tuple[str, ...]] = {
    "farmer_profiles": ("equipment_json",),
    "farm_bases": ("risk_tags_json", "risk_items_json"),
    "farm_base_risk_items": ("risk_code", "risk_level", "risk_message"),
}


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    row = conn.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = :table_name
              AND column_name = :column_name
            LIMIT 1
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    ).fetchone()
    return row is not None


def main() -> None:
    dropped: list[str] = []
    skipped: list[str] = []

    with engine.begin() as conn:
        for table_name, columns in DROP_PLAN.items():
            for column_name in columns:
                fq_column = f"{table_name}.{column_name}"
                if not _column_exists(conn, table_name, column_name):
                    skipped.append(fq_column)
                    continue
                conn.execute(text(f"ALTER TABLE `{table_name}` DROP COLUMN `{column_name}`"))
                dropped.append(fq_column)

    print("[drop-first-batch-columns] migration completed")
    print(f"[drop-first-batch-columns] dropped={len(dropped)}")
    for name in dropped:
        print(f"  - dropped: {name}")
    for name in skipped:
        print(f"  - skipped(not found): {name}")


if __name__ == "__main__":
    main()
