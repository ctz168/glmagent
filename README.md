# GLM Agent Engine

> 复刻自 Z.ai 容器运行时的 AI Agent 引擎，基于 FastAPI + Caddy 架构。完整对齐生产环境 Kata Container 运行时。

[![CI](https://github.com/ctz168/glmagent/actions/workflows/ci.yml/badge.svg)](https://github.com/ctz168/glmagent/actions/workflows/ci.yml)
[![Docker Publish](https://github.com/ctz168/glmagent/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/ctz168/glmagent/actions/workflows/docker-publish.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## 📖 项目概述

GLM Agent Engine 是从 Z.ai 生产容器运行时（Kata Container）完整复刻的 AI Agent 引擎。通过对比真实生产环境的系统环境变量、启动脚本、目录结构和 API 端点，逐一还原了所有运行时细节，包括完整的容器元数据（FC_* 变量）、Skills YAML frontmatter 解析、Z.ai 后端配置加载（含 chatId/token/userId）、mini-services 子服务编排等。

### 核心特性

- **AI 代理引擎** - FastAPI 构建的 RESTful API，代理转发至后端大模型服务，支持 SSE 流式响应
- **多模态支持** - LLM 对话、图像生成 (VLM)、语音转文字 (ASR)、文字转语音 (TTS)
- **Web 能力** - 网页搜索 (Web Search) 和网页内容提取 (Web Read)
- **Skills 系统** - 可插拔技能模块，支持 YAML frontmatter 元数据解析，兼容生产环境 44+ 官方技能
- **沙箱执行** - 容器隔离的工具执行环境，Skill `run.sh` 脚本安全执行
- **会话管理** - 完整的会话创建、查询、列表、删除生命周期管理
- **Caddy 反向代理** - 使用 `FC_CUSTOM_LISTEN_PORT` 环境变量配置端口，WebSocket 支持，静态文件服务
- **项目初始化** - 自动检测并恢复 `/home/sync` 项目快照，支持 Bun/Next.js 项目自动启动
- **Mini-Services** - 子服务编排系统，自动扫描 `mini-services/` 目录启动独立服务
- **自定义 Dev 脚本** - 通过 `.zscripts/dev.sh` 覆盖默认项目启动流程
- **请求日志** - 内置 HTTP 请求日志中间件，记录方法和响应时间
- **生产环境变量对齐** - 完整复刻所有 FC_*, CLAWHUB_*, SIGMA_* 等生产环境变量

## 🏗️ 架构设计

```
┌─────────────────────────────────────────────────────────┐
│                 Docker Container (tini → start.sh)       │
│                                                          │
│  ┌──────────┐   ┌────────────────────────────────────┐   │
│  │  Caddy   │──▶│  GLM Agent Engine (FastAPI)         │   │
│  │  :{PORT} │   │  :12600                            │   │
│  │          │   │                                     │   │
│  │ - HTTP   │   │  ┌────────────┐  ┌──────────────┐  │   │
│  │ - Static │   │  │ AI Proxy   │  │ Tool Sandbox  │  │   │
│  │ - WSS    │   │  │ /v1/*      │  │ /v1/tools/*   │  │   │
│  │ - Proxy  │   │  └────────────┘  └──────────────┘  │   │
│  └──────────┘   │                                     │   │
│                  │  ┌────────────┐  ┌──────────────┐  │   │
│  ┌──────────┐   │  │ Sessions   │  │ File Manager  │  │   │
│  │ Bun/     │   │  │ /v1/sessions│ │ /v1/files/*   │  │   │
│  │ Next.js  │   │  └────────────┘  └──────────────┘  │   │
│  │ :3000    │   └────────────────────────────────────┘   │
│  └──────────┘                        │                   │
│  ┌──────────┐                   ┌─────▼──────┐            │
│  │Mini-Svc  │                   │  Z.ai API  │            │
│  │ :3001    │                   │  (Backend) │            │
│  └──────────┘                   └────────────┘            │
│                                                          │
│  /app/.venv (Python 3.12) | /home/z/.bun (Bun runtime)  │
│  /home/z/my-project/skills/ (44+ skills)                │
│  /home/z/my-project/mini-services/ (sub-services)       │
└─────────────────────────────────────────────────────────┘
```

## 📁 项目结构

```
glmagent/
├── app/                          # Agent 引擎核心代码
│   ├── main.py                   # FastAPI 主应用 (lifespan, 请求日志, 工具执行)
│   ├── requirements.txt          # Python 依赖
│   └── pyproject.toml            # Python 项目配置
├── config/                       # 配置文件
│   ├── Caddyfile                 # Caddy 反向代理 (FC_CUSTOM_LISTEN_PORT)
│   ├── index.html                # 静态落地页
│   └── logo.svg                  # Logo 图标
├── scripts/                      # 脚本
│   ├── start.sh                  # 容器启动脚本 (PID 1 入口, 对齐生产环境)
│   └── dev.sh                    # 本地开发启动脚本
├── skills/                       # Skills 技能模块
│   └── example-skill/            # 示例 Skill (YAML frontmatter 格式)
│       ├── SKILL.md              # Skill 元数据 (YAML frontmatter + Markdown)
│       └── run.sh                # Skill 执行脚本
├── mini-services/                # Mini-Services 子服务模板
│   ├── README.md                 # 子服务说明文档
│   └── .example/                 # 示例子服务模板
│       ├── package.json
│       └── src/index.ts
├── .zscripts/                    # 自定义开发脚本
│   └── dev.sh                    # 自定义项目初始化脚本模板
├── tests/                        # 测试套件
│   ├── __init__.py
│   └── test_engine.py            # API 集成测试 (20+ 测试用例)
├── .github/workflows/            # CI/CD
│   ├── ci.yml                    # 持续集成
│   └── docker-publish.yml        # Docker 镜像发布
├── Dockerfile                    # 容器镜像定义 (完整生产环境变量)
├── docker-compose.yml            # Docker Compose 编排
├── Makefile                      # 常用命令快捷方式
├── .env.example                  # 环境变量模板 (完整生产变量列表)
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
| Mini-Service 1 | `http://localhost:19005` | Next.js 代理 |
| Mini-Service 2 | `http://localhost:19006` | 子服务代理 |

### 使用 Makefile

```bash
make build      # 构建 Docker 镜像
make up         # 启动所有服务
make down       # 停止所有服务
make logs       # 查看日志
make test       # 运行测试
make lint       # 代码检查
make setup      # 初始化配置
make deploy     # 构建并部署
```

## ⚙️ 配置说明

### 环境变量

完整对齐 Z.ai 生产 Kata Container 运行时的环境变量：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ZAI_BASE_URL` | `http://172.25.136.193:8080/v1` | Z.ai 后端 API 地址 |
| `ZAI_API_KEY` | `Z.ai` | Z.ai API 密钥 |
| `PORT` | `12600` | Agent Engine 内部端口 |
| `FC_CUSTOM_LISTEN_PORT` | `81` | Caddy 公共监听端口 |
| `FC_REGION` | `cn-hongkong` | 部署区域标识 |
| `FC_INSTANCE_ID` | - | 实例 ID (编排器注入) |
| `FC_FUNCTION_NAME` | - | 函数名称 (编排器注入) |
| `FC_CONTAINER_ID` | - | 容器 ID (编排器注入) |
| `FC_ACCOUNT_ID` | - | 账户 ID (编排器注入) |
| `FC_FUNCTION_HANDLER` | `index.handler` | 函数入口 |
| `FC_FUNCTION_MEMORY_SIZE` | `8192` | 内存大小 (MB) |
| `CLAWHUB_WORKDIR` | `/home/z/my-project` | 项目工作目录 |
| `CLAWHUB_DISABLE_TELEMETRY` | `1` | 禁用遥测 |
| `KATA_CONTAINER` | `true` | Kata 容器标识 |
| `SIGMA_APP_NAME` | - | 应用名称 (编排器注入) |
| `DATABASE_URL` | `file:/home/z/my-project/db/custom.db` | 数据库路径 |
| `UV` | `/usr/local/bin/uv` | uv 二进制路径 |
| `BUN_INSTALL` | `/home/z/.bun` | Bun 安装路径 |
| `VIRTUAL_ENV` | `/app/.venv` | Python 虚拟环境 |

### Z.ai 后端配置

Agent Engine 自动从 `/etc/.z-ai-config` 加载后端配置。生产环境配置文件包含以下字段：

```json
{
  "baseUrl": "http://172.25.136.193:8080/v1",
  "apiKey": "Z.ai",
  "chatId": "chat-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "token": "eyJhbGciOiJIUzI1NiIs...",
  "userId": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
}
```

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

复刻的原始容器环境配置（与生产 Kata Container 一致）：

| 组件 | 版本/配置 |
|------|-----------|
| 操作系统 | Debian 13 (trixie) |
| 内核 | Linux 5.10.x (Kata Container) |
| CPU | 4 核 Intel Xeon |
| 内存 | 8 GB (8192 MB) |
| Init 系统 | tini (PID 1) |
| Web 服务器 | Caddy |
| 应用框架 | FastAPI (Python 3.12) |
| Python 版本 | 3.12.13 (uv 管理) |
| Node.js | v24.x |
| Bun | 最新版 |
| Java | OpenJDK 21 (headless) |
| 构建工具 | git, docker CLI, cmake |
| 用户 | z (uid=1001, gid=1001) |
| 应用目录 | /app/ (root:root, 700) |
| 项目目录 | /home/z/my-project (z:z, 755) |

## 🔌 API 参考

### 核心端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/info` | 运行时信息 (含 container_id, memory_size_mb, kata_container) |
| GET | `/skills` | 列出可用技能 (解析 YAML frontmatter) |
| GET | `/skills/{name}` | 获取技能详情 (含文件列表) |
| GET | `/v1/env` | 安全环境变量 (不含密钥) |
| GET | `/v1/config` | Z.ai 后端配置 (不含敏感信息) |

### AI 代理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/v1/chat/completions` | LLM 对话补全 (支持流式 SSE) |
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
| GET | `/v1/sessions` | 列出所有会话 |
| GET | `/v1/sessions/{id}` | 获取会话详情 |
| DELETE | `/v1/sessions/{id}` | 删除会话 |

### 工具 & 文件

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/v1/tools/execute` | 执行工具调用 (实际运行 Skill run.sh) |
| POST | `/v1/files/upload` | 上传文件 |
| GET | `/v1/files` | 列出文件 (含修改时间) |
| GET | `/v1/files/{path}` | 下载文件 |
| DELETE | `/v1/files/{path}` | 删除文件 |

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

**执行 Skill 工具：**

```bash
curl -X POST http://localhost:12600/v1/tools/execute \
  -H "Content-Type: application/json" \
  -d '{
    "name": "example-skill",
    "arguments": {"test": true}
  }'
```

## 🧩 Skills 系统

Skills 是 GLM Agent 的可插拔扩展模块。生产环境包含 44+ 官方技能，包括 LLM、VLM、TTS、ASR、pdf、docx、xlsx、pptx、fullstack-dev、web-search、finance 等。

### SKILL.md 格式

生产环境使用 YAML frontmatter 格式定义技能元数据，引擎会自动解析并用于技能匹配：

```markdown
---
name: skill-name
description: "技能描述，用于 Agent 匹配调用"
license: MIT
argument-hint: "输入参数提示"
---

# Skill 名称

## Description
详细描述技能功能。

## Capability
描述 Agent 何时调用此技能。

## Instructions
使用说明和操作指南。
```

### 创建自定义 Skill

```bash
# 在 skills 目录下创建新技能
mkdir -p skills/my-custom-skill

# 编写 SKILL.md 元数据 (使用 YAML frontmatter)
cat > skills/my-custom-skill/SKILL.md << 'EOF'
---
name: my-custom-skill
description: "My custom skill for special processing"
license: MIT
---

# My Custom Skill

## Description
详细描述这个技能的功能和用途。

## Capability
描述 Agent 何时应该使用这个技能。

## Instructions
提供 Agent 使用此技能时的详细操作指南。
EOF

# 添加可执行脚本 (可选)
cat > skills/my-custom-skill/run.sh << 'EOF'
#!/bin/bash
echo "Arguments: $1"
# Your skill logic here
exit 0
EOF
chmod +x skills/my-custom-skill/run.sh
```

### YAML Frontmatter 字段

| 字段 | 必需 | 说明 |
|------|------|------|
| `name` | 是 | 技能唯一标识符 |
| `description` | 是 | 技能描述 (Agent 用于匹配调用) |
| `license` | 否 | 许可证标识 |
| `argument-hint` | 否 | 输入参数格式提示 |

## 🧪 测试

测试套件包含 20+ 测试用例，覆盖所有 API 端点、Skills 解析器和边界情况：

```bash
# 使用 Docker 运行测试
docker compose exec glm-agent bash -c "cd /app && uv run pytest /app/tests/ -v"

# 本地运行测试 (需要 Python 3.12 + uv)
cd app && uv sync && uv run pytest ../tests/ -v
```

## 📋 启动流程

容器启动时 `start.sh` 按以下顺序执行（与生产环境完全一致）：

1. **项目初始化** - 检查 `/home/sync` 是否有项目快照，有则恢复；无则创建干净环境
2. **Skills 解压** - 从 `/home/official_skills` 解压技能包，按 `stages.yaml` 过滤
3. **权限设置** - 设置 z 用户权限，处理 OSS 挂载点特殊情况
4. **Git 初始化** - 首次启动时初始化 Git 仓库
5. **Z.ai 配置** - 写入后端 API 配置到 `/etc/.z-ai-config`
6. **启动 ZAI 服务** - 后台启动 FastAPI 服务 (端口 12600)
7. **项目服务** - 检测 `.zscripts/dev.sh` (自定义流程) 或 `package.json` (bun + mini-services)
8. **等待就绪** - 轮询等待 ZAI 服务健康检查通过
9. **启动 Caddy** - 前台启动 Caddy 反向代理

## 🔄 与生产环境的差异点

本项目已最大程度对齐生产环境，以下为已知差异：

- **生产环境变量**：`FC_INSTANCE_ID`、`FC_CONTAINER_ID`、`FC_FUNCTION_NAME`、`SIGMA_APP_NAME` 等由编排器动态注入，Docker Compose 环境下使用默认值
- **网络**：生产环境使用 Kata Container 虚拟化网络，Docker Compose 使用 bridge 网络
- **持久化**：生产环境使用 NAS/OSS 挂载，Docker Compose 使用 bind mount
- **Skills**：生产环境 44+ 官方技能由 `/home/official_skills` 动态注入，本项目仅包含示例技能

## 📄 许可证

本项目基于 [MIT License](LICENSE) 开源。

## 🙏 致谢

- [Z.ai](https://z.ai) - 原始 Agent 引擎运行时
- [FastAPI](https://fastapi.tiangolo.com/) - Web 框架
- [Caddy](https://caddyserver.com/) - Web 服务器
- [uv](https://github.com/astral-sh/uv) - Python 包管理
- [Bun](https://bun.sh/) - JavaScript 运行时
