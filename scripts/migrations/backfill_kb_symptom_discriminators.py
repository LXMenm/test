from __future__ import annotations

import json

from knowledge_base.kb_store import load_rules, load_symptom_map, save_rules, save_symptom_map
from knowledge_base.symptom_discriminators import (
    DISCRIMINATIVE_SYMPTOM_DISEASES,
    SYMPTOM_ALIASES,
    build_default_symptom_payload,
)


DEFAULT_RULE_WEIGHTS: dict[str, dict[str, float]] = {
    "早疫病": {"同心轮纹": 1.4, "年轮样病斑": 1.2, "较大圆斑": 1.0, "老叶先发病": 0.9, "斑点": 0.2},
    "晚疫病": {"叶背白霉": 1.5, "水渍状快速扩展": 1.2, "油浸样病斑": 1.1, "斑点": 0.2},
    "叶霉病": {"叶背橄榄绒霉": 1.6, "绒毛状霉层": 1.2, "上表浅黄斑": 1.0, "斑点": 0.2},
    "叶斑病": {"黑色小点": 1.4, "灰白中心斑": 1.2, "许多小圆斑": 1.0, "斑点": 0.2},
    "蜘蛛螨": {"叶背结网": 1.8, "黄白小点密布": 1.2, "青铜化": 1.1, "斑点": 0.1},
    "靶斑病": {"靶心状病斑": 1.4, "X形裂纹": 1.5, "星形裂纹": 1.2, "斑点": 0.2},
    "黄化曲叶病毒病": {"节间缩短": 1.5, "叶片上卷": 1.3, "矮化丛生": 1.1, "发黄": 0.25, "花叶": 0.2},
    "花叶病毒病": {"明暗相间花叶": 1.5, "斑驳镶嵌": 1.4, "蕨叶样": 1.1, "花叶": 0.25},
    "细菌性斑点病": {"水渍小斑": 1.2, "黄晕小斑": 1.1, "叶片穿孔": 1.2, "斑点": 0.2},
}


def main() -> None:
    payload = load_symptom_map() or {}
    defaults = build_default_symptom_payload()

    symptom_aliases = dict(payload.get("symptom_aliases") or {})
    symptom_candidates = dict(payload.get("symptom_candidates") or payload.get("symptom_map") or {})
    symptom_map = dict(payload.get("symptom_map") or symptom_candidates)

    new_alias_count = 0
    for alias, canonical in SYMPTOM_ALIASES.items():
        if alias not in symptom_aliases:
            new_alias_count += 1
        symptom_aliases[alias] = canonical

    new_canonical_count = 0
    new_candidate_count = 0
    for symptom, diseases in DISCRIMINATIVE_SYMPTOM_DISEASES.items():
        if symptom not in symptom_candidates:
            new_canonical_count += 1
            symptom_candidates[symptom] = []
        for disease in diseases:
            if disease not in symptom_candidates[symptom]:
                symptom_candidates[symptom].append(disease)
                new_candidate_count += 1
        symptom_map.setdefault(symptom, list(symptom_candidates[symptom]))

    merged_payload = {
        "symptom_aliases": symptom_aliases,
        "symptom_candidates": symptom_candidates,
        "symptom_map": symptom_map,
    }
    for key, value in defaults.items():
        existing = payload.get(key)
        merged = dict(existing) if isinstance(existing, dict) else {}
        for k, v in value.items():
            merged.setdefault(k, v)
        merged_payload[key] = merged
    save_symptom_map(merged_payload)

    rules_payload = load_rules() or {}
    rules = rules_payload.get("rules") if isinstance(rules_payload.get("rules"), list) else []
    rule_updated = 0
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        disease_name = str(rule.get("disease") or "").strip()
        target_weights = DEFAULT_RULE_WEIGHTS.get(disease_name)
        if not target_weights:
            continue
        current = rule.get("symptom_weights") if isinstance(rule.get("symptom_weights"), dict) else {}
        changed = False
        for symptom, weight in target_weights.items():
            prev = float(current.get(symptom, 0.0) or 0.0)
            if prev < weight:
                current[symptom] = weight
                changed = True
        if changed:
            rule["symptom_weights"] = current
            rule_updated += 1
    if rule_updated:
        save_rules({"rules": rules})

    print(
        json.dumps(
            {
                "canonical_symptom_added": new_canonical_count,
                "alias_added": new_alias_count,
                "candidate_added": new_candidate_count,
                "rule_updated": rule_updated,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
