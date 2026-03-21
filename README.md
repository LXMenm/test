# 基于LangGraph的多智能体番茄病害诊治系统设计与实现

这是一个使用LangGraph框架构建的多智能体协作系统，用于农作物（特别是番茄）病害的诊断和治疗方案推荐。系统集成了大语言模型和深度学习模型，提供智能化的病害诊断服务。

## 系统架构

系统包含四个核心智能体：

1. **接待智能体** (Reception Agent) - **使用大模型API**
   - 使用大语言模型解析用户输入
   - 智能识别作物类型、生长阶段
   - 提取症状信息
   - 支持：OpenAI GPT、通义千问、文心一言

2. **诊断智能体** (Diagnosis Agent) - **使用深度学习模型**
   - 基于深度学习模型进行病害诊断
   - 支持DenseNet121、ResNet50、ViT等模型
   - 参考论文算法实现（论文：Transform and Deep Learning Algorithms for the Early Detection and Recognition of Tomato Leaf Disease）
   - 计算诊断置信度
   - 提供病害详细描述

3. **治疗方案智能体** (Treatment Agent) - **使用大模型API**
   - 使用大语言模型制定个性化治疗方案
   - 推荐药物使用方法
   - 提供预防建议

4. **监督智能体** (Supervisor Agent) - **使用大模型API**
   - 使用大语言模型进行智能流程协调
   - 决定下一步执行哪个智能体
   - 控制流程结束条件

## 文件结构

```
test/
├── state.py              # 状态管理模块：定义系统状态结构
├── agents.py             # 智能体模块：实现各个智能体的逻辑
├── workflow.py           # 工作流模块：使用LangGraph构建协作流程
├── main.py               # 示例脚本：演示系统使用
├── config.py             # 配置文件：管理API密钥和模型配置
├── llm_utils.py          # 大模型API工具模块
├── personalization/      # 农户个性设置：档案模型、上下文生成与约束过滤
├── diagnosis_model.py    # 诊断模型模块：深度学习模型实现
├── requirements.txt      # 依赖包列表
├── data/profiles/        # 农户档案样例存储目录（如 F001.json）
└── .env.example          # 环境变量配置示例
```

## 安装依赖

```bash
pip install -r requirements.txt
```

## 配置说明

1. **复制环境变量配置文件**：
```bash
cp .env.example .env
```

2. **配置大模型API密钥**（选择一种）：
   - **OpenAI**：设置 `OPENAI_API_KEY`
   - **通义千问**：设置 `QWEN_API_KEY`，并设置 `LLM_PROVIDER=qwen`
   - **文心一言**：设置 `WENXIN_API_KEY` 和 `WENXIN_SECRET_KEY`，并设置 `LLM_PROVIDER=wenxin`

3. **配置持久化存储**（推荐默认全部使用 MySQL）：
   - `DATABASE_URL`：MySQL 连接串
   - `PROFILE_STORE_MODE=mysql`
   - `EVENT_STORE_MODE=mysql`
   - `TRACE_STORE_MODE=mysql`
   - `KB_STORE_MODE=mysql`
   - 若需要兼容旧路径，仍可按需切回 `file` / `dual` / `mysql`

4. **配置诊断模型**（可选）：
   - `DIAGNOSIS_MODEL_TYPE`：选择模型类型（densenet121, resnet50, vit）
   - `DIAGNOSIS_MODEL_PATH`：自定义模型路径（如果已训练）
   - `USE_GPU`：是否使用GPU加速

## 使用方法

### 推荐默认运行配置

```env
DATABASE_URL=mysql+pymysql://root:123456@127.0.0.1:3306/tomato_diagnosis?charset=utf8mb4
PROFILE_STORE_MODE=mysql
EVENT_STORE_MODE=mysql
TRACE_STORE_MODE=mysql
KB_STORE_MODE=mysql
```

应用启动时会输出 `[StorageResolved] ...` 日志，便于确认当前实际运行模式。

### 方式1：运行示例脚本

```bash
python main.py
```

这将运行4个预设的测试案例，展示系统对不同作物病害的诊断能力。

### 方式2：在代码中使用

```python
from workflow import run_diagnosis

# 输入病害描述
query = "我的水稻叶子发黄了，现在是苗期"

# 运行诊断
result = run_diagnosis(query)

# 查看结果
print(result)
```

## 工作流程

