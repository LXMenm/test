# 使用说明

## 快速开始

### 1. 环境配置

```bash
# 安装依赖
pip install -r requirements.txt

# 配置环境变量
# Windows: 创建 .env 文件
# Linux/Mac: cp .env.example .env
```

### 2. 配置API密钥

编辑 `.env` 文件，配置你选择的大模型API：

#### 选项1：使用OpenAI（推荐）
```env
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-your-api-key-here
OPENAI_MODEL=gpt-3.5-turbo
```

#### 选项2：使用通义千问（国内推荐）
```env
LLM_PROVIDER=qwen
QWEN_API_KEY=your-qwen-api-key-here
QWEN_MODEL=qwen-turbo
```

#### 选项3：使用文心一言
```env
LLM_PROVIDER=wenxin
WENXIN_API_KEY=your-api-key
WENXIN_SECRET_KEY=your-secret-key
WENXIN_MODEL=ernie-bot-turbo
```

### 3. 运行示例

```bash
python main.py
```

## API密钥获取

### OpenAI
1. 访问 https://platform.openai.com/
2. 注册账号并创建API密钥
3. 将密钥配置到 `.env` 文件

### 通义千问（阿里云）
1. 访问 https://dashscope.aliyun.com/
2. 注册阿里云账号
3. 开通DashScope服务
4. 创建API密钥

### 文心一言（百度）
1. 访问 https://cloud.baidu.com/
2. 注册百度智能云账号
3. 开通文心一言服务
4. 创建API密钥和Secret Key

## 诊断模型说明

系统默认使用预训练的DenseNet121模型（ImageNet预训练权重）。如果需要使用自己训练的模型：

1. 训练模型并保存到 `models/diagnosis_model.pth`
2. 在 `.env` 中配置：
```env
DIAGNOSIS_MODEL_PATH=models/diagnosis_model.pth
```

## 使用示例

### 基本使用

```python
from workflow import run_diagnosis

# 输入病害描述
query = "我的番茄叶子发黄了，还有斑点，现在是开花期"

# 运行诊断
result = run_diagnosis(query)

# 查看结果
print(f"病害类型: {result['病害类型']}")
print(f"置信度: {result['诊断置信度']:.2%}")
print(f"治疗方案: {result['治疗方案']}")
```

### 支持的作物

- 番茄（重点支持，使用深度学习模型）
- 水稻
- 小麦
- 玉米
- 黄瓜

### 支持的病害

#### 番茄病害
- 早疫病
- 晚疫病
- 黄化曲叶病毒病
- 叶霉病
- 白粉病
- 细菌性斑点病
- 灰霉病

#### 其他作物病害
- 水稻：稻瘟病、细菌性条斑病、纹枯病
- 小麦：锈病、白粉病、叶枯病

## 故障排除

### 1. API调用失败
- 检查API密钥是否正确
- 检查网络连接
- 系统会自动降级到规则匹配模式

### 2. 模型加载失败
- 首次运行会自动下载预训练权重
- 如果下载失败，检查网络连接
- 系统会自动使用规则诊断

### 3. 诊断准确率低
- 提供更详细的症状描述
- 对于番茄病害，建议提供病害图片（未来功能）
- 检查诊断置信度，低于0.6时建议咨询专家

## 性能优化

### GPU加速
如果有NVIDIA GPU，可以启用GPU加速：

```env
USE_GPU=true
```

### 模型选择
根据需求选择不同的诊断模型：

- `densenet121`：准确率高（99%），速度中等
- `resnet50`：准确率较高（95.6%），速度较快
- `vit`：准确率高（98%），速度较慢

## 注意事项

1. **API费用**：使用大模型API会产生费用，请注意控制调用次数
2. **诊断仅供参考**：系统诊断结果仅供参考，严重病害请咨询专业农技人员
3. **数据隐私**：确保API密钥安全，不要泄露给他人

