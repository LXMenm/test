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
    DIAGNOSIS_BACKEND,
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
    
    def __init__(
        self,
        model_type: str = DIAGNOSIS_MODEL_TYPE,
        model_path: Optional[str] = None,
        backend: Optional[str] = None,
        allow_torch: Optional[bool] = None,
    ):
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

        backend_value = backend if backend is not None else DIAGNOSIS_BACKEND
        backend = (backend_value or "tf").lower()
        if backend not in {"tf", "torch", "auto"}:
            backend = "tf"
        if allow_torch is None:
            allow_torch = str(DIAGNOSIS_ALLOW_TORCH).lower() in {"1", "true", "yes"}
        tf_candidate = (
            bool(model_path)
            and model_path.endswith((".h5", ".keras"))
            and os.path.exists(model_path)
        )

        if backend == "tf":
            if tf_candidate:
                self.tf_backend = True
                self.model_path = model_path
                self._load_tf_model(model_path)
            else:
                print(
                    "[DiagnosisEngine] backend=none "
                    "message=TF模型不存在"
                )
            return

        if backend == "torch":
            if allow_torch:
                self._load_torch_model(model_type, model_path)
            else:
                print(
                    "[DiagnosisEngine] backend=none "
                    "message=Torch未启用"
                )
            return

        if tf_candidate:
            self.tf_backend = True
            self.model_path = model_path
            self._load_tf_model(model_path)
        elif allow_torch:
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
                return "模型未部署", 0.0, {}
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
            return "模型未部署", 0.0, {}
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

    def predict_image_proba(self, image_path: str) -> Dict[str, float]:
        """返回 canonical 中文病害 key 的图像概率分布。"""
        _, _, probs = self.diagnose_from_image(image_path)
        canonical_probs: Dict[str, float] = {}
        for label, prob in (probs or {}).items():
            disease = kb_manager.map_image_label_to_disease(label)
            canonical_probs[disease] = canonical_probs.get(disease, 0.0) + float(prob)
        total = sum(v for v in canonical_probs.values() if v > 0)
        if total <= 0:
            return {}
        return {k: v / total for k, v in canonical_probs.items()}

    def predict_text_proba(
        self,
        symptoms: List[str],
        growth_stage: Optional[str] = None,
        environment: Optional[str] = None,
        facility: Optional[str] = None,
        province: Optional[str] = None,
    ) -> Dict[str, float]:
        """KB 驱动的文本概率诊断。"""
        normalized_symptoms = kb_manager.normalize_symptoms(symptoms or [])
        return kb_manager.score_diseases_from_text(
            crop_type="番茄",
            symptoms=normalized_symptoms,
            growth_stage=growth_stage,
            environment=environment,
            facility=facility,
            province=province,
        )

    def build_prior_proba(
        self,
        growth_stage: Optional[str] = None,
        facility: Optional[str] = None,
        province: Optional[str] = None,
    ) -> Dict[str, float]:
        """轻量先验：仅做小幅偏置，避免过强主导。"""
        priors: Dict[str, float] = {}
        facility_text = str(facility or "").lower()
        if any(x in facility_text for x in ["温室", "大棚", "greenhouse", "棚"]):
            priors["叶霉病"] = priors.get("叶霉病", 0.0) + 0.06
        if any(x in facility_text for x in ["露地", "open", "field"]):
            priors["早疫病"] = priors.get("早疫病", 0.0) + 0.05
            priors["晚疫病"] = priors.get("晚疫病", 0.0) + 0.05
        if not priors:
            return {}
        total = sum(priors.values())
        return {k: v / total for k, v in priors.items()} if total > 0 else {}

    @staticmethod
    def _normalized(dist: Dict[str, float]) -> Dict[str, float]:
        if not dist:
            return {}
        total = sum(max(float(v), 0.0) for v in dist.values())
        if total <= 0:
            return {}
        return {k: max(float(v), 0.0) / total for k, v in dist.items()}

    @staticmethod
    def _topk(dist: Dict[str, float], k: int = 3) -> List[Tuple[str, float]]:
        return sorted([(k0, float(v0)) for k0, v0 in (dist or {}).items()], key=lambda x: x[1], reverse=True)[:k]

    def fuse_multimodal_probs(
        self,
        image_probs: Dict[str, float],
        text_probs: Dict[str, float],
        prior_probs: Dict[str, float],
        image_confidence: float = 0.0,
    ) -> Tuple[Dict[str, float], Dict[str, float]]:
        """图像/文本/先验融合。"""
        image_probs = self._normalized(image_probs)
        text_probs = self._normalized(text_probs)
        prior_probs = self._normalized(prior_probs)

        has_image = bool(image_probs)
        has_text = bool(text_probs)
        reliable_image = image_confidence >= 0.6

        if has_image and has_text and reliable_image:
            weights = {"image": 0.60, "text": 0.30, "prior": 0.10}
        elif has_image and has_text:
            weights = {"image": 0.40, "text": 0.50, "prior": 0.10}
        elif has_image:
            weights = {"image": 0.90, "text": 0.00, "prior": 0.10}
        else:
            weights = {"image": 0.00, "text": 0.85 if has_text else 0.0, "prior": 0.15 if has_text else 1.0}

        keys = set(image_probs) | set(text_probs) | set(prior_probs)
        if not keys:
            return {"健康": 1.0}, weights

        fused = {}
        for key in keys:
            fused[key] = (
                weights["image"] * image_probs.get(key, 0.0)
                + weights["text"] * text_probs.get(key, 0.0)
                + weights["prior"] * prior_probs.get(key, 0.0)
            )
        return self._normalized(fused), weights

    def build_diagnosis_evidence(
        self,
        normalized_symptoms: List[str],
        image_probs: Dict[str, float],
        text_probs: Dict[str, float],
        fusion_probs: Dict[str, float],
        weights: Dict[str, float],
        modality_conflict_flag: bool,
    ) -> Dict[str, object]:
        image_top3 = self._topk(image_probs, 3)
        text_top3 = self._topk(text_probs, 3)
        fusion_top3 = self._topk(fusion_probs, 3)
        summary = f"融合诊断Top1: {fusion_top3[0][0]} ({fusion_top3[0][1]:.2f})" if fusion_top3 else "无可用证据"
        return {
            "normalized_symptoms": normalized_symptoms,
            "image_top3": image_top3,
            "text_top3": text_top3,
            "fusion_top3": fusion_top3,
            "weights": weights,
            "modality_conflict_flag": modality_conflict_flag,
            "summary": summary,
        }


