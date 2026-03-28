"""MySQL KB repository preserving file payload shapes for diseases/treatments/rules/symptom_map."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select

from db import get_db_session
from mysql_models import (
    KBDiseaseORM,
    KBRuleORM,
    KBSymptomAliasORM,
    KBSymptomCandidateDiseaseORM,
    KBSymptomMapORM,
    KBTreatmentActionORM,
    KBTreatmentIngredientORM,
    KBTreatmentORM,
)


_PAYLOAD_KEY = "__payload__"


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _clone_dict(value: dict[str, Any]) -> dict[str, Any]:
    return {str(k): v for k, v in value.items()}


def _normalize_symptom_aliases(payload: dict[str, Any]) -> dict[str, str]:
    aliases = _as_dict(payload.get("symptom_aliases"))
    return {
        str(alias).strip(): str(canonical).strip()
        for alias, canonical in aliases.items()
        if str(alias).strip() and str(canonical).strip()
    }


def _normalize_treatment_actions(value: Any) -> dict[str, Any]:
    actions = _as_dict(value)

    def _to_text_list(items: Any) -> list[str]:
        return [str(item).strip() for item in _as_list(items) if str(item).strip()]

    treatment_plan = _as_dict(actions.get("treatment_plan"))
    return {
        "immediate_actions": _to_text_list(actions.get("immediate_actions")),
        "treatment_plan": {
            "FAMILY": _to_text_list(treatment_plan.get("FAMILY")),
            "MID": _to_text_list(treatment_plan.get("MID")),
            "ENTERPRISE": _to_text_list(treatment_plan.get("ENTERPRISE")),
        },
        "prevention_plan": _to_text_list(actions.get("prevention_plan")),
        "resistance_management": _to_text_list(actions.get("resistance_management")),
        "safety_notes": _to_text_list(actions.get("safety_notes")),
        "follow_up": _to_text_list(actions.get("follow_up")),
    }


def _normalize_treatment_ingredients(value: Any) -> list[str]:
    normalized: list[str] = []
    for item in _as_list(value):
        if isinstance(item, dict):
            ingredient_name = str(item.get("ingredient_name") or item.get("name") or "").strip()
        else:
            ingredient_name = str(item).strip()
        if ingredient_name and ingredient_name not in normalized:
            normalized.append(ingredient_name)
    return normalized


def _load_treatments_from_main_rows(rows: list[KBTreatmentORM]) -> dict[str, Any]:
    treatments: dict[str, Any] = {}
    for row in rows:
        entry = _as_dict(row.meta_json)
        entry.setdefault("treatment", row.treatment or "")
        entry.setdefault("prevention", row.prevention or "")
        entry.setdefault("actions", _as_dict(row.actions_json))
        entry.setdefault("ingredients", _as_list(row.ingredients_json))
        treatments[row.disease_name] = entry
    return {"treatments": treatments}


def _replace_treatment_children(
    *,
    session,
    treatments: dict[str, Any],
) -> dict[str, int]:
    session.execute(delete(KBTreatmentActionORM))
    session.execute(delete(KBTreatmentIngredientORM))

    action_count = 0
    ingredient_count = 0
    for disease_name, raw_entry in sorted(treatments.items()):
        disease_key = str(disease_name).strip()
        if not disease_key:
            continue
        entry = _as_dict(raw_entry)
        actions = _normalize_treatment_actions(entry.get("actions"))
        ingredients = _normalize_treatment_ingredients(entry.get("ingredients"))

        action_sections = [
            ("immediate_actions", actions.get("immediate_actions") or []),
            ("prevention_plan", actions.get("prevention_plan") or []),
            ("resistance_management", actions.get("resistance_management") or []),
            ("safety_notes", actions.get("safety_notes") or []),
            ("follow_up", actions.get("follow_up") or []),
            ("treatment_plan.FAMILY", _as_dict(actions.get("treatment_plan")).get("FAMILY") or []),
            ("treatment_plan.MID", _as_dict(actions.get("treatment_plan")).get("MID") or []),
            ("treatment_plan.ENTERPRISE", _as_dict(actions.get("treatment_plan")).get("ENTERPRISE") or []),
        ]
        for action_section, values in action_sections:
            for idx, action_text in enumerate(values, start=1):
                session.add(
                    KBTreatmentActionORM(
                        disease_name=disease_key,
                        action_section=action_section,
                        seq=idx,
                        action_text=action_text,
                    )
                )
                action_count += 1

        for idx, ingredient_name in enumerate(ingredients, start=1):
            session.add(
                KBTreatmentIngredientORM(
                    disease_name=disease_key,
                    seq=idx,
                    ingredient_name=ingredient_name,
                )
            )
            ingredient_count += 1

    return {
        "disease_count": len([name for name in treatments.keys() if str(name).strip()]),
        "action_count": action_count,
        "ingredient_count": ingredient_count,
    }


def _normalize_symptom_candidates(payload: dict[str, Any]) -> dict[str, list[str]]:
    raw_candidates = _as_dict(payload.get("symptom_candidates") or payload.get("symptom_map"))
    normalized: dict[str, list[str]] = {}
    for canonical, diseases in raw_candidates.items():
        canonical_key = str(canonical).strip()
        if not canonical_key:
            continue
        values: list[str] = []
        for disease in _as_list(diseases):
            disease_name = str(disease).strip()
            if disease_name and disease_name not in values:
                values.append(disease_name)
        normalized[canonical_key] = values
    return normalized


def _normalize_legacy_symptom_map(
    payload: dict[str, Any],
    symptom_candidates: dict[str, list[str]],
) -> dict[str, list[str]]:
    raw_map = _as_dict(payload.get("symptom_map") or symptom_candidates)
    normalized: dict[str, list[str]] = {}
    for canonical, diseases in raw_map.items():
        canonical_key = str(canonical).strip()
        if not canonical_key:
            continue
        values: list[str] = []
        for disease in _as_list(diseases):
            disease_name = str(disease).strip()
            if disease_name and disease_name not in values:
                values.append(disease_name)
        normalized[canonical_key] = values
    return normalized


def _load_symptom_map_from_main_rows(rows: list[KBSymptomMapORM]) -> dict[str, Any]:
    symptom_aliases: dict[str, str] = {}
    symptom_candidates: dict[str, list[str]] = {}
    symptom_map: dict[str, list[str]] = {}

    for row in rows:
        if row.symptom_key == _PAYLOAD_KEY:
            payload = _as_dict(row.meta_json)
            return {
                "symptom_aliases": _clone_dict(_as_dict(payload.get("symptom_aliases"))),
                "symptom_candidates": {
                    str(k): _as_list(v) for k, v in _as_dict(payload.get("symptom_candidates")).items()
                },
                "symptom_map": {
                    str(k): _as_list(v) for k, v in _as_dict(payload.get("symptom_map")).items()
                },
            }

        canonical = str(row.canonical_symptom or row.symptom_key or "").strip()
        if not canonical:
            continue
        for alias in _as_list(row.aliases_json):
            alias_key = str(alias).strip()
            if alias_key:
                symptom_aliases[alias_key] = canonical
        candidates = [str(item).strip() for item in _as_list(row.disease_candidates_json) if str(item).strip()]
        symptom_candidates[canonical] = candidates
        meta = _as_dict(row.meta_json)
        raw_symptom_map = meta.get("symptom_map") if isinstance(meta.get("symptom_map"), list) else None
        symptom_map[canonical] = [str(item).strip() for item in (raw_symptom_map if raw_symptom_map is not None else candidates) if str(item).strip()]

    return {
        "symptom_aliases": symptom_aliases,
        "symptom_candidates": symptom_candidates,
        "symptom_map": symptom_map,
    }


def _replace_symptom_map_children(
    *,
    session,
    symptom_aliases: dict[str, str],
    symptom_candidates: dict[str, list[str]],
) -> dict[str, int]:
    session.execute(delete(KBSymptomAliasORM))
    session.execute(delete(KBSymptomCandidateDiseaseORM))

    alias_count = 0
    candidate_count = 0
    for alias, canonical in sorted(symptom_aliases.items()):
        session.add(
            KBSymptomAliasORM(
                symptom_key=canonical,
                alias=alias,
            )
        )
        alias_count += 1

    for canonical, diseases in sorted(symptom_candidates.items()):
        for idx, disease_name in enumerate(diseases, start=1):
            session.add(
                KBSymptomCandidateDiseaseORM(
                    symptom_key=canonical,
                    disease_name=disease_name,
                    rank_no=idx,
                )
            )
            candidate_count += 1

    return {
        "canonical_symptom_count": len(symptom_candidates),
        "alias_count": alias_count,
        "candidate_disease_count": candidate_count,
    }


def load_diseases_mysql() -> dict[str, Any]:
    with get_db_session() as session:
        rows = session.execute(
            select(KBDiseaseORM).order_by(KBDiseaseORM.disease_name.asc())
        ).scalars().all()

    diseases: dict[str, Any] = {}
    for row in rows:
        entry = _as_dict(row.meta_json)
        entry.setdefault("description", row.description or "")
        if row.image_labels_json is not None:
            entry.setdefault("image_labels", _as_list(row.image_labels_json))
        diseases[row.disease_name] = entry
    return {"diseases": diseases}


def save_diseases_mysql(payload: dict[str, Any]) -> dict[str, Any]:
    diseases = _as_dict(payload.get("diseases"))
    with get_db_session() as session:
        try:
            session.execute(delete(KBDiseaseORM))
            for disease_name in sorted(diseases.keys()):
                entry = _as_dict(diseases.get(disease_name))
                session.add(
                    KBDiseaseORM(
                        disease_name=str(disease_name),
                        description=str(entry.get("description") or "").strip() or None,
                        image_labels_json=_as_list(entry.get("image_labels")) or None,
                        meta_json=entry,
                    )
                )
            session.commit()
        except Exception:
            session.rollback()
            raise
    return load_diseases_mysql()


def load_treatments_mysql() -> dict[str, Any]:
    with get_db_session() as session:
        rows = session.execute(
            select(KBTreatmentORM).order_by(KBTreatmentORM.disease_name.asc())
        ).scalars().all()
        action_rows = session.execute(
            select(KBTreatmentActionORM).order_by(
                KBTreatmentActionORM.disease_name.asc(),
                KBTreatmentActionORM.action_section.asc(),
                KBTreatmentActionORM.seq.asc(),
                KBTreatmentActionORM.id.asc(),
            )
        ).scalars().all()
        ingredient_rows = session.execute(
            select(KBTreatmentIngredientORM).order_by(
                KBTreatmentIngredientORM.disease_name.asc(),
                KBTreatmentIngredientORM.seq.asc(),
                KBTreatmentIngredientORM.id.asc(),
            )
        ).scalars().all()

    fallback_payload = _load_treatments_from_main_rows(rows)
    if not action_rows and not ingredient_rows:
        return fallback_payload

    treatments = {
        str(name): _as_dict(entry)
        for name, entry in _as_dict(fallback_payload.get("treatments")).items()
        if str(name).strip()
    }

    if action_rows:
        rebuilt_actions: dict[str, dict[str, Any]] = {}
        for row in action_rows:
            disease_name = str(row.disease_name or "").strip()
            if not disease_name:
                continue
            actions = rebuilt_actions.setdefault(
                disease_name,
                {
                    "immediate_actions": [],
                    "treatment_plan": {"FAMILY": [], "MID": [], "ENTERPRISE": []},
                    "prevention_plan": [],
                    "resistance_management": [],
                    "safety_notes": [],
                    "follow_up": [],
                },
            )
            if row.action_section.startswith("treatment_plan."):
                branch = row.action_section.split(".", 1)[1].strip().upper()
                if branch in {"FAMILY", "MID", "ENTERPRISE"}:
                    actions["treatment_plan"][branch].append(str(row.action_text or "").strip())
            elif row.action_section in actions:
                actions[row.action_section].append(str(row.action_text or "").strip())
        for disease_name, actions in rebuilt_actions.items():
            entry = treatments.setdefault(disease_name, {})
            entry["actions"] = actions

    if ingredient_rows:
        rebuilt_ingredients: dict[str, list[str]] = {}
        for row in ingredient_rows:
            disease_name = str(row.disease_name or "").strip()
            ingredient_name = str(row.ingredient_name or "").strip()
            if not disease_name or not ingredient_name:
                continue
            rebuilt_ingredients.setdefault(disease_name, [])
            if ingredient_name not in rebuilt_ingredients[disease_name]:
                rebuilt_ingredients[disease_name].append(ingredient_name)
        for disease_name, ingredients in rebuilt_ingredients.items():
            entry = treatments.setdefault(disease_name, {})
            entry["ingredients"] = ingredients

    return {"treatments": treatments}


def save_treatments_mysql(payload: dict[str, Any]) -> dict[str, Any]:
    treatments = _as_dict(payload.get("treatments"))
    with get_db_session() as session:
        try:
            _replace_treatment_children(session=session, treatments=treatments)
            session.execute(delete(KBTreatmentORM))
            for disease_name in sorted(treatments.keys()):
                entry = _as_dict(treatments.get(disease_name))
                session.add(
                    KBTreatmentORM(
                        disease_name=str(disease_name),
                        treatment=str(entry.get("treatment") or "").strip() or None,
                        prevention=str(entry.get("prevention") or "").strip() or None,
                        actions_json=_as_dict(entry.get("actions")) or None,
                        ingredients_json=_as_list(entry.get("ingredients")) or None,
                        meta_json=entry,
                    )
                )
            session.commit()
        except Exception:
            session.rollback()
            raise
    return load_treatments_mysql()


def backfill_treatments_normalized_mysql(payload: dict[str, Any]) -> dict[str, int]:
    treatments = _as_dict(payload.get("treatments"))
    with get_db_session() as session:
        try:
            stats = _replace_treatment_children(session=session, treatments=treatments)
            session.commit()
        except Exception:
            session.rollback()
            raise
    return stats


def load_rules_mysql() -> dict[str, Any]:
    with get_db_session() as session:
        rows = session.execute(
            select(KBRuleORM).order_by(KBRuleORM.rule_id.asc(), KBRuleORM.id.asc())
        ).scalars().all()

    rules: list[dict[str, Any]] = []
    for row in rows:
        entry = _as_dict(row.meta_json)
        entry.setdefault("rule_id", row.rule_id)
        entry.setdefault("crop_type", row.crop_type)
        entry.setdefault("disease", row.disease_name)
        symptoms = _as_list(row.symptoms_json)
        if symptoms and "symptoms" not in entry:
            entry["symptoms"] = symptoms
        if row.confidence is not None and "confidence" not in entry:
            entry["confidence"] = row.confidence
        if row.evidence is not None and "evidence" not in entry:
            entry["evidence"] = row.evidence
        if row.growth_stage_weights_json is not None and "growth_stage_weights" not in entry:
            entry["growth_stage_weights"] = _as_dict(row.growth_stage_weights_json)
        if row.environment_weights_json is not None and "environment_weights" not in entry:
            entry["environment_weights"] = _as_dict(row.environment_weights_json)
        rules.append(entry)
    return {"rules": rules}


def save_rules_mysql(payload: dict[str, Any]) -> dict[str, Any]:
    rules = payload.get("rules") if isinstance(payload.get("rules"), list) else []
    with get_db_session() as session:
        try:
            session.execute(delete(KBRuleORM))
            for item in rules:
                entry = _as_dict(item)
                rule_id = str(entry.get("rule_id") or "").strip() or None
                session.add(
                    KBRuleORM(
                        rule_id=rule_id,
                        crop_type=str(entry.get("crop_type") or "").strip() or None,
                        disease_name=str(entry.get("disease") or "").strip(),
                        symptoms_json=_as_list(entry.get("symptoms") or entry.get("symptoms_any")) or None,
                        confidence=entry.get("confidence", entry.get("base_confidence")),
                        evidence=str(entry.get("evidence") or "").strip() or None,
                        growth_stage_weights_json=_as_dict(entry.get("growth_stage_weights")) or None,
                        environment_weights_json=_as_dict(entry.get("environment_weights")) or None,
                        meta_json=entry,
                    )
                )
            session.commit()
        except Exception:
            session.rollback()
            raise
    return load_rules_mysql()


def load_symptom_map_mysql() -> dict[str, Any]:
    with get_db_session() as session:
        rows = session.execute(
            select(KBSymptomMapORM).order_by(KBSymptomMapORM.symptom_key.asc())
        ).scalars().all()
        alias_rows = session.execute(
            select(KBSymptomAliasORM).order_by(KBSymptomAliasORM.symptom_key.asc(), KBSymptomAliasORM.alias.asc())
        ).scalars().all()
        candidate_rows = session.execute(
            select(KBSymptomCandidateDiseaseORM).order_by(
                KBSymptomCandidateDiseaseORM.symptom_key.asc(),
                KBSymptomCandidateDiseaseORM.rank_no.asc(),
                KBSymptomCandidateDiseaseORM.id.asc(),
            )
        ).scalars().all()

    fallback_payload = _load_symptom_map_from_main_rows(rows)
    if not alias_rows and not candidate_rows:
        return fallback_payload

    symptom_aliases = dict(fallback_payload.get("symptom_aliases") or {})
    symptom_candidates = {
        str(k): [str(item).strip() for item in (v or []) if str(item).strip()]
        for k, v in (fallback_payload.get("symptom_candidates") or {}).items()
        if str(k).strip()
    }
    symptom_map = {
        str(k): [str(item).strip() for item in (v or []) if str(item).strip()]
        for k, v in (fallback_payload.get("symptom_map") or {}).items()
        if str(k).strip()
    }

    if alias_rows:
        symptom_aliases = {}
        for row in alias_rows:
            canonical = str(row.symptom_key or "").strip()
            alias_key = str(row.alias or "").strip()
            if canonical and alias_key:
                symptom_aliases[alias_key] = canonical

    if candidate_rows:
        rebuilt_candidates: dict[str, list[str]] = {}
        for row in candidate_rows:
            canonical = str(row.symptom_key or "").strip()
            disease_name = str(row.disease_name or "").strip()
            if not canonical or not disease_name:
                continue
            rebuilt_candidates.setdefault(canonical, [])
            if disease_name not in rebuilt_candidates[canonical]:
                rebuilt_candidates[canonical].append(disease_name)
        for canonical, diseases in rebuilt_candidates.items():
            symptom_candidates[canonical] = diseases
            symptom_map.setdefault(canonical, list(diseases))

    return {
        "symptom_aliases": symptom_aliases,
        "symptom_candidates": symptom_candidates,
        "symptom_map": symptom_map,
    }


def save_symptom_map_mysql(payload: dict[str, Any]) -> dict[str, Any]:
    symptom_aliases = _normalize_symptom_aliases(payload)
    symptom_candidates = _normalize_symptom_candidates(payload)
    legacy_symptom_map = _normalize_legacy_symptom_map(payload, symptom_candidates)

    canonical_keys = set(symptom_candidates.keys()) | set(legacy_symptom_map.keys())
    canonical_keys |= {str(value).strip() for value in symptom_aliases.values() if str(value).strip()}

    reverse_aliases: dict[str, list[str]] = {}
    for alias, canonical in symptom_aliases.items():
        alias_key = str(alias).strip()
        canonical_key = str(canonical).strip()
        if alias_key and canonical_key:
            reverse_aliases.setdefault(canonical_key, []).append(alias_key)

    with get_db_session() as session:
        try:
            _replace_symptom_map_children(
                session=session,
                symptom_aliases=symptom_aliases,
                symptom_candidates=symptom_candidates,
            )
            session.execute(delete(KBSymptomMapORM))
            session.add(
                KBSymptomMapORM(
                    symptom_key=_PAYLOAD_KEY,
                    canonical_symptom=_PAYLOAD_KEY,
                    aliases_json=None,
                    disease_candidates_json=None,
                    meta_json={
                        "symptom_aliases": symptom_aliases,
                        "symptom_candidates": symptom_candidates,
                        "symptom_map": legacy_symptom_map,
                    },
                )
            )
            for canonical in sorted(canonical_keys):
                session.add(
                    KBSymptomMapORM(
                        symptom_key=canonical,
                        canonical_symptom=canonical,
                        aliases_json=sorted(set(reverse_aliases.get(canonical, []))) or None,
                        disease_candidates_json=_as_list(symptom_candidates.get(canonical)) or None,
                        meta_json={
                            "symptom_map": _as_list(legacy_symptom_map.get(canonical)),
                        },
                    )
                )
            session.commit()
        except Exception:
            session.rollback()
            raise
    return load_symptom_map_mysql()


def backfill_symptom_map_normalized_mysql(payload: dict[str, Any]) -> dict[str, int]:
    symptom_aliases = _normalize_symptom_aliases(payload)
    symptom_candidates = _normalize_symptom_candidates(payload)

    with get_db_session() as session:
        try:
            stats = _replace_symptom_map_children(
                session=session,
                symptom_aliases=symptom_aliases,
                symptom_candidates=symptom_candidates,
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
    return stats
