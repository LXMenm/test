#!/usr/bin/env python3
"""Evaluate image-only / image+rule / image+bert multimodal diagnosis."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Dict, List, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diagnosis_model import DISEASE_CLASSES, get_diagnosis_engine


def parse_symptoms(raw: str | None) -> List[str]:
    if not raw:
        return []
    text = raw.strip()
    if not text:
        return []
    for sep in [",", "，", ";", "；", "|"]:
        text = text.replace(sep, " ")
    return [token for token in text.split() if token]


def top1_label(probs: Dict[str, float], labels: Sequence[str]) -> str:
    if not probs:
        return ""
    return max(labels, key=lambda label: float(probs.get(label, 0.0)))


def accuracy(y_true: Sequence[str], y_pred: Sequence[str]) -> float:
    return (sum(1 for g, p in zip(y_true, y_pred) if g == p) / len(y_true)) if y_true else 0.0


def macro_f1(y_true: Sequence[str], y_pred: Sequence[str], labels: Sequence[str]) -> float:
    f1_scores: List[float] = []
    for label in labels:
        tp = sum(1 for g, p in zip(y_true, y_pred) if g == label and p == label)
        fp = sum(1 for g, p in zip(y_true, y_pred) if g != label and p == label)
        fn = sum(1 for g, p in zip(y_true, y_pred) if g == label and p != label)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1_scores.append(0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall))
    return sum(f1_scores) / len(f1_scores) if f1_scores else 0.0


def evaluate(input_path: Path, output_csv: Path, text_backend: str = "both") -> None:
    engine = get_diagnosis_engine()

    y_true: List[str] = []
    y_image_only: List[str] = []
    y_image_rule: List[str] = []
    y_image_bert: List[str] = []
    rows_out: List[Dict[str, str]] = []

    with input_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            label = (row.get("label") or "").strip()
            image_path = (row.get("image_path") or "").strip()
            if not label or not image_path:
                continue

            text = (row.get("text") or "").strip()
            symptoms = parse_symptoms(row.get("symptoms"))
            growth_stage = (row.get("growth_stage") or "").strip() or None
            environment = (row.get("environment") or "").strip() or None
            facility = (row.get("facility") or "").strip() or None
            province = (row.get("province") or "").strip() or None

            image_probs = engine.predict_image_proba(image_path)
            image_only_pred = top1_label(image_probs, DISEASE_CLASSES)

            rule_text_probs: Dict[str, float] = {}
            bert_text_probs: Dict[str, float] = {}
            if text_backend in {"both", "rule"}:
                rule_text_probs = engine.predict_text_proba_rule_based(
                    raw_text=text,
                    symptoms=symptoms,
                    growth_stage=growth_stage,
                    environment=environment,
                    facility=facility,
                    province=province,
                )
            if text_backend in {"both", "bert"}:
                bert_text_probs = engine.predict_text_proba_bert(
                    raw_text=text,
                    symptoms=symptoms,
                    growth_stage=growth_stage,
                    environment=environment,
                    facility=facility,
                    province=province,
                )

            fused_rule = image_probs
            if text_backend in {"both", "rule"}:
                fused_rule, _ = engine.fuse_multimodal_probs(
                    image_probs=image_probs,
                    text_probs=rule_text_probs,
                    prior_probs={},
                    image_confidence=max(image_probs.values()) if image_probs else 0.0,
                    text_confidence=max(rule_text_probs.values()) if rule_text_probs else 0.0,
                    text_evidence_active=bool(symptoms),
                )

            fused_bert = image_probs
            if text_backend in {"both", "bert"}:
                fused_bert, _ = engine.fuse_multimodal_probs(
                    image_probs=image_probs,
                    text_probs=bert_text_probs,
                    prior_probs={},
                    image_confidence=max(image_probs.values()) if image_probs else 0.0,
                    text_confidence=max(bert_text_probs.values()) if bert_text_probs else 0.0,
                    text_evidence_active=bool(symptoms),
                )

            pred_rule = top1_label(fused_rule, DISEASE_CLASSES)
            pred_bert = top1_label(fused_bert, DISEASE_CLASSES)

            y_true.append(label)
            y_image_only.append(image_only_pred)
            y_image_rule.append(pred_rule)
            y_image_bert.append(pred_bert)

            rows_out.append(
                {
                    "image_path": image_path,
                    "label": label,
                    "text": text,
                    "image_only_top1": image_only_pred,
                    "image_rule_top1": pred_rule,
                    "image_bert_top1": pred_bert,
                    "image_probs": json.dumps(image_probs, ensure_ascii=False),
                    "rule_text_probs": json.dumps(rule_text_probs, ensure_ascii=False),
                    "bert_text_probs": json.dumps(bert_text_probs, ensure_ascii=False),
                    "fused_rule_probs": json.dumps(fused_rule, ensure_ascii=False),
                    "fused_bert_probs": json.dumps(fused_bert, ensure_ascii=False),
                }
            )

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "image_path",
                "label",
                "text",
                "image_only_top1",
                "image_rule_top1",
                "image_bert_top1",
                "image_probs",
                "rule_text_probs",
                "bert_text_probs",
                "fused_rule_probs",
                "fused_bert_probs",
            ],
        )
        writer.writeheader()
        writer.writerows(rows_out)

    print(f"samples={len(y_true)}")
    print(f"[image_only] accuracy={accuracy(y_true, y_image_only):.4f} macro_f1={macro_f1(y_true, y_image_only, DISEASE_CLASSES):.4f}")
    if text_backend in {"both", "rule"}:
        print(f"[image_plus_rule] accuracy={accuracy(y_true, y_image_rule):.4f} macro_f1={macro_f1(y_true, y_image_rule, DISEASE_CLASSES):.4f}")
    if text_backend in {"both", "bert"}:
        print(f"[image_plus_bert] accuracy={accuracy(y_true, y_image_bert):.4f} macro_f1={macro_f1(y_true, y_image_bert, DISEASE_CLASSES):.4f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run multimodal evaluation.")
    parser.add_argument("--input", type=Path, default=Path("data/multimodal_eval.csv"))
    parser.add_argument("--output", type=Path, default=Path("outputs/multimodal_eval_results.csv"))
    parser.add_argument("--text_backend", choices=["both", "rule", "bert"], default="both")
    args = parser.parse_args()

    if not args.input.exists():
        raise FileNotFoundError(
            f"Input file not found: {args.input}. Please create it per experiments/README.md format."
        )

    evaluate(args.input, args.output, text_backend=args.text_backend)


if __name__ == "__main__":
    main()