# 全局诊断引擎实例
_diagnosis_engine: Optional[DiseaseDiagnosisEngine] = None
_diagnosis_engine_model_path: Optional[str] = None
_diagnosis_engine_backend: Optional[str] = None
_diagnosis_engine_allow_torch: Optional[bool] = None


def get_diagnosis_engine(
    model_path: Optional[str] = None,
    backend: Optional[str] = None,
    allow_torch: Optional[bool] = None,
) -> DiseaseDiagnosisEngine:
    """获取诊断引擎单例"""
    global _diagnosis_engine, _diagnosis_engine_model_path, _diagnosis_engine_backend
    global _diagnosis_engine_allow_torch
    resolved_model_path = model_path or DIAGNOSIS_MODEL_PATH
    resolved_backend = backend or DIAGNOSIS_BACKEND
    resolved_allow_torch = allow_torch
    if _diagnosis_engine is None:
        _diagnosis_engine = DiseaseDiagnosisEngine(
            model_path=resolved_model_path,
            backend=resolved_backend,
            allow_torch=allow_torch,
        )
        _diagnosis_engine_model_path = resolved_model_path
        _diagnosis_engine_backend = resolved_backend
        _diagnosis_engine_allow_torch = resolved_allow_torch
    elif (
        _diagnosis_engine_model_path != resolved_model_path
        or _diagnosis_engine_backend != resolved_backend
        or _diagnosis_engine_allow_torch != resolved_allow_torch
    ):
        # 配置路径变更时才重建，避免重复加载
        _diagnosis_engine = DiseaseDiagnosisEngine(
            model_path=resolved_model_path,
            backend=resolved_backend,
            allow_torch=allow_torch,
        )
        _diagnosis_engine_model_path = resolved_model_path
        _diagnosis_engine_backend = resolved_backend
        _diagnosis_engine_allow_torch = resolved_allow_torch
    return _diagnosis_engine
