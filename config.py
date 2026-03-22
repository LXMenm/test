"""
配置文件
管理 API 密钥、存储后端和诊断模型默认配置。
"""
import os
from pathlib import Path

# 尝试加载.env文件
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # 如果 python-dotenv 未安装，跳过 .env 文件加载
    # 环境变量仍可通过系统环境变量设置
    pass

# 持久化/存储配置
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://root:123456@127.0.0.1:3306/tomato_diagnosis?charset=utf8mb4"
)

PROFILE_STORE_MODE = os.getenv("PROFILE_STORE_MODE", "mysql")
EVENT_STORE_MODE = os.getenv("EVENT_STORE_MODE", "mysql")
TRACE_STORE_MODE = os.getenv("TRACE_STORE_MODE", "mysql")
KB_STORE_MODE = os.getenv("KB_STORE_MODE", "mysql")


_STORAGE_CONFIG_LOGGED = False


def log_resolved_storage_config() -> None:
    global _STORAGE_CONFIG_LOGGED
    if _STORAGE_CONFIG_LOGGED:
        return
    print(
        "[StorageResolved] "
        f"DATABASE_URL={DATABASE_URL} "
        f"PROFILE_STORE_MODE={PROFILE_STORE_MODE} "
        f"EVENT_STORE_MODE={EVENT_STORE_MODE} "
        f"TRACE_STORE_MODE={TRACE_STORE_MODE} "
        f"KB_STORE_MODE={KB_STORE_MODE}"
    )
    _STORAGE_CONFIG_LOGGED = True

# 大模型 API 配置
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")

QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
QWEN_BASE_URL = os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen-turbo")

WENXIN_API_KEY = os.getenv("WENXIN_API_KEY", "")
WENXIN_SECRET_KEY = os.getenv("WENXIN_SECRET_KEY", "")
WENXIN_MODEL = os.getenv("WENXIN_MODEL", "ernie-bot-turbo")

# 诊断模型配置
# DIAGNOSIS_MODEL_TYPE 主要在 Torch 后备链路中使用；TF 默认链路以 DEFAULT_TF_MODEL_PATH 为准。
DIAGNOSIS_BACKEND = os.getenv("DIAGNOSIS_BACKEND", "tf").lower()
if DIAGNOSIS_BACKEND not in {"tf", "torch", "auto"}:
    print(
        "[ConfigResolved] "
        f"DIAGNOSIS_BACKEND={DIAGNOSIS_BACKEND} 不合法，回退到 tf。"
    )
    DIAGNOSIS_BACKEND = "tf"

DIAGNOSIS_MODEL_TYPE = os.getenv("DIAGNOSIS_MODEL_TYPE", "densenet121")
PROJECT_ROOT = Path(__file__).resolve().parent

DEFAULT_TF_MODEL_ID = "tf_default"
DEFAULT_TF_MODEL_LABEL = "默认轻量上线模型"
DEFAULT_TF_MODEL_PROFILE = "MobileNetV3LightV1"
DEFAULT_TF_MODEL_PATH = PROJECT_ROOT / "models" / "mobilenetv3_light_v1.keras"
TF_HIGH_ACCURACY_MODEL_ID = "tf_paper_opt"
TF_HIGH_ACCURACY_MODEL_LABEL = "高精度备选模型"
TF_HIGH_ACCURACY_MODEL_PATH = PROJECT_ROOT / "models" / "densenet121_tomato_disease_model_fine_tuned_paper_opt.h5"

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
                f"DIAGNOSIS_MODEL_PATH={_ENV_DIAGNOSIS_MODEL_PATH} 不是 TF 模型，回退默认 TF 模型。"
            )
        if default_exists:
            return str(DEFAULT_TF_MODEL_PATH)
        if env_path:
            print(
                "[ConfigResolved] "
                f"DIAGNOSIS_MODEL_PATH={_ENV_DIAGNOSIS_MODEL_PATH} 不存在，且默认 TF 模型缺失。"
            )
            return str(env_path)
        print(
            "[ConfigResolved] "
            "默认 TF 模型不存在，请先训练并生成 models/mobilenetv3_light_v1.keras。"
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
            f"DIAGNOSIS_MODEL_PATH={_ENV_DIAGNOSIS_MODEL_PATH} 不存在，且默认 TF 模型缺失。"
        )
        return str(env_path)
    if env_path:
        return str(env_path)
    print(
        "[ConfigResolved] "
        "默认 TF 模型不存在，请先训练并生成 models/mobilenetv3_light_v1.keras。"
    )
    return str(DEFAULT_TF_MODEL_PATH)


DIAGNOSIS_MODEL_PATH = _resolve_diagnosis_model_path()

TEXT_DIAGNOSIS_BACKEND = os.getenv("TEXT_DIAGNOSIS_BACKEND", "auto")
TEXT_MODEL_NAME = os.getenv("TEXT_MODEL_NAME", "bert-base-chinese")
TEXT_MODEL_DIR = os.getenv("TEXT_MODEL_DIR", str(PROJECT_ROOT / "models" / "text_cls_bert"))

USE_GPU = os.getenv("USE_GPU", "false").lower() == "true"
DIAGNOSIS_ALLOW_TORCH = os.getenv("DIAGNOSIS_ALLOW_TORCH", "0")
DIAGNOSIS_CONFIDENCE_THRESHOLD = float(os.getenv("DIAGNOSIS_CONFIDENCE_THRESHOLD", "0.6"))


_DIAGNOSIS_CONFIG_LOGGED = False


def log_resolved_diagnosis_config() -> None:
    global _DIAGNOSIS_CONFIG_LOGGED
    if _DIAGNOSIS_CONFIG_LOGGED:
        return
    if not os.path.exists(DIAGNOSIS_MODEL_PATH):
        print(
            "[ConfigResolved] "
            f"模型文件不存在，请先生成默认模型: {DIAGNOSIS_MODEL_PATH}"
        )

    if DIAGNOSIS_BACKEND == "tf":
        print(
            "[ConfigResolved] "
            f"DEFAULT_MODEL_ID={DEFAULT_TF_MODEL_ID} "
            f"DEFAULT_MODEL_LABEL={DEFAULT_TF_MODEL_LABEL} "
            f"DEFAULT_MODEL_PROFILE={DEFAULT_TF_MODEL_PROFILE} "
            f"BACKUP_MODEL_ID={TF_HIGH_ACCURACY_MODEL_ID} "
            f"BACKUP_MODEL_LABEL={TF_HIGH_ACCURACY_MODEL_LABEL} "
            f"DIAGNOSIS_MODEL_PATH={DIAGNOSIS_MODEL_PATH} "
            f"DIAGNOSIS_BACKEND={DIAGNOSIS_BACKEND} "
            f"USE_GPU={USE_GPU} "
            f"DIAGNOSIS_ALLOW_TORCH={DIAGNOSIS_ALLOW_TORCH}"
        )
    else:
        print(
            "[ConfigResolved] "
            f"DIAGNOSIS_MODEL_PATH={DIAGNOSIS_MODEL_PATH} "
            f"DIAGNOSIS_MODEL_TYPE={DIAGNOSIS_MODEL_TYPE} "
            f"DIAGNOSIS_BACKEND={DIAGNOSIS_BACKEND} "
            f"USE_GPU={USE_GPU} "
            f"DIAGNOSIS_ALLOW_TORCH={DIAGNOSIS_ALLOW_TORCH}"
        )
    _DIAGNOSIS_CONFIG_LOGGED = True


log_resolved_storage_config()
log_resolved_diagnosis_config()
