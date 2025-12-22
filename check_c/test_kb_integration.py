"""
测试知识库管理模块与现有系统的集成
"""

from knowledge_base import KnowledgeBaseManager
from diagnosis_model import get_diagnosis_engine
from agents import _get_treatment_from_knowledge_base


def test_kb_integration():
    """测试知识库集成功能"""
    print("=== 测试知识库集成 ===")
    
    # 创建知识库管理器实例
    kb_manager = KnowledgeBaseManager()
    
    print("\n1. 测试诊断模型与知识库集成：")
    diagnosis_engine = get_diagnosis_engine()
    
    # 测试基于症状的诊断
    test_cases = [
        ("番茄", ["斑点", "发黄"]),
        ("番茄", ["腐烂", "霉斑"]),
        ("番茄", ["卷曲", "生长缓慢"])
    ]
    
    for crop, symptoms in test_cases:
        disease_type, confidence, description = diagnosis_engine.diagnose_from_symptoms(crop, symptoms)
        print(f"   作物：{crop}，症状：{symptoms}")
        print(f"   诊断结果：{disease_type}，置信度：{confidence:.2%}，描述：{description}")
    
    print("\n2. 测试治疗方案与知识库集成：")
    test_diseases = ["早疫病", "晚疫病", "黄化曲叶病毒病"]
    
    for disease in test_diseases:
        treatment, prevention = _get_treatment_from_knowledge_base(disease)
        print(f"   病害：{disease}")
        print(f"   治疗方案：{treatment}")
        print(f"   预防措施：{prevention}")
    
    print("\n3. 测试知识库管理器的直接调用：")
    
    # 获取所有病害类别
    disease_classes = kb_manager.get_disease_classes()
    print(f"   所有病害类别：{disease_classes}")
    
    # 获取病害描述
    desc = kb_manager.get_disease_description("早疫病")
    print(f"   早疫病描述：{desc}")
    
    # 根据症状获取可能的病害
    diseases = kb_manager.get_possible_diseases_by_symptom("斑点")
    print(f"   症状 '斑点' 可能的病害：{diseases}")
    
    # 规则诊断
    result = kb_manager.rule_diagnosis("番茄", ["腐烂", "斑点"])
    print(f"   规则诊断结果：{result}")
    
    # 获取治疗方案
    plan = kb_manager.get_treatment_plan("晚疫病")
    print(f"   晚疫病治疗方案：{plan}")


if __name__ == "__main__":
    test_kb_integration()