```
用户输入
   ↓
监督智能体（决策）
   ↓
接待智能体（信息提取）
   ↓
监督智能体（决策）
   ↓
诊断智能体（病害诊断）
   ↓
监督智能体（决策）
   ↓
治疗方案智能体（方案生成）
   ↓
监督智能体（决策）
   ↓
输出诊断报告
```

## 核心特性

### 1. 状态管理
使用TypedDict定义全局状态，所有智能体共享状态信息：
- 作物信息（类型、生长阶段）
- 症状列表
- 诊断结果（病害类型、置信度）
- 治疗方案和预防建议

### 2. 条件路由
监督智能体根据当前步骤动态决定下一步执行的智能体，实现灵活的流程控制。

### 3. 知识库驱动
系统内置病害知识库，包含：
- 水稻常见病害（稻瘟病、纹枯病、细菌性条斑病）
- 番茄常见病害（早疫病、晚疫病、黄化曲叶病毒病）
- 小麦常见病害（锈病、叶枯病）

### 4. 农户个性设置（Farmer Personalization）
- `personalization/` 模块定义了档案模型（Pydantic）、JSON 持久化、个性化上下文生成及治疗方案过滤规则。
- 状态中新增 `farmer_id/base_id` 与个性化上下文，低置信度诊断会按档案偏好自动追问。
- 样例档案：`data/profiles/F001.json`，包含温室位置、有机偏好、禁用成分与采收临近约束。
- CLI 新增 `profile` 子命令，可 `list/show/edit/set-active-base/reset` 档案；诊断命令支持 `--farmer-id`、`--base-id` 直接应用个性化设置。

## 技术特性

### 1. 大模型集成
- **支持多种大模型API**：OpenAI GPT、通义千问、文心一言
- **智能信息提取**：接待智能体使用大模型准确提取作物信息
- **个性化方案生成**：治疗方案智能体根据具体情况生成定制化方案
- **智能流程协调**：监督智能体使用大模型进行决策

### 2. 深度学习诊断
- **多种模型支持**：DenseNet121（论文中准确率99%）、ResNet50、ViT
- **基于论文算法**：参考《Transform and Deep Learning Algorithms for the Early Detection and Recognition of Tomato Leaf Disease》
- **症状+图像诊断**：支持基于症状的规则诊断和基于图像的深度学习诊断
- **置信度评估**：提供诊断置信度，帮助用户判断诊断可靠性

### 3. 容错机制
- **API调用失败自动降级**：大模型API失败时自动使用规则匹配
- **模型加载失败处理**：诊断模型加载失败时使用规则诊断
- **JSON解析容错**：支持多种格式的模型回复解析

## 扩展建议

1. **图像识别增强**
   - 增加图像输入智能体
   - 使用计算机视觉模型分析病害图片
   - 支持多模态输入（文本+图像）

2. **模型训练**
   - 使用自己的数据集训练诊断模型
   - 微调预训练模型以适应特定地区病害

3. **知识库扩展**
   - 增加更多作物类型
   - 丰富病害种类和治疗方案
   - 连接外部农业数据库

4. **用户交互优化**
   - 添加多轮对话能力
   - 支持追问和补充信息
   - 提供可视化诊断报告

## 技术栈

- **LangGraph**: 多智能体协作框架
- **LangChain**: 基础组件库
- **Python**: 3.8+
- **TypedDict**: 类型安全的状态管理

## 示例输出

```
================================================================================
农作物病害诊治系统启动
================================================================================

[监督智能体] 协调流程...
  - 当前步骤: start
  - 下一步动作: reception
  - 是否完成: False

[接待智能体] 正在分析用户输入...
  - 作物类型: 水稻
  - 生长阶段: 苗期
  - 症状: ['发黄']

[监督智能体] 协调流程...
  - 当前步骤: reception_complete
  - 下一步动作: diagnosis
  - 是否完成: False

[诊断智能体] 正在分析病害...
  - 病害类型: 稻瘟病
  - 置信度: 85.00%
  - 描述: 稻瘟病是由真菌引起的病害，主要表现为叶片出现黄褐色病斑

[监督智能体] 协调流程...
  - 当前步骤: diagnosis_complete
  - 下一步动作: treatment
  - 是否完成: False

[治疗方案智能体] 正在制定治疗方案...
  - 治疗方案: 使用三环唑或稻瘟灵进行喷雾，每7-10天一次，连续2-3次...
  - 预防建议: 1. 选用抗病品种 2. 合理密植，加强通风 3. 科学施肥...

[监督智能体] 协调流程...
  - 当前步骤: treatment_complete
  - 下一步动作: end
  - 是否完成: True
```

## 许可证

MIT License
