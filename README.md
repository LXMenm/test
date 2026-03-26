# 番茄病害图文诊断服务（FastAPI + LangGraph + 个性化 + MySQL）

本项目是一个面向番茄病害诊治场景的**服务化系统**，核心能力包括：
- 图像 + 文本联合诊断
- LangGraph 驱动的流程编排
- 基于统一档案（profiles）的个性化约束与风险增强
- 文件/双写/MySQL 多存储模式
- 前后端一体化交付（FastAPI + React/Vite）

> 当前真实后端主入口为 `app.py`（FastAPI 应用），`main.py` 不再作为系统主入口。

---

## 1. 项目简介

后端以 FastAPI 提供 API，整合：
- `workflow.py`：诊疗流程编排
- `agents.py`：智能体执行逻辑
- `personalization/`：档案模型、上下文拼装、规则过滤
- `repositories/` + `mysql_models.py`：MySQL 读写与归一化表支持

前端位于 `app/`，用于诊断、看板、档案管理、知识库与专家复核等页面。

---

## 2. 目录概览

```text
.
├── app.py                       # FastAPI 主入口（后端服务）
├── workflow.py                  # LangGraph 流程编排
├── agents.py                    # 智能体逻辑
├── state.py                     # 工作流状态定义
├── personalization/             # 档案与个性化逻辑
├── repositories/                # MySQL 仓储层
├── mysql_models.py              # MySQL ORM 模型
├── data/                        # 本地数据（profiles/kb 等）
├── scripts/
│   ├── dev/                     # 开发辅助脚本
│   ├── db/                      # 数据库初始化脚本
│   ├── migrations/              # 迁移/归一化脚本
│   └── verify/                  # 校验脚本
├── tests/
│   ├── api/
│   ├── personalization/
│   ├── migrations/
│   ├── storage/
│   └── kb/
└── app/                         # 前端（React + TypeScript + Vite）
```

---

## 3. 最小可运行步骤（推荐：全量 MySQL）

### 3.1 环境准备

```bash
pip install -r requirements.txt
cp .env.example .env
```

按需配置 `.env`（当前主线推荐：四类存储全部 MySQL）：

```env
DATABASE_URL=mysql+pymysql://root:123456@127.0.0.1:3306/tomato_diagnosis?charset=utf8mb4
PROFILE_STORE_MODE=mysql
EVENT_STORE_MODE=mysql
TRACE_STORE_MODE=mysql
KB_STORE_MODE=mysql
ENABLE_DEMO_ACCOUNTS=false
```

> `ENABLE_DEMO_ACCOUNTS` 默认应为 `false`。  
> - `false`：不会自动补 demo 账号；删除 `A0001/E0001/E0002` 后重启不会回来。  
> - `true`：启动时允许补 demo 账号（仅开发演示场景）。

### 3.2 首次建库（新库初始化）

```bash
python scripts/db/init_db.py
```

### 3.3 旧数据迁移 / schema 迁移（仅旧库需要）

> 重要：`init_db.py` 使用 `create_all()`，**不会自动给旧表加列/改列/加约束**。  
> 旧库请按需执行 `scripts/migrations/*.py`（见第 5 节）。

推荐顺序（按需）：

```bash
# 1) 旧 JSON 数据迁入 MySQL（如果你有 file/dual 历史数据）
python scripts/migrations/migrate_json_to_mysql.py
python scripts/migrations/migrate_kb_json_to_mysql.py

# 2) 归一化子表回填
python scripts/migrations/migrate_profile_normalized.py
python scripts/migrations/migrate_farm_bases_normalized.py
python scripts/migrations/migrate_kb_symptom_map_normalized.py
python scripts/migrations/migrate_kb_treatments_normalized.py

# 3) 一账号一档案约束清洗（先 dry-run，确认报告后再 --apply）
python scripts/migrations/migrate_one_account_one_profile_constraints.py
python scripts/migrations/migrate_one_account_one_profile_constraints.py --apply
```

### 3.4 启动后端（推荐）

```bash
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

启动后检查日志：
- `[StorageResolved] ... PROFILE_STORE_MODE=mysql EVENT_STORE_MODE=mysql TRACE_STORE_MODE=mysql KB_STORE_MODE=mysql`
- `[DemoAccounts] ENABLE_DEMO_ACCOUNTS=false`

### 3.5 启动前端

```bash
npm --prefix app install
npm --prefix app run dev
```

前端默认通过相对路径访问 `/api/*`，开发时可通过 Vite 代理或同域部署接入后端。

### 3.6 首次业务操作建议

1. 使用管理员账号登录（若未启用 demo，请先在数据库或初始化流程准备管理员账号）。  
2. 进入“账号管理”创建业务账号。  
3. 系统会自动创建对应空档案（`user_id = farmer_id = owner_user_id`）。  

### 3.7 前端构建产物

```bash
npm --prefix app run build
```

构建产物在 `app/dist/`，后端可直接作为静态资源目录集成。

---

## 4. 存储模式说明（file / dual / mysql）

通过环境变量控制各类数据源：
- `PROFILE_STORE_MODE`
- `EVENT_STORE_MODE`
- `TRACE_STORE_MODE`
- `KB_STORE_MODE`

当前推荐（主线）：
- `PROFILE_STORE_MODE=mysql`
- `EVENT_STORE_MODE=mysql`
- `TRACE_STORE_MODE=mysql`
- `KB_STORE_MODE=mysql`

兼容模式（仅迁移/排障临时使用，不建议新环境长期使用）：
- `file`：仅文件读写（历史兼容）
- `dual`：文件 + MySQL 双路径（迁移过渡兼容）
- `mysql`：仅 MySQL（生产/联调推荐）

服务启动日志会打印 `[StorageResolved]`，用于确认生效模式。

---

## 5. 脚本索引

### 开发脚本（`scripts/dev/`）
- `scripts/dev/demo_main.py`：示例诊断流程脚本
- `scripts/dev/check_config.py`：环境配置检查

### 数据库脚本（`scripts/db/`）
- `scripts/db/init_db.py`：**新库初始化**（create_all，仅创建缺失表，不做旧表 schema migration）

### 迁移脚本（`scripts/migrations/`）
- `migrate_json_to_mysql.py`：历史 profiles/events/traces 文件数据迁入 MySQL
- `migrate_kb_json_to_mysql.py`：历史 KB JSON 迁入 MySQL
- `migrate_profile_normalized.py`：回填档案归一化子表（设备/禁限用/基地）
- `migrate_farm_bases_normalized.py`：回填基地风险归一化子表
- `migrate_kb_symptom_map_normalized.py`：回填症状映射归一化子表
- `migrate_kb_treatments_normalized.py`：回填治疗方案归一化子表
- `migrate_one_account_one_profile_constraints.py`：一账号一档案清洗 + 约束推进（`--apply` 前先 dry-run 看报告）

### 校验脚本（`scripts/verify/`）
- `verify_kb_file_mysql_parity.py`

---

## 6. 测试索引

- `tests/api/`：API 与端点行为相关测试
- `tests/personalization/`：个性化规则/上下文/策略相关测试
- `tests/migrations/`：迁移与规范化相关测试
- `tests/storage/`：存储回填与读路径切换相关测试
- `tests/kb/`：知识库与文本分类集成相关测试

运行示例：

```bash
pytest
# 或按目录运行
pytest tests/personalization
```

---

## 7. 相关子文档索引

- `app/README.md`：前端开发与构建说明
- `experiments/README.md`：实验脚本说明
- `tomato/README.md`：模型训练/推理相关说明
- `docs/`：迁移、回滚、验收等专题文档
