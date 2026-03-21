from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import mysql_models  # noqa: F401,E402
from db import Base, engine  # noqa: E402
from knowledge_base.kb_manager import KnowledgeBaseManager  # noqa: E402
import knowledge_base.kb_store as kb_store  # noqa: E402
from repositories.kb_repo_mysql import (  # noqa: E402
    load_diseases_mysql,
    load_rules_mysql,
    load_symptom_map_mysql,
    load_treatments_mysql,
    save_diseases_mysql,
    save_rules_mysql,
    save_symptom_map_mysql,
    save_treatments_mysql,
)


DEFAULT_KB_DIR = Path("data/kb")
REPRESENTATIVE_CASES = [
    ["叶片发黄", "卷叶"],
    ["小斑点", "叶斑"],
    ["水渍状斑", "腐烂"],
    ["灰色霉层"],
]
REPRESENTATIVE_TREATMENTS = ["晚疫病", "黄化曲叶病毒病", "健康"]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _seed_mysql_payloads(kb_dir: Path) -> None:
    save_diseases_mysql(_read_json(kb_dir / "diseases.json"))
    save_treatments_mysql(_read_json(kb_dir / "treatments.json"))
    save_rules_mysql(_read_json(kb_dir / "rules.json"))
    save_symptom_map_mysql(_read_json(kb_dir / "symptom_map.json"))


def _snapshot(mode: str) -> dict[str, Any]:
    kb_store.KB_STORE_MODE = mode
    manager = KnowledgeBaseManager()
    result: dict[str, Any] = {}
    for symptoms in REPRESENTATIVE_CASES:
        key = "|".join(symptoms)
        result[key] = {
            "normalized": manager.normalize_symptoms(symptoms),
            "candidates": manager.get_candidate_diseases_from_symptoms(symptoms),
            "scores": manager.score_diseases_from_text(
                "番茄",
                symptoms,
                growth_stage="VEGETATIVE",
                environment="白粉虱多发 高湿",
                facility="温室",
                province="山东",
            ),
            "rule": manager.rule_diagnosis("番茄", symptoms),
        }
    for disease in REPRESENTATIVE_TREATMENTS:
        result[f"treatment::{disease}"] = manager.get_treatment_plan(disease)
    return result


def _assert_payload_parity(kb_dir: Path) -> None:
    expected = {
        "diseases": _read_json(kb_dir / "diseases.json"),
        "treatments": _read_json(kb_dir / "treatments.json"),
        "rules": _read_json(kb_dir / "rules.json"),
        "symptom_map": _read_json(kb_dir / "symptom_map.json"),
    }
    actual = {
        "diseases": load_diseases_mysql(),
        "treatments": load_treatments_mysql(),
        "rules": load_rules_mysql(),
        "symptom_map": load_symptom_map_mysql(),
    }
    for key in expected:
        if expected[key] != actual[key]:
            raise AssertionError(f"payload mismatch for {key}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify KB file/mysql parity before mysql-only cutover")
    parser.add_argument("--kb-dir", default=str(DEFAULT_KB_DIR), help="KB JSON directory")
    parser.add_argument(
        "--reset-schema",
        action="store_true",
        help="Drop and recreate all tables before seeding KB payloads",
    )
    args = parser.parse_args()

    kb_dir = Path(args.kb_dir)
    if args.reset_schema:
        Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    _seed_mysql_payloads(kb_dir)
    _assert_payload_parity(kb_dir)

    file_snapshot = _snapshot("file")
    mysql_snapshot = _snapshot("mysql")
    if file_snapshot != mysql_snapshot:
        mismatched_keys = [key for key in file_snapshot if file_snapshot.get(key) != mysql_snapshot.get(key)]
        raise AssertionError(f"KnowledgeBaseManager parity mismatch: {mismatched_keys}")

    treatment = mysql_snapshot["treatment::晚疫病"]
    actions = treatment.get("actions") if isinstance(treatment, dict) else None
    ingredients = treatment.get("ingredients") if isinstance(treatment, dict) else None
    if not isinstance(actions, dict) or not isinstance(ingredients, list):
        raise AssertionError("晚疫病 treatment actions/ingredients shape mismatch")

    print("[kb-verify] DATABASE_URL=", os.getenv("DATABASE_URL", ""), sep="")
    print("[kb-verify] payload parity: ok")
    print("[kb-verify] KnowledgeBaseManager parity: ok")
    print(f"[kb-verify] treatment actions keys={sorted(actions.keys())}")
    print(f"[kb-verify] treatment ingredients={ingredients}")


if __name__ == "__main__":
    main()
