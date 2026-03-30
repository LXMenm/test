"""
大模型API工具模块
支持多种大模型API调用
"""
import json
from typing import Optional, Dict, Any
from config import (
    LLM_PROVIDER,
    OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL,
    QWEN_API_KEY, QWEN_BASE_URL, QWEN_MODEL,
    WENXIN_API_KEY, WENXIN_SECRET_KEY, WENXIN_MODEL
)
from runtime_settings import get_admin_flag


def call_llm(prompt: str, system_prompt: Optional[str] = None, temperature: float = 0.7) -> str:
    """
    调用大模型API生成回复

    Args:
        prompt: 用户提示词
        system_prompt: 系统提示词（可选）
        temperature: 温度参数，控制随机性

    Returns:
        模型生成的回复文本
    """
    if not bool(get_admin_flag("llm.enable_llm", True)):
        raise RuntimeError("LLM_DISABLED_BY_ADMIN_CONFIG")
    if LLM_PROVIDER == "openai":
        return _call_openai(prompt, system_prompt, temperature)
    elif LLM_PROVIDER == "qwen":
        return _call_qwen(prompt, system_prompt, temperature)
    elif LLM_PROVIDER == "wenxin":
        return _call_wenxin(prompt, system_prompt, temperature)
    else:
        raise ValueError(f"不支持的LLM提供商: {LLM_PROVIDER}")


def _call_openai(prompt: str, system_prompt: Optional[str] = None, temperature: float = 0.7) -> str:
    """调用OpenAI API"""
    try:
        from openai import OpenAI
        
        client = OpenAI(
            api_key=OPENAI_API_KEY,
            base_url=OPENAI_BASE_URL
        )
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            temperature=temperature
        )
        
        return response.choices[0].message.content
    except Exception as e:
        print(f"OpenAI API调用失败: {e}")
        return f"API调用失败: {str(e)}"


def _call_qwen(prompt: str, system_prompt: Optional[str] = None, temperature: float = 0.7) -> str:
    """调用通义千问API"""
    try:
        import dashscope
        from dashscope import Generation
        
        if not QWEN_API_KEY or QWEN_API_KEY == "your_qwen_api_key_here":
            return "API调用失败: 未配置QWEN_API_KEY，请在.env文件中设置"
        
        dashscope.api_key = QWEN_API_KEY
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        response = Generation.call(
            model=QWEN_MODEL,
            messages=messages,
            temperature=temperature
        )
        
        if response.status_code == 200:
            # 通义千问API的响应格式：response.output.text
            try:
                if hasattr(response, 'output') and response.output is not None:
                    # 通义千问API返回格式：response.output.text
                    # GenerationOutput对象同时支持属性访问和字典访问
                    
                    # 方式1: 直接属性访问 response.output.text（最直接）
                    try:
                        text = response.output.text
                        if text:
                            return text
                    except (AttributeError, KeyError):
                        pass
                    
                    # 方式2: 字典访问 response.output['text']
                    try:
                        text = response.output['text']
                        if text:
                            return text
                    except (KeyError, TypeError):
                        pass
                    
                    # 方式3: 使用get方法（如果支持）
                    try:
                        if hasattr(response.output, 'get'):
                            text = response.output.get('text')
                            if text:
                                return text
                    except Exception:
                        pass
                
                return f"API调用失败: 无法解析响应格式，响应对象: {type(response)}"
            except Exception as e:
                return f"API调用失败: 解析响应时出错 - {str(e)}"
        else:
            error_msg = getattr(response, 'message', '未知错误')
            return f"API调用失败: {error_msg} (状态码: {response.status_code})"
    except ImportError:
        return "API调用失败: dashscope库未安装，请运行 pip install dashscope"
    except Exception as e:
        print(f"通义千问API调用失败: {e}")
        return f"API调用失败: {str(e)}"


def _call_wenxin(prompt: str, system_prompt: Optional[str] = None, temperature: float = 0.7) -> str:
    """调用文心一言API"""
    try:
        import qianfan
        
        chat_comp = qianfan.ChatCompletion(
            ak=WENXIN_API_KEY,
            sk=WENXIN_SECRET_KEY
        )
        
        messages = []
        if system_prompt:
            messages.append({"role": "user", "content": system_prompt + "\n\n" + prompt})
        else:
            messages.append({"role": "user", "content": prompt})
        
        response = chat_comp.do(
            model=WENXIN_MODEL,
            messages=messages,
            temperature=temperature
        )
        
        return response["result"]
    except Exception as e:
        print(f"文心一言API调用失败: {e}")
        return f"API调用失败: {str(e)}"


def extract_json_from_response(response: str) -> Optional[Dict[str, Any]]:
    """
    从模型回复中提取JSON格式的数据

    Args:
        response: 模型回复文本

    Returns:
        解析后的JSON字典，如果解析失败返回None
    """
    try:
        # 尝试直接解析
        return json.loads(response)
    except:
        # 尝试提取JSON代码块
        import re
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except:
                pass
        
        # 尝试提取大括号内容
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except:
                pass
                pass
        
        return None
