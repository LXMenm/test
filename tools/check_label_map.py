#!/usr/bin/env python3
"""校验番茄标签映射与知识库类别一致性。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Set

REPO_ROOT = Path(__file__).resolve().parents[1]
LABEL_MAP_PATH = REPO_ROOT / "tomato" / "label_map_cn.json"
TRAIN_DIR = REPO_ROOT / "tomato" / "train"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from knowledge_base import get_kb_manager


def load_label_map() -> dict[str, str]:
    if not LABEL_MAP_PATH.exists():
        raise FileNotFoundError(f"未找到标签映射文件: {LABEL_MAP_PATH}")
    return json.loads(LABEL_MAP_PATH.read_text(encoding="utf-8"))


def list_train_categories() -> List[str]:
    if not TRAIN_DIR.exists():
        return []
    return sorted([path.name for path in TRAIN_DIR.iterdir() if path.is_dir()])


def diff_sets(label: str, expected: Set[str], actual: Set[str]) -> None:
    missing = expected - actual
    extra = actual - expected
    if missing:
        print(f"{label} 缺失: {sorted(missing)}")
    if extra:
        print(f"{label} 多余: {sorted(extra)}")
    if not missing and not extra:
        print(f"{label} 一致")


def main() -> None:
    label_map = load_label_map()
    kb_manager = get_kb_manager()
    kb_classes = set(kb_manager.get_disease_classes())

    mapped_values = set(label_map.values())
    diff_sets("知识库类别校验", mapped_values, kb_classes.intersection(mapped_values))
    invalid_values = mapped_values - kb_classes
    if invalid_values:
        print(f"映射值不在知识库中: {sorted(invalid_values)}")

    train_categories = set(list_train_categories())
    if not train_categories:
        print("未找到 tomato/train 类别目录，跳过覆盖性校验")
    else:
        diff_sets("训练目录覆盖校验", train_categories, set(label_map.keys()))


if __name__ == "__main__":
    main()
