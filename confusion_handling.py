"""
易混淆类别处理逻辑
针对早疫病 vs 蜘蛛螨等易混淆类别
"""
from typing import Dict, List, Tuple, Optional

# 易混淆类别对
CONFUSING_PAIRS = {
    # (类别1, 类别2): 特征区分规则
    ("Tomato___Early_blight", "Tomato___Spider_mites Two-spotted_spider_mite"): {
        "name": "早疫病 vs 蜘蛛螨",
        "symptoms_1": ["同心轮纹", "轮纹状", "褐色病斑", "老叶先发病"],
        "symptoms_2": ["叶背结网", "黄白小点", "青铜化", "细网"],
        "confidence_threshold": 0.90  # 超过此阈值才信任模型
    },
    ("Tomato___Early_blight", "Tomato___Target_Spot"): {
        "name": "早疫病 vs 靶斑病",
        "symptoms_1": ["同心轮纹", "轮纹状", "褐色病斑", "老叶先发病"],
        "symptoms_2": ["靶心状", "小黑点", "X形裂纹", "深凹斑"],
        "confidence_threshold": 0.85
    },
    ("Tomato___Late_blight", "Tomato___Leaf_Mold"): {
        "name": "晚疫病 vs 叶霉病",
        "symptoms_1": ["叶背白霉", "水渍状", "快速扩展", "暗绿色病斑"],
        "symptoms_2": ["叶背橄榄绒霉", "淡黄色病斑", "霉层明显", "叶片卷曲"],
        "confidence_threshold": 0.85
    },
    ("Tomato___Bacterial_spot", "Tomato___Septoria_leaf_spot"): {
        "name": "细菌性斑点病 vs 叶斑病",
        "symptoms_1": ["水渍状斑点", "边缘不规则", "穿孔", " angular lesions"],
        "symptoms_2": ["黑色小点", "分生孢子器", "圆形病斑", "灰白色中心"],
        "confidence_threshold": 0.85
    },
    ("Tomato___Tomato_Yellow_Leaf_Curl_Virus", "Tomato___Tomato_mosaic_virus"): {
        "name": "黄化曲叶病毒病 vs 花叶病毒病",
        "symptoms_1": ["节间缩短", "叶片上卷", "矮化", "整体黄化"],
        "symptoms_2": ["明暗相间花叶", "蕨叶样", "斑驳", "叶片畸形"],
        "confidence_threshold": 0.85
    }
}


def is_confusing_pair(class1: str, class2: str) -> bool:
    """检查两个类别是否为易混淆对"""
    pair = tuple(sorted([class1, class2]))
    return pair in CONFUSING_PAIRS


def get_confusing_pair_rule(class1: str, class2: str) -> Optional[Dict]:
    """获取易混淆对的规则"""
    pair = tuple(sorted([class1, class2]))
    return CONFUSING_PAIRS.get(pair)


def get_disease_symptoms(disease_class: str) -> List[str]:
    """获取病害的特征症状"""
    # 定义各病害的特征症状
    disease_symptoms = {
        "Tomato___Early_blight": ["同心轮纹", "轮纹状", "褐色病斑", "老叶先发病", "黄色晕圈"],
        "Tomato___Spider_mites Two-spotted_spider_mite": ["叶背结网", "黄白小点", "青铜化", "细网", "叶背斑点"],
        "Tomato___Target_Spot": ["靶心状", "小黑点", "X形裂纹", "深凹斑", "同心纹"],
        "Tomato___Late_blight": ["叶背白霉", "水渍状", "快速扩展", "暗绿色病斑"],
        "Tomato___Leaf_Mold": ["叶背橄榄绒霉", "淡黄色病斑", "霉层明显", "叶片卷曲"],
        "Tomato___Bacterial_spot": ["水渍状斑点", "边缘不规则", "穿孔", "角斑"],
        "Tomato___Septoria_leaf_spot": ["黑色小点", "分生孢子器", "圆形病斑", "灰白色中心"],
        "Tomato___Tomato_Yellow_Leaf_Curl_Virus": ["节间缩短", "叶片上卷", "矮化", "整体黄化"],
        "Tomato___Tomato_mosaic_virus": ["明暗相间花叶", "蕨叶样", "斑驳", "叶片畸形"],
    }
    return disease_symptoms.get(disease_class, [])


