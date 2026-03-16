from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict

import pandas as pd


def build_input_text(row: Dict[str, object]) -> str:
    parts = []
    symptoms = str(row.get("symptoms") or "").strip()
    growth_stage = str(row.get("growth_stage") or "").strip()
    environment = str(row.get("environment") or "").strip()
    facility = str(row.get("facility") or "").strip()
    province = str(row.get("province") or "").strip()
    text = str(row.get("text") or "").strip()

    if symptoms:
        parts.append(f"症状：{symptoms}")
    if growth_stage:
        parts.append(f"生育期：{growth_stage}")
    if environment:
        parts.append(f"环境：{environment}")
    if facility:
        parts.append(f"设施：{facility}")
    if province:
        parts.append(f"地区：{province}")
    if text:
        parts.append(f"原始描述：{text}")
    return "；".join(parts)


def compute_metrics(eval_pred):
    import numpy as np
    from sklearn.metrics import accuracy_score, f1_score

    logits, labels = eval_pred
    preds = np.argmax(logits, axis=-1)
    return {
        "accuracy": float(accuracy_score(labels, preds)),
        "macro_f1": float(f1_score(labels, preds, average="macro")),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Train BERT text classifier for tomato disease diagnosis")
    parser.add_argument("--train_csv", default="data/text_cls/train.csv")
    parser.add_argument("--dev_csv", default="data/text_cls/dev.csv")
    parser.add_argument("--test_csv", default="data/text_cls/test.csv")
    parser.add_argument("--label_map", default="text_model/label_map.json")
    parser.add_argument("--model_name", default="hfl/chinese-roberta-wwm-ext")
    parser.add_argument("--output_dir", default="models/text_cls_bert")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch_size", type=int, default=8)
    args = parser.parse_args()

    from datasets import Dataset
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        Trainer,
        TrainingArguments,
    )

    label_map = json.loads(Path(args.label_map).read_text(encoding="utf-8"))
    label2id = {str(k): int(v) for k, v in label_map.items()}
    id2label = {int(v): str(k) for k, v in label2id.items()}

    def load_split(path: str) -> Dataset:
        df = pd.read_csv(path)
        if "text" not in df.columns or "label" not in df.columns:
            raise ValueError(f"{path} 缺少必须字段 text/label")
        df = df.fillna("")
        df["input_text"] = df.apply(lambda row: build_input_text(row.to_dict()), axis=1)
        df["labels"] = df["label"].map(label2id)
        if df["labels"].isna().any():
            bad = sorted(set(df.loc[df["labels"].isna(), "label"].tolist()))
            raise ValueError(f"{path} 存在未知标签: {bad}")
        return Dataset.from_pandas(df[["input_text", "labels"]], preserve_index=False)

    train_ds = load_split(args.train_csv)
    dev_ds = load_split(args.dev_csv)
    test_ds = load_split(args.test_csv)

    tokenizer = AutoTokenizer.from_pretrained(args.model_name)

    def tokenize_fn(batch):
        return tokenizer(
            batch["input_text"],
            truncation=True,
            padding="max_length",
            max_length=256,
        )

    train_tok = train_ds.map(tokenize_fn, batched=True)
    dev_tok = dev_ds.map(tokenize_fn, batched=True)
    test_tok = test_ds.map(tokenize_fn, batched=True)

    model = AutoModelForSequenceClassification.from_pretrained(
        args.model_name,
        num_labels=len(label2id),
        label2id=label2id,
        id2label=id2label,
    )

    training_args = TrainingArguments(
        output_dir=args.output_dir,
        eval_strategy="epoch",
        save_strategy="epoch",
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        load_best_model_at_end=True,
        metric_for_best_model="macro_f1",
        greater_is_better=True,
        logging_steps=20,
        report_to="none",
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_tok,
        eval_dataset=dev_tok,
        tokenizer=tokenizer,
        compute_metrics=compute_metrics,
    )

    trainer.train()
    trainer.save_model(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)

    dev_metrics = trainer.evaluate(dev_tok)
    test_metrics = trainer.evaluate(test_tok, metric_key_prefix="test")
    print("[TextCLS] dev:", dev_metrics)
    print("[TextCLS] test:", test_metrics)


if __name__ == "__main__":
    main()
