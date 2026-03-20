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

### 4. 命令行 CLI 使用

在无需额外数据库的原型阶段，可以直接通过 CLI 调用诊断、查看日志、维护知识库：

```bash
# 运行诊断（可加图像路径/生长阶段提示）
python cli.py diagnose --query "番茄叶子发黄有斑点" --growth-stage "开花期" --image ./exam.jpg

# 查看最近 5 条对话记录
python cli.py logs --limit 5

# 知识库：列出病害及描述
python cli.py kb list

# 知识库：新增病害
python cli.py kb add-disease --name "新病害" --description "示例描述"

# 知识库：更新治疗/预防
python cli.py kb update-treatment --name "早疫病" --treatment "喷药方案..." --prevention "田间管理建议..."

# 知识库：添加诊断规则
python cli.py kb add-rule --crop "番茄" --symptom "斑点" --disease "早疫病" --confidence 0.8 --explanation "斑点与早疫病典型症状匹配"

# 知识库：维护症状到病害映射
python cli.py kb add-symptom-map --symptom "霉斑" --diseases "叶霉病,灰霉病"
```

> 说明：知识库管理操作当前为内存级修改，适合演示与快速迭代；若需长期持久化，可在后续接入文件或数据库存储。

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

### 推荐默认持久化配置（生产/部署建议）

```env
DATABASE_URL=mysql+pymysql://root:123456@127.0.0.1:3306/tomato_diagnosis?charset=utf8mb4
PROFILE_STORE_MODE=mysql
EVENT_STORE_MODE=mysql
TRACE_STORE_MODE=mysql
KB_STORE_MODE=mysql
```

> 如需兼容旧文件存储，仍可分别覆盖为 `file` / `dual` / `mysql`。应用启动时会输出 `[StorageResolved] ...` 以确认当前模式。

### 模型选择
根据需求选择不同的诊断模型：

- `densenet121`：准确率高（99%），速度中等
- `resnet50`：准确率较高（95.6%），速度较快
- `vit`：准确率高（98%），速度较慢

## 注意事项

1. **API费用**：使用大模型API会产生费用，请注意控制调用次数
2. **诊断仅供参考**：系统诊断结果仅供参考，严重病害请咨询专业农技人员
3. **数据隐私**：确保API密钥安全，不要泄露给他人


## Day3：FastAPI + Web 上传演示

### 1) 安装依赖

```bash
pip install -r requirements.txt
```

### 2) 启动服务

```bash
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

启动后请确认日志中包含：

```text
[StorageResolved] DATABASE_URL=... PROFILE_STORE_MODE=mysql EVENT_STORE_MODE=mysql TRACE_STORE_MODE=mysql KB_STORE_MODE=mysql
```

### 3) 浏览器访问

打开：`http://127.0.0.1:8000/`

### 4) curl 调用示例

```bash
curl -F "file=@tomato/val/某张图片.jpg" -F "crop_type=番茄" -F "symptoms=斑点,发黄" http://127.0.0.1:8000/api/diagnose-image
```

### 5) 返回字段说明（简要）

- `image_result`：图像诊断主结果（病害名、置信度、Top3）。
- `top3`：候选病害及概率（含百分比字段）。
- `treatment`：基于知识库返回的治疗方案与预防建议；若无则为 `null`。
- `fallback_reason`：回退触发原因（如低置信度、低边际差）。

> 说明：`models/*.h5` 为本地训练生成产物，不随仓库默认提交。
