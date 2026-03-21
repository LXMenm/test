from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

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


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"KB source file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else default


def _assert_dict_of_dicts(payload: dict[str, Any], key: str) -> dict[str, Any]:
    items = payload.get(key)
    if not isinstance(items, dict):
        raise ValueError(f"{key} must be a JSON object")
    for item_key, item_value in items.items():
        if not isinstance(item_value, dict):
            raise ValueError(f"{key}.{item_key} must be a JSON object")
    return items


def _assert_rules(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("rules")
    if not isinstance(items, list):
        raise ValueError("rules must be a JSON array")
    normalized: list[dict[str, Any]] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"rules[{idx}] must be a JSON object")
        if not str(item.get("disease") or "").strip():
            raise ValueError(f"rules[{idx}].disease is required")
        normalized.append(item)
    return normalized


def _assert_symptom_map(payload: dict[str, Any]) -> dict[str, Any]:
    aliases = payload.get("symptom_aliases") or {}
    candidates = payload.get("symptom_candidates") or payload.get("symptom_map") or {}
    symptom_map = payload.get("symptom_map") or candidates
    if not isinstance(aliases, dict):
        raise ValueError("symptom_aliases must be a JSON object")
    if not isinstance(candidates, dict):
        raise ValueError("symptom_candidates must be a JSON object")
    if not isinstance(symptom_map, dict):
        raise ValueError("symptom_map must be a JSON object")
    return {
        "symptom_aliases": aliases,
        "symptom_candidates": candidates,
        "symptom_map": symptom_map,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate KB JSON payloads into MySQL tables")
    parser.add_argument("--kb-dir", default=str(DEFAULT_KB_DIR), help="KB JSON directory")
    args = parser.parse_args()

    kb_dir = Path(args.kb_dir)
    diseases_payload = _load_json(kb_dir / "diseases.json", {"diseases": {}})
    treatments_payload = _load_json(kb_dir / "treatments.json", {"treatments": {}})
    rules_payload = _load_json(kb_dir / "rules.json", {"rules": []})
    symptom_map_payload = _load_json(kb_dir / "symptom_map.json", {"symptom_map": {}})

    diseases = _assert_dict_of_dicts(diseases_payload, "diseases")
    treatments = _assert_dict_of_dicts(treatments_payload, "treatments")
    rules = _assert_rules(rules_payload)
    symptom_map = _assert_symptom_map(symptom_map_payload)

    save_diseases_mysql({"diseases": diseases})
    save_treatments_mysql({"treatments": treatments})
    save_rules_mysql({"rules": rules})
    save_symptom_map_mysql(symptom_map)

    reloaded_diseases = load_diseases_mysql()
    reloaded_treatments = load_treatments_mysql()
    reloaded_rules = load_rules_mysql()
    reloaded_symptom_map = load_symptom_map_mysql()

    if len(reloaded_diseases.get("diseases", {})) != len(diseases):
        raise ValueError("disease count mismatch after migration")
    if len(reloaded_treatments.get("treatments", {})) != len(treatments):
        raise ValueError("treatment count mismatch after migration")
    if len(reloaded_rules.get("rules", [])) != len(rules):
        raise ValueError("rule count mismatch after migration")
    if len(reloaded_symptom_map.get("symptom_map", {})) != len(symptom_map.get("symptom_map", {})):
        raise ValueError("symptom map count mismatch after migration")

    print("[kb-migrate] migration completed")
    print(f"[kb-migrate] diseases={len(diseases)}")
    print(f"[kb-migrate] treatments={len(treatments)}")
    print(f"[kb-migrate] rules={len(rules)}")
    print(f"[kb-migrate] symptom_map={len(symptom_map.get('symptom_map', {}))}")


if __name__ == "__main__":
    main()
