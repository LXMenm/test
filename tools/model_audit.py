#!/usr/bin/env python3
"""模型与数据自检脚本。"""
from __future__ import annotations

import os
import random
from pathlib import Path
from typing import Iterable, List, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_SUFFIXES = (".h5", ".keras", ".pth", ".pt", ".ckpt", ".onnx", ".tflite")


def iter_files_with_suffixes(root: Path, suffixes: Iterable[str]) -> List[Path]:
    return [path for path in root.rglob("*") if path.is_file() and path.suffix in suffixes]


def get_diagnosis_model_path() -> str:
    config_path = REPO_ROOT / "config.py"
    if not config_path.exists():
        return "config.py 不存在"

    config_globals: dict = {}
    exec(compile(config_path.read_text(encoding="utf-8"), str(config_path), "exec"), config_globals)
    return str(config_globals.get("DIAGNOSIS_MODEL_PATH", "未定义"))


def list_category_dirs(directory: Path) -> Tuple[List[str], int]:
    if not directory.exists():
        return [], 0
    subdirs = sorted([p.name for p in directory.iterdir() if p.is_dir()])
    return subdirs, len(subdirs)


def find_random_image(directory: Path) -> str | None:
    if not directory.exists():
        return None
    candidates = [
        path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png"}
    ]
    if not candidates:
        return None
    return str(random.choice(candidates).relative_to(REPO_ROOT))


def find_gitignore_model_rules() -> List[str]:
    gitignore_path = REPO_ROOT / ".gitignore"
    if not gitignore_path.exists():
        return []
    model_tokens = {"*.h5", "*.keras", "*.pth", "*.pt", "*.ckpt", "*.onnx", "*.tflite"}
    matched = []
    for line in gitignore_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped in model_tokens:
            matched.append(stripped)
    return matched


def main() -> None:
    diagnosis_model_path = get_diagnosis_model_path()
    model_path_exists = os.path.exists(diagnosis_model_path)
    print(f"DIAGNOSIS_MODEL_PATH: {diagnosis_model_path}")
    print(f"DIAGNOSIS_MODEL_PATH 是否存在: {model_path_exists}")

    print("\n仓库内模型文件扫描:")
    model_files = iter_files_with_suffixes(REPO_ROOT, MODEL_SUFFIXES)
    if model_files:
        for path in sorted(model_files):
            print(f"- {path.relative_to(REPO_ROOT)}")
    else:
        print("- 未找到匹配的模型文件")

    train_dir = REPO_ROOT / "tomato" / "train"
    train_categories, train_count = list_category_dirs(train_dir)
    print("\n训练数据目录检查:")
    if train_dir.exists():
        print(f"tomato/train 存在，类别目录数量: {train_count}")
        if train_categories:
            print("类别目录:")
            for name in train_categories:
                print(f"- {name}")
    else:
        print("tomato/train 不存在")

    val_dir = REPO_ROOT / "tomato" / "val"
    print("\n验证数据目录检查:")
    if val_dir.exists():
        random_image = find_random_image(val_dir)
        if random_image:
            print(f"随机样本: {random_image}")
        else:
            print("未找到 jpg/jpeg/png 样本")
    else:
        print("tomato/val 不存在")

    print("\n.gitignore 模型文件忽略规则:")
    ignored_rules = find_gitignore_model_rules()
    if ignored_rules:
        for rule in ignored_rules:
            print(f"- {rule}")
    else:
        print("- 未找到匹配规则")

    has_model_files = bool(model_files) or model_path_exists
    has_training_data = train_dir.exists() and train_count > 0
    print("\n结论:")
    print(f"- 当前仓库是否含可用模型文件？{'是' if has_model_files else '否'}")
    print(f"- 当前仓库是否含可训练数据？{'是' if has_training_data else '否'}")
    if has_model_files:
        suggestion = "可直接使用已有模型路径进行推理。"
    elif has_training_data:
        suggestion = "建议运行训练脚本生成模型文件。"
    else:
        suggestion = "建议复制已有模型文件，或先准备训练数据再运行训练脚本。"
    print(f"- 下一步建议（复制已有模型 or 运行训练脚本生成）：{suggestion}")


if __name__ == "__main__":
    main()
