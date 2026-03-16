from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional


def _safe_text(value: object) -> str:
    text = str(value or "").strip()
    return text


def build_input_text(
    *,
    text: str,
    symptoms: Optional[List[str]] = None,
    growth_stage: Optional[str] = None,
    environment: Optional[str] = None,
    facility: Optional[str] = None,
    province: Optional[str] = None,
) -> str:
    """构造文本分类器输入；兼容纯 text 和 text+结构化字段。"""
    fields = []
    if symptoms:
        symptom_text = " ".join([_safe_text(item) for item in symptoms if _safe_text(item)])
        if symptom_text:
            fields.append(f"症状：{symptom_text}")
    if _safe_text(growth_stage):
        fields.append(f"生育期：{_safe_text(growth_stage)}")
    if _safe_text(environment):
        fields.append(f"环境：{_safe_text(environment)}")
    if _safe_text(facility):
        fields.append(f"设施：{_safe_text(facility)}")
    if _safe_text(province):
        fields.append(f"地区：{_safe_text(province)}")
    if _safe_text(text):
        fields.append(f"原始描述：{_safe_text(text)}")
    return "；".join(fields) if fields else ""


class TextClassifierInferencer:
    def __init__(self, model_dir: str, label_map_path: str):
        from transformers import AutoModelForSequenceClassification, AutoTokenizer  # type: ignore
        import torch  # type: ignore

        self._torch = torch
        self.model_dir = model_dir
        self.tokenizer = AutoTokenizer.from_pretrained(model_dir)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_dir)
        self.model.eval()

        payload = json.loads(Path(label_map_path).read_text(encoding="utf-8"))
        self.label2id: Dict[str, int] = {str(k): int(v) for k, v in payload.items()}
        self.id2label: Dict[int, str] = {int(v): str(k) for k, v in self.label2id.items()}
        self.labels: List[str] = [self.id2label[i] for i in sorted(self.id2label)]

    def predict_text_probs(
        self,
        text: str,
        symptoms: Optional[List[str]] = None,
        growth_stage: Optional[str] = None,
        environment: Optional[str] = None,
        facility: Optional[str] = None,
        province: Optional[str] = None,
        topk: int = 3,
    ) -> Dict[str, float]:
        merged_text = build_input_text(
            text=text,
            symptoms=symptoms,
            growth_stage=growth_stage,
            environment=environment,
            facility=facility,
            province=province,
        )
        if not merged_text:
            return {label: 0.0 for label in self.labels}

        encoded = self.tokenizer(
            merged_text,
            truncation=True,
            padding="max_length",
            max_length=256,
            return_tensors="pt",
        )
        with self._torch.no_grad():
            logits = self.model(**encoded).logits
            probs = self._torch.softmax(logits, dim=-1).squeeze(0).cpu().numpy().tolist()

        out = {self.id2label[i]: float(probs[i]) for i in range(len(probs)) if i in self.id2label}
        # 保证概率和为1，并覆盖全部标签
        for label in self.labels:
            out.setdefault(label, 0.0)
        total = sum(max(v, 0.0) for v in out.values())
        if total <= 0:
            return {label: 1.0 / len(self.labels) for label in self.labels}
        out = {k: max(v, 0.0) / total for k, v in out.items()}
        _ = topk
        return out


def load_text_classifier(model_dir: str, label_map_path: str) -> Optional[TextClassifierInferencer]:
    model_path = Path(model_dir)
    if not model_path.exists():
        return None
    try:
        return TextClassifierInferencer(model_dir=model_dir, label_map_path=label_map_path)
    except Exception:
        return None


def topk_from_probs(probs: Dict[str, float], k: int = 3) -> List[tuple[str, float]]:
    return sorted([(k0, float(v0)) for k0, v0 in (probs or {}).items()], key=lambda x: x[1], reverse=True)[:k]
