from __future__ import annotations

from diagnosis_model import get_diagnosis_engine
from config import DIAGNOSIS_ALLOW_TORCH, DIAGNOSIS_MODEL_PATH


def main() -> None:
    engine = get_diagnosis_engine()
    tf_loaded = bool(getattr(engine, "tf_model", None))
    torch_loaded = bool(getattr(engine, "model", None))
    tf_backend = bool(getattr(engine, "tf_backend", False))

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
