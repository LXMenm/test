from __future__ import annotations

from typing import Any

from knowledge_base.kb_manager import KnowledgeBaseManager
from repositories.kb_repo_mysql import load_symptom_map_mysql


REQUIRED_CANDIDATES: dict[str, str] = {
    "同心轮纹": "早疫病",
    "叶背白霉": "晚疫病",
    "叶背橄榄绒霉": "叶霉病",
    "黑色小点": "叶斑病",
    "叶背结网": "蜘蛛螨",
    "节间缩短": "黄化曲叶病毒病",
    "明暗相间花叶": "花叶病毒病",
}

REQUIRED_ALIAS_CASES: dict[str, str] = {
    "一圈一圈的病斑": "同心轮纹",
    "叶背有白毛": "叶背白霉",
    "叶背有细网": "叶背结网",
}


def _check_db(payload: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    symptom_candidates = payload.get("symptom_candidates") or {}
    print("\n[DB 检查]")
    for symptom, expected in REQUIRED_CANDIDATES.items():
        candidates = symptom_candidates.get(symptom) or []
        ok = expected in candidates
        marker = "PASS" if ok else "FAIL"
        print(f"- {marker} {symptom} -> {expected}; current={candidates}")
        if not ok:
            failures.append(f"DB 缺失 candidate: {symptom} -> {expected}")
    return failures


def _check_runtime() -> list[str]:
    failures: list[str] = []
    manager = KnowledgeBaseManager()

    print("\n[运行时加载检查]")
    for symptom, expected in REQUIRED_CANDIDATES.items():
        candidates = manager.symptom_candidates.get(symptom) or []
        ok = expected in candidates
        marker = "PASS" if ok else "FAIL"
        print(f"- {marker} symptom_candidates[{symptom!r}] 包含 {expected!r}; current={candidates}")
        if not ok:
            failures.append(f"运行时缺失 candidate: {symptom} -> {expected}")

    print("\n[alias 归一化检查]")
    for alias, canonical in REQUIRED_ALIAS_CASES.items():
        normalized = manager.normalize_symptoms([alias])
        ok = canonical in normalized
        marker = "PASS" if ok else "FAIL"
        print(f"- {marker} normalize({[alias]}) 包含 {canonical!r}; current={normalized}")
        if not ok:
            failures.append(f"alias 归一化失败: {alias} -> {canonical}")

    return failures


def main() -> None:
    failures: list[str] = []
    payload = load_symptom_map_mysql()
    failures.extend(_check_db(payload))
    failures.extend(_check_runtime())

    if failures:
        print("\n[RESULT] FAIL")
        for item in failures:
            print(f"- {item}")
        raise SystemExit(1)

    print("\n[RESULT] PASS: 关键 candidate 与 alias 闭环检查全部通过")


if __name__ == "__main__":
    main()
