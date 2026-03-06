"""
治疗方案知识模块
定义番茄病害的治疗方案和预防措施
"""

from __future__ import annotations

from typing import Any

from .kb_store import ensure_kb_files, load_treatments, save_treatments


_EMPTY_ACTIONS = {
    "immediate_actions": [],
    "treatment_plan": {"FAMILY": [], "MID": [], "ENTERPRISE": []},
    "prevention_plan": [],
    "resistance_management": [],
    "safety_notes": [],
    "follow_up": [],
}


class TreatmentKnowledge:
    """
    治疗方案知识类
    包含病害的治疗方法和预防措施
    """

    def __init__(self):
        # 治疗方案知识库（内置默认）
        default_plans = {
            "健康": {
                "treatment": "番茄目前健康，无需特殊治疗。",
                "prevention": "1. 继续保持良好的栽培管理 2. 定期巡查，及时发现问题 3. 注意环境控制，避免病害发生",
            },
            "早疫病": {
                "treatment": "1. 发病初期：使用百菌清、代森锰锌或嘧菌酯喷雾，每7-10天一次，连续2-3次。 2. 发病严重时：使用肟菌·戊唑醇或苯甲·嘧菌酯，每5-7天一次。",
                "prevention": "1. 轮作倒茬，避免连作 2. 加强栽培管理，合理密植 3. 摘除底部老叶，增加通风 4. 避免浇水过多，保持叶片干燥",
            },
            "晚疫病": {
                "treatment": "1. 发病初期：使用烯酰吗啉、霜脲氰或氟吡菌胺喷雾，每5-7天一次，连续2-3次。 2. 发病严重时：使用霜霉威盐酸盐+氟吡菌胺复配剂。",
                "prevention": "1. 选用抗病品种 2. 避免密植，增加通风透光 3. 雨后及时排水，降低湿度 4. 摘除病果病叶，集中销毁",
            },
            "蜘蛛螨": {
                "treatment": "1. 初发时优先清除重病叶并冲洗叶背。2. 螨量上升时采用针对性药剂并轮换作用机制。",
                "prevention": "1. 控制棚内高温干燥环境 2. 提高天敌保育比例 3. 定期巡查叶背虫量",
            },
            "未知病害": {
                "treatment": "建议咨询当地番茄病害防治专家，根据实际情况制定具体治疗方案。",
                "prevention": "1. 加强田间管理，保持植株健康 2. 定期巡查，及时发现问题 3. 注意环境控制，避免病害发生 4. 选用抗病品种",
            },
        }
        ensure_kb_files()
        data = load_treatments()
        plans = data.get("treatments") if isinstance(data, dict) else None
        if isinstance(plans, dict) and plans:
            self.treatment_plans = {k: self._normalize_entry(v) for k, v in plans.items()}
        else:
            self.treatment_plans = {k: self._normalize_entry(v) for k, v in default_plans.items()}
            save_treatments({"treatments": self.treatment_plans})

    def _normalize_actions(self, actions: Any) -> dict:
        normalized = {
            "immediate_actions": [],
            "treatment_plan": {"FAMILY": [], "MID": [], "ENTERPRISE": []},
            "prevention_plan": [],
            "resistance_management": [],
            "safety_notes": [],
            "follow_up": [],
        }
        if not isinstance(actions, dict):
            return normalized

        def _to_list(value: Any) -> list[str]:
            if not isinstance(value, list):
                return []
            return [str(item).strip() for item in value if str(item).strip()]

        normalized["immediate_actions"] = _to_list(actions.get("immediate_actions"))
        tp = actions.get("treatment_plan")
        if isinstance(tp, dict):
            normalized["treatment_plan"] = {
                "FAMILY": _to_list(tp.get("FAMILY")),
                "MID": _to_list(tp.get("MID")),
                "ENTERPRISE": _to_list(tp.get("ENTERPRISE")),
            }
        normalized["prevention_plan"] = _to_list(actions.get("prevention_plan"))
        normalized["resistance_management"] = _to_list(actions.get("resistance_management"))
        normalized["safety_notes"] = _to_list(actions.get("safety_notes"))
        normalized["follow_up"] = _to_list(actions.get("follow_up"))
        return normalized

    def _normalize_entry(self, entry: Any) -> dict:
        entry = entry if isinstance(entry, dict) else {}
        treatment = str(entry.get("treatment") or "暂无方案，请完善知识库").strip()
        prevention = str(entry.get("prevention") or "暂无预防建议").strip()
        ingredients_raw = entry.get("ingredients")
        ingredients = [str(item).strip() for item in (ingredients_raw if isinstance(ingredients_raw, list) else []) if str(item).strip()]
        return {
            "treatment": treatment,
            "prevention": prevention,
            "actions": self._normalize_actions(entry.get("actions")),
            "ingredients": sorted(set(ingredients)),
        }

    def _save(self) -> None:
        save_treatments({"treatments": self.treatment_plans})

    def get_treatment_plan(self, disease_type):
        """获取指定病害的治疗方案（兼容旧字段，补齐 actions/ingredients）"""
        plan = self.treatment_plans.get(disease_type)
        if not isinstance(plan, dict):
            plan = {
                "treatment": "暂无方案，请完善知识库",
                "prevention": "暂无预防建议",
                "actions": dict(_EMPTY_ACTIONS),
                "ingredients": [],
            }
        return self._normalize_entry(plan)

    def get_treatment(self, disease_type):
        """获取指定病害的治疗方法"""
        return self.get_treatment_plan(disease_type)["treatment"]

    def get_prevention(self, disease_type):
        """获取指定病害的预防措施"""
        return self.get_treatment_plan(disease_type)["prevention"]

    def add_treatment_plan(self, disease_type, treatment, prevention, actions=None, ingredients=None):
        """添加治疗方案"""
        self.treatment_plans[disease_type] = self._normalize_entry(
            {
                "treatment": treatment,
                "prevention": prevention,
                "actions": actions,
                "ingredients": ingredients,
            }
        )
        self._save()

    def update_treatment_plan(self, disease_type, treatment=None, prevention=None, actions=None, ingredients=None):
        """更新治疗方案（支持部分更新，未提供的字段沿用旧值）"""
        if disease_type not in self.treatment_plans:
            return False
        current = self.get_treatment_plan(disease_type)
        next_payload = {
            "treatment": current["treatment"] if treatment is None else treatment,
            "prevention": current["prevention"] if prevention is None else prevention,
            "actions": current.get("actions") if actions is None else actions,
            "ingredients": current.get("ingredients") if ingredients is None else ingredients,
        }
        self.treatment_plans[disease_type] = self._normalize_entry(next_payload)
        self._save()
        return True

    def upsert_treatment_plan(self, disease_type, treatment, prevention, actions=None, ingredients=None):
        """新增或更新治疗方案（默认合并保留 actions/ingredients）"""
        existing = self.get_treatment_plan(disease_type) if disease_type in self.treatment_plans else None
        merged_actions = existing.get("actions") if (existing and actions is None) else actions
        merged_ingredients = existing.get("ingredients") if (existing and ingredients is None) else ingredients
        self.treatment_plans[disease_type] = self._normalize_entry(
            {
                "treatment": treatment,
                "prevention": prevention,
                "actions": merged_actions,
                "ingredients": merged_ingredients,
            }
        )
        self._save()

    def delete_treatment_plan(self, disease_type):
        """删除治疗方案"""
        if disease_type in self.treatment_plans:
            self.treatment_plans.pop(disease_type, None)
            self._save()
            return True
        return False

    def list_treatments(self):
        """列出治疗方案"""
        items = []
        for disease, plan in self.treatment_plans.items():
            if isinstance(plan, dict):
                normalized = self._normalize_entry(plan)
                items.append(
                    {
                        "disease": disease,
                        "treatment": normalized.get("treatment", ""),
                        "prevention": normalized.get("prevention", ""),
                        "actions": normalized.get("actions", dict(_EMPTY_ACTIONS)),
                        "ingredients": normalized.get("ingredients", []),
                    }
                )
        return items
