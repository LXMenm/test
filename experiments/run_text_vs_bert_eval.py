#!/usr/bin/env python3
"""Evaluate rule-based vs BERT text diagnosis on data/text_cls/test.csv."""

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


def confusion_matrix(y_true: Sequence[str], y_pred: Sequence[str], labels: Sequence[str]) -> List[List[int]]:
    index = {label: i for i, label in enumerate(labels)}
    matrix = [[0 for _ in labels] for _ in labels]
    for gold, pred in zip(y_true, y_pred):
        if gold in index and pred in index:
            matrix[index[gold]][index[pred]] += 1
    return matrix


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


def evaluate(input_csv: Path, output_csv: Path, output_cm_csv: Path, text_backend: str = "both") -> None:
    engine = get_diagnosis_engine()

    rows_out: List[Dict[str, str]] = []
    y_true: List[str] = []
    y_rule: List[str] = []
    y_bert: List[str] = []

    with input_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            label = (row.get("label") or "").strip()
            if not label:
                continue
            text = (row.get("text") or "").strip()
            symptoms = parse_symptoms(row.get("symptoms"))
            growth_stage = (row.get("growth_stage") or "").strip() or None
            environment = (row.get("environment") or "").strip() or None
            facility = (row.get("facility") or "").strip() or None
            province = (row.get("province") or "").strip() or None

            rule_probs: Dict[str, float] = {}
            bert_probs: Dict[str, float] = {}
            if text_backend in {"both", "rule"}:
                rule_probs = engine.predict_text_proba_rule_based(
                    raw_text=text,
                    symptoms=symptoms,
                    growth_stage=growth_stage,
                    environment=environment,
                    facility=facility,
                    province=province,
                )
            if text_backend in {"both", "bert"}:
                bert_probs = engine.predict_text_proba_bert(
                    raw_text=text,
                    symptoms=symptoms,
                    growth_stage=growth_stage,
                    environment=environment,
                    facility=facility,
                    province=province,
                )

            rule_top1 = top1_label(rule_probs, DISEASE_CLASSES)
            bert_top1 = top1_label(bert_probs, DISEASE_CLASSES)
            y_true.append(label)
            y_rule.append(rule_top1)
            y_bert.append(bert_top1)

            rows_out.append(
                {
                    "text": text,
                    "label": label,
                    "rule_top1": rule_top1,
                    "bert_top1": bert_top1,
                    "rule_probs": json.dumps(rule_probs, ensure_ascii=False),
                    "bert_probs": json.dumps(bert_probs, ensure_ascii=False),
                }
            )

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["text", "label", "rule_top1", "bert_top1", "rule_probs", "bert_probs"],
        )
        writer.writeheader()
        writer.writerows(rows_out)

    selected = []
    if text_backend in {"both", "rule"}:
        selected.append(("rule", y_rule))
    if text_backend in {"both", "bert"}:
        selected.append(("bert", y_bert))

    cm_results = []
    for name, pred in selected:
        acc = accuracy(y_true, pred)
        mf1 = macro_f1(y_true, pred, DISEASE_CLASSES)
        cm = confusion_matrix(y_true, pred, DISEASE_CLASSES)
        cm_results.append((name, cm))
        print(f"[{name}] accuracy={acc:.4f} macro_f1={mf1:.4f} samples={len(y_true)}")
        print(f"[{name}] confusion matrix: {cm}")

    with output_cm_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["model", "gold\\pred", *DISEASE_CLASSES])
        for model_name, cm in cm_results:
            for label, row_values in zip(DISEASE_CLASSES, cm):
                writer.writerow([model_name, label, *row_values])


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare rule-based and BERT text diagnosis.")
    parser.add_argument("--input", type=Path, default=Path("data/text_cls/test.csv"))
    parser.add_argument("--output", type=Path, default=Path("outputs/text_eval_results.csv"))
    parser.add_argument("--cm_output", type=Path, default=Path("outputs/text_eval_confusion_matrix.csv"))
    parser.add_argument("--text_backend", choices=["both", "rule", "bert"], default="both")
    args = parser.parse_args()
    evaluate(args.input, args.output, args.cm_output, text_backend=args.text_backend)


if __name__ == "__main__":
    main()
