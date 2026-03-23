"""
配置检查脚本
用于验证.env文件配置是否正确
"""
import os
from dotenv import load_dotenv

# 加载.env文件
load_dotenv()

print("=" * 60)
print("配置检查")
print("=" * 60)

# 检查LLM_PROVIDER
llm_provider = os.getenv("LLM_PROVIDER", "openai")
print(f"\n✓ LLM提供商: {llm_provider}")

# 根据提供商检查配置
if llm_provider == "qwen":
    print("\n【通义千问配置检查】")
    qwen_api_key = os.getenv("QWEN_API_KEY", "")
    qwen_model = os.getenv("QWEN_MODEL", "qwen-turbo")
    qwen_base_url = os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    
    if qwen_api_key and qwen_api_key != "your_qwen_api_key_here":
        print(f"✓ QWEN_API_KEY: 已配置 (长度: {len(qwen_api_key)})")
    else:
        print("✗ QWEN_API_KEY: 未配置或使用默认值")
        print("  请到 https://dashscope.aliyun.com/ 获取API密钥")
    
    print(f"✓ QWEN_MODEL: {qwen_model}")
    print(f"✓ QWEN_BASE_URL: {qwen_base_url}")
    
    # 测试API连接
    if qwen_api_key and qwen_api_key != "your_qwen_api_key_here":
        print("\n【测试API连接】")
        try:
            import dashscope
            from dashscope import Generation
            
            dashscope.api_key = qwen_api_key
            
            response = Generation.call(
                model=qwen_model,
                messages=[{"role": "user", "content": "你好"}],
                temperature=0.7
            )
            
            if response.status_code == 200:
                print("✓ API连接成功！")
                # 安全地访问响应内容
                try:
                    content = None
                    if hasattr(response, 'output') and response.output is not None:
                        # 方式1: 直接属性访问 response.output.text（通义千问标准格式）
                        try:
                            content = response.output.text
                            if content:
                                print(f"  测试回复: {content[:50]}...")
                        except (AttributeError, KeyError):
                            # 方式2: 字典格式访问
                            try:
                                content = response.output['text']
                                if content:
                                    print(f"  测试回复: {content[:50]}...")
                            except (KeyError, TypeError):
                                print("  警告: 无法解析响应内容")
                                print(f"  响应对象类型: {type(response)}")
                                print(f"  response.output类型: {type(response.output)}")
                    else:
                        print("  警告: response.output 为空")
                except Exception as e:
                    print(f"  警告: 解析响应时出错: {e}")
                    print(f"  错误类型: {type(e).__name__}")
                    import traceback
                    print(f"  详细错误: {traceback.format_exc()}")
            else:
                error_msg = getattr(response, 'message', '未知错误')
                print(f"✗ API调用失败: {error_msg}")
                print(f"  状态码: {response.status_code}")
        except ImportError:
            print("✗ dashscope库未安装，请运行: pip install dashscope")
        except Exception as e:
            print(f"✗ API测试失败: {e}")
            print(f"  错误类型: {type(e).__name__}")
            import traceback
            print(f"  详细错误: {traceback.format_exc()}")
            print("  请检查API密钥是否正确")

elif llm_provider == "openai":
    print("\n【OpenAI配置检查】")
    openai_api_key = os.getenv("OPENAI_API_KEY", "")
    if openai_api_key and openai_api_key != "your_openai_api_key_here":
        print(f"✓ OPENAI_API_KEY: 已配置 (长度: {len(openai_api_key)})")
    else:
        print("✗ OPENAI_API_KEY: 未配置或使用默认值")

elif llm_provider == "wenxin":
    print("\n【文心一言配置检查】")
    wenxin_api_key = os.getenv("WENXIN_API_KEY", "")
    wenxin_secret_key = os.getenv("WENXIN_SECRET_KEY", "")
    if wenxin_api_key and wenxin_api_key != "your_wenxin_api_key_here":
        print(f"✓ WENXIN_API_KEY: 已配置")
    else:
        print("✗ WENXIN_API_KEY: 未配置")
    if wenxin_secret_key and wenxin_secret_key != "your_wenxin_secret_key_here":
        print(f"✓ WENXIN_SECRET_KEY: 已配置")
    else:
        print("✗ WENXIN_SECRET_KEY: 未配置")

print("\n" + "=" * 60)
print("配置检查完成")
print("=" * 60)

