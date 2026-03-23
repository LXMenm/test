# 前端应用说明（React + TypeScript + Vite）

本目录是番茄病害诊断系统的前端工程，主要页面包括：
- 诊断
- 数据看板（含天气卡片）
- 档案管理
- 知识库
- 专家复核/管理页面

## 1. 启动开发环境

在仓库根目录执行：

```bash
npm --prefix app install
npm --prefix app run dev
```

默认开发地址通常为 `http://localhost:5173`。

## 2. 连接后端 API

前端通过 `fetch('/api/...')` 访问后端接口。

推荐两种方式：
1. 与后端同域部署（最简单）
2. 本地开发时使用 Vite 代理，将 `/api` 转发到后端（例如 `http://localhost:8000`）

后端服务默认可通过以下命令启动：

```bash
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

## 3. 构建

```bash
npm --prefix app run build
```

该命令会执行 TypeScript 编译并输出生产构建产物。

## 4. dist 产物与后端集成

构建后产物位于：

- `app/dist/`

后端会将该目录作为前端静态资源来源之一（用于一体化部署）。

## 5. 常用命令

```bash
# 开发
npm --prefix app run dev

# 构建
npm --prefix app run build

# 预览构建产物
npm --prefix app run preview
```

