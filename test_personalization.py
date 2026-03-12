#!/usr/bin/env python3
"""
农户个性化设计模块测试脚本

验证农户个性化模块的正确性，包括：
1. 模型定义与基本功能
2. 档案存储与加载
3. 上下文生成
4. 规则过滤功能
5. 与现有系统的集成
"""

import os
import json
import tempfile
from typing import List, Dict, Optional

# 导入个性化模块
from personalization import (
    BaseProfile,
    FarmerProfile,
    TreatmentConstraint,
    compute_profile_hash,
    load_profile,
    save_profile,
    list_profile_ids,
    reset_profile,
    build_personalization_context,
    build_personalization_flags,
    apply_base_profile_to_state,
    filter_treatment_by_constraints
)


def test_model_basics():
    """测试模型的基本功能和验证"""
    print("\n=== 测试模型基本功能 ===")
    
    # 测试TreatmentConstraint
    constraint = TreatmentConstraint(
        banned_ingredients=["甲拌磷", "甲基对硫磷"],
        harvest_window_days=7,
        prefer_organic=True
    )
    print(f"治疗约束: {constraint.model_dump()}")
    
    # 测试BaseProfile
    base = BaseProfile(
        base_id="B001",
        name="番茄种植基地",
        location="XX村",
        province="山东省",
        facility="温室",
        environment="近期多雨",
        growth_stage="结果期",
        notes="注意排水"
    )
    print(f"基地信息: {base.model_dump()}")
    
    # 测试FarmerProfile
    farmer = FarmerProfile(
        farmer_id="F001",
        name="张三",
        active_base_id="B001",
        confirm_when_low_confidence=True,
        bases={"B001": base},
        constraints=constraint
    )
    print(f"农户档案: {farmer.model_dump()}")
    
    # 测试哈希计算
    profile_hash = compute_profile_hash(farmer)
    print(f"档案哈希: {profile_hash}")
    
    assert len(profile_hash) == 64, "哈希长度应为64位"
    print("✓ 模型基本功能测试通过")


def test_storage_functions():
    """测试档案存储与加载功能"""
    print("\n=== 测试存储功能 ===")
    
    # 创建临时目录来测试存储
    original_dir = os.environ.get("PROFILE_DIR")
    try:
        # 准备测试数据
        base = BaseProfile(
            base_id="B002",
            name="测试基地",
            location="测试村",
            growth_stage="苗期"
        )
        
        constraint = TreatmentConstraint(
            banned_ingredients=["高毒成分"],
            harvest_window_days=10,
            prefer_organic=False
        )
        
        farmer = FarmerProfile(
            farmer_id="TEST001",
            name="测试用户",
            active_base_id="B002",
            bases={"B002": base},
            constraints=constraint
        )
        
        # 保存档案
        save_path = save_profile(farmer)
        print(f"保存档案到: {save_path}")
        
        # 验证文件存在
        assert os.path.exists(save_path), "档案文件不存在"
        
        # 列出档案ID
        profile_ids = list_profile_ids()
        print(f"已存在的档案ID: {profile_ids}")
        assert "TEST001" in profile_ids, "档案ID应在列表中"
        
        # 加载档案
        loaded = load_profile("TEST001")
        assert loaded is not None, "无法加载档案"
        print(f"加载的档案: {loaded.farmer_id} - {loaded.name}")
        
        # 验证内容一致性
        assert loaded.name == farmer.name, "名称不一致"
        assert loaded.active_base_id == farmer.active_base_id, "活跃基地ID不一致"
        assert loaded.constraints.banned_ingredients == farmer.constraints.banned_ingredients, "约束不一致"
        
        # 重置档案
        reset_path = reset_profile("TEST001")
        print(f"重置档案到: {reset_path}")
        
        # 验证重置结果
        reset_loaded = load_profile("TEST001")
        assert reset_loaded is not None, "无法加载重置后的档案"
        assert len(reset_loaded.bases) == 0, "重置后基地列表应为空"
        
        print("✓ 存储功能测试通过")
        
    finally:
        # 清理测试数据
        if os.path.exists("data/profiles/TEST001.json"):
            os.remove("data/profiles/TEST001.json")


