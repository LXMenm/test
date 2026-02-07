from __future__ import annotations

import json
from pathlib import Path
from typing import Any

KB_DIR = Path("data/kb")
DISEASES_PATH = KB_DIR / "diseases.json"
TREATMENTS_PATH = KB_DIR / "treatments.json"
RULES_PATH = KB_DIR / "rules.json"
SYMPTOM_MAP_PATH = KB_DIR / "symptom_map.json"


def _atomic_write(path: Path, payload: Any) -> None:
    KB_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp_path.replace(path)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def ensure_kb_files() -> None:
    KB_DIR.mkdir(parents=True, exist_ok=True)
    if not DISEASES_PATH.exists():
        _atomic_write(DISEASES_PATH, {"diseases": {}})
    if not TREATMENTS_PATH.exists():
        _atomic_write(TREATMENTS_PATH, {"treatments": {}})
    if not RULES_PATH.exists():
        _atomic_write(RULES_PATH, {"rules": []})
    if not SYMPTOM_MAP_PATH.exists():
        _atomic_write(SYMPTOM_MAP_PATH, {"symptom_map": {}})


def load_diseases() -> dict:
    ensure_kb_files()
    data = _read_json(DISEASES_PATH, {"diseases": {}})
    return data if isinstance(data, dict) else {"diseases": {}}


def save_diseases(payload: dict) -> None:
    _atomic_write(DISEASES_PATH, payload)


def load_treatments() -> dict:
    ensure_kb_files()
    data = _read_json(TREATMENTS_PATH, {"treatments": {}})
    return data if isinstance(data, dict) else {"treatments": {}}


def save_treatments(payload: dict) -> None:
    _atomic_write(TREATMENTS_PATH, payload)


def load_rules() -> dict:
    ensure_kb_files()
    data = _read_json(RULES_PATH, {"rules": []})
    return data if isinstance(data, dict) else {"rules": []}


def save_rules(payload: dict) -> None:
    _atomic_write(RULES_PATH, payload)


def load_symptom_map() -> dict:
    ensure_kb_files()
    data = _read_json(SYMPTOM_MAP_PATH, {"symptom_map": {}})
    return data if isinstance(data, dict) else {"symptom_map": {}}


def save_symptom_map(payload: dict) -> None:
    _atomic_write(SYMPTOM_MAP_PATH, payload)