def handle_confusing_cases(
    predicted_class: str,
    confidence: float,
    symptoms: List[str],
    other_candidates: List[Tuple[str, float]]
) -> Dict:
    """
    处理易混淆类别的逻辑
    
    Args:
        predicted_class: 模型预测的类别
        confidence: 预测置信度
        symptoms: 用户提供的症状
        other_candidates: 其他候选类别及其置信度
    
    Returns:
        处理后的结果，包含修正后的类别和置信度
    """
    result = {
        "original_class": predicted_class,
        "original_confidence": confidence,
        "final_class": predicted_class,
        "final_confidence": confidence,
        "is_adjusted": False,
        "adjustment_reason": None,
        "label_changed": False,
        "confidence_changed": False,
        "target_confusing_class": None,
    }
    symptoms = [str(s).strip().lower() for s in (symptoms or []) if str(s).strip()]
    
    # 第一步：主动检查症状是否匹配其他易混淆类别
    # 这用于处理高置信度误识别的情况
    for (class1, class2), rule in CONFUSING_PAIRS.items():
        if predicted_class == class1 or predicted_class == class2:
            # 当前预测是易混淆对之一，检查症状
            other_class = class2 if predicted_class == class1 else class1
            pair_threshold = float(rule.get("confidence_threshold", 0.80))
            
            # 获取两个类别的症状特征
            symptoms_predicted = [str(item).strip().lower() for item in (rule["symptoms_1"] if predicted_class == class1 else rule["symptoms_2"])]
            symptoms_other = [str(item).strip().lower() for item in (rule["symptoms_2"] if predicted_class == class1 else rule["symptoms_1"])]
            
            # 统计症状匹配
            match_predicted = sum(1 for sym in symptoms if any(keyword in sym for keyword in symptoms_predicted))
            match_other = sum(1 for sym in symptoms if any(keyword in sym for keyword in symptoms_other))
            
            # 如果症状明显匹配另一个类别，进行修正
            if match_other > match_predicted:
                # 症状更符合另一个类别
                result["final_class"] = other_class
                # 降低置信度，因为模型原本预测错误
                result["final_confidence"] = min(confidence * 0.8, 0.75)
                result["is_adjusted"] = True
                result["label_changed"] = True
                result["confidence_changed"] = True
                result["target_confusing_class"] = other_class
                result["adjustment_reason"] = f"{rule['name']}：症状匹配{other_class.split('___')[-1]}，修正预测"
                return result
            elif match_other > 0 and match_predicted == 0:
                # 症状只匹配另一个类别，完全不匹配当前预测
                result["final_class"] = other_class
                result["final_confidence"] = min(confidence * 0.7, 0.7)
                result["is_adjusted"] = True
                result["label_changed"] = True
                result["confidence_changed"] = True
                result["target_confusing_class"] = other_class
                result["adjustment_reason"] = f"{rule['name']}：症状完全不匹配当前预测，修正为{other_class.split('___')[-1]}"
                return result
            
            # 第二步：无症状时，基于置信度阈值和候选列表进行判断
            # 这用于处理仅上传图片的情况
            # 对于仅图像输入，使用更低的阈值（0.80），因为缺乏症状验证
            image_only_threshold = min(pair_threshold, 0.80)
            if not symptoms and confidence >= image_only_threshold:
                # 高置信度预测，但可能是误识别
                # 检查候选列表中是否有易混淆类别
                has_other_class_in_candidates = False
                other_class_conf = 0.0
                
                for candidate, candidate_conf in other_candidates:
                    if candidate == other_class:
                        has_other_class_in_candidates = True
                        other_class_conf = candidate_conf
                        break
                
                if has_other_class_in_candidates:
                    # 候选列表中有易混淆类别
                    conf_gap = confidence - other_class_conf
                    
                    if conf_gap < 0.20:
                        # 置信度差距小，可能是误识别，降低置信度
                        result["final_confidence"] = min(confidence * 0.85, 0.80)
                        result["is_adjusted"] = True
                        result["confidence_changed"] = True
                        result["target_confusing_class"] = other_class
                        result["adjustment_reason"] = f"{rule['name']}：高置信度预测但候选接近，降低置信度提示确认"
                        return result
                    else:
                        # 置信度差距大，但仍然是易混淆对
                        # 对于仅图像输入，高置信度的易混淆类别预测需要特别小心
                        # 降低置信度并提示用户确认
                        result["final_confidence"] = min(confidence * 0.75, 0.75)
                        result["is_adjusted"] = True
                        result["confidence_changed"] = True
                        result["target_confusing_class"] = other_class
                        result["adjustment_reason"] = f"{rule['name']}：仅图像输入的高置信度预测，建议结合症状确认"
                        return result
                else:
                    # 候选列表中没有易混淆类别，但预测是易混淆类别
                    # 仍然降低置信度，提示用户确认
                    result["final_confidence"] = min(confidence * 0.80, 0.80)
                    result["is_adjusted"] = True
                    result["confidence_changed"] = True
                    result["target_confusing_class"] = other_class
                    result["adjustment_reason"] = f"{rule['name']}：仅图像输入，建议结合症状确认"
                    return result
    
    # 第三步：检查候选列表中的易混淆类别（原有逻辑）
    for candidate, candidate_conf in other_candidates:
        if is_confusing_pair(predicted_class, candidate):
            rule = get_confusing_pair_rule(predicted_class, candidate)
            if not rule:
                continue
            
            # 基于症状进行区分
            class1, class2 = sorted([predicted_class, candidate])
            symptoms1 = [str(item).strip().lower() for item in rule["symptoms_1"]]
            symptoms2 = [str(item).strip().lower() for item in rule["symptoms_2"]]
            
            # 统计症状匹配
            match1 = sum(1 for sym in symptoms if any(keyword in sym for keyword in symptoms1))
            match2 = sum(1 for sym in symptoms if any(keyword in sym for keyword in symptoms2))
            
            if match1 > match2:
                # 更可能是 class1
                if class1 != predicted_class:
                    result["final_class"] = class1
                    result["final_confidence"] = max(confidence * 0.8, candidate_conf, 0.6)
                    result["is_adjusted"] = True
                    result["label_changed"] = True
                    result["confidence_changed"] = True
                    result["target_confusing_class"] = class1
                    result["adjustment_reason"] = f"基于症状匹配，修正为{class1.split('___')[-1]}"
            elif match2 > match1:
                # 更可能是 class2
                if class2 != predicted_class:
                    result["final_class"] = class2
                    result["final_confidence"] = max(confidence * 0.8, candidate_conf, 0.6)
                    result["is_adjusted"] = True
                    result["label_changed"] = True
                    result["confidence_changed"] = True
                    result["target_confusing_class"] = class2
                    result["adjustment_reason"] = f"基于症状匹配，修正为{class2.split('___')[-1]}"
            else:
                # 症状匹配相当，且有明显匹配的特征，才降低置信度
                # 如果两个类别都没有匹配（症状太模糊），不进行调整
                total_match = match1 + match2
                if total_match > 0 and confidence > 0.8:
                    result["final_confidence"] = min(confidence, 0.75)
                    result["is_adjusted"] = True
                    result["confidence_changed"] = True
                    result["target_confusing_class"] = candidate
                    result["adjustment_reason"] = f"{rule['name']}：症状匹配相当，降低置信度"
                # 如果 total_match == 0，说明症状太模糊，不进行调整
    
    return result


