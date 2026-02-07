"""
规则诊断知识模块
定义基于规则的番茄病害诊断知识
"""

import uuid

from .kb_store import ensure_kb_files, load_rules, load_symptom_map, save_rules, save_symptom_map


class RuleDiagnosisKnowledge:
    """
    规则诊断知识类
    包含基于规则的病害诊断逻辑
    """
    def __init__(self):
        # 规则诊断知识库（内置默认）
        default_rules = {
            "番茄": {
                "斑点": {
                    "早疫病": {
                        "confidence": 0.88,
                        "explanation": "早疫病在叶片上形成同心轮纹状病斑，边缘有黄色晕圈"
                    },
                    "晚疫病": {
                        "confidence": 0.85,
                        "explanation": "晚疫病在叶片上形成不规则的水渍状病斑"
                    },
                    "细菌性斑点病": {
                        "confidence": 0.82,
                        "explanation": "细菌性斑点病在叶片上形成小的褐色斑点，周围有黄色晕圈"
                    }
                },
                "叶子发黄": {
                    "黄化曲叶病毒病": {
                        "confidence": 0.90,
                        "explanation": "由白粉虱传播的病毒病，导致叶片黄化卷曲"
                    },
                    "早疫病": {
                        "confidence": 0.75,
                        "explanation": "早疫病严重时会导致叶片发黄枯萎"
                    },
                    "晚疫病": {
                        "confidence": 0.78,
                        "explanation": "晚疫病会导致叶片边缘发黄并逐渐扩大"
                    }
                },
                "腐烂": {
                    "晚疫病": {
                        "confidence": 0.95,
                        "explanation": "晚疫病会导致果实和叶片快速腐烂"
                    },
                    "灰霉病": {
                        "confidence": 0.92,
                        "explanation": "灰霉病在潮湿环境下会导致果实和叶片腐烂"
                    }
                },
                "白粉": {
                    "白粉病": {
                        "confidence": 0.93,
                        "explanation": "白粉病在叶片表面形成白色粉状物"
                    },
                    "叶霉病": {
                        "confidence": 0.80,
                        "explanation": "叶霉病在叶片表面形成淡灰色霉层"
                    }
                },
                "卷曲": {
                    "黄化曲叶病毒病": {
                        "confidence": 0.91,
                        "explanation": "病毒病导致叶片卷曲、变小"
                    }
                },
                "霉斑": {
                    "叶霉病": {
                        "confidence": 0.90,
                        "explanation": "叶霉病在叶片背面产生灰褐色霉层"
                    },
                    "灰霉病": {
                        "confidence": 0.85,
                        "explanation": "灰霉病在叶片上形成灰色霉斑"
                    }
                },
                "生长缓慢": {
                    "黄化曲叶病毒病": {
                        "confidence": 0.88,
                        "explanation": "病毒病导致植株生长缓慢，矮化"
                    }
                },
                "变色": {
                    "细菌性斑点病": {
                        "confidence": 0.85,
                        "explanation": "细菌性斑点病导致叶片变色并形成斑点"
                    }
                }
            }
        }
        default_symptom_map = {
            "斑点": ["早疫病", "晚疫病", "细菌性斑点病"],
            "发黄": ["黄化曲叶病毒病", "早疫病", "晚疫病"],
            "腐烂": ["晚疫病", "灰霉病"],
            "白粉": ["白粉病", "叶霉病"],
            "卷曲": ["黄化曲叶病毒病"],
            "枯萎": ["早疫病", "晚疫病"],
            "霉斑": ["叶霉病", "灰霉病"],
            "虫洞": [],
            "变色": ["细菌性斑点病"],
            "生长缓慢": ["黄化曲叶病毒病"],
            "叶斑": ["叶斑病"],
            "花叶": ["花叶病毒病"],
            "螨虫": ["蜘蛛螨"],
            "虫害": ["蜘蛛螨"],
            "靶斑": ["靶斑病"],
        }
        ensure_kb_files()
        rules_data = load_rules()
        if rules_data.get("rules"):
            self.rules = rules_data["rules"]
        else:
            self.rules = self._convert_default_rules(default_rules)
            if self.rules:
                save_rules({"rules": self.rules})
        if self._ensure_rule_ids():
            save_rules({"rules": self.rules})
        symptom_data = load_symptom_map()
        if symptom_data.get("symptom_map"):
            self.symptom_map = symptom_data["symptom_map"]
        else:
            self.symptom_map = default_symptom_map
            save_symptom_map({"symptom_map": self.symptom_map})
    
    def _convert_default_rules(self, defaults):
        rules = []
        for crop_type, symptom_rules in defaults.items():
            for symptom, disease_rules in symptom_rules.items():
                for disease, info in disease_rules.items():
                    rules.append(
                        {
                            "crop_type": crop_type,
                            "symptoms": [symptom],
                            "disease": disease,
                            "confidence": info.get("confidence", 0.5),
                            "evidence": info.get("explanation", ""),
                        }
                    )
        return rules

    def list_rules(self, crop_type=None):
        """列出诊断规则"""
        if not crop_type:
            return list(self.rules)
        return [rule for rule in self.rules if rule.get("crop_type") == crop_type]

    def add_rule(self, crop_type, symptoms, disease, confidence, evidence):
        """新增规则"""
        rule = {
            "rule_id": uuid.uuid4().hex,
            "crop_type": crop_type,
            "symptoms": symptoms,
            "disease": disease,
            "confidence": confidence,
            "evidence": evidence,
        }
        self.rules.append(rule)
        save_rules({"rules": self.rules})
        return rule["rule_id"]

    def update_rule(self, rule_id, crop_type, symptoms, disease, confidence, evidence):
        updated = False
        for rule in self.rules:
            if rule.get("rule_id") == rule_id:
                rule["crop_type"] = crop_type
                rule["symptoms"] = symptoms
                rule["disease"] = disease
                rule["confidence"] = confidence
                rule["evidence"] = evidence
                updated = True
                break
        if updated:
            save_rules({"rules": self.rules})
        return updated

    def get_symptom_map(self):
        return self.symptom_map

    def get_symptom_diseases(self, symptom):
        return self.symptom_map.get(symptom, [])

    def upsert_symptom_mapping(self, symptom, diseases):
        self.symptom_map[symptom] = diseases
        save_symptom_map({"symptom_map": self.symptom_map})

    def list_symptom_map(self):
        return [{"symptom": key, "diseases": value} for key, value in self.symptom_map.items()]
    
    def get_rules_by_symptom(self, crop_type, symptom):
        """根据作物类型和症状获取诊断规则"""
        rules = {}
        for rule in self.list_rules(crop_type):
            if symptom in rule.get("symptoms", []):
                rules[rule.get("disease")] = {
                    "confidence": rule.get("confidence", 0.5),
                    "explanation": rule.get("evidence", ""),
                }
        return rules
    
    def get_diagnosis_info(self, crop_type, symptom, disease_type):
        """获取指定作物、症状和病害的诊断信息"""
        symptom_rules = self.get_rules_by_symptom(crop_type, symptom)
        return symptom_rules.get(disease_type, {})
    
    def add_diagnosis_rule(self, crop_type, symptom, disease_type, confidence, explanation):
        """添加诊断规则"""
        self.add_rule(crop_type, [symptom], disease_type, confidence, explanation)

    def update_diagnosis_rule(self, crop_type, symptom, disease_type, confidence=None, explanation=None):
        """更新诊断规则"""
        updated = False
        for rule in self.rules:
            if (
                rule.get("crop_type") == crop_type
                and symptom in rule.get("symptoms", [])
                and rule.get("disease") == disease_type
            ):
                if confidence is not None:
                    rule["confidence"] = confidence
                if explanation is not None:
                    rule["evidence"] = explanation
                updated = True
        if updated:
            save_rules({"rules": self.rules})
        return updated

    def delete_rules(self, rule_ids):
        remaining = [rule for rule in self.rules if rule.get("rule_id") not in rule_ids]
        deleted = len(self.rules) - len(remaining)
        self.rules = remaining
        if deleted:
            save_rules({"rules": self.rules})
        return deleted

    def delete_rules_by_disease(self, disease):
        remaining = [rule for rule in self.rules if rule.get("disease") != disease]
        deleted = len(self.rules) - len(remaining)
        self.rules = remaining
        if deleted:
            save_rules({"rules": self.rules})
        return deleted

    def remove_disease_from_symptom_map(self, disease):
        removed = 0
        updated = False
        for symptom, diseases in list(self.symptom_map.items()):
            if disease in diseases:
                self.symptom_map[symptom] = [item for item in diseases if item != disease]
                removed += 1
                updated = True
            if symptom in self.symptom_map and not self.symptom_map[symptom]:
                self.symptom_map.pop(symptom, None)
                updated = True
        if updated:
            save_symptom_map({"symptom_map": self.symptom_map})
        return removed

    def _ensure_rule_ids(self):
        changed = False
        for rule in self.rules:
            if not rule.get("rule_id"):
                rule["rule_id"] = uuid.uuid4().hex
                changed = True
        return changed
