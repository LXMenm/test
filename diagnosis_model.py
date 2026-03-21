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
from pathlib import Path
from config import (
    DIAGNOSIS_MODEL_TYPE,
    DIAGNOSIS_MODEL_PATH,
    DIAGNOSIS_ALLOW_TORCH,
    DIAGNOSIS_BACKEND,
    USE_GPU,
    DIAGNOSIS_CONFIDENCE_THRESHOLD,
    TEXT_DIAGNOSIS_BACKEND,
    TEXT_MODEL_DIR,
)
import os
from knowledge_base import get_kb_manager
from text_model.infer_text_classifier import BertTextClassifier


_kb_manager = None
_disease_classes_cache = None


def _get_kb_manager():
    global _kb_manager
    if _kb_manager is None:
        _kb_manager = get_kb_manager()
    return _kb_manager


def _get_disease_classes() -> list[str]:
    global _disease_classes_cache
    if _disease_classes_cache is None:
        _disease_classes_cache = list(_get_kb_manager().get_disease_classes())
    return list(_disease_classes_cache)


FUSE_MULTIMODAL_VERSION = "fuse_v4_text_gate_with_weak_conflict_20260321"
PREDICT_TEXT_PROBA_VERSION = "text_v3_bert_with_rule_fallback_20260316"
IMAGE_RELIABLE_TOP1_THRESHOLD = 0.70
IMAGE_RELIABLE_MARGIN_THRESHOLD = 0.15
TEXT_RELIABLE_TOP1_THRESHOLD = 0.45
TEXT_RELIABLE_MARGIN_THRESHOLD = 0.10
WEAK_CONFLICT_MIN_IMAGE_TOP1 = 0.50
WEAK_CONFLICT_MIN_TEXT_TOP1 = 0.40


class DiagnosisModel(nn.Module):
    """诊断模型基类"""
    
    def __init__(self, num_classes: int | None = None):
        super(DiagnosisModel, self).__init__()
        self.num_classes = num_classes or len(_get_disease_classes())
    
    def forward(self, x):
        raise NotImplementedError


class DenseNet121Model(DiagnosisModel):
    """DenseNet121模型"""
    
    def __init__(self, num_classes: int | None = None):
        super(DenseNet121Model, self).__init__(num_classes)
        self.model = models.densenet121(pretrained=True)
        num_features = self.model.classifier.in_features
        self.model.classifier = nn.Linear(num_features, self.num_classes)
    
    def forward(self, x):
        return self.model(x)


class ResNet50Model(DiagnosisModel):
    """ResNet50模型"""
    
    def __init__(self, num_classes: int | None = None):
        super(ResNet50Model, self).__init__(num_classes)
        self.model = models.resnet50(pretrained=True)
        num_features = self.model.fc.in_features
        self.model.fc = nn.Linear(num_features, self.num_classes)
    
    def forward(self, x):
        return self.model(x)


class ViTModel(DiagnosisModel):
    """Vision Transformer模型"""
    
    def __init__(self, num_classes: int | None = None):
        super(ViTModel, self).__init__(num_classes)
        self.model = models.vit_b_16(pretrained=True)
        num_features = self.model.heads.head.in_features
        self.model.heads.head = nn.Linear(num_features, self.num_classes)
    
    def forward(self, x):
        return self.model(x)


