"""
测试知识库管理模块
验证知识库的功能是否正常工作
"""

from knowledge_base import KnowledgeBaseManager, get_kb_manager
from knowledge_base import (
    get_disease_classes,
    get_disease_description,
    get_possible_diseases_by_symptom,
    rule_diagnosis,
    get_treatment_plan
)


def test_kb_manager():
    """测试知识库管理器的基本功能"""
    print("=== 测试知识库管理器 ===")
    
    # 创建知识库管理器实例
    kb_manager = KnowledgeBaseManager()
    
    # 测试获取病害类别
    print("\n1. 测试获取病害类别：")
    disease_classes = kb_manager.get_disease_classes()
    print(f"   病害类别列表：{disease_classes}")
    
    # 测试获取病害描述
    print("\n2. 测试获取病害描述：")
    for disease in ["早疫病", "晚疫病", "健康"]:
        desc = kb_manager.get_disease_description(disease)
        print(f"   {disease}：{desc}")
    
    # 测试根据症状获取可能的病害
    print("\n3. 测试根据症状获取可能的病害：")
    for symptom in ["斑点", "发黄", "腐烂"]:
        diseases = kb_manager.get_possible_diseases_by_symptom(symptom)
        print(f"   症状 '{symptom}' 可能的病害：{diseases}")
    
    # 测试规则诊断
    print("\n4. 测试规则诊断：")
    test_cases = [
        ("番茄", ["斑点", "发黄"]),
        ("番茄", ["腐烂", "霉斑"]),
        ("番茄", ["卷曲", "生长缓慢"])
    ]
    
    for crop, symptoms in test_cases:
        result = kb_manager.rule_diagnosis(crop, symptoms)
        print(f"   作物：{crop}，症状：{symptoms}")
        print(f"   诊断结果：{result}")
    
    # 测试获取治疗方案
    print("\n5. 测试获取治疗方案：")
    for disease in ["早疫病", "晚疫病", "黄化曲叶病毒病"]:
        plan = kb_manager.get_treatment_plan(disease)
        print(f"   {disease} 的治疗方案：")
        print(f"     治疗方法：{plan['treatment']}")
        print(f"     预防措施：{plan['prevention']}")
    
    # 测试系统管理员接口
    print("\n6. 测试系统管理员接口：")
    
    # 测试添加新病害
    print("   测试添加新病害：")
    success = kb_manager.add_disease("病毒病", "由病毒引起的番茄病害")
    print(f"     添加新病害 '病毒病'：{'成功' if success else '失败'}")
    
    # 测试更新治疗方案
    print("   测试更新治疗方案：")
    success = kb_manager.update_treatment(
        "病毒病", 
        "使用抗病毒药剂喷雾", 
        "定期消毒，防止病毒传播"
    )
    print(f"     更新 '病毒病' 治疗方案：{'成功' if success else '失败'}")
    
    # 测试添加诊断规则
    print("   测试添加诊断规则：")
    success = kb_manager.add_diagnosis_rule(
        "番茄", 
        "叶子卷曲", 
        "病毒病", 
        0.85, 
        "病毒病导致叶片卷曲"
    )
    print(f"     添加诊断规则：{'成功' if success else '失败'}")
    
    # 测试添加症状映射
    print("   测试添加症状映射：")
    success = kb_manager.add_symptom_mapping("叶子卷曲", ["病毒病", "黄化曲叶病毒病"])
    print(f"     添加症状映射：{'成功' if success else '失败'}")


def test_global_kb_manager():
    """测试全局知识库管理器"""
    print("\n=== 测试全局知识库管理器 ===")
    
    # 测试通过全局方法访问知识库
    print("\n1. 测试全局方法：")
    
    # 获取病害类别
    disease_classes = get_disease_classes()
    print(f"   病害类别列表：{disease_classes}")
    
    # 获取病害描述
    desc = get_disease_description("早疫病")
    print(f"   早疫病描述：{desc}")
    
    # 根据症状获取可能的病害
    diseases = get_possible_diseases_by_symptom("斑点")
    print(f"   症状 '斑点' 可能的病害：{diseases}")
    
    # 规则诊断
    result = rule_diagnosis("番茄", ["腐烂", "斑点"])
    print(f"   诊断结果：{result}")
    
    # 获取治疗方案
    plan = get_treatment_plan("晚疫病")
    print(f"   晚疫病治疗方法：{plan['treatment']}")


def test_multi_agent_integration():
    """测试多智能体集成"""
    print("\n=== 测试多智能体集成 ===")
    
    # 模拟诊断智能体调用
    print("\n1. 模拟诊断智能体调用：")
    kb_manager = get_kb_manager()
    
    # 诊断智能体需要的功能
    symptoms = ["斑点", "发黄"]
    diagnosis_result = kb_manager.rule_diagnosis("番茄", symptoms)
    print(f"   诊断智能体调用 rule_diagnosis('番茄', {symptoms})：")
    print(f"     诊断结果：{diagnosis_result}")
    
    # 模拟治疗方案智能体调用
    print("\n2. 模拟治疗方案智能体调用：")
    disease_type = diagnosis_result["disease_type"]
    treatment_plan = kb_manager.get_treatment_plan(disease_type)
    print(f"   治疗方案智能体调用 get_treatment_plan('{disease_type}')：")
    print(f"     治疗方法：{treatment_plan['treatment']}")
    print(f"     预防措施：{treatment_plan['prevention']}")
    
    # 模拟监督智能体调用
    print("\n3. 模拟监督智能体调用：")
    # 监督智能体可能需要的功能
    disease_classes = kb_manager.get_disease_classes()
    disease_description = kb_manager.get_disease_description(disease_type)
    print(f"   监督智能体调用 get_disease_classes()：")
    print(f"     病害类别数量：{len(disease_classes)}")
    print(f"   监督智能体调用 get_disease_description('{disease_type}')：")
    print(f"     病害描述：{disease_description}")


if __name__ == "__main__":
    # 运行所有测试
    test_kb_manager()
    test_global_kb_manager()
    test_multi_agent_integration()
    
    print("\n=== 所有测试完成 ===")
