from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from config import KB_STORE_MODE

KB_DIR = Path("data/kb")
DISEASES_PATH = KB_DIR / "diseases.json"
TREATMENTS_PATH = KB_DIR / "treatments.json"
RULES_PATH = KB_DIR / "rules.json"
SYMPTOM_MAP_PATH = KB_DIR / "symptom_map.json"
_VALID_KB_STORE_MODES = {"file", "dual", "mysql"}


def _get_mysql_repo() -> dict[str, Callable[..., dict[str, Any]]]:
    from repositories.kb_repo_mysql import (
        load_diseases_mysql,
        load_rules_mysql,
        load_symptom_map_mysql,
        load_treatments_mysql,
        save_diseases_mysql,
        save_rules_mysql,
        save_symptom_map_mysql,
        save_treatments_mysql,
    )

    return {
        "load_diseases_mysql": load_diseases_mysql,
        "save_diseases_mysql": save_diseases_mysql,
        "load_treatments_mysql": load_treatments_mysql,
        "save_treatments_mysql": save_treatments_mysql,
        "load_rules_mysql": load_rules_mysql,
        "save_rules_mysql": save_rules_mysql,
        "load_symptom_map_mysql": load_symptom_map_mysql,
        "save_symptom_map_mysql": save_symptom_map_mysql,
    }


def _store_mode() -> str:
    mode = str(KB_STORE_MODE or "file").strip().lower()
    if mode not in _VALID_KB_STORE_MODES:
        print(f"[KBStore] invalid KB_STORE_MODE={KB_STORE_MODE!r}, fallback to file")
        return "file"
    return mode


def _log(action: str, detail: str | None = None) -> None:
    suffix = f" {detail}" if detail else ""
    print(f"[KBStore:{_store_mode()}] {action}{suffix}")


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


def _load_from_file(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    ensure_kb_files()
    data = _read_json(path, default)
    return data if isinstance(data, dict) else dict(default)


def _load_payload(
    *,
    path: Path,
    default: dict[str, Any],
    mysql_loader_name: str,
) -> dict[str, Any]:
    mode = _store_mode()
    if mode == "mysql":
        _log(f"load {path.name}", "via mysql")
        return _get_mysql_repo()[mysql_loader_name]()

    payload = _load_from_file(path, default)
    if mode == "dual":
        _log(f"load {path.name}", "via file (dual-read)")
    return payload


def _save_payload(
    payload: dict[str, Any],
    *,
    path: Path,
    mysql_saver_name: str,
) -> None:
    mode = _store_mode()
    if mode == "mysql":
        _log(f"save {path.name}", "via mysql")
        _get_mysql_repo()[mysql_saver_name](payload)
        return

    _log(f"save {path.name}", "via file")
    _atomic_write(path, payload)
    if mode == "dual":
        _log(f"save {path.name}", "dual-write mysql")
        _get_mysql_repo()[mysql_saver_name](payload)


def load_diseases() -> dict:
    return _load_payload(
        path=DISEASES_PATH,
        default={"diseases": {}},
        mysql_loader_name="load_diseases_mysql",
    )


def save_diseases(payload: dict) -> None:
    _save_payload(payload, path=DISEASES_PATH, mysql_saver_name="save_diseases_mysql")


def load_treatments() -> dict:
    return _load_payload(
        path=TREATMENTS_PATH,
        default={"treatments": {}},
        mysql_loader_name="load_treatments_mysql",
    )


def save_treatments(payload: dict) -> None:
    _save_payload(payload, path=TREATMENTS_PATH, mysql_saver_name="save_treatments_mysql")


def load_rules() -> dict:
    return _load_payload(
        path=RULES_PATH,
        default={"rules": []},
        mysql_loader_name="load_rules_mysql",
    )


def save_rules(payload: dict) -> None:
    _save_payload(payload, path=RULES_PATH, mysql_saver_name="save_rules_mysql")


def load_symptom_map() -> dict:
    return _load_payload(
        path=SYMPTOM_MAP_PATH,
        default={"symptom_map": {}},
        mysql_loader_name="load_symptom_map_mysql",
    )


def save_symptom_map(payload: dict) -> None:
    _save_payload(payload, path=SYMPTOM_MAP_PATH, mysql_saver_name="save_symptom_map_mysql")
