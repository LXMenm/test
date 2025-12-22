"""
配置文件
管理API密钥和模型配置
"""
import os
from typing import Optional

# 尝试加载.env文件
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # 如果python-dotenv未安装，跳过.env文件加载
    # 环境变量仍可通过系统环境变量设置
    pass

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
DIAGNOSIS_MODEL_PATH = os.getenv("DIAGNOSIS_MODEL_PATH", "models/diagnosis_model.pth")
USE_GPU = os.getenv("USE_GPU", "false").lower() == "true"

# 诊断置信度阈值
DIAGNOSIS_CONFIDENCE_THRESHOLD = float(os.getenv("DIAGNOSIS_CONFIDENCE_THRESHOLD", "0.6"))

