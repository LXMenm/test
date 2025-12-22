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
        return self.disease_kb.get_possible_diseases_by_symptom(symptom)
    
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
        
        # 统计每个病害的匹配得分
        disease_scores = {}
        explanations = {}
        
        for symptom in symptoms:
            # 获取该症状下的所有诊断规则
            symptom_rules = self.diagnosis_kb.get_rules_by_symptom(crop, symptom)
            
            for disease, info in symptom_rules.items():
                confidence = info["confidence"]
                explanation = info["explanation"]
                
                # 累加置信度
                if disease in disease_scores:
                    disease_scores[disease] += confidence
                    explanations[disease].append(explanation)
                else:
                    disease_scores[disease] = confidence
                    explanations[disease] = [explanation]
        
        if not disease_scores:
            return {
                "disease_type": "未知病害",
                "confidence": 0.5,
                "explanation": "无法根据提供的症状确定具体病害类型。"
            }
        
        # 计算平均置信度
        for disease in disease_scores:
            disease_scores[disease] /= len(symptoms)
        
        # 选择置信度最高的病害
        best_disease = max(disease_scores, key=disease_scores.get)
        max_confidence = disease_scores[best_disease]
        
        # 合并所有诊断依据
        merged_explanation = "基于以下症状和规则进行诊断：" + "\n".join(
            f"- {symptom}：{explanation}" for symptom, explanation in zip(symptoms, explanations[best_disease])
        )
        
        return {
            "disease_type": best_disease,
            "confidence": max_confidence,
            "explanation": merged_explanation
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
        
        # 添加到病害类别列表
        self.disease_kb.disease_classes.append(disease_name)
        
        # 添加病害描述
        self.disease_kb.disease_descriptions[disease_name] = description
        
        # 添加默认治疗方案
        self.treatment_kb.add_treatment_plan(
            disease_name,
            "暂无具体治疗方案，请咨询农业专家。",
            "暂无具体预防措施，请咨询农业专家。"
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
        
        self.diagnosis_kb.add_diagnosis_rule(crop_type, symptom, disease_type, confidence, explanation)
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
        # 验证所有病害是否存在
        for disease in diseases:
            if disease not in self.disease_kb.disease_classes:
                return False
        
        self.disease_kb.add_symptom_mapping(symptom, diseases)
        return True