def test_context_generation():
    """测试上下文生成功能"""
    print("\n=== 测试上下文生成 ===")
    
    base = BaseProfile(
        base_id="B003",
        name="测试基地",
        location="XX乡",
        province="山东省",
        facility="温室",
        environment="高温多雨",
        growth_stage="结果期"
    )
    
    constraint = TreatmentConstraint(
        banned_ingredients=["甲拌磷", "甲基对硫磷"],
        harvest_window_days=7,
        prefer_organic=True
    )
    
    farmer = FarmerProfile(
        farmer_id="F003",
        name="李四",
        active_base_id="B003",
        bases={"B003": base},
        constraints=constraint
    )
    
    # 测试上下文构建
    context = build_personalization_context(farmer, base)
    print(f"生成的上下文: {context}")
    
    assert "农户ID: F003" in context, "上下文应包含农户ID"
    assert "基地ID: B003" in context, "上下文应包含基地ID"
    assert "禁用成分: 甲拌磷, 甲基对硫磷" in context, "上下文应包含禁用成分"
    assert "偏好有机/低残留方案" in context, "上下文应包含有机偏好"
    
    # 测试标志构建
    flags = build_personalization_flags(farmer, base)
    print(f"生成的标志: {flags}")
    
    assert flags["confirm_when_low_confidence"] is True, "标志值不正确"
    assert "base_id" in flags, "标志应包含基地ID"
    assert "profile_hash" in flags, "标志应包含档案哈希"
    
    # 测试状态应用
    state = {}
    apply_base_profile_to_state(state, base)
    print(f"应用基地信息后的状态: {state}")
    
    assert state["location"] == "XX乡", "状态应包含位置"
    assert state["province"] == "山东省", "状态应包含省份"
    assert state["crop_growth_stage"] == "结果期", "状态应包含生长阶段"
    
    print("✓ 上下文生成测试通过")


def test_rule_filtering():
    """测试规则过滤功能"""
    print("\n=== 测试规则过滤功能 ===")
    
    # 示例治疗方案
    treatment = """1. 发病初期：使用甲拌磷喷雾，每7-10天一次，连续2-3次。
2. 发病严重时：使用百菌清、代森锰锌或嘧菌酯喷雾。
3. 注意事项：避免在高温时段用药，保持田间通风。"""
    
    constraint = TreatmentConstraint(
        banned_ingredients=["甲拌磷", "甲基对硫磷"],
        harvest_window_days=7,
        prefer_organic=True
    )
    
    # 测试过滤
    filtered, dropped = filter_treatment_by_constraints(treatment, constraint)
    print(f"原始治疗方案:\n{treatment}")
    print(f"\n过滤后的方案:\n{filtered}")
    print(f"\n被移除的方案: {dropped}")
    
    # 验证过滤结果
    print(f"\n调试信息：")
    print(f"'甲拌磷' in filtered: {'甲拌磷' in filtered}")
    print(f"'百菌清' in filtered: {'百菌清' in filtered}")
    print(f"'已根据偏好优先保留低毒/有机或物理防治建议' in filtered: {'已根据偏好优先保留低毒/有机或物理防治建议' in filtered}")
    print(f"'采收临近' in filtered: {'采收临近' in filtered}")
    print(f"dropped长度: {len(dropped)}")
    if dropped:
        print(f"dropped[0]: {dropped[0]}")
        print(f"'使用甲拌磷喷雾' in dropped[0]: {'使用甲拌磷喷雾' in dropped[0]}")
    
    # 使用更安全的验证方式
    assert "甲拌磷" not in filtered, "过滤后的方案不应包含禁用成分"
    assert "百菌清" in filtered, "过滤后的方案应包含可用成分"
    assert "有机" in filtered, "应包含有机偏好提示"
    assert "采收临近" in filtered, "应包含采收临近提示"
    assert len(dropped) > 0, "应有被移除的方案"
    assert "甲拌磷" in str(dropped), "被移除的方案应包含禁用成分"
    
    print("✓ 规则过滤功能测试通过")


def test_integration():
    """测试与现有系统的集成"""
    print("\n=== 测试与现有系统集成 ===")
    
    try:
        # 测试从文件加载现有农户档案
        print("\n尝试加载现有农户档案...")
        existing_profiles = list_profile_ids()
        print(f"现有档案ID: {existing_profiles}")
        
        if existing_profiles:
            # 加载第一个现有档案
            profile_id = existing_profiles[0]
            profile = load_profile(profile_id)
            print(f"加载的档案: {profile.farmer_id} - {profile.name}")
            
            # 测试生成上下文
            active_base = None
            if profile.active_base_id and profile.active_base_id in profile.bases:
                active_base = profile.bases[profile.active_base_id]
            
            context = build_personalization_context(profile, active_base)
            print(f"生成的上下文: {context[:100]}...")
            
            print("✓ 与现有系统集成测试通过")
        else:
            print("无现有档案，跳过集成测试")
            print("✓ 集成测试通过（无现有档案）")
            
    except Exception as e:
        print(f"集成测试失败: {e}")
        raise


def main():
    """主测试函数"""
    print("农户个性化设计模块测试")
    print("=" * 50)
    
    try:
        test_model_basics()
        test_storage_functions()
        test_context_generation()
        test_rule_filtering()
        test_integration()
        
        print("\n" + "=" * 50)
        print("🎉 所有测试通过！农户个性化设计模块功能正常。")
        return 0
        
    except Exception as e:
        print(f"\n" + "=" * 50)
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
