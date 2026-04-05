"""
GLM Agent Engine v2.0 - Production-Grade AI Agent Runtime
==========================================================
Replicated from Z.ai Container Runtime (PID 438, Port 12600)

A comprehensive FastAPI-based agent engine providing:
- AI chat completions (LLM proxy with SSE streaming)
- Image generation, speech-to-text, text-to-speech
- Vision understanding, web search & page reading
- Video generation & understanding (async task polling)
- Tool execution with sandbox management (run.sh/run.py/run.ts)
- Persistent session & conversation management (SQLAlchemy async)
- JWT authentication & API key authorization
- WebSocket bidirectional real-time communication
- Cron job management with APScheduler (persistent)
- Prometheus metrics, OpenTelemetry, Datadog ddtrace
- Redis caching with graceful degradation
- MCP (Model Context Protocol) support via fastmcp
- Structured JSON logging with loguru

All optional features degrade gracefully:
- DB falls back to SQLite if MySQL unavailable
- Redis is optional (falls back to in-memory / DB)
- ddtrace only imported if available
- Auth is optional for public endpoints
"""

# ============================================================
# Imports - Core (always required)
# ============================================================
import json
import os
import re
import sys
import time
import uuid
import asyncio
import hashlib
import subprocess
import traceback
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Any, AsyncGenerator, Dict, List

import httpx
import uvicorn

# ============================================================
# Imports - FastAPI & Pydantic
# ============================================================
from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    UploadFile,
    File,
    Depends,
    Header,
    WebSocket,
    WebSocketDisconnect,
    Query,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    JSONResponse,
    StreamingResponse,
    HTMLResponse,
    FileResponse,
)
from pydantic import BaseModel, Field


# ============================================================
# Imports - Optional (graceful degradation)
# ============================================================

# --- loguru structured logging ---
try:
    from loguru import logger
    LOGURU_AVAILABLE = True
except ImportError:
    import logging
    LOGURU_AVAILABLE = False
    logger = logging.getLogger("glm-agent")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

# --- SQLAlchemy async (DB) ---
try:
    from sqlalchemy.ext.asyncio import (
        create_async_engine,
        AsyncSession,
        async_sessionmaker,
    )
    from sqlalchemy.orm import DeclarativeBase
    from sqlalchemy import Column, String, Text, Integer, Float, DateTime, JSON, Boolean, ForeignKey
    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False
    AsyncSession = None  # type: ignore[assignment,misc]
    async_sessionmaker = None  # type: ignore[assignment,misc]
    create_async_engine = None  # type: ignore[assignment,misc]

# --- sse-starlette (SSE) ---
try:
    from sse_starlette.sse import EventSourceResponse
    SSE_STARLETTE_AVAILABLE = True
except ImportError:
    SSE_STARLETTE_AVAILABLE = False

# --- PyJWT (auth) ---
try:
    import jwt as _jwt
    JWT_AVAILABLE = True
except ImportError:
    JWT_AVAILABLE = False
    _jwt = None  # type: ignore[assignment,misc]

# --- Redis ---
try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

# --- APScheduler (cron jobs) ---
try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.triggers.date import DateTrigger
    APSCHEDULER_AVAILABLE = True
except ImportError:
    APSCHEDULER_AVAILABLE = False

# --- Prometheus metrics ---
try:
    from prometheus_client import (
        Counter, Histogram, Gauge, Info, generate_latest, CONTENT_TYPE_LATEST,
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

# --- OpenTelemetry ---
try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False
    trace = None  # type: ignore[assignment,misc]
    TracerProvider = None  # type: ignore[assignment,misc]

# --- Datadog ddtrace ---
try:
    import ddtrace
    ddtrace.patch(fastapi=True)
    DDTRACE_AVAILABLE = True
    logger.info("ddtrace loaded and FastAPI auto-instrumented")
except ImportError:
    DDTRACE_AVAILABLE = False

# --- MCP / fastmcp ---
try:
    from mcp.server.fastmcp import FastMCP
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False


# ============================================================
# Configuration
# ============================================================

class Settings:
    """Application settings loaded from environment variables.

    These mirror the real Z.ai container runtime environment variables
    exactly, as observed from the production Kata Container deployment.
    """

    # Server
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "12600"))

    # Z.ai API (backend AI service at 172.25.136.193:8080)
    ZAI_BASE_URL: str = os.getenv("ZAI_BASE_URL", "http://172.25.136.193:8080")
    ZAI_API_KEY: str = os.getenv("ZAI_API_KEY", "Z.ai")
    ZAI_TIMEOUT: int = int(os.getenv("ZAI_TIMEOUT", "120"))

    # Z.ai runtime config fields (populated from /etc/.z-ai-config)
    ZAI_CHAT_ID: str = ""
    ZAI_TOKEN: str = ""
    ZAI_USER_ID: str = ""

    # Authentication
    JWT_SECRET: str = os.getenv("JWT_SECRET", "glm-agent-secret-change-me")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_EXPIRATION_HOURS: int = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))
    AUTH_ENABLED: bool = os.getenv("AUTH_ENABLED", "false").lower() == "true"

    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "sqlite+aiosqlite:///home/z/my-project/db/agent.db"
    )

    # Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # Project paths
    PROJECT_DIR: str = os.getenv("CLAWHUB_WORKDIR", "/home/z/my-project")
    DOWNLOAD_DIR: str = os.path.join(PROJECT_DIR, "download")
    UPLOAD_DIR: str = os.path.join(PROJECT_DIR, "upload")
    SKILLS_DIR: str = os.path.join(PROJECT_DIR, "skills")
    DB_PATH: str = os.getenv("DATABASE_URL", "file:/home/z/my-project/db/custom.db").replace("file:", "")

    # Session
    SESSION_TIMEOUT: int = int(os.getenv("SESSION_TIMEOUT", "3600"))

    # Container metadata (FC = Function Compute)
    FC_REGION: str = os.getenv("FC_REGION", "cn-hongkong")
    FC_INSTANCE_ID: str = os.getenv("FC_INSTANCE_ID", "local-dev")
    FC_FUNCTION_NAME: str = os.getenv("FC_FUNCTION_NAME", "glm-agent-local")
    FC_CONTAINER_ID: str = os.getenv("FC_CONTAINER_ID", "")
    FC_ACCOUNT_ID: str = os.getenv("FC_ACCOUNT_ID", "")
    FC_FUNCTION_HANDLER: str = os.getenv("FC_FUNCTION_HANDLER", "index.handler")
    FC_FUNCTION_MEMORY_SIZE: int = int(os.getenv("FC_FUNCTION_MEMORY_SIZE", "8192"))
    FC_CUSTOM_LISTEN_PORT: int = int(os.getenv("FC_CUSTOM_LISTEN_PORT", "81"))

    # Platform
    SIGMA_APP_NAME: str = os.getenv("SIGMA_APP_NAME", "")
    CLAWHUB_DISABLE_TELEMETRY: str = os.getenv("CLAWHUB_DISABLE_TELEMETRY", "1")
    KATA_CONTAINER: str = os.getenv("KATA_CONTAINER", "true")

    # Runtime tools
    UV_BIN: str = os.getenv("UV", "/usr/local/bin/uv")
    BUN_INSTALL: str = os.getenv("BUN_INSTALL", "/home/z/.bun")
    BUN_INSTALL_BIN: str = os.getenv("BUN_INSTALL_BIN", "/usr/local/bin")
    VIRTUAL_ENV: str = os.getenv("VIRTUAL_ENV", "/app/.venv")

    # SSE heartbeat
    SSE_HEARTBEAT_INTERVAL: int = int(os.getenv("SSE_HEARTBEAT_INTERVAL", "15"))

    # Tool execution timeout (seconds)
    TOOL_TIMEOUT: int = int(os.getenv("TOOL_TIMEOUT", "30"))

    @classmethod
    def load_zai_config(cls):
        """Load Z.ai config from /etc/.z-ai-config if exists.

        The real production config file contains:
        {"baseUrl": "...", "apiKey": "...", "chatId": "...", "token": "...", "userId": "..."}
        """
        config_path = Path("/etc/.z-ai-config")
        if config_path.exists():
            try:
                with open(config_path) as f:
                    config = json.load(f)
                cls.ZAI_BASE_URL = config.get("baseUrl", cls.ZAI_BASE_URL)
                cls.ZAI_API_KEY = config.get("apiKey", cls.ZAI_API_KEY)
                cls.ZAI_CHAT_ID = config.get("chatId", "")
                cls.ZAI_TOKEN = config.get("token", "")
                cls.ZAI_USER_ID = config.get("userId", "")
                logger.info(
                    "Loaded Z.ai config from {} (chatId={})",
                    config_path,
                    cls.ZAI_CHAT_ID[:8] + "..." if cls.ZAI_CHAT_ID else "N/A",
                )
            except (json.JSONDecodeError, IOError) as e:
                logger.warning("Failed to load Z.ai config: {}", e)


