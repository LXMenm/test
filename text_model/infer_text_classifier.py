from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

import torch
import torch.nn.functional as F


class BertTextClassifier:
    def __init__(self, model_dir: str):
        self.model_dir = Path(model_dir)
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.tokenizer = AutoTokenizer.from_pretrained(str(self.model_dir))
        self.model = AutoModelForSequenceClassification.from_pretrained(str(self.model_dir))
        self.model.eval()

        label_map_path = self.model_dir / "label_map.json"
        if not label_map_path.exists():
            label_map_path = Path(__file__).resolve().parent / "label_map.json"
        with open(label_map_path, "r", encoding="utf-8") as f:
            self.label2id: Dict[str, int] = {str(k): int(v) for k, v in json.load(f).items()}
        self.id2label: Dict[int, str] = {v: k for k, v in self.label2id.items()}

    def build_input_text(
        self,
        *,
        raw_text: Optional[str] = None,
        symptoms: Optional[List[str]] = None,
        growth_stage: Optional[str] = None,
        environment: Optional[str] = None,
        facility: Optional[str] = None,
        province: Optional[str] = None,
    ) -> str:
        parts: List[str] = []
        if symptoms:
            cleaned = [str(symptom).strip() for symptom in symptoms if str(symptom).strip()]
            if cleaned:
                parts.append(f"症状：{' '.join(cleaned)}")
        if growth_stage and str(growth_stage).strip():
            parts.append(f"生育期：{str(growth_stage).strip()}")
        if environment and str(environment).strip():
            parts.append(f"环境：{str(environment).strip()}")
        if facility and str(facility).strip():
            parts.append(f"设施：{str(facility).strip()}")
        if province and str(province).strip():
            parts.append(f"地区：{str(province).strip()}")
        if raw_text and str(raw_text).strip():
            parts.append(f"原始描述：{str(raw_text).strip()}")
        return "；".join(parts).strip()

    @torch.no_grad()
    def predict_probs(
        self,
        *,
        raw_text: Optional[str] = None,
        symptoms: Optional[List[str]] = None,
        growth_stage: Optional[str] = None,
        environment: Optional[str] = None,
        facility: Optional[str] = None,
        province: Optional[str] = None,
    ) -> Dict[str, float]:
        text = self.build_input_text(
            raw_text=raw_text,
            symptoms=symptoms,
            growth_stage=growth_stage,
            environment=environment,
            facility=facility,
            province=province,
        )
        if not text:
            return {}

        encoded = self.tokenizer(
            text,
            truncation=True,
            padding=True,
            max_length=256,
            return_tensors="pt",
        )
        outputs = self.model(**encoded)
        probs = F.softmax(outputs.logits, dim=-1).squeeze(0)

        result: Dict[str, float] = {}
        for idx, prob in enumerate(probs.tolist()):
            label = self.id2label.get(idx)
            if label is not None:
                result[label] = float(prob)

        total = sum(result.values())
        if total > 0:
            result = {k: float(v) / total for k, v in result.items()}
        return result


def load_text_classifier(model_dir: str) -> Optional[BertTextClassifier]:
    model_path = Path(model_dir)
    if not model_path.exists():
        return None
    try:
        return BertTextClassifier(str(model_path))
    except Exception:
        return None
