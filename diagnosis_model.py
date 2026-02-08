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
from config import (
    DIAGNOSIS_MODEL_TYPE,
    DIAGNOSIS_MODEL_PATH,
    DIAGNOSIS_ALLOW_TORCH,
    USE_GPU,
    DIAGNOSIS_CONFIDENCE_THRESHOLD,
)
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
    _tf_load_announced_paths: set[str] = set()
    _torch_load_announced_paths: set[str] = set()
    
    def __init__(self, model_type: str = DIAGNOSIS_MODEL_TYPE, model_path: Optional[str] = None):
        if model_path is None:
            model_path = DIAGNOSIS_MODEL_PATH
        self.model_path = model_path
        self.tf_backend = False
        self.tf_model = None
        self.class_names: List[str] = []
        self.label_map_cn: Dict[str, str] = {}
        self.device = torch.device("cuda" if USE_GPU and torch.cuda.is_available() else "cpu")
        self.model = None
        self.transform = None

        tf_default_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "models",
            "densenet121_tomato_disease_model_fine_tuned.h5",
        )
        if os.path.exists(tf_default_path):
            self.tf_backend = True
            self.model_path = tf_default_path
            self._load_tf_model(tf_default_path)
        elif model_path and model_path.endswith((".h5", ".keras")) and os.path.exists(model_path):
            self.tf_backend = True
            self.model_path = model_path
            self._load_tf_model(model_path)
        else:
            allow_torch = str(DIAGNOSIS_ALLOW_TORCH).lower() in {"1", "true", "yes"}
            if allow_torch:
                self._load_torch_model(model_type, model_path)
            else:
                print(
                    "[DiagnosisEngine] backend=none "
                    "message=TF模型不存在且Torch未启用"
                )

    def _load_tf_model(self, model_path: str) -> None:
        if not os.path.exists(model_path):
            print(f"模型文件不存在，请先运行 tomato/train_densenet121.py 生成 models/*.h5: {model_path}")
            return
        try:
            import tensorflow as tf
        except ImportError as exc:
            raise ImportError("未安装 TensorFlow，无法加载 .h5/.keras 模型") from exc

        self.tf_model = tf.keras.models.load_model(model_path)
        self.class_names = self._load_tf_class_names()
        self.label_map_cn = self._load_label_map_cn()
        output_dim = self.tf_model.output_shape[-1]
        if output_dim != len(self.class_names):
            raise ValueError(
                f"模型输出维度({output_dim})与类别数量({len(self.class_names)})不一致"
            )
        normalized_path = os.path.abspath(model_path)
        if normalized_path not in self._tf_load_announced_paths:
            print(f"[DiagnosisEngine] backend=tf model_path={model_path}")
            self._tf_load_announced_paths.add(normalized_path)

    def _load_torch_model(self, model_type: str, model_path: Optional[str]) -> None:
        self.model = create_model(model_type)

        # 加载预训练模型（如果存在）
        if model_path and os.path.exists(model_path):
            try:
                self.model.load_state_dict(torch.load(model_path, map_location=self.device))
                print(f"已加载模型: {model_path}")
            except Exception as e:
                print(f"加载模型失败: {e}，使用预训练权重")
        else:
            print("模型文件不存在，使用预训练权重")

        self.model.to(self.device)
        self.model.eval()
        normalized_path = os.path.abspath(model_path) if model_path else "torch:default"
        if normalized_path not in self._torch_load_announced_paths:
            print(f"[DiagnosisEngine] backend=torch model_path={model_path}")
            self._torch_load_announced_paths.add(normalized_path)

        # 图像预处理
        self.transform = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
        ])

    def _load_tf_class_names(self) -> List[str]:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        classes_path = os.path.join(base_dir, "tomato", "tomato_disease_classes.txt")
        train_dir = os.path.join(base_dir, "tomato", "train")
        if os.path.exists(classes_path):
            with open(classes_path, "r", encoding="utf-8") as f:
                return [line.strip() for line in f if line.strip()]
        if os.path.isdir(train_dir):
            return sorted(
                [name for name in os.listdir(train_dir) if os.path.isdir(os.path.join(train_dir, name))]
            )
        return []

    def _load_label_map_cn(self) -> Dict[str, str]:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        label_map_path = os.path.join(base_dir, "tomato", "label_map_cn.json")
        if not os.path.exists(label_map_path):
            return {}
        try:
            import json
            with open(label_map_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _map_label_cn(self, label: str) -> str:
        return self.label_map_cn.get(label, label)
    
    def diagnose_from_image(self, image_path: str) -> Tuple[str, float, Dict[str, float]]:
        """
        从图像诊断病害

        Args:
            image_path: 图像路径

        Returns:
            (病害类型, 置信度, 所有类别的概率分布)
        """
        if self.tf_backend:
            if not self.tf_model:
                return "模型未加载", 0.0, {}
            try:
                from tensorflow.keras.preprocessing.image import load_img, img_to_array
            except ImportError as exc:
                raise ImportError("未安装 TensorFlow，无法进行图像诊断") from exc

            try:
                img = load_img(image_path, target_size=(224, 224))
                img_array = img_to_array(img)
                img_array = np.expand_dims(img_array, axis=0)
                img_array = img_array / 255.0
                predictions = self.tf_model.predict(img_array)
                probs = predictions[0]
                predicted_idx = int(np.argmax(probs))
                confidence_score = float(probs[predicted_idx])
                raw_label = self.class_names[predicted_idx]
                disease_type = self._map_label_cn(raw_label)
                probs_dict = {
                    self._map_label_cn(label): float(prob)
                    for label, prob in zip(self.class_names, probs)
                }
                if confidence_score < DIAGNOSIS_CONFIDENCE_THRESHOLD:
                    disease_type = "疑似病害（置信度不足）"
                return disease_type, confidence_score, probs_dict
            except Exception as e:
                print(f"图像诊断失败: {e}")
                return "未知病害", 0.0, {}

        if self.model is None:
            return "模型未加载", 0.0, {}
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
_diagnosis_engine_model_path: Optional[str] = None


def get_diagnosis_engine() -> DiseaseDiagnosisEngine:
    """获取诊断引擎单例"""
    global _diagnosis_engine, _diagnosis_engine_model_path
    resolved_model_path = DIAGNOSIS_MODEL_PATH
    if _diagnosis_engine is None:
        _diagnosis_engine = DiseaseDiagnosisEngine(model_path=DIAGNOSIS_MODEL_PATH)
        _diagnosis_engine_model_path = resolved_model_path
    elif _diagnosis_engine_model_path != resolved_model_path:
        # 配置路径变更时才重建，避免重复加载
        _diagnosis_engine = DiseaseDiagnosisEngine(model_path=DIAGNOSIS_MODEL_PATH)
        _diagnosis_engine_model_path = resolved_model_path
    return _diagnosis_engine
