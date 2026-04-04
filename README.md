# GLM Agent Engine

> 复刻自 Z.ai 容器运行时的 AI Agent 引擎，基于 FastAPI + Caddy 架构。完整对齐生产环境 Kata Container 运行时。

[![CI](https://github.com/ctz168/glmagent/actions/workflows/ci.yml/badge.svg)](https://github.com/ctz168/glmagent/actions/workflows/ci.yml)
[![Docker Publish](https://github.com/ctz168/glmagent/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/ctz168/glmagent/actions/workflows/docker-publish.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## 📖 项目概述

GLM Agent Engine 是从 Z.ai 生产容器运行时（Kata Container）完整复刻的 AI Agent 引擎 v2.0。通过对比真实生产环境的系统环境变量、启动脚本、目录结构和 API 端点，逐一还原了所有运行时细节，包括完整的容器元数据（FC_* 变量）、Skills YAML frontmatter 解析、Z.ai 后端配置加载（含 chatId/token/userId）、mini-services 子服务编排等。

### 核心特性

- **AI 代理引擎** - FastAPI 构建的 RESTful API，代理转发至后端大模型服务，支持 SSE 流式响应
- **多模态支持** - LLM 对话、图像生成 (VLM)、语音转文字 (ASR)、文字转语音 (TTS)、视频生成/理解
- **Web 能力** - 网页搜索 (Web Search) 和网页内容提取 (Web Read)
- **Skills 系统** - 可插拔技能模块，支持 YAML frontmatter 元数据解析，兼容生产环境 44+ 官方技能
- **沙箱执行** - 容器隔离的工具执行环境，支持 `run.sh`、`run.py`、`run.ts` 三种脚本类型
- **会话管理** - 完整的会话创建、查询、列表、删除生命周期管理，支持消息历史记录
- **数据库持久化** - SQLAlchemy 异步 ORM（MySQL + SQLite 回退），会话/消息/文件/CronJob/工具执行记录全部入库
- **JWT 认证** - 支持 JWT Bearer Token 和 API Key 两种认证方式，可选启用
- **WebSocket** - `/ws/{session_id}` 双向实时通信，支持消息流式传输和工具执行推送
- **Cron 定时任务** - APScheduler 持久化定时任务，支持 cron 表达式/固定频率/单次执行
- **Redis 缓存** - 会话缓存、事件发布/订阅（Pub/Sub），Redis 不可用时自动降级
- **可观测性** - Prometheus 指标、OpenTelemetry 链路追踪、Datadog ddtrace、结构化 JSON 日志（loguru）
- **MCP 支持** - Model Context Protocol 服务端，暴露 AI 工具给外部 MCP 客户端
- **Caddy 反向代理** - 使用 `FC_CUSTOM_LISTEN_PORT` 环境变量配置端口，WebSocket 支持，静态文件服务
- **请求追踪** - Correlation ID 自动注入（请求头 `X-Correlation-ID`），错误响应结构化
- **项目初始化** - 自动检测并恢复 `/home/sync` 项目快照，支持 Bun/Next.js 项目自动启动
- **Mini-Services** - 子服务编排系统，自动扫描 `mini-services/` 目录启动独立服务
- **自定义 Dev 脚本** - 通过 `.zscripts/dev.sh` 覆盖默认项目启动流程
- **生产环境变量对齐** - 完整复刻所有 FC_*, CLAWHUB_*, SIGMA_* 等生产环境变量

## 🏗️ 架构设计

```
┌─────────────────────────────────────────────────────────────────┐
│                 Docker Container (tini → start.sh)               │
│                                                                  │
│  ┌──────────┐   ┌──────────────────────────────────────────┐    │
│  │  Caddy   │──▶│  GLM Agent Engine v2.0 (FastAPI)          │    │
│  │  :{PORT} │   │  :12600                                   │    │
│  │          │   │                                           │    │
│  │ - HTTP   │   │  ┌────────────┐  ┌──────────────┐       │    │
│  │ - Static │   │  │ AI Proxy   │  │ Tool Sandbox  │       │    │
│  │ - WSS    │   │  │ /v1/*      │  │ run.sh/py/ts  │       │    │
│  │ - Proxy  │   │  └────────────┘  └──────────────┘       │    │
│  └──────────┘   │                                           │    │
│                  │  ┌────────────┐  ┌──────────────┐       │    │
│  ┌──────────┐   │  │ Sessions   │  │ File Manager  │       │    │
│  │ Bun/     │   │  │ /v1/sessions│ │ /v1/files/*   │       │    │
│  │ Next.js  │   │  │ + Messages │  │ + Upload/DB   │       │    │
│  │ :3000    │   │  └────────────┘  └──────────────┘       │    │
│  └──────────┘   │                                           │    │
│                  │  ┌────────────┐  ┌──────────────┐       │    │
│  ┌──────────┐   │  │ WebSocket  │  │ Cron Jobs     │       │    │
│  │Mini-Svc  │   │  │ /ws/{id}   │  │ /v1/cron/*    │       │    │
│  │ :3001    │   │  └────────────┘  └──────────────┘       │    │
│  └──────────┘   │                                           │    │
│                  │  ┌──────────────────────────────────┐   │    │
│                  │  │  Middleware                       │   │    │
│                  │  │  - Request Logging + Correlation  │   │    │
│                  │  │  - Prometheus Metrics             │   │    │
│                  │  │  - OpenTelemetry Tracing          │   │    │
│                  │  │  - JWT/API Key Auth               │   │    │
│                  │  └──────────────────────────────────┘   │    │
│                  └──────────────────────────────────────────┘    │
│                                  │                               │
│                  ┌───────────────┼───────────────┐               │
│                  │               │               │               │
│             ┌────▼────┐   ┌─────▼─────┐   ┌─────▼─────┐        │
│             │ Z.ai API│   │  MySQL /  │   │  Redis    │        │
│             │(Backend)│   │  SQLite   │   │ (Cache)   │        │
│             └─────────┘   └───────────┘   └───────────┘        │
│                                                                  │
│  /app/.venv (Python 3.12) | /home/z/.bun (Bun runtime)          │
│  /home/z/my-project/skills/ (44+ skills)                        │
│  /home/z/my-project/mini-services/ (sub-services)               │
└─────────────────────────────────────────────────────────────────┘
```

## 📁 项目结构

```
glmagent/
├── app/                          # Agent 引擎核心代码
│   ├── main.py                   # FastAPI 主应用 v2.0 (2330+ 行)
│   ├── requirements.txt          # Python 依赖
│   └── pyproject.toml            # Python 项目配置 (uv)
├── config/                       # 配置文件
│   ├── Caddyfile                 # Caddy 反向代理 (FC_CUSTOM_LISTEN_PORT)
│   ├── index.html                # 静态落地页
│   └── logo.svg                  # Logo 图标
├── scripts/                      # 脚本
│   ├── start.sh                  # 容器启动脚本 (PID 1 入口, 对齐生产环境)
│   └── dev.sh                    # 本地开发启动脚本 (热重载)
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
│   └── test_engine.py            # API 集成测试 (50+ 测试用例)
├── .github/workflows/            # CI/CD
│   ├── ci.yml                    # 持续集成
│   └── docker-publish.yml        # Docker 镜像发布
├── Dockerfile                    # 容器镜像定义 (完整生产环境变量)
├── docker-compose.yml            # Docker Compose 编排 (含 Redis/MySQL)
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

# 启动服务 (包含 Redis 和 MySQL)
docker compose up -d

# 查看日志
docker compose logs -f
```

### 服务端点

| 端点 | 地址 | 说明 |
|------|------|------|
| 公共入口 | `http://localhost:81` | Caddy HTTP 服务 |
| API 文档 | `http://localhost:12600/docs` | Swagger UI |
| ReDoc | `http://localhost:12600/redoc` | ReDoc 文档 |
| 健康检查 | `http://localhost:81/health` | 服务健康状态 |
| Agent API | `http://localhost:12600/v1/*` | Agent 引擎 API |
| Prometheus | `http://localhost:12600/metrics` | Prometheus 指标 |
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
make format     # 代码格式化
make setup      # 初始化配置
make deploy     # 构建并部署
```

## ⚙️ 配置说明

### 环境变量

完整对齐 Z.ai 生产 Kata Container 运行时的环境变量：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ZAI_BASE_URL` | `http://172.25.136.193:8080` | Z.ai 后端 API 地址 |
| `ZAI_API_KEY` | `Z.ai` | Z.ai API 密钥 |
| `ZAI_TIMEOUT` | `120` | 后端 API 超时时间 (秒) |
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
| `DATABASE_URL` | `sqlite+aiosqlite:///...` | 数据库连接 URL |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis 连接 URL |
| `JWT_SECRET` | `glm-agent-secret-change-me` | JWT 签名密钥 |
| `JWT_ALGORITHM` | `HS256` | JWT 签名算法 |
| `JWT_EXPIRATION_HOURS` | `24` | JWT 过期时间 (小时) |
| `AUTH_ENABLED` | `false` | 是否启用认证 |
| `SESSION_TIMEOUT` | `3600` | 会话缓存 TTL (秒) |
| `TOOL_TIMEOUT` | `30` | 工具执行超时 (秒) |
| `SSE_HEARTBEAT_INTERVAL` | `15` | SSE 心跳间隔 (秒) |
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

## 🗄️ 数据库配置

### MySQL (生产推荐)

```bash
# 环境变量设置
DATABASE_URL=mysql+aiomysql://user:password@mysql-host:3306/glm_agent
```

### SQLite (开发/测试默认)

```bash
# 默认使用内存 SQLite（测试）或文件 SQLite（生产）
DATABASE_URL=sqlite+aiosqlite:///home/z/my-project/db/agent.db
```

### 数据模型

| 表名 | 说明 |
|------|------|
| `sessions` | 会话元数据 (id, metadata, status, user_id) |
| `messages` | 聊天消息 (session_id, role, content, model, tokens) |
| `files` | 文件元数据 (filename, path, size, checksum_sha256) |
| `cron_jobs` | 定时任务 (name, schedule_type, payload, run_count) |
| `tool_executions` | 工具执行记录 (tool_name, arguments, exit_code, stdout, duration_ms) |

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

## 📦 Redis 配置

Redis 用于会话缓存和事件发布/订阅（Pub/Sub）。Redis 不可用时引擎会自动降级到纯数据库模式。

```bash
# 环境变量
REDIS_URL=redis://localhost:6379/0
```

### Redis 用途

| 功能 | Key 模式 | TTL |
|------|----------|-----|
| 会话缓存 | `session:{session_id}` | 3600s |
| 事件发布 | `channel: video:completed, cron:executed` | - |

## 🔐 认证

### JWT Token 认证

```bash
# 获取 JWT Token
curl -X POST "http://localhost:12600/v1/auth/token?user_id=my-user"

# 使用 Token 访问受保护端点
curl -H "Authorization: Bearer <token>" http://localhost:12600/v1/sessions
```

### API Key 认证

```bash
# 通过 ZAI_API_KEY Header 认证
curl -H "ZAI_API_KEY: Z.ai" http://localhost:12600/v1/sessions
```

### 启用认证

```bash
# 设置 AUTH_ENABLED=true 启用认证保护
AUTH_ENABLED=true
JWT_SECRET=your-production-secret-key
```

## 📊 可观测性

### Prometheus 指标

访问 `/metrics` 端点获取 Prometheus 格式的指标数据。

**内置指标：**

| 指标名 | 类型 | 标签 | 说明 |
|--------|------|------|------|
| `glm_http_requests_total` | Counter | method, endpoint, status_code | HTTP 请求总数 |
| `glm_http_request_duration_seconds` | Histogram | method, endpoint | 请求延迟分布 |
| `glm_active_sessions` | Gauge | - | 活跃会话数 |
| `glm_tool_executions_total` | Counter | tool_name, status | 工具执行总数 |
| `glm_ai_operations_total` | Counter | operation, model | AI API 操作数 |
| `glm_cron_jobs_active` | Gauge | - | 活跃定时任务数 |
| `glm_engine` | Info | - | 引擎版本和区域信息 |

### OpenTelemetry

引擎支持 OpenTelemetry 自动埋点（FastAPI + httpx），导出到配置的 OTLP Collector。

### Datadog ddtrace

安装 ddtrace 后自动启用 FastAPI 埋点，无需额外配置。

### 结构化日志

使用 loguru 输出 JSON 格式结构化日志，包含 correlation_id 和请求耗时。

## 🔌 API 参考

### 核心端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 (含 database/redis 组件状态) |
| GET | `/info` | 运行时信息 (含 features 特性标志) |
| GET | `/metrics` | Prometheus 指标 |
| POST | `/v1/auth/token` | 创建 JWT Token |
| GET | `/skills` | 列出可用技能 (解析 YAML frontmatter) |
| GET | `/skills/{name}` | 获取技能详情 (含 executable_type) |
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

### 视频生成与理解

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/v1/videos/generations` | 异步视频生成 (返回 task_id) |
| POST | `/v1/videos/understand` | 视频内容理解与分析 |
| GET | `/v1/videos/tasks/{task_id}` | 查询视频生成任务状态 |

### 会话管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/v1/sessions` | 创建会话 |
| GET | `/v1/sessions` | 列出所有会话 |
| GET | `/v1/sessions/{id}` | 获取会话详情 |
| GET | `/v1/sessions/{id}/messages` | 获取会话消息历史 |
| DELETE | `/v1/sessions/{id}` | 删除会话 |

### 工具 & 文件

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/v1/tools/execute` | 执行工具 (run.sh/run.py/run.ts) |
| GET | `/v1/tools/executions` | 工具执行历史记录 |
| POST | `/v1/files/upload` | 上传文件 (含 SHA-256 校验) |
| GET | `/v1/files` | 列出文件 |
| GET | `/v1/files/{path}` | 下载文件 |
| DELETE | `/v1/files/{path}` | 删除文件 |

### 定时任务

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/v1/cron` | 创建定时任务 (cron/fixed_rate/one_time) |
| GET | `/v1/cron` | 列出所有定时任务 |
| GET | `/v1/cron/{job_id}` | 获取任务详情 |
| DELETE | `/v1/cron/{job_id}` | 删除定时任务 |

### WebSocket & MCP

| 方法 | 路径 | 说明 |
|------|------|------|
| WS | `/ws/{session_id}` | WebSocket 双向实时通信 |
| - | MCP | Model Context Protocol (fastmcp) |

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

**视频生成：**

```bash
# 1. 提交视频生成任务
curl -X POST http://localhost:12600/v1/videos/generations \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "A cat playing piano in a jazz bar",
    "model": "video-gen",
    "size": "1280x720",
    "duration": 5
  }'
# 返回: {"task_id": "vt_abc123...", "status": "pending", ...}

# 2. 轮询任务状态
curl http://localhost:12600/v1/videos/tasks/vt_abc123...
# 返回: {"task_id": "...", "status": "completed", "result": {...}, ...}
```

**视频理解：**

```bash
curl -X POST http://localhost:12600/v1/videos/understand \
  -H "Content-Type: application/json" \
  -d '{
    "video_base64": "<base64编码的视频>",
    "prompt": "描述这个视频的内容"
  }'
```

**创建 Cron 定时任务：**

```bash
# 固定频率 (每 60 秒)
curl -X POST http://localhost:12600/v1/cron \
  -H "Content-Type: application/json" \
  -d '{
    "name": "health-check",
    "schedule_type": "fixed_rate",
    "schedule_value": "60",
    "payload": {"url": "/health"}
  }'

# Cron 表达式 (每天凌晨 2 点)
curl -X POST http://localhost:12600/v1/cron \
  -H "Content-Type: application/json" \
  -d '{
    "name": "daily-report",
    "schedule_type": "cron",
    "schedule_value": "0 2 * * *",
    "payload": {"action": "generate_report"}
  }'

# 单次执行 (指定时间)
curl -X POST http://localhost:12600/v1/cron \
  -H "Content-Type: application/json" \
  -d '{
    "name": "one-time-task",
    "schedule_type": "one_time",
    "schedule_value": "2025-06-01T00:00:00Z",
    "payload": {"action": "backup"}
  }'
```

**WebSocket 实时通信：**

```javascript
// JavaScript WebSocket 客户端示例
const ws = new WebSocket('ws://localhost:12600/ws/YOUR_SESSION_ID');

ws.onopen = () => {
  console.log('Connected');
  // 发送 ping
  ws.send(JSON.stringify({ type: 'ping' }));
  // 发送消息
  ws.send(JSON.stringify({
    type: 'message',
    model: 'glm-4',
    messages: [{ role: 'user', content: 'Hello' }]
  }));
  // 执行工具
  ws.send(JSON.stringify({
    type: 'tool_call',
    name: 'example-skill',
    arguments: { key: 'value' }
  }));
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  switch (data.type) {
    case 'pong': console.log('Pong:', data.timestamp); break;
    case 'delta': console.log('Stream:', data.data); break;
    case 'tool_start': console.log('Tool started:', data.tool); break;
    case 'tool_result': console.log('Tool result:', data); break;
    case 'error': console.error('Error:', data.detail); break;
  }
};
```

**文件上传（含校验）：**

```bash
curl -X POST http://localhost:12600/v1/files/upload \
  -F "file=@/path/to/your/file.pdf" \
  -F "session_id=your-session-id"
# 返回: {"file_id": "...", "filename": "file.pdf", "size": 1234, "checksum_sha256": "..."}
```

## 🧩 Skills 系统

Skills 是 GLM Agent 的可插拔扩展模块。生产环境包含 44+ 官方技能，包括 LLM、VLM、TTS、ASR、pdf、docx、xlsx、pptx、fullstack-dev、web-search、finance 等。

### 执行脚本类型

引擎自动检测并执行以下脚本类型（优先级从高到低）：

| 脚本 | 类型 | 执行方式 |
|------|------|----------|
| `run.sh` | Shell | `bash run.sh '<json_args>'` |
| `run.py` | Python | `python run.py '<json_args>'` |
| `run.ts` | TypeScript | `bun run run.ts '<json_args>'` |

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

## 🐳 Docker 部署

### 完整 Stack（含 Redis + MySQL）

```yaml
# docker-compose.yml 中已包含完整配置
# 启动时自动创建 Redis 和 MySQL 服务
docker compose up -d

# 仅启动 Agent（使用 SQLite，无 Redis）
docker compose up -d glm-agent
```

### Docker 端口映射

| 端口 | 服务 | 说明 |
|------|------|------|
| `81` | Caddy | 公共 HTTP 入口 |
| `12600` | FastAPI | Agent API (内部) |
| `19005` | Mini-Service 1 | Next.js 代理 |
| `19006` | Mini-Service 2 | 子服务代理 |
| `3306` | MySQL | 数据库 (可选) |
| `6379` | Redis | 缓存 (可选) |

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

## 🧪 测试

测试套件包含 50+ 测试用例，覆盖所有 API 端点、认证、WebSocket、Cron 任务、Prometheus 指标和错误处理：

```bash
# 使用 Docker 运行测试
docker compose exec glm-agent bash -c "cd /app && uv run pytest /app/tests/ -v"

# 本地运行测试 (需要 Python 3.12 + uv)
cd app && uv sync && uv run pytest ../tests/ -v

# 运行测试并生成覆盖率报告
cd app && uv run pytest ../tests/ -v --cov=app --cov-report=term-missing

# 运行特定测试类
cd app && uv run pytest ../tests/test_engine.py::TestVideoGeneration -v

# 运行特定测试方法
cd app && uv run pytest ../tests/test_engine.py::TestCronJobs::test_create_cron_job -v
```

### 测试覆盖范围

| 测试类 | 覆盖内容 |
|--------|----------|
| `TestHealthAndInfo` | /health, /info, /metrics |
| `TestSkills` | /skills 列表和详情, frontmatter 解析 |
| `TestSessions` | 会话 CRUD, 消息历史 |
| `TestFiles` | 文件上传、下载、列表、路径遍历防护 |
| `TestToolExecution` | 工具执行、执行历史、过滤 |
| `TestAuthentication` | JWT 创建、Bearer Token、API Key |
| `TestVideoGeneration` | 视频生成任务、状态轮询、视频理解 |
| `TestCronJobs` | 定时任务 CRUD、cron 表达式 |
| `TestEnvironment` | 环境变量、配置 |
| `TestWebSocket` | WebSocket 连接、ping/pong、错误消息类型 |
| `TestSSEStreaming` | SSE 流式响应 |
| `TestAIProxy` | AI 代理转发、错误处理 |
| `TestErrorHandling` | 404/405/422/500、correlation_id |
| `TestSkillMetadataParser` | YAML frontmatter 解析、回退逻辑 |
| `TestCORS` | CORS 中间件 |
| `TestEnhancedSkillExecution` | 执行记录、stdout、session_id 关联 |

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

### v2.0 启动新增流程

10. **初始化数据库** - SQLAlchemy 创建所有表 (sessions, messages, files, cron_jobs, tool_executions)
11. **连接 Redis** - 建立 Redis 连接（失败则降级）
12. **恢复 Cron 任务** - 从数据库恢复活跃的定时任务到 APScheduler
13. **启动调度器** - APScheduler 开始执行定时任务
14. **OpenTelemetry** - 配置链路追踪和自动埋点

## 💻 本地开发

### 热重载模式

```bash
# 使用 dev.sh 启动（自动启用 uvicorn --reload）
cd glmagent
./scripts/dev.sh

# 或手动启动
cd app && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 12600
```

### 运行测试

```bash
# 安装测试依赖
cd app && uv sync

# 运行全部测试
make test

# 运行并查看覆盖率
cd app && uv run pytest ../tests/ -v --cov=app --cov-report=html
```

## 🔄 与生产环境的差异点

本项目已最大程度对齐生产环境，以下为已知差异：

- **生产环境变量**：`FC_INSTANCE_ID`、`FC_CONTAINER_ID`、`FC_FUNCTION_NAME`、`SIGMA_APP_NAME` 等由编排器动态注入，Docker Compose 环境下使用默认值
- **网络**：生产环境使用 Kata Container 虚拟化网络，Docker Compose 使用 bridge 网络
- **持久化**：生产环境使用 NAS/OSS 挂载，Docker Compose 使用 bind mount
- **Skills**：生产环境 44+ 官方技能由 `/home/official_skills` 动态注入，本项目仅包含示例技能
- **认证**：生产环境 AUTH_ENABLED=true，本地开发默认关闭
- **数据库**：生产环境使用 MySQL，本地开发使用 SQLite

## 📄 许可证

本项目基于 [MIT License](LICENSE) 开源。

## 🙏 致谢

- [Z.ai](https://z.ai) - 原始 Agent 引擎运行时
- [FastAPI](https://fastapi.tiangolo.com/) - Web 框架
- [Caddy](https://caddyserver.com/) - Web 服务器
- [SQLAlchemy](https://www.sqlalchemy.org/) - Python ORM
- [Redis](https://redis.io/) - 缓存和消息队列
- [APScheduler](https://apscheduler.readthedocs.io/) - 定时任务调度
- [Prometheus](https://prometheus.io/) - 指标监控
- [OpenTelemetry](https://opentelemetry.io/) - 链路追踪
- [uv](https://github.com/astral-sh/uv) - Python 包管理
- [Bun](https://bun.sh/) - JavaScript 运行时