# Load settings
settings = Settings()
Settings.load_zai_config()


# ============================================================
# Prometheus Metrics Setup
# ============================================================

if PROMETHEUS_AVAILABLE:
    REQUEST_COUNT = Counter(
        "glm_http_requests_total", "Total HTTP requests",
        ["method", "endpoint", "status_code"],
    )
    REQUEST_LATENCY = Histogram(
        "glm_http_request_duration_seconds", "HTTP request latency",
        ["method", "endpoint"],
    )
    ACTIVE_SESSIONS = Gauge(
        "glm_active_sessions", "Number of active sessions",
    )
    TOOL_EXECUTIONS = Counter(
        "glm_tool_executions_total", "Total tool executions",
        ["tool_name", "status"],
    )
    AI_OPERATIONS = Counter(
        "glm_ai_operations_total", "AI API operations",
        ["operation", "model"],
    )
    CRON_JOBS_ACTIVE = Gauge(
        "glm_cron_jobs_active", "Number of active cron jobs",
    )
    ENGINE_INFO = Info(
        "glm_engine", "GLM Agent Engine information",
    )
    ENGINE_INFO.info({
        "version": "2.0.0",
        "region": settings.FC_REGION,
        "instance": settings.FC_INSTANCE_ID,
    })


# ============================================================
# Database Models & Engine
# ============================================================

if SQLALCHEMY_AVAILABLE:
    class Base(DeclarativeBase):
        """SQLAlchemy declarative base for all ORM models."""
        pass

    class SessionModel(Base):
        """Persistent session storage - replaces in-memory dict."""
        __tablename__ = "sessions"

        id = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
        created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
        updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
        metadata_json = Column(JSON, default=dict)
        status = Column(String(32), default="active")
        user_id = Column(String(128), nullable=True)

    class MessageModel(Base):
        """Chat messages associated with sessions."""
        __tablename__ = "messages"

        id = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
        session_id = Column(String(64), ForeignKey("sessions.id"), index=True)
        role = Column(String(32), nullable=False)
        content = Column(Text, nullable=False)
        model = Column(String(64), nullable=True)
        tokens = Column(Integer, nullable=True)
        created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    class FileModel(Base):
        """File metadata storage."""
        __tablename__ = "files"

        id = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
        filename = Column(String(512), nullable=False)
        file_path = Column(String(1024), nullable=False)
        size_bytes = Column(Integer, default=0)
        content_type = Column(String(256), nullable=True)
        checksum_sha256 = Column(String(64), nullable=True)
        session_id = Column(String(64), nullable=True, index=True)
        uploaded_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    class CronJobModel(Base):
        """Persistent cron job definitions."""
        __tablename__ = "cron_jobs"

        id = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
        name = Column(String(256), nullable=False)
        schedule_type = Column(String(32), nullable=False)  # cron, fixed_rate, one_time
        schedule_value = Column(String(256), nullable=False)
        payload = Column(JSON, default=dict)
        status = Column(String(32), default="active")
        last_run = Column(DateTime(timezone=True), nullable=True)
        next_run = Column(DateTime(timezone=True), nullable=True)
        run_count = Column(Integer, default=0)
        created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    class ToolExecutionModel(Base):
        """Tool execution history and logs."""
        __tablename__ = "tool_executions"

        id = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
        tool_name = Column(String(256), nullable=False, index=True)
        arguments = Column(JSON, default=dict)
        session_id = Column(String(64), nullable=True, index=True)
        exit_code = Column(Integer, nullable=True)
        stdout = Column(Text, nullable=True)
        stderr = Column(Text, nullable=True)
        duration_ms = Column(Float, nullable=True)
        created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Database engine & session factory
    _db_url = settings.DATABASE_URL
    # Fallback: if MySQL specified but aiomysql unavailable, switch to SQLite
    if "mysql" in _db_url:
        try:
            import aiomysql  # noqa: F401 - test availability
        except ImportError:
            logger.warning("aiomysql not available, falling back to SQLite")
            _db_url = "sqlite+aiosqlite:///home/z/my-project/db/agent.db"

    db_engine = create_async_engine(_db_url, echo=False, pool_pre_ping=True)
    async_session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False,
    )

    async def init_db():
        """Create all tables on startup (simple migration support)."""
        async with db_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database initialized: {}", _db_url.split("://")[0])

    async def get_db() -> AsyncGenerator[AsyncSession, None]:
        """FastAPI dependency that yields an async DB session."""
        async with async_session_factory() as session:
            try:
                yield session
            finally:
                await session.close()
else:
    # Fallback: no-op stubs when SQLAlchemy is not available
    async def init_db():
        logger.warning("SQLAlchemy not available - using in-memory storage")

    async def get_db():
        yield None


# ============================================================
# Redis Cache Layer
# ============================================================

redis_client: Any = None
redis_pubsub: Any = None


async def init_redis():
    """Initialize Redis connection (optional - fails silently)."""
    global redis_client, redis_pubsub
    if not REDIS_AVAILABLE:
        logger.info("Redis not installed - caching disabled")
        return
    try:
        redis_client = aioredis.from_url(
            settings.REDIS_URL, decode_responses=True, max_connections=10,
        )
        await redis_client.ping()
        logger.info("Redis connected: {}", settings.REDIS_URL)
    except Exception as e:
        logger.warning("Redis unavailable ({}): caching disabled", e)
        redis_client = None


async def cache_get(key: str) -> Optional[str]:
    """Get a value from Redis cache. Returns None on miss or failure."""
    if redis_client is None:
        return None
    try:
        return await redis_client.get(key)
    except Exception:
        return None


async def cache_set(key: str, value: str, ttl: int = 3600):
    """Set a value in Redis cache with TTL. Fails silently."""
    if redis_client is None:
        return
    try:
        await redis_client.setex(key, ttl, value)
    except Exception:
        pass


async def cache_delete(key: str):
    """Delete a key from Redis cache. Fails silently."""
    if redis_client is None:
        return
    try:
        await redis_client.delete(key)
    except Exception:
        pass


async def publish_event(channel: str, data: dict):
    """Publish an event to Redis Pub/Sub. Fails silently."""
    if redis_client is None:
        return
    try:
        await redis_client.publish(channel, json.dumps(data))
    except Exception:
        pass


# ============================================================
# Authentication Layer
# ============================================================

async def verify_api_key(api_key: Optional[str] = Header(None, alias="ZAI_API_KEY")) -> Optional[dict]:
    """Verify API key from header. Returns user info dict or None."""
    if not settings.AUTH_ENABLED:
        return {"user_id": "anonymous", "method": "no-auth"}
    if api_key and api_key == settings.ZAI_API_KEY:
        return {"user_id": "api-key-user", "method": "api-key"}
    return None


async def verify_jwt_token(
    authorization: Optional[str] = Header(None),
) -> Optional[dict]:
    """Verify JWT bearer token. Returns payload dict or None."""
    if not settings.AUTH_ENABLED:
        return {"user_id": "anonymous", "method": "no-auth"}
    if not JWT_AVAILABLE or not authorization:
        return None
    try:
        token = authorization.replace("Bearer ", "").strip()
        payload = _jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except Exception:
        return None


def create_jwt_token(user_id: str, extra_claims: Optional[dict] = None) -> str:
    """Create a signed JWT token for the given user."""
    if not JWT_AVAILABLE:
        raise HTTPException(status_code=500, detail="JWT not available")
    payload = {
        "sub": user_id,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRATION_HOURS),
        **(extra_claims or {}),
    }
    return _jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


async def require_auth(
    api_key: Optional[str] = Header(None, alias="ZAI_API_KEY"),
    authorization: Optional[str] = Header(None),
) -> dict:
    """Dependency that enforces authentication. Raises 401 if no valid auth."""
    # Try API key first
    if api_key and api_key == settings.ZAI_API_KEY:
        return {"user_id": "api-key-user", "method": "api-key"}
    # Try JWT
    result = await verify_jwt_token(authorization)
    if result:
        return result
    if settings.AUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide ZAI_API_KEY header or Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {"user_id": "anonymous", "method": "no-auth"}


# ============================================================
# SKILL.md Frontmatter Parser
# ============================================================

