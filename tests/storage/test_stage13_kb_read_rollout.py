from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import knowledge_base.kb_store as kb_store
from knowledge_base.kb_manager import KnowledgeBaseManager


class _InMemoryKBMysqlRepo:
    def __init__(self, seed: dict[str, Any] | None = None):
        seed = seed or {}
        self.diseases = json.loads(json.dumps(seed.get("diseases", {"diseases": {}}), ensure_ascii=False))
        self.treatments = json.loads(json.dumps(seed.get("treatments", {"treatments": {}}), ensure_ascii=False))
        self.rules = json.loads(json.dumps(seed.get("rules", {"rules": []}), ensure_ascii=False))
        self.symptom_map = json.loads(json.dumps(seed.get("symptom_map", {"symptom_map": {}}), ensure_ascii=False))

    def load_diseases_mysql(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.diseases, ensure_ascii=False))

    def save_diseases_mysql(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.diseases = json.loads(json.dumps(payload, ensure_ascii=False))
        return self.load_diseases_mysql()

    def load_treatments_mysql(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.treatments, ensure_ascii=False))

    def save_treatments_mysql(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.treatments = json.loads(json.dumps(payload, ensure_ascii=False))
        return self.load_treatments_mysql()

    def load_rules_mysql(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.rules, ensure_ascii=False))

    def save_rules_mysql(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.rules = json.loads(json.dumps(payload, ensure_ascii=False))
        return self.load_rules_mysql()

    def load_symptom_map_mysql(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.symptom_map, ensure_ascii=False))

    def save_symptom_map_mysql(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.symptom_map = json.loads(json.dumps(payload, ensure_ascii=False))
        return self.load_symptom_map_mysql()


def _load_fixture_payloads() -> dict[str, Any]:
    kb_dir = Path("data/kb")
    return {
        "diseases": json.loads((kb_dir / "diseases.json").read_text(encoding="utf-8")),
        "treatments": json.loads((kb_dir / "treatments.json").read_text(encoding="utf-8")),
        "rules": json.loads((kb_dir / "rules.json").read_text(encoding="utf-8")),
        "symptom_map": json.loads((kb_dir / "symptom_map.json").read_text(encoding="utf-8")),
    }


def _install_kb_store(monkeypatch, tmp_path: Path, *, mode: str, repo: _InMemoryKBMysqlRepo) -> dict[str, Any]:
    payloads = _load_fixture_payloads()
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        filename = f"{name}.json" if name != "symptom_map" else "symptom_map.json"
        (kb_dir / filename).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    monkeypatch.setattr(kb_store, "KB_DIR", kb_dir)
    monkeypatch.setattr(kb_store, "DISEASES_PATH", kb_dir / "diseases.json")
    monkeypatch.setattr(kb_store, "TREATMENTS_PATH", kb_dir / "treatments.json")
    monkeypatch.setattr(kb_store, "RULES_PATH", kb_dir / "rules.json")
    monkeypatch.setattr(kb_store, "SYMPTOM_MAP_PATH", kb_dir / "symptom_map.json")
    monkeypatch.setattr(kb_store, "KB_STORE_MODE", mode)
    monkeypatch.setattr(
        kb_store,
        "_get_mysql_repo",
        lambda: {
            "load_diseases_mysql": repo.load_diseases_mysql,
            "save_diseases_mysql": repo.save_diseases_mysql,
            "load_treatments_mysql": repo.load_treatments_mysql,
            "save_treatments_mysql": repo.save_treatments_mysql,
            "load_rules_mysql": repo.load_rules_mysql,
            "save_rules_mysql": repo.save_rules_mysql,
            "load_symptom_map_mysql": repo.load_symptom_map_mysql,
            "save_symptom_map_mysql": repo.save_symptom_map_mysql,
        },
    )
    return payloads


def test_kb_dual_mode_reads_file_and_dual_writes(monkeypatch, tmp_path: Path) -> None:
    repo = _InMemoryKBMysqlRepo()
    payloads = _install_kb_store(monkeypatch, tmp_path, mode="dual", repo=repo)

    assert kb_store.load_diseases() == payloads["diseases"]
    assert kb_store.load_treatments() == payloads["treatments"]
    assert kb_store.load_rules() == payloads["rules"]
    assert kb_store.load_symptom_map() == payloads["symptom_map"]

    new_diseases = json.loads(json.dumps(payloads["diseases"], ensure_ascii=False))
    new_diseases["diseases"]["测试病害"] = {"description": "测试描述", "image_labels": ["Test___disease"]}
    kb_store.save_diseases(new_diseases)
    assert repo.load_diseases_mysql()["diseases"]["测试病害"]["description"] == "测试描述"

    new_treatments = json.loads(json.dumps(payloads["treatments"], ensure_ascii=False))
    new_treatments["treatments"]["测试病害"] = {"treatment": "喷施A", "prevention": "加强通风", "actions": {}, "ingredients": ["A"]}
    kb_store.save_treatments(new_treatments)
    assert repo.load_treatments_mysql()["treatments"]["测试病害"]["treatment"] == "喷施A"

    new_rules = json.loads(json.dumps(payloads["rules"], ensure_ascii=False))
    new_rules["rules"].append({"rule_id": "R999", "crop_type": "番茄", "disease": "测试病害", "symptoms": ["斑点"], "confidence": 0.5, "evidence": "测试规则"})
    kb_store.save_rules(new_rules)
    assert any(item.get("rule_id") == "R999" for item in repo.load_rules_mysql()["rules"])

    new_symptom_map = json.loads(json.dumps(payloads["symptom_map"], ensure_ascii=False))
    new_symptom_map.setdefault("symptom_aliases", {})["测试黄叶"] = "发黄"
    kb_store.save_symptom_map(new_symptom_map)
    assert repo.load_symptom_map_mysql()["symptom_aliases"]["测试黄叶"] == "发黄"



def test_kb_manager_key_behaviors_remain_stable_in_dual_mode(monkeypatch, tmp_path: Path) -> None:
    repo = _InMemoryKBMysqlRepo(_load_fixture_payloads())
    _install_kb_store(monkeypatch, tmp_path, mode="dual", repo=repo)

    manager = KnowledgeBaseManager()

    assert manager.normalize_symptoms(["叶片发黄", "叶子发黄", "卷叶"]) == ["发黄", "卷曲"]
    assert manager.get_candidate_diseases_from_symptoms(["叶片发黄", "卷叶"])

    scores = manager.score_diseases_from_text(
        "番茄",
        ["叶片发黄", "卷叶"],
        growth_stage="VEGETATIVE",
        environment="白粉虱多发",
        facility="温室",
        province="山东",
    )
    assert scores
    assert "黄化曲叶病毒病" in scores

    plan = manager.get_treatment_plan("晚疫病")
    assert plan["treatment"]
    assert "actions" in plan



def test_kb_mysql_mode_matches_file_mode_for_key_manager_behaviors(monkeypatch, tmp_path: Path) -> None:
    payloads = _load_fixture_payloads()
    repo = _InMemoryKBMysqlRepo(seed=payloads)
    _install_kb_store(monkeypatch, tmp_path, mode="file", repo=repo)

    file_manager = KnowledgeBaseManager()
    file_snapshot = {
        "normalized": file_manager.normalize_symptoms(["叶片发黄", "卷叶"]),
        "candidates": file_manager.get_candidate_diseases_from_symptoms(["叶片发黄", "卷叶"]),
        "scores": file_manager.score_diseases_from_text(
            "番茄",
            ["叶片发黄", "卷叶"],
            growth_stage="VEGETATIVE",
            environment="白粉虱多发 高湿",
            facility="温室",
            province="山东",
        ),
        "treatment": file_manager.get_treatment_plan("晚疫病"),
    }

    monkeypatch.setattr(kb_store, "KB_STORE_MODE", "mysql")
    mysql_manager = KnowledgeBaseManager()
    mysql_snapshot = {
        "normalized": mysql_manager.normalize_symptoms(["叶片发黄", "卷叶"]),
        "candidates": mysql_manager.get_candidate_diseases_from_symptoms(["叶片发黄", "卷叶"]),
        "scores": mysql_manager.score_diseases_from_text(
            "番茄",
            ["叶片发黄", "卷叶"],
            growth_stage="VEGETATIVE",
            environment="白粉虱多发 高湿",
            facility="温室",
            province="山东",
        ),
        "treatment": mysql_manager.get_treatment_plan("晚疫病"),
    }

    assert kb_store.load_diseases() == payloads["diseases"]
    assert file_snapshot == mysql_snapshot
    assert mysql_snapshot["treatment"]["actions"]["treatment_plan"]
    assert mysql_snapshot["treatment"]["ingredients"]


def test_kb_parity_verification_script_passes_with_sqlite(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "kb-parity.db"
    command = [
        sys.executable,
        "scripts/verify/verify_kb_file_mysql_parity.py",
        "--reset-schema",
    ]
    env = dict(**__import__("os").environ, DATABASE_URL=f"sqlite:///{sqlite_path}")
    completed = subprocess.run(command, cwd=Path(__file__).resolve().parents[2], env=env, capture_output=True, text=True, check=True)
    assert "[kb-verify] payload parity: ok" in completed.stdout
    assert "[kb-verify] KnowledgeBaseManager parity: ok" in completed.stdout
