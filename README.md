# GLM Agent Engine

> 复刻自 Z.ai 容器运行时的 AI Agent 引擎，基于 FastAPI + Caddy 架构。

[![CI](https://github.com/ctz168/glmagent/actions/workflows/ci.yml/badge.svg)](https://github.com/ctz168/glmagent/actions/workflows/ci.yml)
[![Docker Publish](https://github.com/ctz168/glmagent/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/ctz168/glmagent/actions/workflows/docker-publish.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## 📖 项目概述

GLM Agent Engine 是从 Z.ai 生产容器运行时完整复刻的 AI Agent 引擎。它提供了与原始环境一致的运行时能力，包括 LLM 对话代理、图像生成、语音处理、网页搜索等 AI 能力，以及完整的 Skills 扩展系统和沙箱执行环境。

### 核心特性

- **AI 代理引擎** - FastAPI 构建的 RESTful API，代理转发至后端大模型服务
- **多模态支持** - LLM 对话、图像生成 (VLM)、语音转文字 (ASR)、文字转语音 (TTS)
- **Web 能力** - 网页搜索 (Web Search) 和网页内容提取 (Web Read)
- **Skills 系统** - 可插拔的技能模块，支持官方技能和自定义技能
- **沙箱执行** - 容器隔离的工具执行环境，安全的文件管理
- **会话管理** - 完整的会话创建、查询、删除生命周期管理
- **Caddy 反向代理** - 自动 HTTPS、WebSocket 支持、静态文件服务
- **项目初始化** - 自动检测并恢复项目状态，支持 Bun/Next.js 项目自动启动

## 🏗️ 架构设计

```
┌─────────────────────────────────────────────────────┐
│                   Docker Container                    │
│                                                      │
│  ┌─────────┐    ┌──────────────────────────────────┐ │
│  │  Caddy  │───▶│  GLM Agent Engine (FastAPI)       │ │
│  │  :81    │    │  :12600                           │ │
│  │         │    │                                    │ │
│  │  - HTTPS│    │  ┌──────────┐  ┌───────────────┐ │ │
│  │  - Static│   │  │ AI Proxy │  │ Tool Sandbox  │ │ │
│  │  - WSS   │   │  │ /v1/*    │  │ /v1/tools/*   │ │ │
│  │  - Proxy │   │  └──────────┘  └───────────────┘ │ │
│  └─────────┘    │                                    │ │
│                  │  ┌──────────┐  ┌───────────────┐ │ │
│  ┌─────────┐    │  │ Sessions │  │ File Manager  │ │ │
│  │  Bun/   │    │  │ /v1/sessions│ │ /v1/files/*  │ │ │
│  │  Next.js│    │  └──────────┘  └───────────────┘ │ │
│  │  :3000  │    └──────────────────────────────────┘ │
│  └─────────┘                    │                     │
│                           ┌─────▼──────┐              │
│                           │  Z.ai API  │              │
│                           │  (Backend) │              │
│                           └────────────┘              │
└─────────────────────────────────────────────────────┘
```

## 📁 项目结构

```
glmagent/
├── app/                          # Agent 引擎核心代码
│   ├── main.py                   # FastAPI 主应用
│   ├── requirements.txt          # Python 依赖
│   └── pyproject.toml            # Python 项目配置
├── config/                       # 配置文件
│   ├── Caddyfile                 # Caddy 反向代理配置
│   ├── index.html                # 静态落地页
│   └── logo.svg                  # Logo 图标
├── scripts/                      # 脚本
│   ├── start.sh                  # 容器启动脚本 (PID 1 入口)
│   └── dev.sh                    # 本地开发启动脚本
├── skills/                       # Skills 技能模块
│   └── example-skill/            # 示例 Skill
│       ├── SKILL.md              # Skill 元数据 (必需)
│       └── run.sh                # Skill 执行脚本
├── tests/                        # 测试套件
│   ├── __init__.py
│   └── test_engine.py            # API 集成测试
├── .github/workflows/            # CI/CD
│   ├── ci.yml                    # 持续集成
│   └── docker-publish.yml        # Docker 镜像发布
├── Dockerfile                    # 容器镜像定义
├── docker-compose.yml            # Docker Compose 编排
├── Makefile                      # 常用命令快捷方式
├── .env.example                  # 环境变量模板
├── .dockerignore                 # Docker 忽略文件
├── .gitignore                    # Git 忽略文件
├── LICENSE                       # MIT 许可证
└── README.md                     # 本文档
```

## 🚀 快速开始

### 前提条件

- Docker 20.10+
- Docker Compose V2+

### 一键启动

```bash
# 克隆仓库
git clone https://github.com/ctz168/glmagent.git
cd glmagent

# 配置环境变量
cp .env.example .env
# 编辑 .env，填入你的 Z.ai API Key

# 启动服务
docker compose up -d

# 查看日志
docker compose logs -f
```

### 服务端点

| 端点 | 地址 | 说明 |
|------|------|------|
| 公共入口 | `http://localhost:81` | Caddy HTTP 服务 |
| API 文档 | `http://localhost:12600/docs` | Swagger UI |
| 健康检查 | `http://localhost:81/health` | 服务健康状态 |
| Agent API | `http://localhost:12600/v1/*` | Agent 引擎 API |

### 使用 Makefile

```bash
make build      # 构建 Docker 镜像
make up         # 启动所有服务
make down       # 停止所有服务
make logs       # 查看日志
make test       # 运行测试
make lint       # 代码检查
make setup      # 初始化配置
```

## ⚙️ 配置说明

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ZAI_BASE_URL` | `http://172.25.136.193:8080/v1` | Z.ai 后端 API 地址 |
| `ZAI_API_KEY` | `Z.ai` | Z.ai API 密钥 |
| `PORT` | `81` | Caddy 公共监听端口 |
| `FC_REGION` | `local` | 部署区域标识 |
| `FC_INSTANCE_ID` | `glm-agent-local-001` | 实例 ID |
| `CLAWHUB_WORKDIR` | `/home/z/my-project` | 项目工作目录 |
| `DATABASE_URL` | `file:/home/z/my-project/db/custom.db` | 数据库路径 |

### 数据持久化

所有数据通过 Docker 卷持久化，挂载点如下：

```
data/
├── project/     # 项目代码和配置
├── upload/      # 上传的文件
├── download/    # 生成的文件
├── db/          # 数据库文件
└── sync/        # 项目恢复快照
```

## 🛠️ 容器运行时环境

复刻的原始容器环境配置：

| 组件 | 版本/配置 |
|------|-----------|
| 操作系统 | Debian 13 (trixie) |
| 内核 | Linux 5.10.x (Kata Container) |
| CPU | 4 核 Intel Xeon |
| 内存 | 8 GB |
| Init 系统 | tini 0.19.0 |
| Web 服务器 | Caddy |
| 应用框架 | FastAPI (Python 3.12) |
| Python 版本 | 3.12.13 (uv 管理) |
| Node.js | v24.14.1 |
| Bun | 最新版 |
| Java | OpenJDK 21 |
| 构建工具 | git, docker CLI, cmake |

## 🔌 API 参考

### 核心端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/info` | 运行时信息 |
| GET | `/skills` | 列出可用技能 |

### AI 代理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/v1/chat/completions` | LLM 对话补全 (支持流式) |
| POST | `/v1/images/generations` | AI 图像生成 |
| POST | `/v1/audio/speech` | 文字转语音 (TTS) |
| POST | `/v1/audio/transcriptions` | 语音转文字 (ASR) |
| POST | `/v1/chat/completions:multimodal` | 多模态视觉对话 |
| POST | `/v1/web/search` | 网页搜索 |
| POST | `/v1/web/read` | 网页内容提取 |

### 会话管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/v1/sessions` | 创建会话 |
| GET | `/v1/sessions/{id}` | 获取会话 |
| DELETE | `/v1/sessions/{id}` | 删除会话 |

### 工具 & 文件

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/v1/tools/execute` | 执行工具调用 |
| POST | `/v1/files/upload` | 上传文件 |
| GET | `/v1/files` | 列出文件 |
| GET | `/v1/files/{path}` | 下载文件 |

### 请求示例

**LLM 对话：**

```bash
curl -X POST http://localhost:12600/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "glm-4",
    "messages": [
      {"role": "user", "content": "你好，请介绍一下你自己"}
    ],
    "temperature": 0.7,
    "max_tokens": 4096
  }'
```

**流式对话：**

```bash
curl -X POST http://localhost:12600/v1/chat/completions \
  -H "Content-Type: application/json" \
  -N \
  -d '{
    "model": "glm-4",
    "messages": [
      {"role": "user", "content": "写一首诗"}
    ],
    "stream": true
  }'
```

## 🧩 Skills 系统

Skills 是 GLM Agent 的可插拔扩展模块。每个 Skill 是一个独立目录，包含一个 `SKILL.md` 元数据文件。

### 创建自定义 Skill

```bash
# 在 skills 目录下创建新技能
mkdir -p skills/my-custom-skill

# 编写 SKILL.md 元数据
cat > skills/my-custom-skill/SKILL.md << 'EOF'
# My Custom Skill

自定义技能的简短描述。

## Description
详细描述这个技能的功能和用途。

## Capability
描述 Agent 何时应该使用这个技能。

## Instructions
提供 Agent 使用此技能时的详细操作指南。
EOF

# 添加技能实现脚本
echo '#!/bin/bash
echo "My custom skill running..."
' > skills/my-custom-skill/run.sh
chmod +x skills/my-custom-skill/run.sh
```

### SKILL.md 格式规范

| 字段 | 必需 | 说明 |
|------|------|------|
| 标题 (`#`) | 是 | Skill 名称 |
| `## Description` | 是 | 功能描述 |
| `## Capability` | 是 | Agent 调用条件 |
| `## Instructions` | 是 | 使用说明 |

## 🧪 测试

```bash
# 使用 Docker 运行测试
docker compose exec glm-agent bash -c "cd /app && uv run pytest /app/tests/ -v"

# 本地运行测试 (需要 Python 3.12 + uv)
cd app && uv sync && uv run pytest ../tests/ -v
```

## 📋 启动流程

容器启动时 `start.sh` 按以下顺序执行：

1. **项目初始化** - 检查 `/home/sync` 是否有项目快照，有则恢复
2. **Skills 解压** - 从 `/home/official_skills` 解压技能包到项目目录
3. **权限设置** - 设置正确的文件所有权和权限
4. **Git 初始化** - 首次启动时初始化 Git 仓库
5. **Z.ai 配置** - 写入后端 API 配置到 `/etc/.z-ai-config`
6. **启动 Agent 引擎** - 后台启动 FastAPI 服务 (端口 12600)
7. **项目服务** - 检测并启动 Bun/Next.js 项目和 mini-services
8. **等待就绪** - 轮询等待 Agent 引擎健康检查通过
9. **启动 Caddy** - 前台启动 Caddy 反向代理 (端口 81)

## 📄 许可证

本项目基于 [MIT License](LICENSE) 开源。

## 🙏 致谢

- [Z.ai](https://z.ai) - 原始 Agent 引擎运行时
- [FastAPI](https://fastapi.tiangolo.com/) - Web 框架
- [Caddy](https://caddyserver.com/) - Web 服务器
- [uv](https://github.com/astral-sh/uv) - Python 包管理
- [Bun](https://bun.sh/) - JavaScript 运行时
