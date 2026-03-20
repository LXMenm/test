"""
配置文件
管理API密钥和模型配置
"""
import os
from pathlib import Path
from typing import Optional

# 尝试加载.env文件
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # 如果python-dotenv未安装，跳过.env文件加载
    # 环境变量仍可通过系统环境变量设置
    pass

# 持久化/存储配置
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://root:123456@127.0.0.1:3306/tomato_diagnosis?charset=utf8mb4"
)

PROFILE_STORE_MODE = os.getenv("PROFILE_STORE_MODE", "file")
EVENT_STORE_MODE = os.getenv("EVENT_STORE_MODE", "file")
TRACE_STORE_MODE = os.getenv("TRACE_STORE_MODE", "file")
KB_STORE_MODE = os.getenv("KB_STORE_MODE", "file")

# 大模型API配置
# 支持多种API：openai, qwen(通义千问), wenxin(文心一言)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")  # 默认使用openai

# OpenAI配置
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")

# 通义千问配置（阿里云）
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
QWEN_BASE_URL = os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen-turbo")

# 文心一言配置（百度）
WENXIN_API_KEY = os.getenv("WENXIN_API_KEY", "")
WENXIN_SECRET_KEY = os.getenv("WENXIN_SECRET_KEY", "")
WENXIN_MODEL = os.getenv("WENXIN_MODEL", "ernie-bot-turbo")

# 诊断模型配置
DIAGNOSIS_MODEL_TYPE = os.getenv("DIAGNOSIS_MODEL_TYPE", "densenet121")  # densenet121, resnet50, vit
DIAGNOSIS_BACKEND = os.getenv("DIAGNOSIS_BACKEND", "tf").lower()
if DIAGNOSIS_BACKEND not in {"tf", "torch", "auto"}:
    print(
        "[ConfigResolved] "
        f"DIAGNOSIS_BACKEND={DIAGNOSIS_BACKEND} 不合法，回退到 tf。"
    )
    DIAGNOSIS_BACKEND = "tf"
PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_TF_MODEL_PATH = PROJECT_ROOT / "models" / "densenet121_tomato_disease_model_fine_tuned.h5"
_ENV_DIAGNOSIS_MODEL_PATH = os.getenv("DIAGNOSIS_MODEL_PATH")


def _resolve_diagnosis_model_path() -> str:
    env_path = Path(_ENV_DIAGNOSIS_MODEL_PATH) if _ENV_DIAGNOSIS_MODEL_PATH else None
    env_exists = env_path.exists() if env_path else False
    env_is_tf = env_path.suffix.lower() in {".h5", ".keras"} if env_path else False
    default_exists = DEFAULT_TF_MODEL_PATH.exists()

    if DIAGNOSIS_BACKEND == "tf":
        if env_exists and env_is_tf:
            return str(env_path)
        if env_exists and not env_is_tf:
            print(
                "[ConfigResolved] "
                f"DIAGNOSIS_MODEL_PATH={_ENV_DIAGNOSIS_MODEL_PATH} 不是TF模型，回退默认TF模型。"
            )
        if default_exists:
            return str(DEFAULT_TF_MODEL_PATH)
        if env_path:
            print(
                "[ConfigResolved] "
                f"DIAGNOSIS_MODEL_PATH={_ENV_DIAGNOSIS_MODEL_PATH} 不存在，且默认TF模型缺失。"
            )
            return str(env_path)
        print(
            "[ConfigResolved] "
            "默认TF模型不存在，请先运行 tomato/train_densenet121.py 生成模型。"
        )
        return str(DEFAULT_TF_MODEL_PATH)

    if DIAGNOSIS_BACKEND == "torch":
        if env_path:
            if not env_exists:
                print(
                    "[ConfigResolved] "
                    f"DIAGNOSIS_MODEL_PATH={_ENV_DIAGNOSIS_MODEL_PATH} 不存在，Torch 将尝试使用默认权重。"
                )
            return str(env_path)
        print(
            "[ConfigResolved] "
            "DIAGNOSIS_BACKEND=torch 但未设置 DIAGNOSIS_MODEL_PATH。"
        )
        return ""

    if default_exists:
        return str(DEFAULT_TF_MODEL_PATH)
    if env_exists and env_is_tf:
        return str(env_path)
    if env_path and not env_exists:
        print(
            "[ConfigResolved] "
            f"DIAGNOSIS_MODEL_PATH={_ENV_DIAGNOSIS_MODEL_PATH} 不存在，且默认TF模型缺失。"
        )
        return str(env_path)
    if env_path:
        return str(env_path)
    print(
        "[ConfigResolved] "
        "默认TF模型不存在，请先运行 tomato/train_densenet121.py 生成模型。"
    )
    return str(DEFAULT_TF_MODEL_PATH)


DIAGNOSIS_MODEL_PATH = _resolve_diagnosis_model_path()

TEXT_DIAGNOSIS_BACKEND = os.getenv("TEXT_DIAGNOSIS_BACKEND", "auto")
TEXT_MODEL_NAME = os.getenv("TEXT_MODEL_NAME", "bert-base-chinese")
TEXT_MODEL_DIR = os.getenv("TEXT_MODEL_DIR", str(PROJECT_ROOT / "models" / "text_cls_bert"))

USE_GPU = os.getenv("USE_GPU", "false").lower() == "true"
DIAGNOSIS_ALLOW_TORCH = os.getenv("DIAGNOSIS_ALLOW_TORCH", "0")

# 诊断置信度阈值
DIAGNOSIS_CONFIDENCE_THRESHOLD = float(os.getenv("DIAGNOSIS_CONFIDENCE_THRESHOLD", "0.6"))


_DIAGNOSIS_CONFIG_LOGGED = False


def log_resolved_diagnosis_config() -> None:
    global _DIAGNOSIS_CONFIG_LOGGED
    if _DIAGNOSIS_CONFIG_LOGGED:
        return
    if not os.path.exists(DIAGNOSIS_MODEL_PATH):
        print(
            "[ConfigResolved] "
            "模型文件不存在，请先运行 tomato/train_densenet121.py 生成模型。"
        )
    print(
        "[ConfigResolved] "
        f"DIAGNOSIS_MODEL_PATH={DIAGNOSIS_MODEL_PATH} "
        f"DIAGNOSIS_MODEL_TYPE={DIAGNOSIS_MODEL_TYPE} "
        f"DIAGNOSIS_BACKEND={DIAGNOSIS_BACKEND} "
        f"USE_GPU={USE_GPU} "
        f"DIAGNOSIS_ALLOW_TORCH={DIAGNOSIS_ALLOW_TORCH}"
    )
    _DIAGNOSIS_CONFIG_LOGGED = True


log_resolved_diagnosis_config()
