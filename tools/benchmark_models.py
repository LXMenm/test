from __future__ import annotations

import sys
import json
import time
from pathlib import Path

import numpy as np
import tensorflow as tf
from tensorflow.keras.preprocessing.image import img_to_array, load_img

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

IMAGE_PATH = PROJECT_ROOT / "tomato" / "val" / "Tomato___Early_blight" / "0ae44a6c-1213-4312-a11b-c7c5d4e585d0___RS_Erly.B 9442.JPG"
PAPER_OPT_PATH = PROJECT_ROOT / "models" / "densenet121_tomato_disease_model_fine_tuned_paper_opt.h5"
LIGHT_PATH = PROJECT_ROOT / "models" / "mobilenetv3_light_v1.keras"

IMAGE_SIZE = 224
WARMUP = 10
RUNS = 100


def preprocess(image_path: Path) -> np.ndarray:
    img = load_img(image_path, target_size=(IMAGE_SIZE, IMAGE_SIZE))
    arr = img_to_array(img).astype("float32") / 255.0
    return np.expand_dims(arr, axis=0)


def load_benchmark_model(model_path: Path):
    name = model_path.name.lower()

    if "paper_opt" in name:
        from tomato.densenet121_paper_opt import get_custom_objects
        return tf.keras.models.load_model(
            model_path,
            custom_objects=get_custom_objects(),
            compile=False,
        )

    if "light_v1" in name or "mobilenet" in name:
        from tomato.mobilenetv3_light_v1 import get_custom_objects
        return tf.keras.models.load_model(
            model_path,
            custom_objects=get_custom_objects(),
            compile=False,
        )

    return tf.keras.models.load_model(model_path, compile=False)


def benchmark(model_path: Path) -> dict[str, float]:
    model = load_benchmark_model(model_path)
    x = preprocess(IMAGE_PATH)

    for _ in range(WARMUP):
        _ = model.predict(x, verbose=0)

    start = time.perf_counter()
    for _ in range(RUNS):
        _ = model.predict(x, verbose=0)
    elapsed = time.perf_counter() - start

    return {
        "runs": RUNS,
        "total_seconds": round(elapsed, 4),
        "avg_ms_per_image": round(elapsed * 1000 / RUNS, 3),
    }


def file_size_mb(path: Path) -> float:
    return round(path.stat().st_size / (1024 * 1024), 2)


def main() -> None:
    results = {
        "tf_paper_opt": {
            "path": str(PAPER_OPT_PATH),
            "size_mb": file_size_mb(PAPER_OPT_PATH),
            "benchmark": benchmark(PAPER_OPT_PATH),
        },
        "tf_light_v1": {
            "path": str(LIGHT_PATH),
            "size_mb": file_size_mb(LIGHT_PATH),
            "benchmark": benchmark(LIGHT_PATH),
        },
    }
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()