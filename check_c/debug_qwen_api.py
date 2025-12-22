"""
调试通义千问API响应格式
"""
import os
from dotenv import load_dotenv

load_dotenv()

qwen_api_key = os.getenv("QWEN_API_KEY", "")
qwen_model = os.getenv("QWEN_MODEL", "qwen-turbo")

if not qwen_api_key or qwen_api_key == "your_qwen_api_key_here":
    print("错误: 未配置QWEN_API_KEY")
    exit(1)

try:
    import dashscope
    from dashscope import Generation
    
    dashscope.api_key = qwen_api_key
    
    print("=" * 60)
    print("测试通义千问API")
    print("=" * 60)
    print(f"模型: {qwen_model}")
    print(f"API密钥: {qwen_api_key[:10]}...{qwen_api_key[-5:]}")
    print()
    
    response = Generation.call(
        model=qwen_model,
        messages=[{"role": "user", "content": "你好"}],
        temperature=0.7
    )
    
    print(f"状态码: {response.status_code}")
    print(f"响应类型: {type(response)}")
    print()
    
    print("响应对象属性:")
    print(f"  - dir(response): {[attr for attr in dir(response) if not attr.startswith('_')]}")
    print()
    
    if hasattr(response, 'output'):
        print(f"response.output: {response.output}")
        print(f"response.output类型: {type(response.output)}")
        if response.output:
            print(f"response.output属性: {[attr for attr in dir(response.output) if not attr.startswith('_')]}")
            # 安全地检查text属性
            try:
                if hasattr(response.output, 'text'):
                    print(f"response.output.text: {response.output.text}")
            except Exception as e:
                print(f"访问text属性失败: {e}")
            # 安全地检查choices属性
            try:
                if hasattr(response.output, 'choices'):
                    print(f"response.output.choices: {response.output.choices}")
            except Exception as e:
                print(f"访问choices属性失败: {e}")
    print()
    
    if response.status_code == 200:
        print("尝试提取内容:")
        # 方式1: response.output.text（通义千问标准格式）
        try:
            if hasattr(response, 'output') and response.output:
                if hasattr(response.output, 'text'):
                    content = response.output.text
                    if content:
                        print(f"✓ 方式1成功 (response.output.text): {content[:50]}...")
        except Exception as e:
            print(f"✗ 方式1失败: {e}")
        
        # 方式2: 字典格式访问text
        try:
            if hasattr(response, 'output') and response.output:
                if isinstance(response.output, dict) and 'text' in response.output:
                    content = response.output['text']
                    if content:
                        print(f"✓ 方式2成功 (response.output['text']): {content[:50]}...")
        except Exception as e:
            print(f"✗ 方式2失败: {e}")
        
        # 方式3: response.output.choices[0].message.content（OpenAI兼容格式）
        try:
            if hasattr(response, 'output') and response.output:
                if hasattr(response.output, 'choices') and response.output.choices:
                    content = response.output.choices[0].message.content
                    print(f"✓ 方式3成功 (response.output.choices): {content[:50]}...")
        except Exception as e:
            print(f"✗ 方式3失败: {e}")
    else:
        print(f"API调用失败: {getattr(response, 'message', '未知错误')}")
    
    print()
    print("=" * 60)
    print("完整响应对象:")
    print(response)
    
except ImportError:
    print("错误: dashscope库未安装")
    print("请运行: pip install dashscope")
except Exception as e:
    print(f"错误: {e}")
    import traceback
    traceback.print_exc()

