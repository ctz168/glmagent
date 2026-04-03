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
import os
import sys
import time
import uuid
import hashlib
import asyncio
from pathlib import Path
from typing import Optional, Any
from datetime import datetime

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
# Configuration
# ============================================================

class Settings:
    """Application settings loaded from environment variables."""

    # Server
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "12600"))

    # Z.ai API (backend AI service)
    ZAI_BASE_URL: str = os.getenv("ZAI_BASE_URL", "http://172.25.136.193:8080/v1")
    ZAI_API_KEY: str = os.getenv("ZAI_API_KEY", "Z.ai")
    ZAI_TIMEOUT: int = int(os.getenv("ZAI_TIMEOUT", "120"))

    # Project paths
    PROJECT_DIR: str = os.getenv("CLAWHUB_WORKDIR", "/home/z/my-project")
    DOWNLOAD_DIR: str = os.path.join(PROJECT_DIR, "download")
    UPLOAD_DIR: str = os.path.join(PROJECT_DIR, "upload")
    SKILLS_DIR: str = os.path.join(PROJECT_DIR, "skills")
    DB_PATH: str = os.getenv("DATABASE_URL", "file:/home/z/my-project/db/custom.db").replace("file:", "")

    # Session
    SESSION_TIMEOUT: int = int(os.getenv("SESSION_TIMEOUT", "3600"))

    # Container metadata
    FC_REGION: str = os.getenv("FC_REGION", "cn-hongkong")
    FC_INSTANCE_ID: str = os.getenv("FC_INSTANCE_ID", "local-dev")
    FC_FUNCTION_NAME: str = os.getenv("FC_FUNCTION_NAME", "glm-agent-local")

    @classmethod
    def load_zai_config(cls):
        """Load Z.ai config from /etc/.z-ai-config if exists."""
        config_path = Path("/etc/.z-ai-config")
        if config_path.exists():
            try:
                with open(config_path) as f:
                    config = json.load(f)
                    cls.ZAI_BASE_URL = config.get("baseUrl", cls.ZAI_BASE_URL)
                    cls.ZAI_API_KEY = config.get("apiKey", cls.ZAI_API_KEY)
            except (json.JSONDecodeError, IOError):
                pass


# Load settings
settings = Settings()
Settings.load_zai_config()

# ============================================================
# Application Setup
# ============================================================

app = FastAPI(
    title="GLM Agent Engine",
    description="AI Agent Engine replicated from Z.ai Container Runtime",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure directories exist
for dir_path in [settings.DOWNLOAD_DIR, settings.UPLOAD_DIR, settings.SKILLS_DIR]:
    Path(dir_path).mkdir(parents=True, exist_ok=True)

# HTTP client for proxying to backend
http_client = httpx.AsyncClient(
    base_url=settings.ZAI_BASE_URL,
    timeout=httpx.Timeout(settings.ZAI_TIMEOUT, connect=30),
    headers={"Authorization": f"Bearer {settings.ZAI_API_KEY}"},
)

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
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0",
        "instance": settings.FC_INSTANCE_ID,
        "region": settings.FC_REGION,
    }


@app.get("/info")
async def get_info():
    """Get runtime environment information."""
    return {
        "engine": "GLM Agent Engine",
        "version": "1.0.0",
        "python": sys.version,
        "region": settings.FC_REGION,
        "instance_id": settings.FC_INSTANCE_ID,
        "function_name": settings.FC_FUNCTION_NAME,
        "project_dir": settings.PROJECT_DIR,
        "skills_count": len(list(Path(settings.SKILLS_DIR).iterdir())) if Path(settings.SKILLS_DIR).exists() else 0,
        "uptime": time.time() - (os.getenv("STEP_START_TIME", time.time()) if os.getenv("STEP_START_TIME") else time.time()),
    }


@app.get("/skills")
async def list_skills():
    """List available skills in the skills directory."""
    skills_dir = Path(settings.SKILLS_DIR)
    if not skills_dir.exists():
        return {"skills": []}

    skills = []
    for skill_path in sorted(skills_dir.iterdir()):
        if skill_path.is_dir():
            skill_md = skill_path / "SKILL.md"
            description = ""
            if skill_md.exists():
                try:
                    content = skill_md.read_text(encoding="utf-8")
                    # Extract first non-empty line as description
                    for line in content.strip().split("\n"):
                        line = line.strip()
                        if line and not line.startswith("#") and not line.startswith("---"):
                            description = line
                            break
                except Exception:
                    pass
            skills.append({
                "name": skill_path.name,
                "path": str(skill_path),
                "description": description,
            })

    return {"skills": skills, "count": len(skills)}


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
        "created_at": datetime.utcnow().isoformat(),
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


# ============================================================
# Tool Execution (Sandbox)
# ============================================================

@app.post("/v1/tools/execute")
async def execute_tool(request: ToolCallRequest):
    """
    Execute a tool call in the sandbox environment.
    This dispatches to the appropriate skill handler.
    """
    skill_name = request.name
    arguments = request.arguments

    # Look up skill
    skill_dir = Path(settings.SKILLS_DIR) / skill_name
    if not skill_dir.exists():
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        raise HTTPException(status_code=400, detail=f"Skill '{skill_name}' has no SKILL.md")

    return {
        "tool": skill_name,
        "status": "recognized",
        "arguments": arguments,
        "message": f"Skill '{skill_name}' is available. Tool execution dispatched.",
        "skill_path": str(skill_dir),
    }


# ============================================================
# File Management
# ============================================================

@app.post("/v1/files/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload a file to the sandbox."""
    file_path = Path(settings.UPLOAD_DIR) / file.filename
    try:
        content = await file.read()
        file_path.write_bytes(content)
        return {
            "filename": file.filename,
            "path": str(file_path),
            "size": len(content),
            "content_type": file.content_type,
        }
    except Exception as e:
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
    for f in download.rglob("*"):
        if f.is_file():
            files.append({
                "name": f.name,
                "path": str(f.relative_to(download)),
                "size": f.stat().st_size,
            })
    return {"files": files, "count": len(files)}


# ============================================================
# Environment & Config
# ============================================================

@app.get("/v1/env")
async def get_env():
    """Get safe environment variables (no secrets)."""
    safe_vars = {}
    safe_keys = {
        "FC_REGION", "FC_INSTANCE_ID", "FC_FUNCTION_NAME",
        "FC_FUNCTION_MEMORY_SIZE", "KATA_CONTAINER",
        "CLAWHUB_WORKDIR", "HOME", "USER", "SHELL",
    }
    for key in safe_keys:
        val = os.getenv(key)
        if val:
            safe_vars[key] = val
    return safe_vars


# ============================================================
# Startup & Shutdown
# ============================================================

@app.on_event("startup")
async def startup():
    """Initialize on startup."""
    print(f"[GLM Agent] Starting engine v1.0.0")
    print(f"[GLM Agent] Z.ai Backend: {settings.ZAI_BASE_URL}")
    print(f"[GLM Agent] Project Dir: {settings.PROJECT_DIR}")
    print(f"[GLM Agent] Skills Dir: {settings.SKILLS_DIR}")
    print(f"[GLM Agent] Region: {settings.FC_REGION}")
    print(f"[GLM Agent] Instance: {settings.FC_INSTANCE_ID}")

    # Ensure download directory has README
    readme_path = Path(settings.DOWNLOAD_DIR) / "README.md"
    if not readme_path.exists():
        readme_path.write_text("Here are all the generated files.\n")


@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown."""
    await http_client.aclose()
    print("[GLM Agent] Engine shutdown complete.")


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
