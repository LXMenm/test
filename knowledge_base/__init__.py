"""
番茄病害诊疗系统知识库模块
提供统一的知识库管理接口
"""

from .kb_manager import KnowledgeBaseManager
from .disease_kb import DiseaseKnowledge
from .diagnosis_kb import RuleDiagnosisKnowledge
from .treatment_kb import TreatmentKnowledge

__all__ = [
    "KnowledgeBaseManager",
    "DiseaseKnowledge",
    "RuleDiagnosisKnowledge",
    "TreatmentKnowledge"
]

# 创建全局知识库管理器实例，方便直接导入使用
_kb_manager = None

def get_kb_manager():
    """
    获取全局知识库管理器实例
    
    Returns:
        KnowledgeBaseManager: 知识库管理器实例
    """
    global _kb_manager
    if _kb_manager is None:
        _kb_manager = KnowledgeBaseManager()
    return _kb_manager

# 直接导出常用方法，方便使用
def get_disease_classes():
    """获取所有病害类别"""
    return get_kb_manager().get_disease_classes()

def get_disease_description(disease_name):
    """获取指定病害的描述"""
    return get_kb_manager().get_disease_description(disease_name)

def get_possible_diseases_by_symptom(symptom):
    """根据症状获取可能的病害列表"""
    return get_kb_manager().get_possible_diseases_by_symptom(symptom)

def rule_diagnosis(crop, symptoms):
    """基于规则进行病害诊断"""
    return get_kb_manager().rule_diagnosis(crop, symptoms)

def get_treatment_plan(disease_name):
    """获取指定病害的治疗方案"""
    return get_kb_manager().get_treatment_plan(disease_name)
