"""
知识库统一管理模块
作为整个知识库系统的入口点，统一管理和调用各个知识库
"""

from .disease_kb import DiseaseKnowledge
from .diagnosis_kb import RuleDiagnosisKnowledge
from .treatment_kb import TreatmentKnowledge


class KnowledgeBaseManager:
    """
    知识库统一管理类
    作为整个知识库系统的入口点，统一管理和调用各个知识库
    """
    def __init__(self):
        # 初始化各个知识库
        self.disease_kb = DiseaseKnowledge()
        self.diagnosis_kb = RuleDiagnosisKnowledge()
        self.treatment_kb = TreatmentKnowledge()
    
    def get_disease_classes(self):
        """
        获取所有病害类别
        
        Returns:
            list: 病害类别列表
        """
        return self.disease_kb.get_disease_classes()
    
    def get_disease_description(self, disease_name):
        """
        获取指定病害的描述
        
        Args:
            disease_name: 病害名称
            
        Returns:
            str: 病害描述
        """
        return self.disease_kb.get_disease_description(disease_name)
    
    def get_possible_diseases_by_symptom(self, symptom):
        """
        根据症状获取可能的病害列表
        
        Args:
            symptom: 症状名称
            
        Returns:
            list: 可能的病害列表
        """
        return self.diagnosis_kb.get_symptom_diseases(symptom)
    
    def rule_diagnosis(self, crop, symptoms):
        """
        基于规则进行病害诊断
        
        Args:
            crop: 作物类型
            symptoms: 症状列表
            
        Returns:
            dict: 诊断结果，包含病害类型、置信度和诊断依据
        """
        if not symptoms:
            return {
                "disease_type": "健康",
                "confidence": 0.99,
                "explanation": "无任何病害症状，植株健康。"
            }
        
        symptoms_set = set(symptoms)
        matched_rules = [
            rule
            for rule in self.diagnosis_kb.list_rules(crop)
            if set(rule.get("symptoms", [])) <= symptoms_set
        ]
        if matched_rules:
            best_rule = max(matched_rules, key=lambda rule: rule.get("confidence", 0))
            return {
                "disease_type": best_rule.get("disease", "未知病害"),
                "confidence": best_rule.get("confidence", 0.5),
                "explanation": f"规则命中：{best_rule.get('evidence', '')}",
            }

        disease_scores = {}
        for symptom in symptoms:
            for disease in self.diagnosis_kb.get_symptom_diseases(symptom):
                disease_scores[disease] = disease_scores.get(disease, 0) + 1

        if not disease_scores:
            return {
                "disease_type": "未知病害",
                "confidence": 0.5,
                "explanation": "无法根据提供的症状确定具体病害类型。",
            }

        best_disease = max(disease_scores, key=disease_scores.get)
        max_confidence = disease_scores[best_disease] / max(len(symptoms), 1)
        merged_explanation = "基于症状映射进行诊断：" + "，".join(symptoms)
        return {
            "disease_type": best_disease,
            "confidence": max_confidence,
            "explanation": merged_explanation,
        }
    
    def get_treatment_plan(self, disease_name):
        """
        获取指定病害的治疗方案
        
        Args:
            disease_name: 病害名称
            
        Returns:
            dict: 治疗方案，包含治疗方法和预防措施
        """
        return self.treatment_kb.get_treatment_plan(disease_name)
    
    def get_treatment(self, disease_name):
        """
        获取指定病害的治疗方法
        
        Args:
            disease_name: 病害名称
            
        Returns:
            str: 治疗方法
        """
        return self.treatment_kb.get_treatment(disease_name)
    
    def get_prevention(self, disease_name):
        """
        获取指定病害的预防措施
        
        Args:
            disease_name: 病害名称
            
        Returns:
            str: 预防措施
        """
        return self.treatment_kb.get_prevention(disease_name)
    
    # 系统管理员管理接口
    def add_disease(self, disease_name, description):
        """
        添加新的病害
        
        Args:
            disease_name: 病害名称
            description: 病害描述
            
        Returns:
            bool: 添加是否成功
        """
        if disease_name in self.disease_kb.disease_classes:
            return False
        self.disease_kb.upsert_disease(disease_name, description)
        self.treatment_kb.upsert_treatment_plan(
            disease_name,
            "暂无方案，请完善知识库",
            "暂无预防建议",
        )
        return True
    
    def update_treatment(self, disease_name, treatment=None, prevention=None):
        """
        更新病害的治疗方案
        
        Args:
            disease_name: 病害名称
            treatment: 治疗方法（可选）
            prevention: 预防措施（可选）
            
        Returns:
            bool: 更新是否成功
        """
        return self.treatment_kb.update_treatment_plan(disease_name, treatment, prevention)
    
    def add_diagnosis_rule(self, crop_type, symptom, disease_type, confidence, explanation):
        """
        添加诊断规则
        
        Args:
            crop_type: 作物类型
            symptom: 症状
            disease_type: 病害类型
            confidence: 置信度
            explanation: 诊断依据
            
        Returns:
            bool: 添加是否成功
        """
        if disease_type not in self.disease_kb.disease_classes:
            return False
        self.diagnosis_kb.add_rule(crop_type, [symptom], disease_type, confidence, explanation)
        return True
    
    def add_symptom_mapping(self, symptom, diseases):
        """
        添加症状到病害的映射
        
        Args:
            symptom: 症状名称
            diseases: 病害列表
            
        Returns:
            bool: 添加是否成功
        """
        for disease in diseases:
            if disease not in self.disease_kb.disease_classes:
                return False
        self.diagnosis_kb.upsert_symptom_mapping(symptom, diseases)
        return True

    def list_diseases(self):
        return self.disease_kb.list_diseases()

    def upsert_disease(self, name, description):
        self.disease_kb.upsert_disease(name, description)

    def delete_disease(self, name):
        return self.disease_kb.delete_disease(name)

    def list_treatments(self):
        return self.treatment_kb.list_treatments()

    def upsert_treatment_plan(self, disease, treatment, prevention):
        self.treatment_kb.upsert_treatment_plan(disease, treatment, prevention)

    def delete_treatment_plan(self, disease):
        return self.treatment_kb.delete_treatment_plan(disease)

    def list_rules(self, crop_type=None):
        return self.diagnosis_kb.list_rules(crop_type)

    def add_rule(self, crop_type, symptoms, disease, confidence, evidence):
        self.diagnosis_kb.add_rule(crop_type, symptoms, disease, confidence, evidence)

    def list_symptom_map(self):
        return self.diagnosis_kb.list_symptom_map()

    def upsert_symptom_mapping(self, symptom, diseases):
        self.diagnosis_kb.upsert_symptom_mapping(symptom, diseases)
