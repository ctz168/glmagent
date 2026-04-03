"""
GLM Agent Engine - Main Application
Replicated from Z.ai Container Runtime

This is a FastAPI-based agent engine that provides:
- AI chat completions (LLM proxy)
- Image generation
- Speech-to-text / Text-to-speech
- Vision understanding
- Web search & page reading
- Tool execution & sandbox management
- Session & conversation management
"""

import json
import logging
import os
import re
import subprocess
import sys
import time
import uuid
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, Any
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    JSONResponse,
    StreamingResponse,
    HTMLResponse,
    FileResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import httpx
import uvicorn


# ============================================================
# Logging
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("glm-agent")


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

    # Z.ai API (backend AI service)
    ZAI_BASE_URL: str = os.getenv("ZAI_BASE_URL", "http://172.25.136.193:8080")
    ZAI_API_KEY: str = os.getenv("ZAI_API_KEY", "Z.ai")
    ZAI_TIMEOUT: int = int(os.getenv("ZAI_TIMEOUT", "120"))

    # Z.ai runtime config fields (populated from /etc/.z-ai-config)
    ZAI_CHAT_ID: str = ""
    ZAI_TOKEN: str = ""
    ZAI_USER_ID: str = ""

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
                logger.info("Loaded Z.ai config from %s (chatId=%s)", config_path, cls.ZAI_CHAT_ID[:8] + "..." if cls.ZAI_CHAT_ID else "N/A")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning("Failed to load Z.ai config: %s", e)


# Load settings
settings = Settings()
Settings.load_zai_config()


