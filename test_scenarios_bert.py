#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
执行BERT模型测试数据集的测试脚本
"""

import os
import json
import requests
from typing import Dict, List, Any

def test_scenario(test_case: Dict[str, Any], base_url: str = "http://localhost:8000") -> Dict[str, Any]:
    """测试单个场景"""
    print(f"\n测试用例: {test_case['name']}")
    print(f"场景: {test_case['scenario']}")
    print(f"描述: {test_case['description']}")
    
    # 准备请求数据
    image_path = test_case['input']['image_path']
    full_image_path = os.path.join(os.getcwd(), image_path)
    
    if not os.path.exists(full_image_path):
        print(f"❌ 图片文件不存在: {full_image_path}")
        return {
            "id": test_case['id'],
            "name": test_case['name'],
            "status": "error",
            "message": f"图片文件不存在: {full_image_path}"
        }
    
    # 构建请求数据
    data = {
        "crop_type": test_case['input']['crop_type'],
        "symptoms": ",".join(test_case['input']['symptoms']),
        "growth_stage": test_case['input']['growth_stage'],
        "base_id": test_case['input']['base_id'],
        "farmer_id": test_case['input']['farmer_id']
    }
    
    print(f"输入症状: {data['symptoms']}")
    print(f"预期reason code: {test_case['expected']['reason_code']}")
    print(f"预期UI模式: {test_case['expected']['ui_mode']}")
    
    # 发送请求并验证结果
    try:
        with open(full_image_path, "rb") as f:
            files = {"file": (os.path.basename(full_image_path), f.read(), "image/jpeg")}
            response = requests.post(f"{base_url}/api/diagnose-image", files=files, data=data, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            print(f"响应状态码: {response.status_code}")
            
            # 提取相关字段
            actual_reason_code = result.get('confirm_reason_code', 'N/A')
            actual_ui_mode = result.get('confirm_ui_mode', 'N/A')
            reliability_issue_types = result.get('reliability_issue_types', [])
            supplement_mode = result.get('supplement_mode', 'none')
            
            # 映射到预期的reason_code
            if actual_reason_code == 'N/A':
                # 根据reliability_issue_types和supplement_mode推断reason_code
                if 'image_weak' in reliability_issue_types:
                    actual_reason_code = 'IMAGE_QUALITY_LOW'
                elif 'text_weak' in reliability_issue_types:
                    actual_reason_code = 'SYMPTOM_TEXT_INSUFFICIENT'
                elif 'image_weak' in reliability_issue_types and 'text_weak' in reliability_issue_types:
                    actual_reason_code = 'BOTH_IMAGE_AND_TEXT_WEAK'
                elif result.get('modality_conflict_flag', False):
                    actual_reason_code = 'IMAGE_TEXT_CONFLICT'
                else:
                    actual_reason_code = 'NONE'
            
            # 映射到预期的ui_mode
            if actual_ui_mode == 'N/A':
                if supplement_mode == 'image_only':
                    actual_ui_mode = 'image'
                elif supplement_mode == 'text_only':
                    actual_ui_mode = 'text'
                elif supplement_mode == 'image_and_text':
                    actual_ui_mode = 'image_and_text'
                else:
                    actual_ui_mode = 'none'
            
            print(f"实际reason code: {actual_reason_code}")
            print(f"实际UI模式: {actual_ui_mode}")
            print(f"可靠性问题类型: {reliability_issue_types}")
            print(f"补充模式: {supplement_mode}")
            print(f"诊断结果: {result.get('final_disease', 'N/A')} (置信度: {result.get('final_confidence', 'N/A')})")
            
            # 验证结果
            expected_reason_code = test_case['expected']['reason_code']
            expected_ui_mode = test_case['expected']['ui_mode']
            
            passed = (actual_reason_code == expected_reason_code) and (actual_ui_mode == expected_ui_mode)
            
            return {
                "id": test_case['id'],
                "name": test_case['name'],
                "status": "passed" if passed else "failed",
                "expected": {
                    "reason_code": expected_reason_code,
                    "ui_mode": expected_ui_mode
                },
                "actual": {
                    "reason_code": actual_reason_code,
                    "ui_mode": actual_ui_mode,
                    "disease": result.get('final_disease', 'N/A'),
                    "confidence": result.get('final_confidence', 'N/A'),
                    "reliability_issue_types": reliability_issue_types,
                    "supplement_mode": supplement_mode
                },
                "message": f"测试{'通过' if passed else '失败'}"
            }
        else:
            print(f"❌ 请求失败，状态码: {response.status_code}")
            print(f"响应内容: {response.text}")
            return {
                "id": test_case['id'],
                "name": test_case['name'],
                "status": "error",
                "message": f"请求失败，状态码: {response.status_code}"
            }
    except Exception as e:
        print(f"❌ 测试失败: {str(e)}")
        return {
            "id": test_case['id'],
            "name": test_case['name'],
            "status": "error",
            "message": f"测试失败: {str(e)}"
        }

def main() -> None:
    """主函数"""
    # 加载测试数据集
    dataset_path = "test_dataset_bert.json"
    if not os.path.exists(dataset_path):
        print(f"❌ 测试数据集文件不存在: {dataset_path}")
        return
    
    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)
    
    test_cases = dataset.get("test_cases", [])
    print(f"加载测试用例数量: {len(test_cases)}")
    
    # 执行测试
    results = []
    for test_case in test_cases:
        result = test_scenario(test_case)
        results.append(result)
    
    # 统计结果
    passed_count = sum(1 for r in results if r['status'] == 'passed')
    failed_count = sum(1 for r in results if r['status'] == 'failed')
    error_count = sum(1 for r in results if r['status'] == 'error')
    
    print("\n" + "="*60)
    print("测试结果统计")
    print("="*60)
    print(f"总测试用例: {len(test_cases)}")
    print(f"通过: {passed_count}")
    print(f"失败: {failed_count}")
    print(f"错误: {error_count}")
    print(f"通过率: {passed_count / len(test_cases) * 100:.2f}%")
    
    # 输出详细结果
    print("\n" + "="*60)
    print("详细测试结果")
    print("="*60)
    for result in results:
        print(f"\n测试用例: {result['name']}")
        print(f"状态: {result['status']}")
        print(f"消息: {result['message']}")
        if 'expected' in result and 'actual' in result:
            print(f"预期reason code: {result['expected']['reason_code']}")
            print(f"实际reason code: {result['actual']['reason_code']}")
            print(f"预期UI模式: {result['expected']['ui_mode']}")
            print(f"实际UI模式: {result['actual']['ui_mode']}")
            if 'disease' in result['actual']:
                print(f"诊断结果: {result['actual']['disease']}")
            if 'confidence' in result['actual']:
                print(f"置信度: {result['actual']['confidence']}")

if __name__ == "__main__":
    main()