def integrate_with_fusion(
    image_pred: str,
    image_conf: float,
    text_pred: str,
    text_conf: float,
    symptoms: List[str],
    image_top3: List[Tuple[str, float]],
    text_top3: List[Tuple[str, float]]
) -> Dict:
    """
    与融合系统集成，处理易混淆类别
    
    Args:
        image_pred: 图像模型预测类别
        image_conf: 图像模型置信度
        text_pred: 文本模型预测类别
        text_conf: 文本模型置信度
        symptoms: 用户提供的症状
        image_top3: 图像模型Top3预测
        text_top3: 文本模型Top3预测
    
    Returns:
        处理后的融合结果
    """
    # 处理图像模型的易混淆情况
    image_other = [item for item in image_top3 if item[0] != image_pred]
    image_result = handle_confusing_cases(image_pred, image_conf, symptoms, image_other)
    
    # 处理文本模型的易混淆情况
    text_other = [item for item in text_top3 if item[0] != text_pred]
    text_result = handle_confusing_cases(text_pred, text_conf, symptoms, text_other)
    
    # 构建结果
    result = {
        "image": {
            "original_pred": image_result["original_class"],
            "original_conf": image_result["original_confidence"],
            "adjusted_pred": image_result["final_class"],
            "adjusted_conf": image_result["final_confidence"],
            "is_adjusted": image_result["is_adjusted"],
            "adjustment_reason": image_result["adjustment_reason"]
        },
        "text": {
            "original_pred": text_result["original_class"],
            "original_conf": text_result["original_confidence"],
            "adjusted_pred": text_result["final_class"],
            "adjusted_conf": text_result["final_confidence"],
            "is_adjusted": text_result["is_adjusted"],
            "adjustment_reason": text_result["adjustment_reason"]
        },
        "symptoms_used": symptoms
    }
    
    return result


