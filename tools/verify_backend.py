from __future__ import annotations

from pathlib import Path
import os
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from diagnosis_model import get_diagnosis_engine
from config import DIAGNOSIS_ALLOW_TORCH, DIAGNOSIS_MODEL_PATH, DEFAULT_TF_MODEL_PATH


def main() -> None:
    engine = get_diagnosis_engine()
    tf_loaded = bool(getattr(engine, "tf_model", None))
    torch_loaded = bool(getattr(engine, "model", None))
    tf_backend = bool(getattr(engine, "tf_backend", False))

    env_path = os.getenv("DIAGNOSIS_MODEL_PATH")
    env_exists = Path(env_path).exists() if env_path else False
    default_tf_exists = Path(DEFAULT_TF_MODEL_PATH).exists()
    resolved_exists = Path(DIAGNOSIS_MODEL_PATH).exists()

    print(f"cwd={Path.cwd()}")
    print(f"DEFAULT_TF_MODEL_PATH={DEFAULT_TF_MODEL_PATH} exists={default_tf_exists}")
    if env_path:
        print(f"ENV_DIAGNOSIS_MODEL_PATH={env_path} exists={env_exists}")
    else:
        print("ENV_DIAGNOSIS_MODEL_PATH=<unset>")
    print(f"RESOLVED_DIAGNOSIS_MODEL_PATH={DIAGNOSIS_MODEL_PATH} exists={resolved_exists}")

    print(f"DIAGNOSIS_MODEL_PATH={DIAGNOSIS_MODEL_PATH}")
    print(f"DIAGNOSIS_ALLOW_TORCH={DIAGNOSIS_ALLOW_TORCH}")
    print(f"tf_backend={tf_backend}")
    print(f"tf_model_loaded={tf_loaded}")
    print(f"torch_model_loaded={torch_loaded}")

    if tf_backend and tf_loaded:
        print("USING_TF")
    elif torch_loaded:
        print("USING_TORCH")
    else:
        print("NO_MODEL")


if __name__ == "__main__":
    main()