def parse_skill_metadata(skill_dir: Path) -> dict[str, str]:
    """Parse SKILL.md frontmatter and extract metadata.

    Real skills use YAML frontmatter format:
    ---
    name: skill-name
    description: Skill description text
    license: MIT
    ---

    Falls back to extracting first paragraph as description if no frontmatter.
    """
    skill_md = skill_dir / "SKILL.md"
    metadata: dict[str, str] = {
        "name": skill_dir.name,
        "description": "",
        "license": "",
    }

    if not skill_md.exists():
        return metadata

    try:
        content = skill_md.read_text(encoding="utf-8")
    except Exception:
        return metadata

    # Try to parse YAML frontmatter (between --- markers)
    frontmatter_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if frontmatter_match:
        fm_text = frontmatter_match.group(1)
        for line in fm_text.strip().split("\n"):
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip().lower()
                value = value.strip().strip('"').strip("'")
                if key in metadata:
                    metadata[key] = value

    # If no description from frontmatter, extract from body
    if not metadata["description"]:
        body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", content, count=1, flags=re.DOTALL)
        for line in body.strip().split("\n"):
            line = line.strip()
            if line and not line.startswith("#") and len(line) > 10:
                metadata["description"] = line
                break

    return metadata


# ============================================================
# Pydantic Request/Response Models
# ============================================================

class ChatMessage(BaseModel):
    role: str
    content: str | list | None = None


class ChatCompletionRequest(BaseModel):
    model: str = "glm-4"
    messages: list[ChatMessage]
    temperature: float | None = 0.7
    max_tokens: int | None = 4096
    stream: bool = False
    tools: list[dict] | None = None


class ImageGenerationRequest(BaseModel):
    prompt: str
    size: str = "1024x1024"
    n: int = 1


class TTSRequest(BaseModel):
    text: str
    voice: str = "default"
    speed: float = 1.0


class ASRRequest(BaseModel):
    audio_base64: str
    language: str = "auto"


class WebSearchRequest(BaseModel):
    query: str
    num: int = 10


class WebReadRequest(BaseModel):
    url: str


