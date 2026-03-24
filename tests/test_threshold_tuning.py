#!/usr/bin/env python3
"""
诊断阈值离线调优功能单元测试

测试目标：
  1. verify_confirmation_decision 纯函数的正确性
  2. 确保线上/离线逻辑一致性
  3. 覆盖关键边界场景

运行方式：
  pytest tests/test_threshold_tuning.py -v
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from diagnosis_model import evaluate_confirmation_decision


def test_conflict_sample_should_need_confirm():
    """测试：conflict 样本应 need_confirm=true"""
    fusion_top3 = [("早疫病", 0.55), ("细菌性斑点病", 0.45)]
    fusion_meta = {
        "fusion_case": "conflict",
        "image_reliable": True,
        "text_reliable": True,
        "modality_conflict_flag": True,
        "weak_conflict_candidate": False,
        "supplement_mode": "image_and_text",
    }
    image_top3 = [("早疫病", 0.78)]
    text_top3 = [("细菌性斑点病", 0.72)]
    
    result = evaluate_confirmation_decision(
        fusion_top3=fusion_top3,
        fusion_meta=fusion_meta,
        image_top3=image_top3,
        text_top3=text_top3,
        final_confidence=0.55,
    )
    
    assert result["need_confirm"] is True, "conflict 样本应该需要确认"
    assert "image_text_conflict" in result["reasons"]
    assert result["fusion_case"] == "conflict"
    print("✓ test_conflict_sample_should_need_confirm 通过")


def test_image_strong_text_weak_high_confidence_should_clear():
    """测试：image_strong_text_weak 样本在高置信时应可直接放行"""
    fusion_top3 = [("细菌性斑点病", 0.82), ("早疫病", 0.10)]
    fusion_meta = {
        "fusion_case": "image_strong_text_weak",
        "image_reliable": True,
        "text_reliable": False,
        "modality_conflict_flag": False,
        "weak_conflict_candidate": False,
        "supplement_mode": "image_only",
    }
    image_top3 = [("细菌性斑点病", 0.82)]
    text_top3 = [("早疫病", 0.35)]
    
    result = evaluate_confirmation_decision(
        fusion_top3=fusion_top3,
        fusion_meta=fusion_meta,
        image_top3=image_top3,
        text_top3=text_top3,
        final_confidence=0.82,
        diagnosis_conf_threshold=0.60,
        need_confirm_threshold=0.60,
    )
    
    assert result["need_confirm"] is False, "高置信度 image_strong_text_weak 样本应该不需要确认"
    assert result["should_clear_confirm"] is True
    assert result["reasons"] == []
    print("✓ test_image_strong_text_weak_high_confidence_should_clear 通过")


def test_both_weak_sample_should_need_confirm():
    """测试：both_weak 样本应 need_confirm=true"""
    fusion_top3 = [("叶霉病", 0.42), ("早疫病", 0.28)]
    fusion_meta = {
        "fusion_case": "both_weak",
        "image_reliable": False,
        "text_reliable": False,
        "modality_conflict_flag": False,
        "weak_conflict_candidate": False,
        "supplement_mode": "image_and_text",
    }
    image_top3 = [("叶霉病", 0.42)]
    text_top3 = [("叶霉病", 0.38)]
    
    result = evaluate_confirmation_decision(
        fusion_top3=fusion_top3,
        fusion_meta=fusion_meta,
        image_top3=image_top3,
        text_top3=text_top3,
        final_confidence=0.42,
    )
    
    assert result["need_confirm"] is True, "both_weak 样本应该需要确认"
    assert "both_modalities_weak" in result["reasons"]
    assert result["fusion_case"] == "both_weak"
    print("✓ test_both_weak_sample_should_need_confirm 通过")


def test_low_confidence_should_need_confirm():
    """测试：低置信度样本应 need_confirm=true"""
    fusion_top3 = [("早疫病", 0.48), ("晚疫病", 0.35)]
    fusion_meta = {
        "fusion_case": "consistent",
        "image_reliable": True,
        "text_reliable": True,
        "modality_conflict_flag": False,
        "weak_conflict_candidate": False,
        "supplement_mode": "none",
    }
    image_top3 = [("早疫病", 0.65)]
    text_top3 = [("早疫病", 0.58)]
    
    result = evaluate_confirmation_decision(
        fusion_top3=fusion_top3,
        fusion_meta=fusion_meta,
        image_top3=image_top3,
        text_top3=text_top3,
        final_confidence=0.48,
        diagnosis_conf_threshold=0.60,
    )
    
    assert result["need_confirm"] is True, "低置信度样本应该需要确认"
    assert "low_confidence" in result["reasons"]
    print("✓ test_low_confidence_should_need_confirm 通过")


def test_low_margin_should_need_confirm():
    """测试：低 margin 样本应 need_confirm=true"""
    fusion_top3 = [("早疫病", 0.62), ("晚疫病", 0.58)]
    fusion_meta = {
        "fusion_case": "consistent",
        "image_reliable": True,
        "text_reliable": True,
        "modality_conflict_flag": False,
        "weak_conflict_candidate": False,
        "supplement_mode": "none",
    }
    image_top3 = [("早疫病", 0.65)]
    text_top3 = [("早疫病", 0.58)]
    
    result = evaluate_confirmation_decision(
        fusion_top3=fusion_top3,
        fusion_meta=fusion_meta,
        image_top3=image_top3,
        text_top3=text_top3,
        final_confidence=0.62,
        diagnosis_conf_threshold=0.60,
        low_margin_threshold=0.05,
    )
    
    assert result["need_confirm"] is True, "低 margin 样本应该需要确认"
    assert "low_margin" in result["reasons"]
    print("✓ test_low_margin_should_need_confirm 通过")


def test_high_confidence_consistent_should_clear():
    """测试：高置信度 consistent 样本应清除确认"""
    fusion_top3 = [("晚疫病", 0.85), ("早疫病", 0.08)]
    fusion_meta = {
        "fusion_case": "consistent",
        "image_reliable": True,
        "text_reliable": True,
        "modality_conflict_flag": False,
        "weak_conflict_candidate": False,
        "supplement_mode": "none",
    }
    image_top3 = [("晚疫病", 0.85)]
    text_top3 = [("晚疫病", 0.72)]
    
    result = evaluate_confirmation_decision(
        fusion_top3=fusion_top3,
        fusion_meta=fusion_meta,
        image_top3=image_top3,
        text_top3=text_top3,
        final_confidence=0.85,
        diagnosis_conf_threshold=0.60,
        need_confirm_threshold=0.60,
    )
    
    assert result["need_confirm"] is False, "高置信度 consistent 样本应该不需要确认"
    assert result["should_clear_confirm"] is True
    assert result["reasons"] == []
    print("✓ test_high_confidence_consistent_should_clear 通过")


def test_weak_conflict_flag():
    """测试：weak_conflict_flag 的计算"""
    fusion_top3 = [("早疫病", 0.45), ("晚疫病", 0.35)]
    fusion_meta = {
        "fusion_case": "image_strong_text_weak",
        "image_reliable": True,
        "text_reliable": False,
        "modality_conflict_flag": False,
        "weak_conflict_candidate": True,
        "supplement_mode": "image_only",
    }
    image_top3 = [("早疫病", 0.65)]
    text_top3 = [("晚疫病", 0.48)]
    
    result = evaluate_confirmation_decision(
        fusion_top3=fusion_top3,
        fusion_meta=fusion_meta,
        image_top3=image_top3,
        text_top3=text_top3,
        final_confidence=0.45,
    )
    
    assert result["weak_conflict_flag"] is True, "weak_conflict_candidate=True 且 final_confidence<0.5 时，weak_conflict_flag 应为 True"
    assert result["need_confirm"] is True
    assert "weak_image_text_conflict" in result["reasons"]
    print("✓ test_weak_conflict_flag 通过")


def test_image_weak_text_strong_high_confidence():
    """测试：image_weak_text_strong 高置信度样本"""
    fusion_top3 = [("早疫病", 0.75), ("晚疫病", 0.12)]
    fusion_meta = {
        "fusion_case": "image_weak_text_strong",
        "image_reliable": False,
        "text_reliable": True,
        "modality_conflict_flag": False,
        "weak_conflict_candidate": False,
        "supplement_mode": "text_only",
    }
    image_top3 = [("早疫病", 0.38)]
    text_top3 = [("早疫病", 0.75)]
    
    result = evaluate_confirmation_decision(
        fusion_top3=fusion_top3,
        fusion_meta=fusion_meta,
        image_top3=image_top3,
        text_top3=text_top3,
        final_confidence=0.75,
        diagnosis_conf_threshold=0.60,
        need_confirm_threshold=0.60,
    )
    
    assert result["need_confirm"] is False, "高置信度 image_weak_text_strong 样本应该不需要确认"
    assert result["should_clear_confirm"] is True
    print("✓ test_image_weak_text_strong_high_confidence 通过")


def test_conflict_must_confirm():
    """测试：conflict 必须确认"""
    fusion_top3 = [("早疫病", 0.80), ("晚疫病", 0.20)]
    fusion_meta = {
        "fusion_case": "conflict",
        "image_reliable": True,
        "text_reliable": True,
        "modality_conflict_flag": True,
        "weak_conflict_candidate": False,
        "supplement_mode": "image_and_text",
    }
    image_top3 = [("早疫病", 0.78)]
    text_top3 = [("晚疫病", 0.72)]
    
    result = evaluate_confirmation_decision(
        fusion_top3=fusion_top3,
        fusion_meta=fusion_meta,
        image_top3=image_top3,
        text_top3=text_top3,
        final_confidence=0.80,
    )
    
    assert result["need_confirm"] is True, "conflict 样本必须确认"
    assert "image_text_conflict" in result["reasons"], "reasons 应包含 image_text_conflict"
    assert result["should_clear_confirm"] is False, "conflict 不应清除确认"
    print("✓ test_conflict_must_confirm 通过")


def test_both_weak_must_confirm():
    """测试：both_weak 必须确认"""
    fusion_top3 = [("叶霉病", 0.42), ("早疫病", 0.28)]
    fusion_meta = {
        "fusion_case": "both_weak",
        "image_reliable": False,
        "text_reliable": False,
        "modality_conflict_flag": False,
        "weak_conflict_candidate": False,
        "supplement_mode": "image_and_text",
    }
    image_top3 = [("叶霉病", 0.42)]
    text_top3 = [("叶霉病", 0.38)]
    
    result = evaluate_confirmation_decision(
        fusion_top3=fusion_top3,
        fusion_meta=fusion_meta,
        image_top3=image_top3,
        text_top3=text_top3,
        final_confidence=0.42,
    )
    
    assert result["need_confirm"] is True, "both_weak 样本必须确认"
    assert "both_modalities_weak" in result["reasons"], "reasons 应包含 both_modalities_weak"
    print("✓ test_both_weak_must_confirm 通过")


def test_image_strong_text_weak_clear_low_confidence():
    """测试：image_strong_text_weak 在高置信下可清除 low_confidence"""
    fusion_top3 = [("细菌性斑点病", 0.82), ("早疫病", 0.10)]
    fusion_meta = {
        "fusion_case": "image_strong_text_weak",
        "image_reliable": True,
        "text_reliable": False,
        "modality_conflict_flag": False,
        "weak_conflict_candidate": False,
        "supplement_mode": "image_only",
    }
    image_top3 = [("细菌性斑点病", 0.82)]
    text_top3 = [("早疫病", 0.35)]
    
    result = evaluate_confirmation_decision(
        fusion_top3=fusion_top3,
        fusion_meta=fusion_meta,
        image_top3=image_top3,
        text_top3=text_top3,
        final_confidence=0.82,
        diagnosis_conf_threshold=0.60,
        need_confirm_threshold=0.60,
    )
    
    assert result["need_confirm"] is False, "高置信度 image_strong_text_weak 样本应该不需要确认"
    assert result["should_clear_confirm"] is True, "应该清除确认"
    assert result["reasons"] == [], "高置信度下不应有 reasons"
    print("✓ test_image_strong_text_weak_clear_low_confidence 通过")


def test_weak_conflict_with_adjustable_threshold():
    """测试：weak_conflict 使用可调阈值而不是 0.5"""
    fusion_top3 = [("早疫病", 0.54), ("晚疫病", 0.35)]
    fusion_meta = {
        "fusion_case": "image_strong_text_weak",
        "image_reliable": True,
        "text_reliable": False,
        "modality_conflict_flag": False,
        "weak_conflict_candidate": True,
        "supplement_mode": "image_only",
    }
    image_top3 = [("早疫病", 0.65)]
    text_top3 = [("晚疫病", 0.48)]
    
    result = evaluate_confirmation_decision(
        fusion_top3=fusion_top3,
        fusion_meta=fusion_meta,
        image_top3=image_top3,
        text_top3=text_top3,
        final_confidence=0.54,
        need_confirm_threshold=0.55,
    )
    
    assert result["weak_conflict_flag"] is True, "final_confidence=0.54 < threshold=0.55 时，weak_conflict_flag 应为 True"
    
    result2 = evaluate_confirmation_decision(
        fusion_top3=fusion_top3,
        fusion_meta=fusion_meta,
        image_top3=image_top3,
        text_top3=text_top3,
        final_confidence=0.54,
        need_confirm_threshold=0.50,
    )
    
    assert result2["weak_conflict_flag"] is False, "final_confidence=0.54 >= threshold=0.50 时，weak_conflict_flag 应为 False"
    print("✓ test_weak_conflict_with_adjustable_threshold 通过")


def run_all_tests():
    """运行所有测试"""
    print("="*80)
    print("诊断阈值离线调优功能单元测试")
    print("="*80 + "\n")
    
    test_conflict_sample_should_need_confirm()
    test_image_strong_text_weak_high_confidence_should_clear()
    test_both_weak_sample_should_need_confirm()
    test_low_confidence_should_need_confirm()
    test_low_margin_should_need_confirm()
    test_high_confidence_consistent_should_clear()
    test_weak_conflict_flag()
    test_image_weak_text_strong_high_confidence()
    test_conflict_must_confirm()
    test_both_weak_must_confirm()
    test_image_strong_text_weak_clear_low_confidence()
    test_weak_conflict_with_adjustable_threshold()
    
    print("\n" + "="*80)
    print("所有测试通过！✓")
    print("="*80)


if __name__ == '__main__':
    run_all_tests()
