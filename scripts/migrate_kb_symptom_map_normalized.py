from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from db import engine  # noqa: E402
from mysql_models import KBSymptomAliasORM, KBSymptomCandidateDiseaseORM, KBSymptomMapORM  # noqa: E402
from repositories.kb_repo_mysql import backfill_symptom_map_normalized_mysql, load_symptom_map_mysql  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill normalized KB symptom-map child tables from existing symptom map data")
    _ = parser.parse_args()

    KBSymptomMapORM.__table__.create(bind=engine, checkfirst=True)
    KBSymptomAliasORM.__table__.create(bind=engine, checkfirst=True)
    KBSymptomCandidateDiseaseORM.__table__.create(bind=engine, checkfirst=True)

    payload = load_symptom_map_mysql()
    stats = backfill_symptom_map_normalized_mysql(payload)

    print("[kb-symptom-map-normalize] migration completed")
    print(f"[kb-symptom-map-normalize] canonical_symptoms={stats['canonical_symptom_count']}")
    print(f"[kb-symptom-map-normalize] aliases={stats['alias_count']}")
    print(f"[kb-symptom-map-normalize] candidate_diseases={stats['candidate_disease_count']}")


if __name__ == "__main__":
    main()