# ============================================================
# Application Setup (using lifespan context manager)
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown logic.

    Replaces the deprecated @app.on_event("startup") and @app.on_event("shutdown").
    """
    # --- Startup ---
    logger.info("Starting GLM Agent Engine v1.0.0")
    logger.info("Z.ai Backend: %s", settings.ZAI_BASE_URL)
    logger.info("Project Dir: %s", settings.PROJECT_DIR)
    logger.info("Skills Dir: %s", settings.SKILLS_DIR)
    logger.info("Region: %s | Instance: %s", settings.FC_REGION, settings.FC_INSTANCE_ID)
    logger.info("Container: %s | Kata: %s", settings.FC_CONTAINER_ID, settings.KATA_CONTAINER)
    logger.info("Function: %s (handler=%s, memory=%dMB)",
                settings.FC_FUNCTION_NAME, settings.FC_FUNCTION_HANDLER, settings.FC_FUNCTION_MEMORY_SIZE)

    # Ensure download directory has README
    readme_path = Path(settings.DOWNLOAD_DIR) / "README.md"
    if not readme_path.exists():
        readme_path.parent.mkdir(parents=True, exist_ok=True)
        readme_path.write_text("Here are all the generated files.\n")

    yield  # --- Application running ---

    # --- Shutdown ---
    await http_client.aclose()
    logger.info("Engine shutdown complete.")


app = FastAPI(
    title="GLM Agent Engine",
    description="AI Agent Engine replicated from Z.ai Container Runtime",
    version="1.0.0",
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


# Request logging middleware
@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """Log all incoming API requests for observability."""
    start_time = time.time()
    response = await call_next(request)
    duration_ms = (time.time() - start_time) * 1000
    logger.info(
        "%s %s -> %d (%.1fms)",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


# Ensure directories exist
for dir_path in [settings.DOWNLOAD_DIR, settings.UPLOAD_DIR, settings.SKILLS_DIR]:
    Path(dir_path).mkdir(parents=True, exist_ok=True)

# Normalize ZAI_BASE_URL (strip trailing /v1 to avoid path duplication)
_ZAI_BASE = settings.ZAI_BASE_URL.rstrip("/")
if _ZAI_BASE.endswith("/v1"):
    _ZAI_BASE = _ZAI_BASE[:-3]

# HTTP client for proxying to backend
http_client = httpx.AsyncClient(
    base_url=_ZAI_BASE,
    timeout=httpx.Timeout(settings.ZAI_TIMEOUT, connect=30),
    headers={"Authorization": f"Bearer {settings.ZAI_API_KEY}"},
)


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
    metadata = {
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
# Models
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


# ============================================================
# Health & Info Endpoints
# ============================================================

@app.get("/health")
async def health_check():
    """Health check endpoint used by Caddy and container orchestrator."""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0",
        "instance": settings.FC_INSTANCE_ID,
        "region": settings.FC_REGION,
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

    uptime_seconds = time.time() - float(os.getenv("STEP_START_TIME", time.time()))

    return {
        "engine": "GLM Agent Engine",
        "version": "1.0.0",
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
    }


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
    skill_md = skill_dir / "SKILL.md"

    # List all files in skill directory
    files = []
    for f in sorted(skill_dir.rglob("*")):
        if f.is_file() and f.name != "SKILL.md":
            files.append(f.name)

    return {
        "name": meta["name"],
        "description": meta["description"],
        "license": meta.get("license", ""),
        "path": str(skill_dir),
        "files": files,
    }


# ============================================================
# AI Proxy Endpoints
# ============================================================

@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    """
    Proxy chat completion requests to the backend Z.ai API.
    Supports both streaming and non-streaming responses.
    """
    payload = request.model_dump(exclude_none=True)

    if request.stream:
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
        logger.error("Chat completion error: %s", e)
        raise HTTPException(status_code=502, detail=f"Backend API error: {str(e)}")


async def _stream_chat(payload: dict):
    """Stream chat completions from backend."""
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


@app.post("/v1/images/generations")
async def image_generation(request: ImageGenerationRequest):
    """Generate images using AI model."""
    try:
        response = await http_client.post(
            "/v1/images/generations",
            json=request.model_dump(),
        )
        response.raise_for_status()
        return JSONResponse(content=response.json())
    except httpx.HTTPError as e:
        logger.error("Image generation error: %s", e)
        raise HTTPException(status_code=502, detail=f"Image generation error: {str(e)}")


@app.post("/v1/audio/speech")
async def text_to_speech(request: TTSRequest):
    """Convert text to speech."""
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
        logger.error("TTS error: %s", e)
        raise HTTPException(status_code=502, detail=f"TTS error: {str(e)}")


@app.post("/v1/audio/transcriptions")
async def speech_to_text(request: ASRRequest):
    """Transcribe audio to text."""
    try:
        response = await http_client.post(
            "/v1/audio/transcriptions",
            json=request.model_dump(),
        )
        response.raise_for_status()
        return JSONResponse(content=response.json())
    except httpx.HTTPError as e:
        logger.error("ASR error: %s", e)
        raise HTTPException(status_code=502, detail=f"ASR error: {str(e)}")


@app.post("/v1/chat/completions:multimodal")
async def vision_chat(request: ChatCompletionRequest):
    """Vision-based multimodal chat completion."""
    try:
        response = await http_client.post(
            "/v1/chat/completions:multimodal",
            json=request.model_dump(),
        )
        response.raise_for_status()
        return JSONResponse(content=response.json())
    except httpx.HTTPError as e:
        logger.error("Vision API error: %s", e)
        raise HTTPException(status_code=502, detail=f"Vision API error: {str(e)}")


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
        logger.error("Web search error: %s", e)
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
        logger.error("Web read error: %s", e)
        raise HTTPException(status_code=502, detail=f"Web read error: {str(e)}")


# ============================================================
# Session Management
# ============================================================

# In-memory session store (replace with database in production)
sessions: dict[str, dict] = {}


@app.post("/v1/sessions")
async def create_session(request: SessionCreate):
    """Create a new agent session."""
    session_id = str(uuid.uuid4())
    sessions[session_id] = {
        "id": session_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "metadata": request.metadata,
        "messages": [],
        "status": "active",
    }
    return {"session_id": session_id, **sessions[session_id]}


@app.get("/v1/sessions/{session_id}")
async def get_session(session_id: str):
    """Get session details."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return sessions[session_id]