def create_model(model_type: str = DIAGNOSIS_MODEL_TYPE, num_classes: int | None = None) -> DiagnosisModel:
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
        self._text_classifier = None
        self._text_classifier_available = None

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
                disease_classes = _get_disease_classes()
                probs_dict = {
                    disease_classes[i]: probabilities[0][i].item()
                    for i in range(len(disease_classes))
                }
                
                disease_type = disease_classes[predicted.item()]
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
        diagnosis_result = _get_kb_manager().rule_diagnosis(crop_type, symptoms)
        
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
        diagnosis_result = _get_kb_manager().rule_diagnosis(crop_type, symptoms)
        
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
        base_description = _get_kb_manager().get_disease_description(disease_type)
        symptom_text = "、".join(symptoms)
        return f"{base_description} 当前观察到的症状包括：{symptom_text}。"

    def predict_image_proba(self, image_path: str) -> Dict[str, float]:
        """返回 canonical 中文病害 key 的图像概率分布。"""
        _, _, probs = self.diagnose_from_image(image_path)
        canonical_probs: Dict[str, float] = {}
        for label, prob in (probs or {}).items():
            disease = _get_kb_manager().map_image_label_to_disease(label)
            canonical_probs[disease] = canonical_probs.get(disease, 0.0) + float(prob)
        total = sum(v for v in canonical_probs.values() if v > 0)
        if total <= 0:
            return {}
        return {k: v / total for k, v in canonical_probs.items()}

    def _load_text_classifier(self):
        if self._text_classifier_available is True:
            return self._text_classifier
        if self._text_classifier_available is False:
            return None
        if not TEXT_MODEL_DIR:
            self._text_classifier_available = False
            return None
        model_path = Path(TEXT_MODEL_DIR)
        if not model_path.exists():
            self._text_classifier_available = False
            return None
        try:
            self._text_classifier = BertTextClassifier(str(model_path))
            self._text_classifier_available = True
            return self._text_classifier
        except Exception:
            self._text_classifier = None
            self._text_classifier_available = False
            return None

    def predict_text_proba_rule_based(
        self,
        raw_text: Optional[str] = None,
        symptoms: Optional[List[str]] = None,
        growth_stage: Optional[str] = None,
        environment: Optional[str] = None,
        facility: Optional[str] = None,
        province: Optional[str] = None,
    ) -> Dict[str, float]:
        """KB 规则版文本概率诊断（fallback）。"""
        normalized_symptoms = _get_kb_manager().normalize_symptoms(symptoms or [])
        if not _get_kb_manager().has_effective_text_evidence(normalized_symptoms):
            return {}
        return _get_kb_manager().score_diseases_from_text(
            crop_type="番茄",
            symptoms=normalized_symptoms,
            growth_stage=growth_stage,
            environment=environment,
            facility=facility,
            province=province,
        )

    def predict_text_proba_bert(
        self,
        raw_text: Optional[str] = None,
        symptoms: Optional[List[str]] = None,
        growth_stage: Optional[str] = None,
        environment: Optional[str] = None,
        facility: Optional[str] = None,
        province: Optional[str] = None,
    ) -> Dict[str, float]:
        normalized_symptoms = _get_kb_manager().normalize_symptoms(symptoms or [])
        classifier = self._load_text_classifier()
        if not classifier:
            return {}

        probs = classifier.predict_probs(
            raw_text=raw_text,
            symptoms=normalized_symptoms,
            growth_stage=growth_stage,
            environment=environment,
            facility=facility,
            province=province,
        )
        disease_classes = _get_disease_classes()
        filtered = {k: float(v) for k, v in (probs or {}).items() if k in disease_classes}
        # 输出格式与融合层兼容：只保留 canonical disease 且归一化
        return self._normalized(filtered)

    def predict_text_proba(
        self,
        raw_text: Optional[str] = None,
        symptoms: Optional[List[str]] = None,
        growth_stage: Optional[str] = None,
        environment: Optional[str] = None,
        facility: Optional[str] = None,
        province: Optional[str] = None,
    ) -> Dict[str, float]:
        """优先 BERT 文本分类器，失败时回退 KB 规则。"""
        normalized_symptoms = _get_kb_manager().normalize_symptoms(symptoms or [])
        text_evidence_active = bool(normalized_symptoms)
        if not text_evidence_active:
            return {}

        backend = (TEXT_DIAGNOSIS_BACKEND or "auto").lower()

        if backend == "rule":
            return self.predict_text_proba_rule_based(
                raw_text=raw_text,
                symptoms=normalized_symptoms,
                growth_stage=growth_stage,
                environment=environment,
                facility=facility,
                province=province,
            )

        if backend == "bert":
            return self.predict_text_proba_bert(
                raw_text=raw_text,
                symptoms=normalized_symptoms,
                growth_stage=growth_stage,
                environment=environment,
                facility=facility,
                province=province,
            )

        if backend != "auto":
            backend = "auto"

        try:
            bert_probs = self.predict_text_proba_bert(
                raw_text=raw_text,
                symptoms=normalized_symptoms,
                growth_stage=growth_stage,
                environment=environment,
                facility=facility,
                province=province,
            )
            if bert_probs:
                return bert_probs
        except Exception:
            pass

        return self.predict_text_proba_rule_based(
            raw_text=raw_text,
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
        text_confidence: float = 0.0,
        text_evidence_active: Optional[bool] = None,
    ) -> Tuple[Dict[str, float], Dict[str, object]]:
        """图像/文本/先验融合（动态权重，避免缺失模态稀释主模态）。"""
        image_probs = self._normalized(image_probs)
        text_probs = self._normalized(text_probs)
        prior_probs = self._normalized(prior_probs)

        has_image = bool(image_probs)
        has_text = bool(text_evidence_active) if text_evidence_active is not None else bool(text_probs)
        has_prior = bool(prior_probs)

        image_top3 = self._topk(image_probs, 3)
        text_top3 = self._topk(text_probs, 3)
        prior_top3 = self._topk(prior_probs, 3)
        image_top1_conf = float(image_top3[0][1]) if image_top3 else 0.0
        image_top2_conf = float(image_top3[1][1]) if len(image_top3) > 1 else 0.0
        image_margin = image_top1_conf - image_top2_conf
        reliable_image = bool(
            image_top3
            and image_top1_conf >= IMAGE_RELIABLE_TOP1_THRESHOLD
            and image_margin >= IMAGE_RELIABLE_MARGIN_THRESHOLD
        )
        text_top1_conf = float(text_top3[0][1]) if text_top3 else 0.0
        text_top2_conf = float(text_top3[1][1]) if len(text_top3) > 1 else 0.0
        text_margin = text_top1_conf - text_top2_conf
        reliable_text = bool(
            text_top3
            and text_top1_conf >= TEXT_RELIABLE_TOP1_THRESHOLD
            and text_margin >= TEXT_RELIABLE_MARGIN_THRESHOLD
        )
        text_probs_for_fusion = text_probs if reliable_text else {}
        image_top1 = image_top3[0][0] if image_top3 else None
        text_top1 = text_top3[0][0] if text_top3 else None
        conflict = bool(
            has_image
            and has_text
            and reliable_image
            and reliable_text
            and image_top1
            and text_top1
            and image_top1 != text_top1
        )
        weak_conflict_candidate = bool(
            has_image
            and has_text
            and image_top1
            and text_top1
            and image_top1 != text_top1
            and (
                image_top1_conf >= WEAK_CONFLICT_MIN_IMAGE_TOP1
                or text_top1_conf >= WEAK_CONFLICT_MIN_TEXT_TOP1
            )
        )

        base_weights = {"image": 0.0, "text": 0.0, "prior": 0.0}
        confidence_drop_reason = None
        fusion_case = "none"

        if has_image and has_text:
            if reliable_image and reliable_text and conflict:
                fusion_case = "conflict"
                base_weights = {"image": 0.50, "text": 0.50, "prior": 0.0}
                confidence_drop_reason = "image_text_conflict"
            elif reliable_image and reliable_text:
                fusion_case = "consistent"
                base_weights = {"image": 0.65, "text": 0.35, "prior": 0.0}
            elif reliable_image and not reliable_text:
                fusion_case = "image_strong_text_weak"
                base_weights = {"image": 1.0, "text": 0.0, "prior": 0.0}
            elif (not reliable_image) and reliable_text:
                fusion_case = "image_weak_text_strong"
                base_weights = {"image": 0.2, "text": 0.8, "prior": 0.0}
            else:
                fusion_case = "both_weak"
                base_weights = {"image": 0.5, "text": 0.5, "prior": 0.0}
        elif has_image:
            fusion_case = "image_only"
            base_weights = {"image": 1.0, "text": 0.0, "prior": 0.0}
        elif has_text:
            fusion_case = "text_only"
            base_weights = {"image": 0.0, "text": 1.0, "prior": 0.0}
        else:
            fusion_case = "prior_only"
            base_weights = {"image": 0.0, "text": 0.0, "prior": 1.0 if has_prior else 0.0}

        if not reliable_text and fusion_case != "both_weak":
            text_probs_for_fusion = {}
        if fusion_case == "both_weak":
            text_probs_for_fusion = text_probs

        # 无文本证据时，避免 text 权重被误激活。
        if not has_text:
            base_weights["text"] = 0.0
        # 无图像证据时，避免 image 权重被误激活。
        if not has_image:
            base_weights["image"] = 0.0

        if confidence_drop_reason and not conflict:
            confidence_drop_reason = None

        # 仅对存在模态做权重重分配，缺失模态不参与。
        active = {
            "image": has_image,
            "text": has_text and bool(text_probs_for_fusion),
            "prior": has_prior and base_weights.get("prior", 0.0) > 0,
        }
        active_sum = sum(base_weights[k] for k, on in active.items() if on)
        if active_sum <= 0:
            normalized_weights = {"image": 0.0, "text": 0.0, "prior": 0.0}
        else:
            normalized_weights = {
                k: (base_weights[k] / active_sum if active.get(k) else 0.0)
                for k in ["image", "text", "prior"]
            }

        keys = set(image_probs) | set(text_probs) | set(prior_probs)
        if not keys:
            meta = {
                "fuse_version": FUSE_MULTIMODAL_VERSION,
                "has_image": has_image,
                "has_text": has_text,
                "has_prior": has_prior,
                "image_reliable": reliable_image,
                "text_reliable": reliable_text,
                "image_top1_conf": image_top1_conf,
                "text_top1_conf": text_top1_conf,
                "image_margin": image_margin,
                "text_margin": text_margin,
                "fusion_case": fusion_case,
                "normalized_weights": normalized_weights,
                "pre_fusion_top1": {"image": image_top3[:1], "text": text_top3[:1], "prior": prior_top3[:1]},
                "pre_fusion_top3": {"image": image_top3, "text": text_top3, "prior": prior_top3},
                "post_fusion_top3": [("健康", 1.0)],
                "confidence_drop_reason": confidence_drop_reason,
                "modality_conflict_flag": conflict,
                "weak_conflict_candidate": weak_conflict_candidate,
            }
            return {"健康": 1.0}, meta

        fused = {}
        for key in keys:
            fused[key] = (
                normalized_weights["image"] * image_probs.get(key, 0.0)
                + normalized_weights["text"] * text_probs_for_fusion.get(key, 0.0)
                + normalized_weights["prior"] * prior_probs.get(key, 0.0)
            )
        fused = self._normalized(fused)
        meta = {
            "fuse_version": FUSE_MULTIMODAL_VERSION,
            "has_image": has_image,
            "has_text": has_text,
            "has_prior": has_prior,
            "image_reliable": reliable_image,
            "text_reliable": reliable_text,
            "image_top1_conf": image_top1_conf,
            "text_top1_conf": text_top1_conf,
            "image_margin": image_margin,
            "text_margin": text_margin,
            "fusion_case": fusion_case,
            "normalized_weights": normalized_weights,
            "pre_fusion_top1": {"image": image_top3[:1], "text": text_top3[:1], "prior": prior_top3[:1]},
            "pre_fusion_top3": {"image": image_top3, "text": text_top3, "prior": prior_top3},
            "post_fusion_top3": self._topk(fused, 3),
            "confidence_drop_reason": confidence_drop_reason,
            "modality_conflict_flag": conflict,
            "weak_conflict_candidate": weak_conflict_candidate,
        }
        return fused, meta

    def build_diagnosis_evidence(
        self,
        normalized_symptoms: List[str],
        raw_symptoms: List[str],
        image_probs: Dict[str, float],
        text_probs: Dict[str, float],
        prior_probs: Dict[str, float],
        fusion_probs: Dict[str, float],
        fusion_meta: Dict[str, object],
        modality_conflict_flag: bool,
        final_disease: str,
        final_confidence: float,
        final_source: str,
    ) -> Dict[str, object]:
        image_top3 = self._topk(image_probs, 3)
        text_top3 = self._topk(text_probs, 3)
        prior_top3 = self._topk(prior_probs, 3)
        fusion_top3 = self._topk(fusion_probs, 3)
        concise_summary = f"融合诊断Top1: {final_disease} ({final_confidence:.2f})" if fusion_top3 else "无可用证据"
        detailed_reason = (
            f"图像top1={image_top3[0][0]}({image_top3[0][1]:.2f})；" if image_top3 else "图像分支缺失；"
        )
        detailed_reason += (
            f"文本top1={text_top3[0][0]}({text_top3[0][1]:.2f})；" if text_top3 else "文本分支缺失；"
        )
        if prior_top3:
            detailed_reason += f"先验top1={prior_top3[0][0]}({prior_top3[0][1]:.2f})；"
        detailed_reason += f"融合后={final_disease}({final_confidence:.2f})。"
        if modality_conflict_flag:
            detailed_reason += "图文top1冲突，已采用保守融合权重。"

        return {
            "normalized_symptoms": normalized_symptoms,
            "raw_symptoms": raw_symptoms,
            "image_top3": image_top3,
            "text_top3": text_top3,
            "prior_top3": prior_top3,
            "fusion_top3": fusion_top3,
            "weights": fusion_meta.get("normalized_weights") if isinstance(fusion_meta, dict) else {},
            "fusion_meta": fusion_meta,
            "modality_conflict_flag": modality_conflict_flag,
            "final_disease": final_disease,
            "final_confidence": final_confidence,
            "final_source": final_source,
            "concise_summary": concise_summary,
            "detailed_reason": detailed_reason,
            "summary": concise_summary,
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