class ToolCallRequest(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = None


class SessionCreate(BaseModel):
    metadata: dict[str, Any] = Field(default_factory=dict)


class CronJobCreate(BaseModel):
    name: str
    schedule_type: str = Field(description="cron | fixed_rate | one_time")
    schedule_value: str = Field(description="Cron expr, interval in seconds, or ISO datetime")
    payload: dict[str, Any] = Field(default_factory=dict)


class CronJobUpdate(BaseModel):
    status: str | None = None
    schedule_value: str | None = None


class VideoGenerationRequest(BaseModel):
    prompt: str
    model: str = "video-gen"
    size: str = "1280x720"
    duration: int = Field(default=5, ge=1, le=60)


class VideoUnderstandRequest(BaseModel):
    video_base64: str
    prompt: str = "Describe this video in detail."


class ErrorResponse(BaseModel):
    error: str
    detail: str
    correlation_id: str = ""
    timestamp: str = ""


# ============================================================
# Application Setup (Lifespan)
# ============================================================

# APScheduler instance
scheduler: Any = None
if APSCHEDULER_AVAILABLE:
    scheduler = AsyncIOScheduler(timezone="UTC")
else:
    logger.warning("APScheduler not available - cron jobs disabled")

# WebSocket connection manager
class ConnectionManager:
    """Manages active WebSocket connections for broadcasting."""

    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = []
        self.active_connections[session_id].append(websocket)
        logger.debug("WebSocket connected for session {}", session_id)

    def disconnect(self, websocket: WebSocket, session_id: str):
        if session_id in self.active_connections:
            self.active_connections[session_id].remove(websocket)
            if not self.active_connections[session_id]:
                del self.active_connections[session_id]

    async def broadcast_to_session(self, session_id: str, message: dict):
        if session_id in self.active_connections:
            disconnected = []
            for ws in self.active_connections[session_id]:
                try:
                    await ws.send_json(message)
                except Exception:
                    disconnected.append(ws)
            for ws in disconnected:
                self.disconnect(ws, session_id)

    async def broadcast_all(self, message: dict):
        for session_id in list(self.active_connections.keys()):
            await self.broadcast_to_session(session_id, message)


ws_manager = ConnectionManager()

# Video generation task store (in-memory, with DB fallback)
video_tasks: Dict[str, dict] = {}

# HTTP client for proxying to backend
_ZAI_BASE = settings.ZAI_BASE_URL.rstrip("/")
if _ZAI_BASE.endswith("/v1"):
    _ZAI_BASE = _ZAI_BASE[:-3]

http_client = httpx.AsyncClient(
    base_url=_ZAI_BASE,
    timeout=httpx.Timeout(settings.ZAI_TIMEOUT, connect=30),
    headers={"Authorization": f"Bearer {settings.ZAI_API_KEY}"},
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown logic.

    Initializes database, Redis, scheduler, OpenTelemetry, and MCP.
    """
    # --- Startup ---
    _startup_time = time.time()
    logger.info("=" * 60)
    logger.info("Starting GLM Agent Engine v2.0.0")
    logger.info("Z.ai Backend: {}", settings.ZAI_BASE_URL)
    logger.info("Project Dir: {}", settings.PROJECT_DIR)
    logger.info("Skills Dir: {}", settings.SKILLS_DIR)
    logger.info("Region: {} | Instance: {}", settings.FC_REGION, settings.FC_INSTANCE_ID)
    logger.info("Container: {} | Kata: {}", settings.FC_CONTAINER_ID, settings.KATA_CONTAINER)
    logger.info("Function: {} (handler={}, memory={}MB)",
                settings.FC_FUNCTION_NAME, settings.FC_FUNCTION_HANDLER, settings.FC_FUNCTION_MEMORY_SIZE)
    logger.info("Auth: {} | DB: {} | Redis: {} | SSE: {} | Scheduler: {} | Prometheus: {}",
                settings.AUTH_ENABLED,
                SQLALCHEMY_AVAILABLE,
                REDIS_AVAILABLE,
                SSE_STARLETTE_AVAILABLE,
                APSCHEDULER_AVAILABLE,
                PROMETHEUS_AVAILABLE)
    logger.info("=" * 60)

    # Initialize database
    await init_db()

    # Initialize Redis
    await init_redis()

    # Ensure directories
    for dir_path in [settings.DOWNLOAD_DIR, settings.UPLOAD_DIR, settings.SKILLS_DIR]:
        Path(dir_path).mkdir(parents=True, exist_ok=True)

    # Ensure download directory has README
    readme_path = Path(settings.DOWNLOAD_DIR) / "README.md"
    if not readme_path.exists():
        readme_path.parent.mkdir(parents=True, exist_ok=True)
        readme_path.write_text("Here are all the generated files.\n")

    # Restore cron jobs from DB
    if APSCHEDULER_AVAILABLE and SQLALCHEMY_AVAILABLE:
        await _restore_cron_jobs()

    # Start APScheduler
    if APSCHEDULER_AVAILABLE and scheduler:
        scheduler.start()
        logger.info("APScheduler started")

    # Setup OpenTelemetry
    if OTEL_AVAILABLE:
        try:
            resource = Resource.create({
                "service.name": "glm-agent-engine",
                "service.version": "2.0.0",
                "deployment.environment": settings.FC_REGION,
            })
            provider = TracerProvider(resource=resource)
            trace.set_tracer_provider(provider)
            FastAPIInstrumentor.instrument_app(app)
            logger.info("OpenTelemetry instrumented")
        except Exception as e:
            logger.warning("OpenTelemetry setup failed: {}", e)

    # Store startup time for uptime calculation
    app.state.startup_time = _startup_time

    yield  # --- Application running ---

    # --- Shutdown ---
    if APSCHEDULER_AVAILABLE and scheduler:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped")

    await http_client.aclose()

    if redis_client:
        await redis_client.close()
        logger.info("Redis disconnected")

    if SQLALCHEMY_AVAILABLE:
        await db_engine.dispose()
        logger.info("Database engine disposed")

    logger.info("Engine shutdown complete.")


# ============================================================
# FastAPI Application
# ============================================================

app = FastAPI(
    title="GLM Agent Engine",
    description=(
        "Production-grade AI Agent Engine replicated from Z.ai Container Runtime. "
        "Provides LLM chat, image/speech/vision/video AI, tool execution, "
        "session management, cron jobs, WebSocket, and comprehensive observability."
    ),
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# Middleware: Request Logging & Metrics
# ============================================================

@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """Log all requests with timing, trace IDs, and update Prometheus metrics."""
    start_time = time.time()
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4())[:8])

    # Inject correlation ID into request state for handlers
    request.state.correlation_id = correlation_id

    try:
        response = await call_next(request)
    except Exception as exc:
        duration_ms = (time.time() - start_time) * 1000
        logger.error(
            "{} {} -> UNHANDLED ({:.1f}ms) [{}] {}",
            request.method, request.url.path, duration_ms,
            correlation_id, str(exc),
        )
        raise

    duration_ms = (time.time() - start_time) * 1000

    # Prometheus metrics
    if PROMETHEUS_AVAILABLE:
        endpoint = request.url.path
        # Normalize endpoints for metrics (replace path params)
        for pattern in ["/v1/sessions/", "/v1/files/", "/v1/skills/", "/v1/cron/", "/v1/videos/tasks/"]:
            if pattern in endpoint:
                endpoint = endpoint[:endpoint.index(pattern) + len(pattern) - 1]
        REQUEST_COUNT.labels(
            method=request.method,
            endpoint=endpoint,
            status_code=response.status_code,
        ).inc()
        REQUEST_LATENCY.labels(
            method=request.method,
            endpoint=endpoint,
        ).observe(duration_ms / 1000.0)

    # Log level based on status code
    log_method = logger.info if response.status_code < 400 else logger.warning
    log_method(
        "{} {} -> {} ({:.1f}ms) [{}]",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        correlation_id,
    )

    # Add correlation ID to response
    response.headers["X-Correlation-ID"] = correlation_id
    return response


# ============================================================
# Global Exception Handlers
# ============================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Return structured error responses for HTTP exceptions."""
    correlation_id = getattr(request.state, "correlation_id", "")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "detail": "",
            "correlation_id": correlation_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Catch-all handler for unhandled exceptions."""
    correlation_id = getattr(request.state, "correlation_id", "")
    logger.error(
        "Unhandled exception [{}]: {} - {}",
        correlation_id,
        type(exc).__name__,
        str(exc),
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc) if settings.FC_REGION == "local-dev" else "An unexpected error occurred",
            "correlation_id": correlation_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


# ============================================================
# Health, Info & Metrics Endpoints
# ============================================================

@app.get("/health")
async def health_check():
    """Health check endpoint used by Caddy and container orchestrator."""
    components = {"database": False, "redis": False}
    if SQLALCHEMY_AVAILABLE:
        try:
            async with async_session_factory() as session:
                from sqlalchemy import text
                await session.execute(text("SELECT 1"))
            components["database"] = True
        except Exception:
            pass
    if redis_client:
        try:
            await redis_client.ping()
            components["redis"] = True
        except Exception:
            pass

    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "2.0.0",
        "instance": settings.FC_INSTANCE_ID,
        "region": settings.FC_REGION,
        "components": components,
    }


@app.get("/info")
async def get_info():
    """Get runtime environment information.

    Exposes the same metadata as the real Z.ai container for debugging
    and orchestration compatibility.
    """
    skills_count = 0
    skills_dir = Path(settings.SKILLS_DIR)
    if skills_dir.exists():
        skills_count = sum(1 for p in skills_dir.iterdir() if p.is_dir())

    uptime_seconds = time.time() - getattr(app.state, "startup_time", time.time())

    return {
        "engine": "GLM Agent Engine",
        "version": "2.0.0",
        "python": sys.version,
        "region": settings.FC_REGION,
        "instance_id": settings.FC_INSTANCE_ID,
        "container_id": settings.FC_CONTAINER_ID,
        "function_name": settings.FC_FUNCTION_NAME,
        "function_handler": settings.FC_FUNCTION_HANDLER,
        "memory_size_mb": settings.FC_FUNCTION_MEMORY_SIZE,
        "project_dir": settings.PROJECT_DIR,
        "skills_count": skills_count,
        "kata_container": settings.KATA_CONTAINER,
        "uptime_seconds": int(uptime_seconds),
        "features": {
            "auth": settings.AUTH_ENABLED,
            "database": SQLALCHEMY_AVAILABLE,
            "redis": REDIS_AVAILABLE and redis_client is not None,
            "sse": SSE_STARLETTE_AVAILABLE,
            "scheduler": APSCHEDULER_AVAILABLE,
            "prometheus": PROMETHEUS_AVAILABLE,
            "otel": OTEL_AVAILABLE,
            "ddtrace": DDTRACE_AVAILABLE,
            "mcp": MCP_AVAILABLE,
            "jwt": JWT_AVAILABLE,
        },
    }


@app.get("/metrics")
async def prometheus_metrics():
    """Expose Prometheus metrics at /metrics endpoint."""
    if not PROMETHEUS_AVAILABLE:
        raise HTTPException(status_code=501, detail="Prometheus not available")
    body = generate_latest()
    return StreamingResponse(
        iter([body]),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.post("/v1/auth/token")
async def create_auth_token(user_id: str = "default-user"):
    """Create a JWT authentication token.

    Primarily for development/testing. In production, tokens are issued
    by the Z.ai backend and validated from /etc/.z-ai-config.
    """
    token = create_jwt_token(user_id)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": settings.JWT_EXPIRATION_HOURS * 3600,
    }


# ============================================================
# Skills Endpoints
# ============================================================

@app.get("/skills")
async def list_skills():
    """List available skills in the skills directory.

    Parses SKILL.md frontmatter for metadata. Returns the same format
    as the real Z.ai runtime skill enumeration.
    """
    skills_dir = Path(settings.SKILLS_DIR)
    if not skills_dir.exists():
        return {"skills": [], "count": 0}

    skills = []
    for skill_path in sorted(skills_dir.iterdir()):
        if skill_path.is_dir():
            meta = parse_skill_metadata(skill_path)
            skills.append({
                "name": meta["name"],
                "path": str(skill_path),
                "description": meta["description"],
                "license": meta.get("license", ""),
            })

    return {"skills": skills, "count": len(skills)}


@app.get("/skills/{skill_name}")
async def get_skill_detail(skill_name: str):
    """Get detailed information about a specific skill."""
    skill_dir = Path(settings.SKILLS_DIR) / skill_name
    if not skill_dir.exists() or not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

    meta = parse_skill_metadata(skill_dir)

    # List all files in skill directory
    files = []
    for f in sorted(skill_dir.rglob("*")):
        if f.is_file() and f.name != "SKILL.md":
            files.append(f.name)

    # Detect executable type
    executable_type = "none"
    for script_name, script_type in [("run.sh", "shell"), ("run.py", "python"), ("run.ts", "typescript")]:
        if (skill_dir / script_name).exists():
            executable_type = script_type
            break

    return {
        "name": meta["name"],
        "description": meta["description"],
        "license": meta.get("license", ""),
        "path": str(skill_dir),
        "files": files,
        "executable_type": executable_type,
    }


# ============================================================
# AI Proxy Endpoints (Backward Compatible)
# ============================================================

@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    """
    Proxy chat completion requests to the backend Z.ai API.
    Supports both streaming and non-streaming responses.
    """
    payload = request.model_dump(exclude_none=True)

    if PROMETHEUS_AVAILABLE:
        AI_OPERATIONS.labels(operation="chat", model=request.model).inc()

    if request.stream:
        if SSE_STARLETTE_AVAILABLE:
            return EventSourceResponse(
                _stream_chat_enhanced(payload),
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )
        # Fallback to raw StreamingResponse
        return StreamingResponse(
            _stream_chat(payload),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        response = await http_client.post("/v1/chat/completions", json=payload)
        response.raise_for_status()
        return JSONResponse(content=response.json())
    except httpx.HTTPError as e:
        logger.error("Chat completion error: {}", e)
        raise HTTPException(status_code=502, detail=f"Backend API error: {str(e)}")


async def _stream_chat(payload: dict) -> AsyncGenerator[bytes, None]:
    """Stream chat completions from backend (raw SSE)."""
    try:
        async with http_client.stream("POST", "/v1/chat/completions", json=payload) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                yield chunk
    except httpx.HTTPError as e:
        error_data = json.dumps({"error": f"Stream error: {str(e)}"})
        yield f"data: {error_data}\n\n"
    except asyncio.CancelledError:
        logger.info("Chat stream cancelled by client")
        raise


async def _stream_chat_enhanced(payload: dict) -> AsyncGenerator[dict, None]:
    """Enhanced SSE streaming with typed events and heartbeat.

    Event types:
    - delta: Content token delta
    - done: Stream completed
    - error: Error occurred
    - tool_call: Tool invocation detected
    """
    try:
        async with http_client.stream("POST", "/v1/chat/completions", json=payload) as response:
            response.raise_for_status()
            buffer = ""
            async for chunk in response.aiter_text():
                buffer += chunk
                # Process SSE lines
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line or line.startswith(":"):
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            yield {"event": "done", "data": json.dumps({"reason": "complete"})}
                            return
                        try:
                            data = json.loads(data_str)
                            # Detect tool calls
                            choices = data.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                if delta.get("tool_calls"):
                                    yield {
                                        "event": "tool_call",
                                        "data": json.dumps(delta["tool_calls"]),
                                    }
                                elif delta.get("content"):
                                    yield {
                                        "event": "delta",
                                        "data": json.dumps({"content": delta["content"]}),
                                    }
                            # Forward raw data as well
                            yield {"event": "message", "data": data_str}
                        except json.JSONDecodeError:
                            yield {"event": "raw", "data": data_str}
    except httpx.HTTPError as e:
        yield {
            "event": "error",
            "data": json.dumps({"error": str(e)}),
        }
    except asyncio.CancelledError:
        logger.info("Enhanced chat stream cancelled by client")
        raise


@app.post("/v1/images/generations")
async def image_generation(request: ImageGenerationRequest):
    """Generate images using AI model."""
    if PROMETHEUS_AVAILABLE:
        AI_OPERATIONS.labels(operation="image_gen", model="default").inc()
    try:
        response = await http_client.post(
            "/v1/images/generations",
            json=request.model_dump(),
        )
        response.raise_for_status()
        return JSONResponse(content=response.json())
    except httpx.HTTPError as e:
        logger.error("Image generation error: {}", e)
        raise HTTPException(status_code=502, detail=f"Image generation error: {str(e)}")


@app.post("/v1/audio/speech")
async def text_to_speech(request: TTSRequest):
    """Convert text to speech."""
    if PROMETHEUS_AVAILABLE:
        AI_OPERATIONS.labels(operation="tts", model=request.voice).inc()
    try:
        response = await http_client.post(
            "/v1/audio/speech",
            json=request.model_dump(),
        )
        response.raise_for_status()
        return StreamingResponse(
            content=iter([response.content]),
            media_type="audio/mpeg",
        )
    except httpx.HTTPError as e:
        logger.error("TTS error: {}", e)
        raise HTTPException(status_code=502, detail=f"TTS error: {str(e)}")


@app.post("/v1/audio/transcriptions")
async def speech_to_text(request: ASRRequest):
    """Transcribe audio to text."""
    if PROMETHEUS_AVAILABLE:
        AI_OPERATIONS.labels(operation="asr", model="default").inc()
    try:
        response = await http_client.post(
            "/v1/audio/transcriptions",
            json=request.model_dump(),
        )
        response.raise_for_status()
        return JSONResponse(content=response.json())
    except httpx.HTTPError as e:
        logger.error("ASR error: {}", e)
        raise HTTPException(status_code=502, detail=f"ASR error: {str(e)}")


@app.post("/v1/chat/completions:multimodal")
async def vision_chat(request: ChatCompletionRequest):
    """Vision-based multimodal chat completion."""
    if PROMETHEUS_AVAILABLE:
        AI_OPERATIONS.labels(operation="vision", model=request.model).inc()
    try:
        response = await http_client.post(
            "/v1/chat/completions:multimodal",
            json=request.model_dump(),
        )
        response.raise_for_status()
        return JSONResponse(content=response.json())
    except httpx.HTTPError as e:
        logger.error("Vision API error: {}", e)
        raise HTTPException(status_code=502, detail=f"Vision API error: {str(e)}")


# ============================================================
# Video Generation & Understanding
# ============================================================

@app.post("/v1/videos/generations")
async def video_generation(request: VideoGenerationRequest):
    """Async video generation. Returns a task_id for polling."""
    if PROMETHEUS_AVAILABLE:
        AI_OPERATIONS.labels(operation="video_gen", model=request.model).inc()

    task_id = f"vt_{uuid.uuid4().hex[:16]}"
    video_tasks[task_id] = {
        "task_id": task_id,
        "status": "pending",
        "prompt": request.prompt,
        "model": request.model,
        "size": request.size,
        "duration": request.duration,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "result": None,
        "error": None,
    }

    # Kick off video generation in background
    asyncio.create_task(_process_video_generation(task_id, request))

    return {
        "task_id": task_id,
        "status": "pending",
        "message": "Video generation task submitted. Poll /v1/videos/tasks/{task_id} for status.",
    }


async def _process_video_generation(task_id: str, request: VideoGenerationRequest):
    """Background task to process video generation."""
    video_tasks[task_id]["status"] = "processing"

    try:
        # Proxy to backend video generation API
        response = await http_client.post(
            "/v1/videos/generations",
            json=request.model_dump(),
            timeout=httpx.Timeout(300),  # Video gen can be slow
        )
        response.raise_for_status()
        result = response.json()
        video_tasks[task_id]["status"] = "completed"
        video_tasks[task_id]["result"] = result
        video_tasks[task_id]["completed_at"] = datetime.now(timezone.utc).isoformat()

        # Publish event via Redis
        await publish_event("video:completed", {
            "task_id": task_id,
            "status": "completed",
        })
    except httpx.HTTPError as e:
        video_tasks[task_id]["status"] = "failed"
        video_tasks[task_id]["error"] = str(e)
        logger.error("Video generation task {} failed: {}", task_id, e)


@app.post("/v1/videos/understand")
async def video_understand(request: VideoUnderstandRequest):
    """Analyze and understand video content."""
    if PROMETHEUS_AVAILABLE:
        AI_OPERATIONS.labels(operation="video_understand", model="default").inc()
    try:
        response = await http_client.post(
            "/v1/videos/understand",
            json=request.model_dump(),
            timeout=httpx.Timeout(120),
        )
        response.raise_for_status()
        return JSONResponse(content=response.json())
    except httpx.HTTPError as e:
        logger.error("Video understand error: {}", e)
        raise HTTPException(status_code=502, detail=f"Video analysis error: {str(e)}")


@app.get("/v1/videos/tasks/{task_id}")
async def get_video_task(task_id: str):
    """Check video generation task status."""
    if task_id not in video_tasks:
        raise HTTPException(status_code=404, detail=f"Video task '{task_id}' not found")
    return video_tasks[task_id]


# ============================================================
# Web Search & Read
# ============================================================

@app.post("/v1/web/search")
async def web_search(request: WebSearchRequest):
    """Search the web for information."""
    try:
        response = await http_client.post(
            "/functions/web_search",
            json={"query": request.query, "num": request.num},
        )
        response.raise_for_status()
        return JSONResponse(content=response.json())
    except httpx.HTTPError as e:
        logger.error("Web search error: {}", e)
        raise HTTPException(status_code=502, detail=f"Web search error: {str(e)}")


@app.post("/v1/web/read")
async def web_read(request: WebReadRequest):
    """Read and extract content from a web page."""
    try:
        response = await http_client.post(
            "/functions/web_read",
            json={"url": request.url},
        )
        response.raise_for_status()
        return JSONResponse(content=response.json())
    except httpx.HTTPError as e:
        logger.error("Web read error: {}", e)
        raise HTTPException(status_code=502, detail=f"Web read error: {str(e)}")


# ============================================================
# Session Management (DB-backed with Redis cache)
# ============================================================

@app.post("/v1/sessions")
async def create_session(request: SessionCreate, auth: dict = Depends(require_auth)):
    """Create a new agent session. Persisted to database."""
    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    if SQLALCHEMY_AVAILABLE:
        async with async_session_factory() as db:
            session_model = SessionModel(
                id=session_id,
                metadata_json=request.metadata,
                user_id=auth.get("user_id"),
                status="active",
                created_at=now,
                updated_at=now,
            )
            db.add(session_model)
            await db.commit()

    # Cache in Redis
    await cache_set(f"session:{session_id}", json.dumps({
        "id": session_id,
        "created_at": now.isoformat(),
        "metadata": request.metadata,
        "status": "active",
        "user_id": auth.get("user_id"),
    }), ttl=settings.SESSION_TIMEOUT)

    if PROMETHEUS_AVAILABLE:
        ACTIVE_SESSIONS.inc()

    return {
        "session_id": session_id,
        "created_at": now.isoformat(),
        "metadata": request.metadata,
        "status": "active",
    }


@app.get("/v1/sessions")
async def list_sessions(auth: dict = Depends(require_auth)):
    """List all active sessions from database."""
    if SQLALCHEMY_AVAILABLE:
        async with async_session_factory() as db:
            from sqlalchemy import select
            result = await db.execute(
                select(SessionModel).where(SessionModel.status == "active").order_by(SessionModel.created_at.desc())
            )
            sessions = result.scalars().all()
            return {
                "sessions": [
                    {
                        "id": s.id,
                        "created_at": s.created_at.isoformat() if s.created_at else "",
                        "updated_at": s.updated_at.isoformat() if s.updated_at else "",
                        "metadata": s.metadata_json or {},
                        "status": s.status,
                        "user_id": s.user_id,
                    }
                    for s in sessions
                ],
                "count": len(sessions),
            }
    return {"sessions": [], "count": 0}


@app.get("/v1/sessions/{session_id}")
async def get_session(session_id: str, auth: dict = Depends(require_auth)):
    """Get session details from cache or database."""
    # Try Redis cache first
    cached = await cache_get(f"session:{session_id}")
    if cached:
        return json.loads(cached)

    if SQLALCHEMY_AVAILABLE:
        async with async_session_factory() as db:
            from sqlalchemy import select
            result = await db.execute(select(SessionModel).where(SessionModel.id == session_id))
            session_model = result.scalar_one_or_none()
            if not session_model or session_model.status == "deleted":
                raise HTTPException(status_code=404, detail="Session not found")
            data = {
                "id": session_model.id,
                "created_at": session_model.created_at.isoformat() if session_model.created_at else "",
                "updated_at": session_model.updated_at.isoformat() if session_model.updated_at else "",
                "metadata": session_model.metadata_json or {},
                "status": session_model.status,
                "user_id": session_model.user_id,
            }
            # Re-cache
            await cache_set(f"session:{session_id}", json.dumps(data), ttl=settings.SESSION_TIMEOUT)
            return data

    raise HTTPException(status_code=404, detail="Session not found")


@app.delete("/v1/sessions/{session_id}")
async def delete_session(session_id: str, auth: dict = Depends(require_auth)):
    """Delete a session from database and cache."""
    if SQLALCHEMY_AVAILABLE:
        async with async_session_factory() as db:
            from sqlalchemy import select
            result = await db.execute(select(SessionModel).where(SessionModel.id == session_id))
            session_model = result.scalar_one_or_none()
            if not session_model:
                raise HTTPException(status_code=404, detail="Session not found")
            session_model.status = "deleted"
            await db.commit()

    await cache_delete(f"session:{session_id}")

    if PROMETHEUS_AVAILABLE:
        ACTIVE_SESSIONS.dec()

    return {"status": "deleted"}


@app.get("/v1/sessions/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth: dict = Depends(require_auth),
):
    """Get messages for a session, newest first."""
    if SQLALCHEMY_AVAILABLE:
        async with async_session_factory() as db:
            from sqlalchemy import select
            result = await db.execute(
                select(MessageModel)
                .where(MessageModel.session_id == session_id)
                .order_by(MessageModel.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
            messages = result.scalars().all()
            return {
                "session_id": session_id,
                "messages": [
                    {
                        "id": m.id,
                        "role": m.role,
                        "content": m.content,
                        "model": m.model,
                        "tokens": m.tokens,
                        "created_at": m.created_at.isoformat() if m.created_at else "",
                    }
                    for m in reversed(messages)
                ],
                "count": len(messages),
            }
    return {"session_id": session_id, "messages": [], "count": 0}


# ============================================================
# Tool Execution (Enhanced with DB logging & sandboxing)
# ============================================================

@app.post("/v1/tools/execute")
async def execute_tool(request: ToolCallRequest, auth: dict = Depends(require_auth)):
    """
    Execute a tool call in the sandbox environment.

    Looks up the skill by name, verifies its SKILL.md exists,
    and attempts to run the skill's executable script (run.sh/run.py/run.ts)
    if present. Execution results are logged to the database.
    """
    skill_name = request.name
    arguments = request.arguments

    # Look up skill directory
    skill_dir = Path(settings.SKILLS_DIR) / skill_name
    if not skill_dir.exists() or not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        raise HTTPException(status_code=400, detail=f"Skill '{skill_name}' has no SKILL.md")

    # Parse skill metadata
    meta = parse_skill_metadata(skill_dir)

    execution_start = time.time()
    execution_result = None
    exit_code = None

    # Detect and run appropriate script
    script_info = _detect_run_script(skill_dir)
    if script_info:
        script_path, script_type = script_info
        execution_result, exit_code = await _run_skill_script(
            script_path, script_type, arguments, skill_dir,
        )

    duration_ms = (time.time() - execution_start) * 1000

    # Log execution to database
    exec_record_id = None
    if SQLALCHEMY_AVAILABLE:
        async with async_session_factory() as db:
            exec_record = ToolExecutionModel(
                tool_name=skill_name,
                arguments=arguments,
                session_id=request.session_id,
                exit_code=exit_code,
                stdout=execution_result.get("stdout", "") if execution_result else "",
                stderr=execution_result.get("stderr", "") if execution_result else "",
                duration_ms=duration_ms,
            )
            db.add(exec_record)
            await db.commit()
            exec_record_id = exec_record.id

    # Update Prometheus
    if PROMETHEUS_AVAILABLE:
        status_label = "success" if exit_code == 0 else ("timeout" if exit_code == -1 else "error")
        TOOL_EXECUTIONS.labels(tool_name=skill_name, status=status_label).inc()

    # Broadcast to WebSocket subscribers
    await ws_manager.broadcast_to_session(request.session_id or "", {
        "type": "tool_execution",
        "tool": skill_name,
        "status": "executed" if execution_result else "recognized",
        "duration_ms": duration_ms,
    })

    return {
        "execution_id": exec_record_id,
        "tool": skill_name,
        "status": "executed" if execution_result else "recognized",
        "description": meta["description"],
        "arguments": arguments,
        "execution": execution_result,
        "skill_path": str(skill_dir),
        "duration_ms": round(duration_ms, 2),
    }


def _detect_run_script(skill_dir: Path) -> tuple[Path, str] | None:
    """Detect the primary executable script in a skill directory.

    Priority: run.sh > run.py > run.ts
    Returns (script_path, script_type) or None.
    """
    for script_name, script_type in [("run.sh", "shell"), ("run.py", "python"), ("run.ts", "typescript")]:
        script_path = skill_dir / script_name
        if script_path.exists():
            return script_path, script_type
    return None


async def _run_skill_script(
    script_path: Path,
    script_type: str,
    arguments: dict[str, Any],
    skill_dir: Path,
) -> tuple[dict, int]:
    """Execute a skill script in a sandboxed subprocess.

    Returns (execution_result_dict, exit_code).
    """
    try:
        env = {**os.environ, "CLAWHUB_WORKDIR": settings.PROJECT_DIR}
        args_json = json.dumps(arguments) if arguments else "{}"

        if script_type == "shell":
            cmd = [str(script_path), args_json]
        elif script_type == "python":
            cmd = [sys.executable, str(script_path), args_json]
        elif script_type == "typescript":
            bun_bin = os.path.join(settings.BUN_INSTALL_BIN, "bun")
            cmd = [bun_bin, "run", str(script_path), args_json]
        else:
            cmd = [str(script_path), args_json]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=settings.PROJECT_DIR,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=settings.TOOL_TIMEOUT)

        return (
            {
                "exit_code": proc.returncode,
                "stdout": stdout.decode("utf-8", errors="replace") if stdout else "",
                "stderr": stderr.decode("utf-8", errors="replace") if stderr else "",
            },
            proc.returncode,
        )
    except asyncio.TimeoutError:
        return (
            {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Skill execution timed out after {settings.TOOL_TIMEOUT} seconds",
            },
            -1,
        )
    except Exception as e:
        return (
            {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Failed to execute skill: {str(e)}",
            },
            -1,
        )


@app.get("/v1/tools/executions")
async def list_tool_executions(
    tool_name: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    auth: dict = Depends(require_auth),
):
    """List recent tool execution history."""
    if SQLALCHEMY_AVAILABLE:
        async with async_session_factory() as db:
            from sqlalchemy import select
            query = select(ToolExecutionModel).order_by(ToolExecutionModel.created_at.desc()).limit(limit)
            if tool_name:
                query = query.where(ToolExecutionModel.tool_name == tool_name)
            result = await db.execute(query)
            executions = result.scalars().all()
            return {
                "executions": [
                    {
                        "id": e.id,
                        "tool_name": e.tool_name,
                        "arguments": e.arguments,
                        "session_id": e.session_id,
                        "exit_code": e.exit_code,
                        "duration_ms": e.duration_ms,
                        "created_at": e.created_at.isoformat() if e.created_at else "",
                    }
                    for e in executions
                ],
                "count": len(executions),
            }
    return {"executions": [], "count": 0}


# ============================================================
# WebSocket Support
# ============================================================

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for real-time bidirectional communication.

    Clients connect with a session_id and receive real-time updates for:
    - Tool execution status
    - Message streaming
    - Session state changes
    """
    await ws_manager.connect(websocket, session_id)
    try:
        while True:
            # Receive messages from client
            data = await websocket.receive_json()
            msg_type = data.get("type", "message")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong", "timestamp": datetime.now(timezone.utc).isoformat()})
            elif msg_type == "message":
                # Forward to chat completions and stream response
                await _handle_ws_message(websocket, session_id, data)
            elif msg_type == "tool_call":
                # Execute tool and stream result
                await _handle_ws_tool_call(websocket, session_id, data)
            else:
                await websocket.send_json({"type": "error", "detail": f"Unknown message type: {msg_type}"})
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, session_id)
        logger.debug("WebSocket disconnected for session {}", session_id)
    except Exception as e:
        ws_manager.disconnect(websocket, session_id)
        logger.error("WebSocket error for session {}: {}", session_id, e)


async def _handle_ws_message(websocket: WebSocket, session_id: str, data: dict):
    """Handle a chat message from WebSocket client."""
    try:
        payload = {
            "model": data.get("model", "glm-4"),
            "messages": data.get("messages", []),
            "stream": True,
        }
        async with http_client.stream("POST", "/v1/chat/completions", json=payload) as response:
            response.raise_for_status()
            async for chunk in response.aiter_text():
                if chunk.strip():
                    await websocket.send_json({"type": "delta", "data": chunk})
    except Exception as e:
        await websocket.send_json({"type": "error", "detail": str(e)})


async def _handle_ws_tool_call(websocket: WebSocket, session_id: str, data: dict):
    """Handle a tool call from WebSocket client."""
    tool_name = data.get("name", "")
    arguments = data.get("arguments", {})

    await websocket.send_json({"type": "tool_start", "tool": tool_name})

    # Execute the tool
    try:
        skill_dir = Path(settings.SKILLS_DIR) / tool_name
        if not skill_dir.exists():
            await websocket.send_json({"type": "tool_error", "tool": tool_name, "error": "Skill not found"})
            return

        script_info = _detect_run_script(skill_dir)
        if script_info:
            result, exit_code = await _run_skill_script(script_info[0], script_info[1], arguments, skill_dir)
            await websocket.send_json({
                "type": "tool_result",
                "tool": tool_name,
                "exit_code": exit_code,
                "stdout": result.get("stdout", "")[:2000],  # Truncate for WS
                "stderr": result.get("stderr", "")[:2000],
            })
        else:
            await websocket.send_json({"type": "tool_result", "tool": tool_name, "status": "recognized"})
    except Exception as e:
        await websocket.send_json({"type": "tool_error", "tool": tool_name, "error": str(e)})


# ============================================================
# Cron Job Management
# ============================================================

async def _restore_cron_jobs():
    """Restore active cron jobs from database on startup."""
    if not APSCHEDULER_AVAILABLE or not SQLALCHEMY_AVAILABLE or scheduler is None:
        return
    jobs = []
    async with async_session_factory() as db:
        from sqlalchemy import select
        result = await db.execute(
            select(CronJobModel).where(CronJobModel.status == "active")
        )
        jobs = result.scalars().all()
        for job in jobs:
            _schedule_cron_job(job)
    if PROMETHEUS_AVAILABLE:
        CRON_JOBS_ACTIVE.set(len(jobs))


def _schedule_cron_job(job_model: Any):
    """Add a cron job to the APScheduler from a DB model."""
    if scheduler is None:
        return
    try:
        if job_model.schedule_type == "cron":
            parts = job_model.schedule_value.strip().split()
            trigger = CronTrigger(
                minute=parts[0] if len(parts) > 0 else "*",
                hour=parts[1] if len(parts) > 1 else "*",
                day=parts[2] if len(parts) > 2 else "*",
                month=parts[3] if len(parts) > 3 else "*",
                day_of_week=parts[4] if len(parts) > 4 else "*",
            )
        elif job_model.schedule_type == "fixed_rate":
            seconds = int(job_model.schedule_value)
            trigger = IntervalTrigger(seconds=seconds)
        elif job_model.schedule_type == "one_time":
            run_time = datetime.fromisoformat(job_model.schedule_value)
            trigger = DateTrigger(run_time=run_time)
        else:
            logger.warning("Unknown schedule type: {}", job_model.schedule_type)
            return

        async def _run_job(job_id: str = job_model.id, payload: dict = job_model.payload):
            """Execute cron job and update DB record."""
            logger.info("Executing cron job {}", job_id)
            if SQLALCHEMY_AVAILABLE:
                async with async_session_factory() as db:
                    from sqlalchemy import select
                    result = await db.execute(select(CronJobModel).where(CronJobModel.id == job_id))
                    job = result.scalar_one_or_none()
                    if job:
                        job.last_run = datetime.now(timezone.utc)
                        job.run_count += 1
                        await db.commit()
            await publish_event("cron:executed", {"job_id": job_id, "payload": payload})

        scheduler.add_job(_run_job, trigger, id=job_model.id, replace_existing=True)
    except Exception as e:
        logger.error("Failed to schedule cron job {}: {}", job_model.id, e)


@app.post("/v1/cron", status_code=201)
async def create_cron_job(request: CronJobCreate, auth: dict = Depends(require_auth)):
    """Create a new cron job.

    Schedule types:
    - cron: Standard cron expression (e.g. "*/5 * * * *")
    - fixed_rate: Interval in seconds (e.g. "60")
    - one_time: ISO datetime (e.g. "2025-01-01T00:00:00Z")
    """
    if not APSCHEDULER_AVAILABLE:
        raise HTTPException(status_code=501, detail="APScheduler not available")

    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    if SQLALCHEMY_AVAILABLE:
        async with async_session_factory() as db:
            job_model = CronJobModel(
                id=job_id,
                name=request.name,
                schedule_type=request.schedule_type,
                schedule_value=request.schedule_value,
                payload=request.payload,
                status="active",
                created_at=now,
            )
            db.add(job_model)
            await db.commit()
            _schedule_cron_job(job_model)
    else:
        # In-memory only
        job_model = type("JobModel", (), {
            "id": job_id,
            "name": request.name,
            "schedule_type": request.schedule_type,
            "schedule_value": request.schedule_value,
            "payload": request.payload,
            "status": "active",
        })()
        _schedule_cron_job(job_model)

    if PROMETHEUS_AVAILABLE:
        CRON_JOBS_ACTIVE.inc()

    return {
        "job_id": job_id,
        "name": request.name,
        "schedule_type": request.schedule_type,
        "schedule_value": request.schedule_value,
        "status": "active",
        "created_at": now.isoformat(),
    }


@app.get("/v1/cron")
async def list_cron_jobs(auth: dict = Depends(require_auth)):
    """List all cron jobs."""
    if SQLALCHEMY_AVAILABLE:
        async with async_session_factory() as db:
            from sqlalchemy import select
            result = await db.execute(select(CronJobModel).where(CronJobModel.status != "deleted").order_by(CronJobModel.created_at.desc()))
            jobs = result.scalars().all()
            return {
                "jobs": [
                    {
                        "id": j.id,
                        "name": j.name,
                        "schedule_type": j.schedule_type,
                        "schedule_value": j.schedule_value,
                        "payload": j.payload,
                        "status": j.status,
                        "last_run": j.last_run.isoformat() if j.last_run else None,
                        "next_run": j.next_run.isoformat() if j.next_run else None,
                        "run_count": j.run_count,
                        "created_at": j.created_at.isoformat() if j.created_at else None,
                    }
                    for j in jobs
                ],
                "count": len(jobs),
            }
    return {"jobs": [], "count": 0}


@app.get("/v1/cron/{job_id}")
async def get_cron_job(job_id: str, auth: dict = Depends(require_auth)):
    """Get details of a specific cron job."""
    if SQLALCHEMY_AVAILABLE:
        async with async_session_factory() as db:
            from sqlalchemy import select
            result = await db.execute(select(CronJobModel).where(CronJobModel.id == job_id))
            job = result.scalar_one_or_none()
            if not job or job.status == "deleted":
                raise HTTPException(status_code=404, detail="Cron job not found")
            return {
                "id": job.id,
                "name": job.name,
                "schedule_type": job.schedule_type,
                "schedule_value": job.schedule_value,
                "payload": job.payload,
                "status": job.status,
                "last_run": job.last_run.isoformat() if job.last_run else None,
                "run_count": job.run_count,
                "created_at": job.created_at.isoformat() if job.created_at else None,
            }
    raise HTTPException(status_code=404, detail="Cron job not found")


@app.delete("/v1/cron/{job_id}")
async def delete_cron_job(job_id: str, auth: dict = Depends(require_auth)):
    """Delete a cron job."""
    if APSCHEDULER_AVAILABLE and scheduler:
        try:
            scheduler.remove_job(job_id)
        except Exception:
            pass

    if SQLALCHEMY_AVAILABLE:
        async with async_session_factory() as db:
            from sqlalchemy import select
            result = await db.execute(select(CronJobModel).where(CronJobModel.id == job_id))
            job = result.scalar_one_or_none()
            if not job:
                raise HTTPException(status_code=404, detail="Cron job not found")
            job.status = "deleted"
            await db.commit()

    if PROMETHEUS_AVAILABLE:
        CRON_JOBS_ACTIVE.dec()

    return {"status": "deleted", "job_id": job_id}


# ============================================================
# Enhanced File Management
# ============================================================

@app.post("/v1/files/upload")
async def upload_file(
    file: UploadFile = File(...),
    session_id: Optional[str] = None,
    auth: dict = Depends(require_auth),
):
    """Upload a file to the sandbox with metadata storage in database."""
    # Sanitize filename to prevent path traversal
    safe_filename = os.path.basename(file.filename) if file.filename else "unnamed"
    if not safe_filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = Path(settings.UPLOAD_DIR) / safe_filename
    try:
        content = await file.read()
        file_path.write_bytes(content)

        # Compute SHA-256 checksum
        checksum = hashlib.sha256(content).hexdigest()

        # Store metadata in DB
        file_id = None
        if SQLALCHEMY_AVAILABLE:
            async with async_session_factory() as db:
                file_model = FileModel(
                    filename=safe_filename,
                    file_path=str(file_path),
                    size_bytes=len(content),
                    content_type=file.content_type,
                    checksum_sha256=checksum,
                    session_id=session_id,
                )
                db.add(file_model)
                await db.commit()
                file_id = file_model.id

        return {
            "file_id": file_id,
            "filename": safe_filename,
            "path": str(file_path),
            "size": len(content),
            "content_type": file.content_type,
            "checksum_sha256": checksum,
        }
    except Exception as e:
        logger.error("Upload failed: {}", e)
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@app.get("/v1/files/{file_path:path}")
async def download_file(file_path: str):
    """Download a file from the sandbox with range request support."""
    resolved = (Path(settings.DOWNLOAD_DIR) / file_path).resolve()
    if not resolved.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if not resolved.is_relative_to(settings.DOWNLOAD_DIR):
        raise HTTPException(status_code=403, detail="Access denied")
    stat = resolved.stat()
    return FileResponse(
        str(resolved),
        filename=resolved.name,
        stat_result=stat,
    )


@app.get("/v1/files")
async def list_files(auth: dict = Depends(require_auth)):
    """List files in the download directory."""
    download = Path(settings.DOWNLOAD_DIR)
    files = []
    if download.exists():
        for f in download.rglob("*"):
            if f.is_file():
                stat = f.stat()
                files.append({
                    "name": f.name,
                    "path": str(f.relative_to(download)),
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                })
    return {"files": files, "count": len(files)}


@app.delete("/v1/files/{file_path:path}")
async def delete_file(file_path: str, auth: dict = Depends(require_auth)):
    """Delete a file from the download directory."""
    resolved = (Path(settings.DOWNLOAD_DIR) / file_path).resolve()
    if not resolved.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if not resolved.is_relative_to(settings.DOWNLOAD_DIR):
        raise HTTPException(status_code=403, detail="Access denied")
    try:
        resolved.unlink()
        return {"status": "deleted", "path": file_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")


# ============================================================
# MCP (Model Context Protocol) Support
# ============================================================

if MCP_AVAILABLE:
    mcp_server = FastMCP("glm-agent-mcp")

    @mcp_server.tool()
    async def mcp_chat_completion(prompt: str, model: str = "glm-4") -> str:
        """Send a chat completion request to the GLM model."""
        try:
            response = await http_client.post(
                "/v1/chat/completions",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
            )
            response.raise_for_status()
            data = response.json()
            return json.dumps(data, indent=2)
        except Exception as e:
            return f"Error: {str(e)}"

    @mcp_server.tool()
    async def mcp_web_search(query: str, num_results: int = 5) -> str:
        """Search the web for information."""
        try:
            response = await http_client.post(
                "/functions/web_search",
                json={"query": query, "num": num_results},
            )
            response.raise_for_status()
            return json.dumps(response.json(), indent=2)
        except Exception as e:
            return f"Error: {str(e)}"

    @mcp_server.tool()
    async def mcp_list_skills() -> str:
        """List all available skills in the agent."""
        skills_dir = Path(settings.SKILLS_DIR)
        if not skills_dir.exists():
            return "No skills directory found"
        skills = []
        for p in sorted(skills_dir.iterdir()):
            if p.is_dir():
                meta = parse_skill_metadata(p)
                skills.append(f"- {meta['name']}: {meta['description'] or 'No description'}")
        return "\n".join(skills) if skills else "No skills installed"

    @mcp_server.tool()
    async def mcp_execute_tool(tool_name: str, arguments: str = "{}") -> str:
        """Execute a skill tool by name with JSON arguments."""
        try:
            args = json.loads(arguments) if isinstance(arguments, str) else arguments
            skill_dir = Path(settings.SKILLS_DIR) / tool_name
            if not skill_dir.exists():
                return f"Error: Skill '{tool_name}' not found"
            script_info = _detect_run_script(skill_dir)
            if not script_info:
                return f"Skill '{tool_name}' found but has no executable script"
            result, exit_code = await _run_skill_script(script_info[0], script_info[1], args, skill_dir)
            output = result.get("stdout", "")
            if result.get("stderr"):
                output += f"\nstderr: {result['stderr']}"
            return output or f"Tool exited with code {exit_code}, no output"
        except json.JSONDecodeError:
            return "Error: Invalid JSON arguments"
        except Exception as e:
            return f"Error: {str(e)}"

    @mcp_server.tool()
    async def mcp_generate_image(prompt: str, size: str = "1024x1024") -> str:
        """Generate an image from a text prompt."""
        try:
            response = await http_client.post(
                "/v1/images/generations",
                json={"prompt": prompt, "size": size, "n": 1},
            )
            response.raise_for_status()
            return json.dumps(response.json(), indent=2)
        except Exception as e:
            return f"Error: {str(e)}"

    logger.info("MCP server initialized with {} tools", len(mcp_server._tool_manager._tools))


# ============================================================
# Environment & Config Endpoints
# ============================================================

@app.get("/v1/env")
async def get_env(auth: dict = Depends(require_auth)):
    """Get safe environment variables (no secrets).

    Exposes the full set of non-sensitive container metadata
    as observed in the real Z.ai production runtime.
    """
    safe_vars: dict[str, str] = {}
    safe_keys = {
        # Container metadata
        "FC_REGION", "FC_INSTANCE_ID", "FC_FUNCTION_NAME",
        "FC_CONTAINER_ID", "FC_ACCOUNT_ID", "FC_FUNCTION_HANDLER",
        "FC_FUNCTION_MEMORY_SIZE", "FC_CUSTOM_LISTEN_PORT",
        "SIGMA_APP_NAME",
        # Runtime flags
        "KATA_CONTAINER", "CLAWHUB_WORKDIR", "CLAWHUB_DISABLE_TELEMETRY",
        # Paths
        "HOME", "USER", "SHELL", "VIRTUAL_ENV", "UV_CACHE_DIR",
        "UV_PYTHON", "BUN_INSTALL",
        # Database & Redis
        "DATABASE_URL",
    }
    for key in safe_keys:
        val = os.getenv(key)
        if val:
            safe_vars[key] = val
    return safe_vars


@app.get("/v1/config")
async def get_zai_config(auth: dict = Depends(require_auth)):
    """Get Z.ai backend configuration (non-sensitive fields only)."""
    return {
        "base_url": settings.ZAI_BASE_URL,
        "chat_id": settings.ZAI_CHAT_ID[:8] + "..." if settings.ZAI_CHAT_ID else "",
        "user_id": settings.ZAI_USER_ID[:8] + "..." if settings.ZAI_USER_ID else "",
        "has_token": bool(settings.ZAI_TOKEN),
        "auth_enabled": settings.AUTH_ENABLED,
    }


# ============================================================
# Main Entry Point
# ============================================================

if __name__ == "__main__":
    logger.info("Starting uvicorn on {}:{}", settings.HOST, settings.PORT)
    uvicorn.run(
        app,
        host=settings.HOST,
        port=settings.PORT,
        log_level="info",
        access_log=True,
    )