@app.delete("/v1/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a session."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    del sessions[session_id]
    return {"status": "deleted"}


@app.get("/v1/sessions")
async def list_sessions():
    """List all active sessions."""
    return {
        "sessions": list(sessions.values()),
        "count": len(sessions),
    }


# ============================================================
# Tool Execution (Sandbox)
# ============================================================

@app.post("/v1/tools/execute")
async def execute_tool(request: ToolCallRequest):
    """
    Execute a tool call in the sandbox environment.

    Looks up the skill by name, verifies its SKILL.md exists,
    and attempts to run the skill's executable script (run.sh)
    if present. Returns the skill metadata and execution result.
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

    # Check for executable script
    run_script = skill_dir / "run.sh"
    execution_result = None

    if run_script.exists() and os.access(run_script, os.X_OK):
        try:
            # Build environment with CLAWHUB_WORKDIR set
            env = {**os.environ, "CLAWHUB_WORKDIR": settings.PROJECT_DIR}

            # Pass arguments as JSON string
            args_json = json.dumps(arguments) if arguments else "{}"

            proc = await asyncio.create_subprocess_exec(
                str(run_script),
                args_json,
                cwd=settings.PROJECT_DIR,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

            execution_result = {
                "exit_code": proc.returncode,
                "stdout": stdout.decode("utf-8", errors="replace") if stdout else "",
                "stderr": stderr.decode("utf-8", errors="replace") if stderr else "",
            }
        except asyncio.TimeoutError:
            execution_result = {
                "exit_code": -1,
                "stdout": "",
                "stderr": "Skill execution timed out after 30 seconds",
            }
        except Exception as e:
            execution_result = {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Failed to execute skill: {str(e)}",
            }

    return {
        "tool": skill_name,
        "status": "executed" if execution_result else "recognized",
        "description": meta["description"],
        "arguments": arguments,
        "execution": execution_result,
        "skill_path": str(skill_dir),
    }


# ============================================================
# File Management
# ============================================================

@app.post("/v1/files/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload a file to the sandbox."""
    # Sanitize filename to prevent path traversal
    safe_filename = os.path.basename(file.filename)
    if not safe_filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = Path(settings.UPLOAD_DIR) / safe_filename
    try:
        content = await file.read()
        file_path.write_bytes(content)
        return {
            "filename": safe_filename,
            "path": str(file_path),
            "size": len(content),
            "content_type": file.content_type,
        }
    except Exception as e:
        logger.error("Upload failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@app.get("/v1/files/{file_path:path}")
async def download_file(file_path: str):
    """Download a file from the sandbox."""
    resolved = (Path(settings.DOWNLOAD_DIR) / file_path).resolve()
    if not resolved.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if not resolved.is_relative_to(settings.DOWNLOAD_DIR):
        raise HTTPException(status_code=403, detail="Access denied")
    return FileResponse(str(resolved))


@app.get("/v1/files")
async def list_files():
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
async def delete_file(file_path: str):
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
# Environment & Config
# ============================================================

@app.get("/v1/env")
async def get_env():
    """Get safe environment variables (no secrets).

    Exposes the full set of non-sensitive container metadata
    as observed in the real Z.ai production runtime.
    """
    safe_vars = {}
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
        # Database
        "DATABASE_URL",
    }
    for key in safe_keys:
        val = os.getenv(key)
        if val:
            safe_vars[key] = val
    return safe_vars


@app.get("/v1/config")
async def get_zai_config():
    """Get Z.ai backend configuration (non-sensitive fields only)."""
    return {
        "base_url": settings.ZAI_BASE_URL,
        "chat_id": settings.ZAI_CHAT_ID[:8] + "..." if settings.ZAI_CHAT_ID else "",
        "user_id": settings.ZAI_USER_ID[:8] + "..." if settings.ZAI_USER_ID else "",
        "has_token": bool(settings.ZAI_TOKEN),
    }


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    uvicorn.run(
        app,
        host=settings.HOST,
        port=settings.PORT,
        log_level="info",
        access_log=True,
    )
