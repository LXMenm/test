"""
规则诊断知识模块
定义基于规则的番茄病害诊断知识
"""


class RuleDiagnosisKnowledge:
    """
    规则诊断知识类
    包含基于规则的病害诊断逻辑
    """
    def __init__(self):
        # 规则诊断知识库
        self.diagnosis_rules = {
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
    
    def get_rules_by_crop(self, crop_type):
        """根据作物类型获取诊断规则"""
        return self.diagnosis_rules.get(crop_type, {})
    
    def get_rules_by_symptom(self, crop_type, symptom):
        """根据作物类型和症状获取诊断规则"""
        crop_rules = self.get_rules_by_crop(crop_type)
        return crop_rules.get(symptom, {})
    
    def get_diagnosis_info(self, crop_type, symptom, disease_type):
        """获取指定作物、症状和病害的诊断信息"""
        symptom_rules = self.get_rules_by_symptom(crop_type, symptom)
        return symptom_rules.get(disease_type, {})
    
    def add_diagnosis_rule(self, crop_type, symptom, disease_type, confidence, explanation):
        """添加诊断规则"""
        if crop_type not in self.diagnosis_rules:
            self.diagnosis_rules[crop_type] = {}
        
        if symptom not in self.diagnosis_rules[crop_type]:
            self.diagnosis_rules[crop_type][symptom] = {}
        
        self.diagnosis_rules[crop_type][symptom][disease_type] = {
            "confidence": confidence,
            "explanation": explanation
        }
    
    def update_diagnosis_rule(self, crop_type, symptom, disease_type, confidence=None, explanation=None):
        """更新诊断规则"""
        if (crop_type in self.diagnosis_rules and 
            symptom in self.diagnosis_rules[crop_type] and 
            disease_type in self.diagnosis_rules[crop_type][symptom]):
            
            if confidence is not None:
                self.diagnosis_rules[crop_type][symptom][disease_type]["confidence"] = confidence
            
            if explanation is not None:
                self.diagnosis_rules[crop_type][symptom][disease_type]["explanation"] = explanation
            
            return True
        return False
