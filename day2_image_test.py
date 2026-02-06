#!/usr/bin/env python3
"""Day2 图像识别自检脚本（不走工作流、不用 LLM）。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, Optional

from diagnosis_model import get_diagnosis_engine


REPO_ROOT = Path(__file__).resolve().parent
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Day2 图像识别测试脚本")
    parser.add_argument("--image", help="指定图片路径")
    return parser.parse_args()


def find_first_image(directories: Iterable[Path]) -> Optional[Path]:
    for directory in directories:
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                return path
    return None


def main() -> int:
    args = parse_args()
    image_path = Path(args.image).expanduser().resolve() if args.image else None

    if image_path and not image_path.exists():
        print(f"未找到图片: {image_path}")
        return 1

    if image_path is None:
        image_path = find_first_image([
            REPO_ROOT / "tomato" / "val",
            REPO_ROOT / "tomato" / "train",
        ])
        if image_path is None:
            print("未找到可用图片，请指定 --image 或检查 tomato/val 与 tomato/train")
            return 1

    engine = get_diagnosis_engine()
    disease_type, confidence, probs_dict = engine.diagnose_from_image(str(image_path))
    if disease_type == "模型未加载":
        print("模型未加载，请先生成或配置模型文件。")
        return 1
    if not probs_dict:
        print("未获取到有效预测结果。")
        return 1

    top3 = sorted(probs_dict.items(), key=lambda item: item[1], reverse=True)[:3]
    print(f"Image: {image_path}")
    print(f"Top1: {disease_type} conf={confidence:.2f}")
    print(f"Top3: {[(name, round(prob, 4)) for name, prob in top3]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
