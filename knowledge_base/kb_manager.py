"""
知识库统一管理模块
作为整个知识库系统的入口点，统一管理和调用各个知识库
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .disease_kb import DiseaseKnowledge
from .diagnosis_kb import RuleDiagnosisKnowledge
from .treatment_kb import TreatmentKnowledge
from .kb_store import load_diseases, load_symptom_map
from .symptom_discriminators import (
    CONFUSION_GROUPS,
    DISCRIMINATIVE_SYMPTOM_DISEASES,
    GENERIC_SYMPTOMS,
    SYMPTOM_ALIASES,
    build_default_symptom_payload,
)

CANONICAL_DISEASES_10 = ["健康", "早疫病", "晚疫病", "黄化曲叶病毒病", "叶霉病", "细菌性斑点病", "叶斑病", "蜘蛛螨", "靶斑病", "花叶病毒病"]


class KnowledgeBaseManager:
    """知识库统一管理类。"""

    def __init__(self):
        self.disease_kb = DiseaseKnowledge()
        self.diagnosis_kb = RuleDiagnosisKnowledge()
        self.treatment_kb = TreatmentKnowledge()
        self._refresh_unified_views()

    def _refresh_unified_views(self) -> None:
        """加载统一 schema 视图（兼容旧字段）。"""
        diseases_payload = load_diseases().get("diseases", {})
        self.disease_meta: Dict[str, Dict[str, Any]] = {
            str(name): info for name, info in diseases_payload.items() if isinstance(info, dict)
        }
        self.canonical_diseases: List[str] = [d for d in CANONICAL_DISEASES_10 if d in self.disease_meta]

        self.image_label_to_disease: Dict[str, str] = {}
        for disease, meta in self.disease_meta.items():
            labels = meta.get("image_labels") or []
            if isinstance(labels, str):
                labels = [labels]
            for label in labels:
                key = str(label).strip()
                if key and disease in self.canonical_diseases:
                    self.image_label_to_disease[key] = disease

        symptom_payload = load_symptom_map()
        default_payload = build_default_symptom_payload()
        aliases = symptom_payload.get("symptom_aliases") or {}
        candidates = symptom_payload.get("symptom_candidates") or symptom_payload.get("symptom_map") or {}
        self.symptom_aliases: Dict[str, str] = {
            str(k).strip(): str(v).strip() for k, v in aliases.items() if str(k).strip() and str(v).strip()
        }
        for alias, canonical in SYMPTOM_ALIASES.items():
            self.symptom_aliases.setdefault(alias, canonical)
        self.symptom_candidates: Dict[str, List[str]] = {
            str(k).strip(): [str(item).strip() for item in (v or []) if str(item).strip()]
            for k, v in candidates.items()
            if str(k).strip()
        }
        merged_tiers = dict(default_payload.get("symptom_tiers") or {})
        merged_tiers.update(symptom_payload.get("symptom_tiers") or {})
        self.symptom_tiers: Dict[str, str] = {
            str(k).strip(): str(v).strip().lower()
            for k, v in merged_tiers.items()
            if str(k).strip()
        }
        merged_discriminator_groups = dict(default_payload.get("symptom_discriminator_groups") or {})
        merged_discriminator_groups.update(symptom_payload.get("symptom_discriminator_groups") or {})
        self.symptom_discriminator_groups: Dict[str, List[str]] = {
            str(k).strip(): [str(item).strip() for item in (v or []) if str(item).strip()]
            for k, v in merged_discriminator_groups.items()
            if str(k).strip()
        }
        merged_follow_up_hints = dict(default_payload.get("follow_up_hints") or {})
        merged_follow_up_hints.update(symptom_payload.get("follow_up_hints") or {})
        self.follow_up_hints: Dict[str, List[str]] = {
            str(k).strip(): [str(item).strip() for item in (v or []) if str(item).strip()]
            for k, v in merged_follow_up_hints.items()
            if str(k).strip()
        }
        self.confusion_groups: Dict[str, List[str]] = {
            str(k).strip(): [str(item).strip() for item in (v or []) if str(item).strip()]
            for k, v in CONFUSION_GROUPS.items()
            if str(k).strip()
        }

    def get_disease_classes(self):
        return list(self.canonical_diseases)

    def get_disease_description(self, disease_name):
        return self.disease_kb.get_disease_description(disease_name)

    def map_image_label_to_disease(self, label: str) -> str:
        if not label:
            return label
        text = str(label).strip()
        return self.image_label_to_disease.get(text, text)

    def normalize_symptoms(self, symptoms: List[str]) -> List[str]:
        normalized: List[str] = []
        seen = set()
        for symptom in symptoms or []:
            raw = str(symptom).strip()
            if not raw:
                continue
            canonical = self.symptom_aliases.get(raw, raw)
            if canonical not in seen:
                seen.add(canonical)
                normalized.append(canonical)
        return normalized

    @staticmethod
    def has_effective_text_evidence(
        symptoms: List[str],
        growth_stage: Optional[str] = None,
        environment: Optional[str] = None,
        facility: Optional[str] = None,
        province: Optional[str] = None,
    ) -> bool:
        """判断是否存在可用于文本诊断的有效证据。

        注意：文本证据仅来自用户显式症状描述，不包含生长阶段/设施/地域等背景字段。
        这些背景字段应仅参与 prior 分支。
        """
        _ = (growth_stage, environment, facility, province)
        normalized = [str(item).strip() for item in (symptoms or []) if str(item).strip()]
        return bool(normalized)

    def get_candidate_diseases_from_symptoms(self, symptoms: List[str]) -> List[str]:
        score_by_disease: Dict[str, float] = {}
        for symptom in self.normalize_symptoms(symptoms):
            tier = self.symptom_tiers.get(symptom, "generic")
            tier_weight = 2.5 if tier == "discriminative" else 1.0
            for rank, disease in enumerate(self.symptom_candidates.get(symptom, []), start=1):
                if disease in self.canonical_diseases:
                    score_by_disease[disease] = score_by_disease.get(disease, 0.0) + tier_weight / max(rank, 1)
        ranked = sorted(score_by_disease.items(), key=lambda item: item[1], reverse=True)
        return [name for name, _ in ranked]

    def has_discriminative_text_evidence(self, symptoms: List[str]) -> bool:
        normalized = self.normalize_symptoms(symptoms)
        if not normalized:
            return False
        for symptom in normalized:
            tier = self.symptom_tiers.get(symptom, "")
            if tier == "discriminative":
                return True
            if symptom in DISCRIMINATIVE_SYMPTOM_DISEASES:
                return True
        if all(symptom in GENERIC_SYMPTOMS for symptom in normalized):
            return False
        return False

    def generate_text_follow_up_questions(
        self,
        symptoms: List[str],
        text_probs: Optional[Dict[str, float]] = None,
    ) -> List[str]:
        normalized = self.normalize_symptoms(symptoms)
        groups = set()
        for symptom in normalized:
            for group in self.symptom_discriminator_groups.get(symptom, []):
                groups.add(group)
        probs = text_probs or {}
        ranked = sorted(probs.items(), key=lambda item: item[1], reverse=True)
        if len(ranked) >= 2 and abs(ranked[0][1] - ranked[1][1]) <= 0.12:
            top_set = {ranked[0][0], ranked[1][0]}
            for group_name, diseases in self.confusion_groups.items():
                if len(top_set.intersection(set(diseases))) >= 2:
                    groups.add(group_name)

        questions: List[str] = []
        for group in groups:
            for question in self.follow_up_hints.get(group, []):
                if question not in questions:
                    questions.append(question)
        return questions[:6]

    def rerank_text_candidates_with_discriminators(
        self,
        scores: Dict[str, float],
        symptoms: List[str],
    ) -> Dict[str, float]:
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        if len(ranked) < 2:
            return scores
        if abs(ranked[0][1] - ranked[1][1]) > 0.12:
            return scores

        top_names = {ranked[0][0], ranked[1][0], ranked[2][0] if len(ranked) > 2 else ranked[1][0]}
        active_groups = [
            group_name
            for group_name, diseases in self.confusion_groups.items()
            if len(top_names.intersection(set(diseases))) >= 2
        ]
        if not active_groups:
            return scores

        adjusted = dict(scores)
        for symptom in self.normalize_symptoms(symptoms):
            preferred = DISCRIMINATIVE_SYMPTOM_DISEASES.get(symptom, [])
            tier = self.symptom_tiers.get(symptom, "")
            if tier != "discriminative" and not preferred:
                continue
            for disease_name in preferred:
                if disease_name in adjusted:
                    adjusted[disease_name] += 0.15
        total = sum(v for v in adjusted.values() if v > 0)
        if total <= 0:
            return scores
        return {k: max(v, 0.0) / total for k, v in adjusted.items()}

    def get_possible_diseases_by_symptom(self, symptom):
        canonical = self.normalize_symptoms([symptom])
        key = canonical[0] if canonical else str(symptom)
        return self.symptom_candidates.get(key, self.diagnosis_kb.get_symptom_diseases(key))

    def score_diseases_from_text(
        self,
        crop_type: str,
        symptoms: List[str],
        growth_stage: Optional[str] = None,
        environment: Optional[str] = None,
        facility: Optional[str] = None,
        province: Optional[str] = None,
    ) -> Dict[str, float]:
        """KB 驱动文本打分：症状权重 + 生长阶段权重 + 环境权重 + 基础置信度。"""
        normalized_symptoms = self.normalize_symptoms(symptoms)
        # 无症状文本证据时，禁止仅靠背景字段生成 text_probs。
        if not normalized_symptoms:
            return {}
        if not self.has_effective_text_evidence(
            normalized_symptoms,
            growth_stage=growth_stage,
            environment=environment,
            facility=facility,
            province=province,
        ):
            return {}
        rules = self.diagnosis_kb.list_rules(crop_type)
        if not rules:
            return {}

        candidate_pool = self.get_candidate_diseases_from_symptoms(normalized_symptoms)
        if not candidate_pool:
            candidate_pool = [rule.get("disease") for rule in rules if rule.get("disease") in self.canonical_diseases]

        stage = str(growth_stage or "").strip().upper()
        env_text = "\n".join([str(environment or ""), str(facility or ""), str(province or "")]).lower()

        scores: Dict[str, float] = {}
        for rule in rules:
            disease = str(rule.get("disease") or "").strip()
            if not disease or disease not in candidate_pool:
                continue

            base_conf = float(rule.get("base_confidence", rule.get("confidence", 0.2)) or 0.2)
            score = max(base_conf, 0.01)

            symptom_weights = rule.get("symptom_weights") if isinstance(rule.get("symptom_weights"), dict) else {}
            symptoms_any = rule.get("symptoms_any") or rule.get("symptoms") or []
            if not symptom_weights and symptoms_any:
                # 兼容旧规则：平均分配权重
                uniform = 1.0 / max(len(symptoms_any), 1)
                symptom_weights = {str(s): uniform for s in symptoms_any}

            for symptom in normalized_symptoms:
                score += float(symptom_weights.get(symptom, 0.0) or 0.0)

            growth_stage_weights = rule.get("growth_stage_weights") if isinstance(rule.get("growth_stage_weights"), dict) else {}
            score += float(growth_stage_weights.get(stage, 0.0) or 0.0)

            environment_weights = rule.get("environment_weights") if isinstance(rule.get("environment_weights"), dict) else {}
            for hint, weight in environment_weights.items():
                if str(hint).strip().lower() in env_text:
                    score += float(weight or 0.0)

            scores[disease] = max(scores.get(disease, 0.0), score)

        if not scores:
            return {}

        scores = self.rerank_text_candidates_with_discriminators(scores, normalized_symptoms)
        if not self.has_discriminative_text_evidence(normalized_symptoms):
            # 只有粗粒度词时，避免过度自信：向均匀分布轻微回拉
            smooth = 0.15
            uniform = 1.0 / max(len(scores), 1)
            scores = {k: (1 - smooth) * v + smooth * uniform for k, v in scores.items()}

        total = sum(v for v in scores.values() if v > 0)
        if total <= 0:
            return {k: 1.0 / len(scores) for k in scores}
        return {k: v / total for k, v in scores.items() if k in self.canonical_diseases}

    def rule_diagnosis(self, crop, symptoms):
        if not symptoms:
            return {
                "disease_type": "健康",
                "confidence": 0.99,
                "explanation": "无任何病害症状，植株健康。",
            }

        probs = self.score_diseases_from_text(crop, symptoms)
        best = max(probs.items(), key=lambda item: item[1]) if probs else ("未知病害", 0.5)
        return {
            "disease_type": best[0],
            "confidence": float(best[1]),
            "explanation": "KB文本规则打分：" + "，".join(self.normalize_symptoms(symptoms)),
            "text_probs": probs,
            "normalized_symptoms": self.normalize_symptoms(symptoms),
        }

    def get_treatment_plan(self, disease_name):
        return self.treatment_kb.get_treatment_plan(disease_name)

    def get_treatment(self, disease_name):
        return self.treatment_kb.get_treatment(disease_name)

    def get_prevention(self, disease_name):
        return self.treatment_kb.get_prevention(disease_name)

    # 系统管理员管理接口
    def add_disease(self, disease_name, description):
        if disease_name in self.disease_kb.disease_classes:
            return False
        self.disease_kb.upsert_disease(disease_name, description)
        self.treatment_kb.upsert_treatment_plan(
            disease_name,
            "暂无方案，请完善知识库",
            "暂无预防建议",
        )
        self._refresh_unified_views()
        return True

    def update_treatment(self, disease_name, treatment=None, prevention=None, actions=None, ingredients=None):
        return self.treatment_kb.update_treatment_plan(disease_name, treatment, prevention, actions=actions, ingredients=ingredients)

    def add_diagnosis_rule(self, crop_type, symptom, disease_type, confidence, explanation):
        if disease_type not in self.disease_kb.disease_classes:
            return False
        self.diagnosis_kb.add_rule(crop_type, [symptom], disease_type, confidence, explanation)
        return True

    def add_symptom_mapping(self, symptom, diseases):
        for disease in diseases:
            if disease not in self.disease_kb.disease_classes:
                return False
        self.diagnosis_kb.upsert_symptom_mapping(symptom, diseases)
        self._refresh_unified_views()
        return True

    def list_diseases(self):
        return self.disease_kb.list_diseases()

    def upsert_disease(self, name, description):
        self.disease_kb.upsert_disease(name, description)
        self._refresh_unified_views()

    def delete_disease(self, name):
        ok = self.disease_kb.delete_disease(name)
        if ok:
            self._refresh_unified_views()
        return ok

    def list_treatments(self):
        return self.treatment_kb.list_treatments()

    def upsert_treatment_plan(self, disease, treatment, prevention, actions=None, ingredients=None):
        self.treatment_kb.upsert_treatment_plan(disease, treatment, prevention, actions=actions, ingredients=ingredients)

    def delete_treatment_plan(self, disease):
        return self.treatment_kb.delete_treatment_plan(disease)

    def list_rules(self, crop_type=None):
        return self.diagnosis_kb.list_rules(crop_type)

    def add_rule(self, crop_type, symptoms, disease, confidence, evidence):
        return self.diagnosis_kb.add_rule(crop_type, symptoms, disease, confidence, evidence)

    def update_rule(self, rule_id, crop_type, symptoms, disease, confidence, evidence):
        return self.diagnosis_kb.update_rule(rule_id, crop_type, symptoms, disease, confidence, evidence)

    def delete_rules(self, rule_ids):
        return self.diagnosis_kb.delete_rules(rule_ids)

    def delete_rules_by_disease(self, disease):
        return self.diagnosis_kb.delete_rules_by_disease(disease)

    def list_symptom_map(self):
        return self.diagnosis_kb.list_symptom_map()

    def upsert_symptom_mapping(self, symptom, diseases):
        self.diagnosis_kb.upsert_symptom_mapping(symptom, diseases)
        self._refresh_unified_views()

    def remove_disease_from_symptom_map(self, disease):
        return self.diagnosis_kb.remove_disease_from_symptom_map(disease)

    def delete_diseases(self, names):
        deleted = 0
        warnings = []
        for name in names:
            if not self.delete_disease(name):
                continue
            deleted += 1
            self.delete_treatment_plan(name)
            self.delete_rules_by_disease(name)
            self.remove_disease_from_symptom_map(name)
        return {"deleted": deleted, "warnings": warnings}

    def delete_treatments(self, diseases):
        deleted = 0
        for disease in diseases:
            if self.delete_treatment_plan(disease):
                deleted += 1
        return deleted

    def delete_symptom_map_entries(self, symptoms):
        deleted = 0
        for symptom in symptoms:
            if symptom in self.diagnosis_kb.symptom_map:
                self.diagnosis_kb.symptom_map.pop(symptom, None)
                deleted += 1
        if deleted:
            from .kb_store import save_symptom_map

            save_symptom_map({"symptom_map": self.diagnosis_kb.symptom_map})
            self._refresh_unified_views()
        return deleted
