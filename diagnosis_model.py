"""
诊断智能体模型模块
基于深度学习的番茄病害诊断模型
参考论文：Transform and Deep Learning Algorithms for the Early Detection and Recognition of Tomato Leaf Disease
"""
import torch
import torch.nn as nn
import torchvision.models as models
from torchvision import transforms
from PIL import Image
import numpy as np
from typing import Dict, Tuple, Optional, List
from config import DIAGNOSIS_MODEL_TYPE, DIAGNOSIS_MODEL_PATH, USE_GPU, DIAGNOSIS_CONFIDENCE_THRESHOLD
import os
from knowledge_base import get_kb_manager


# 获取知识库管理器实例
kb_manager = get_kb_manager()

# 从知识库获取病害类别
DISEASE_CLASSES = kb_manager.get_disease_classes()


class DiagnosisModel(nn.Module):
    """诊断模型基类"""
    
    def __init__(self, num_classes: int = len(DISEASE_CLASSES)):
        super(DiagnosisModel, self).__init__()
        self.num_classes = num_classes
    
    def forward(self, x):
        raise NotImplementedError


class DenseNet121Model(DiagnosisModel):
    """DenseNet121模型"""
    
    def __init__(self, num_classes: int = len(DISEASE_CLASSES)):
        super(DenseNet121Model, self).__init__(num_classes)
        self.model = models.densenet121(pretrained=True)
        num_features = self.model.classifier.in_features
        self.model.classifier = nn.Linear(num_features, num_classes)
    
    def forward(self, x):
        return self.model(x)


class ResNet50Model(DiagnosisModel):
    """ResNet50模型"""
    
    def __init__(self, num_classes: int = len(DISEASE_CLASSES)):
        super(ResNet50Model, self).__init__(num_classes)
        self.model = models.resnet50(pretrained=True)
        num_features = self.model.fc.in_features
        self.model.fc = nn.Linear(num_features, num_classes)
    
    def forward(self, x):
        return self.model(x)


class ViTModel(DiagnosisModel):
    """Vision Transformer模型"""
    
    def __init__(self, num_classes: int = len(DISEASE_CLASSES)):
        super(ViTModel, self).__init__(num_classes)
        self.model = models.vit_b_16(pretrained=True)
        num_features = self.model.heads.head.in_features
        self.model.heads.head = nn.Linear(num_features, num_classes)
    
    def forward(self, x):
        return self.model(x)


def create_model(model_type: str = DIAGNOSIS_MODEL_TYPE, num_classes: int = len(DISEASE_CLASSES)) -> DiagnosisModel:
    """
    创建诊断模型

    Args:
        model_type: 模型类型 (densenet121, resnet50, vit)
        num_classes: 分类数量

    Returns:
        模型实例
    """
    if model_type == "densenet121":
        return DenseNet121Model(num_classes)
    elif model_type == "resnet50":
        return ResNet50Model(num_classes)
    elif model_type == "vit":
        return ViTModel(num_classes)
    else:
        raise ValueError(f"不支持的模型类型: {model_type}")


class DiseaseDiagnosisEngine:
    """病害诊断引擎"""
    
    def __init__(self, model_type: str = DIAGNOSIS_MODEL_TYPE, model_path: Optional[str] = None):
        if model_path is None:
            model_path = DIAGNOSIS_MODEL_PATH
        self.device = torch.device("cuda" if USE_GPU and torch.cuda.is_available() else "cpu")
        self.model = create_model(model_type)
        
        # 加载预训练模型（如果存在）
        if model_path and os.path.exists(model_path):
            try:
                self.model.load_state_dict(torch.load(model_path, map_location=self.device))
                print(f"已加载模型: {model_path}")
            except Exception as e:
                print(f"加载模型失败: {e}，使用预训练权重")
        else:
            print(f"模型文件不存在，使用预训练权重")
        
        self.model.to(self.device)
        self.model.eval()
        
        # 图像预处理
        self.transform = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
        ])
    
    def diagnose_from_image(self, image_path: str) -> Tuple[str, float, Dict[str, float]]:
        """
        从图像诊断病害

        Args:
            image_path: 图像路径

        Returns:
            (病害类型, 置信度, 所有类别的概率分布)
        """
        try:
            image = Image.open(image_path).convert('RGB')
            image_tensor = self.transform(image).unsqueeze(0).to(self.device)
            
            with torch.no_grad():
                outputs = self.model(image_tensor)
                probabilities = torch.softmax(outputs, dim=1)
                confidence, predicted = torch.max(probabilities, 1)
                
                # 获取所有类别的概率
                probs_dict = {
                    DISEASE_CLASSES[i]: probabilities[0][i].item()
                    for i in range(len(DISEASE_CLASSES))
                }
                
                disease_type = DISEASE_CLASSES[predicted.item()]
                confidence_score = confidence.item()
                
                return disease_type, confidence_score, probs_dict
        except Exception as e:
            print(f"图像诊断失败: {e}")
            return "未知病害", 0.0, {}
    
    def diagnose_from_symptoms(
        self,
        crop_type: str,
        symptoms: List[str],
        growth_stage: Optional[str] = None
    ) -> Tuple[str, float, str]:
        """
        基于症状进行诊断（规则+模型结合）

        Args:
            crop_type: 作物类型
            symptoms: 症状列表
            growth_stage: 生长阶段

        Returns:
            (病害类型, 置信度, 病害描述)
        """
        # 如果作物不是番茄，使用规则匹配
        if crop_type != "番茄":
            return "非番茄作物", 0.0, "本系统仅支持番茄病害诊断"
        
        # 使用知识库管理器进行规则诊断
        diagnosis_result = kb_manager.rule_diagnosis(crop_type, symptoms)
        
        # 获取病害描述
        description = self._get_disease_description(diagnosis_result["disease_type"], symptoms)
        
        return (
            diagnosis_result["disease_type"],
            diagnosis_result["confidence"],
            description
        )
    
    def _rule_based_diagnosis(self, crop_type: str, symptoms: List[str]) -> Tuple[str, float, str]:
        """
        基于规则的诊断（仅用于番茄作物）
        """
        if crop_type != "番茄":
            return "非番茄作物", 0.0, "本系统仅支持番茄病害诊断"
        
        # 使用知识库管理器进行规则诊断
        diagnosis_result = kb_manager.rule_diagnosis(crop_type, symptoms)
        
        # 获取病害描述
        description = self._get_disease_description(diagnosis_result["disease_type"], symptoms)
        
        return (
            diagnosis_result["disease_type"],
            diagnosis_result["confidence"],
            description
        )
    
    def _get_disease_description(self, disease_type: str, symptoms: List[str]) -> str:
        """
        获取病害描述
        """
        # 使用知识库管理器获取病害描述
        base_description = kb_manager.get_disease_description(disease_type)
        symptom_text = "、".join(symptoms)
        return f"{base_description} 当前观察到的症状包括：{symptom_text}。"


# 全局诊断引擎实例
_diagnosis_engine: Optional[DiseaseDiagnosisEngine] = None


def get_diagnosis_engine() -> DiseaseDiagnosisEngine:
    """获取诊断引擎单例"""
    global _diagnosis_engine
    if _diagnosis_engine is None:
        _diagnosis_engine = DiseaseDiagnosisEngine(model_path=DIAGNOSIS_MODEL_PATH)
    return _diagnosis_engine