# 测试
if __name__ == "__main__":
    # 测试早疫病 vs 蜘蛛螨的情况
    test_cases = [
        # 早疫病症状，模型误识别为蜘蛛螨
        {
            "name": "早疫病被误识别为蜘蛛螨",
            "image_pred": "Tomato___Spider_mites Two-spotted_spider_mite",
            "image_conf": 0.93,
            "symptoms": ["褐色病斑", "轮纹状", "黄色晕圈", "叶片枯萎"],
            "image_top3": [
                ("Tomato___Spider_mites Two-spotted_spider_mite", 0.93),
                ("Tomato___Target_Spot", 0.04),
                ("Tomato___Early_blight", 0.02)
            ]
        },
        # 蜘蛛螨症状，模型正确识别
        {
            "name": "蜘蛛螨正确识别",
            "image_pred": "Tomato___Spider_mites Two-spotted_spider_mite",
            "image_conf": 0.63,
            "symptoms": ["叶背结网", "黄白小点密布"],
            "image_top3": [
                ("Tomato___Spider_mites Two-spotted_spider_mite", 0.63),
                ("Tomato___Target_Spot", 0.37),
                ("Tomato___Early_blight", 0.01)
            ]
        }
    ]
    
    print("测试易混淆类别处理逻辑:")
    print("=" * 60)
    
    for test_case in test_cases:
        print(f"\n测试用例: {test_case['name']}")
        print(f"原始预测: {test_case['image_pred']} (置信度: {test_case['image_conf']:.2f})")
        print(f"症状: {test_case['symptoms']}")
        
        result = handle_confusing_cases(
            test_case['image_pred'],
            test_case['image_conf'],
            test_case['symptoms'],
            test_case['image_top3'][1:]
        )
        
        print(f"\n处理结果:")
        print(f"  最终类别: {result['final_class']}")
        print(f"  最终置信度: {result['final_confidence']:.2f}")
        print(f"  是否调整: {'是' if result['is_adjusted'] else '否'}")
        if result['is_adjusted']:
            print(f"  调整原因: {result['adjustment_reason']}")
        
        print("-" * 60)
