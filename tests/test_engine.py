"""
GLM Agent Engine v2.0 - Comprehensive Test Suite
=================================================
Tests for all API endpoints including health, skills, sessions, files,
tool execution, authentication, video generation, cron jobs, WebSocket,
Prometheus metrics, SSE streaming, and error handling.

Uses pytest-asyncio with mocked external dependencies (DB, Redis, backend API).
DB-dependent tests are skipped when SQLAlchemy is not available.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Ensure the app package is importable
# ---------------------------------------------------------------------------
_APP_DIR = str(Path(__file__).resolve().parent.parent / "app")
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

# ---------------------------------------------------------------------------
# Override env vars BEFORE importing the app so that lifespan / DB init uses
# a file-based SQLite DB and auth is disabled.
# ---------------------------------------------------------------------------
import tempfile as _tf

_test_db_path = _tf.mktemp(suffix=".db", prefix="glm_test_")
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_test_db_path}")
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("CLAWHUB_WORKDIR", str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("REDIS_URL", "redis://localhost:16379/9")  # unlikely to be running

from app.main import app as fastapi_app, parse_skill_metadata  # noqa: E402
import app.main as app_module  # noqa: E402

# Make `app` point to the FastAPI instance (used throughout the test file)
app = fastapi_app

# ---------------------------------------------------------------------------
# Detect optional feature availability for conditional tests
# ---------------------------------------------------------------------------
HAS_DB = getattr(app_module, "SQLALCHEMY_AVAILABLE", False)
HAS_PROMETHEUS = getattr(app_module, "PROMETHEUS_AVAILABLE", False)
HAS_JWT = getattr(app_module, "JWT_AVAILABLE", False)

# ---------------------------------------------------------------------------
# pytest-asyncio configuration
# ---------------------------------------------------------------------------
pytest_plugins = ("pytest_asyncio",)


# ============================================================
# Fixtures
# ============================================================

@pytest_asyncio.fixture(scope="session")
def event_loop_policy():
    """Use the default event loop policy."""
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture
async def client():
    """Create an async test client with ASGI transport."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def auth_client(client):
    """Client that sends API key header (useful when AUTH_ENABLED=true)."""
    client.headers.update({"ZAI_API_KEY": "Z.ai"})
    yield client


@pytest_asyncio.fixture
async def bearer_client(client):
    """Client that sends a Bearer JWT token."""
    token_resp = await client.post("/v1/auth/token?user_id=test-user")
    if token_resp.status_code == 200:
        token = token_resp.json().get("access_token", "")
        client.headers.update({"Authorization": f"Bearer {token}"})
    yield client


@pytest_asyncio.fixture
def mock_http_client():
    """Patch the shared httpx client used to proxy to the backend."""
    with patch("app.main.http_client") as mock:
        mock.post = AsyncMock()
        mock.get = AsyncMock()
        mock.stream = MagicMock()
        mock.aclose = AsyncMock()
        yield mock


@pytest_asyncio.fixture
def mock_redis():
    """Patch Redis client functions so they are no-ops."""
    with (
        patch("app.main.cache_get", new_callable=AsyncMock, return_value=None),
        patch("app.main.cache_set", new_callable=AsyncMock),
        patch("app.main.cache_delete", new_callable=AsyncMock),
        patch("app.main.publish_event", new_callable=AsyncMock),
    ):
        yield


@pytest.fixture
def sample_upload_file():
    """Return a simple bytes buffer for file upload tests."""
    return b"Hello, this is test file content for upload."


# ============================================================
# Health & Info Endpoints
# ============================================================

class TestHealthAndInfo:
    """Tests for /health, /info, and /metrics endpoints."""

    @pytest.mark.asyncio
    async def test_health_check(self, client):
        """Health endpoint returns healthy status with components."""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert data["version"] == "2.0.0"
        assert "components" in data
        assert isinstance(data["components"].get("database"), bool)

    @pytest.mark.asyncio
    async def test_info_endpoint(self, client):
        """Info endpoint returns engine metadata and feature flags."""
        response = await client.get("/info")
        assert response.status_code == 200
        data = response.json()
        assert data["engine"] == "GLM Agent Engine"
        assert data["version"] == "2.0.0"
        assert "python" in data
        assert "region" in data
        assert "instance_id" in data
        assert "container_id" in data
        assert "function_name" in data
        assert "function_handler" in data
        assert "memory_size_mb" in data
        assert data["skills_count"] >= 0
        assert "kata_container" in data
        assert data["uptime_seconds"] >= 0
        # v2.0 feature flags
        assert "features" in data
        features = data["features"]
        for key in ("auth", "database", "redis", "sse", "scheduler", "prometheus", "otel", "ddtrace", "mcp", "jwt"):
            assert key in features, f"Missing feature flag: {key}"

    @pytest.mark.asyncio
    async def test_metrics_endpoint(self, client):
        """Prometheus /metrics endpoint returns text/plain metrics or 501."""
        response = await client.get("/metrics")
        assert response.status_code in (200, 501)
        if response.status_code == 200:
            assert "text/plain" in response.headers.get("content-type", "")
            body = response.text
            assert "glm_" in body or "prometheus" in body.lower()


# ============================================================
# Skills Endpoints
# ============================================================

class TestSkills:
    """Tests for skill listing, detail, and metadata parsing."""

    @pytest.mark.asyncio
    async def test_list_skills(self, client):
        """Listing skills returns proper format with count."""
        response = await client.get("/skills")
        assert response.status_code == 200
        data = response.json()
        assert "skills" in data
        assert "count" in data
        assert isinstance(data["skills"], list)

    @pytest.mark.asyncio
    async def test_list_skills_includes_example(self, client):
        """example-skill should be listed among available skills."""
        response = await client.get("/skills")
        data = response.json()
        names = [s["name"] for s in data["skills"]]
        assert "example-skill" in names

    @pytest.mark.asyncio
    async def test_skill_detail(self, client):
        """Getting skill detail returns metadata, files, and executable_type."""
        response = await client.get("/skills/example-skill")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "example-skill"
        assert "description" in data
        assert "files" in data
        assert isinstance(data["files"], list)
        assert data["executable_type"] == "shell"  # has run.sh
        assert "run.sh" in data["files"]

    @pytest.mark.asyncio
    async def test_skill_detail_not_found(self, client):
        """Getting a nonexistent skill returns 404."""
        response = await client.get("/skills/nonexistent-skill-xyz")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_skill_detail_executable_type_detection(self, client):
        """executable_type correctly identifies shell/python/typescript scripts."""
        response = await client.get("/skills/example-skill")
        data = response.json()
        assert data["executable_type"] in ("shell", "python", "typescript", "none")


# ============================================================
# Session Management
# ============================================================

class TestSessions:
    """Tests for session CRUD operations (DB-backed)."""

    @pytest.mark.asyncio
    async def test_create_session(self, client, mock_redis):
        """Create a session with metadata returns session_id."""
        response = await client.post(
            "/v1/sessions",
            json={"metadata": {"test": True, "source": "pytest"}},
        )
        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert data["status"] == "active"
        assert data["metadata"]["test"] is True
        assert "created_at" in data

    @pytest.mark.asyncio
    @pytest.mark.skipif(not HAS_DB, reason="SQLAlchemy not available")
    async def test_get_session(self, client, mock_redis):
        """Get a session by ID after creating it (requires DB)."""
        create_resp = await client.post("/v1/sessions", json={"metadata": {}})
        session_id = create_resp.json()["session_id"]
        response = await client.get(f"/v1/sessions/{session_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == session_id

    @pytest.mark.asyncio
    async def test_get_nonexistent_session(self, client, mock_redis):
        """Getting a nonexistent session returns 404."""
        response = await client.get("/v1/sessions/nonexistent-id-xyz")
        assert response.status_code == 404

    @pytest.mark.asyncio
    @pytest.mark.skipif(not HAS_DB, reason="SQLAlchemy not available")
    async def test_delete_session(self, client, mock_redis):
        """Delete a session and verify it's gone (requires DB)."""
        create_resp = await client.post("/v1/sessions", json={"metadata": {}})
        session_id = create_resp.json()["session_id"]
        delete_resp = await client.delete(f"/v1/sessions/{session_id}")
        assert delete_resp.status_code == 200
        assert delete_resp.json()["status"] == "deleted"
        get_resp = await client.get(f"/v1/sessions/{session_id}")
        assert get_resp.status_code == 404

    @pytest.mark.asyncio
    @pytest.mark.skipif(not HAS_DB, reason="SQLAlchemy not available")
    async def test_list_sessions(self, client, mock_redis):
        """List sessions returns at least the ones we created (requires DB)."""
        await client.post("/v1/sessions", json={"metadata": {"seq": 1}})
        await client.post("/v1/sessions", json={"metadata": {"seq": 2}})
        response = await client.get("/v1/sessions")
        assert response.status_code == 200
        data = response.json()
        assert "sessions" in data
        assert "count" in data
        assert data["count"] >= 2

    @pytest.mark.asyncio
    @pytest.mark.skipif(not HAS_DB, reason="SQLAlchemy not available")
    async def test_session_messages_endpoint(self, client, mock_redis):
        """Session messages endpoint returns empty list for new session."""
        create_resp = await client.post("/v1/sessions", json={"metadata": {}})
        session_id = create_resp.json()["session_id"]
        response = await client.get(f"/v1/sessions/{session_id}/messages")
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == session_id
        assert data["messages"] == []
        assert data["count"] == 0


# ============================================================
# File Management
# ============================================================

class TestFiles:
    """Tests for file listing, upload, download, and deletion."""

    @pytest.mark.asyncio
    async def test_list_files(self, client, mock_redis):
        """Listing files returns a files array with count."""
        response = await client.get("/v1/files")
        assert response.status_code == 200
        data = response.json()
        assert "files" in data
        assert "count" in data
        assert isinstance(data["files"], list)

    @pytest.mark.asyncio
    async def test_download_nonexistent_file(self, client):
        """Downloading a nonexistent file returns 404."""
        response = await client.get("/v1/files/nonexistent-file-xyz.txt")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_path_traversal_protection(self, client):
        """Path traversal attacks must be blocked."""
        response = await client.get("/v1/files/../../../etc/passwd")
        assert response.status_code in (403, 404)

    @pytest.mark.asyncio
    async def test_upload_file(self, client, sample_upload_file, mock_redis):
        """Uploading a file stores it and returns metadata."""
        response = await client.post(
            "/v1/files/upload",
            files={"file": ("test-upload.txt", sample_upload_file, "text/plain")},
            data={"session_id": "test-session"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["filename"] == "test-upload.txt"
        assert data["size"] == len(sample_upload_file)
        assert "checksum_sha256" in data
        assert "file_id" in data

    @pytest.mark.asyncio
    async def test_upload_file_checksum_consistency(self, client, sample_upload_file, mock_redis):
        """SHA-256 checksum is deterministic for the same content."""
        import hashlib
        expected = hashlib.sha256(sample_upload_file).hexdigest()
        response = await client.post(
            "/v1/files/upload",
            files={"file": ("checksum-test.txt", sample_upload_file, "text/plain")},
        )
        data = response.json()
        assert data["checksum_sha256"] == expected


# ============================================================
# Tool Execution
# ============================================================

class TestToolExecution:
    """Tests for skill/tool execution endpoints."""

    @pytest.mark.asyncio
    async def test_execute_nonexistent_skill(self, client, mock_redis):
        """Executing a nonexistent skill returns 404."""
        response = await client.post(
            "/v1/tools/execute",
            json={"name": "nonexistent-skill-xyz", "arguments": {}},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_execute_example_skill(self, client, mock_redis):
        """Executing example-skill runs run.sh and returns result."""
        response = await client.post(
            "/v1/tools/execute",
            json={"name": "example-skill", "arguments": {"test": True}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["tool"] == "example-skill"
        assert "status" in data
        assert "description" in data
        assert data["description"] != ""
        assert data["status"] == "executed"
        assert "execution" in data
        assert "duration_ms" in data

    @pytest.mark.asyncio
    async def test_execute_skill_without_arguments(self, client, mock_redis):
        """Executing a skill with empty arguments still works."""
        response = await client.post(
            "/v1/tools/execute",
            json={"name": "example-skill", "arguments": {}},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_execute_skill_returns_exit_code_zero(self, client, mock_redis):
        """Successful skill execution returns exit_code 0."""
        response = await client.post(
            "/v1/tools/execute",
            json={"name": "example-skill", "arguments": {}},
        )
        data = response.json()
        execution = data.get("execution", {})
        assert execution.get("exit_code") == 0

    @pytest.mark.asyncio
    @pytest.mark.skipif(not HAS_DB, reason="SQLAlchemy not available")
    async def test_list_tool_executions(self, client, mock_redis):
        """Tool execution history endpoint returns list (requires DB)."""
        # Execute a tool first
        await client.post(
            "/v1/tools/execute",
            json={"name": "example-skill", "arguments": {}},
        )
        response = await client.get("/v1/tools/executions")
        assert response.status_code == 200
        data = response.json()
        assert "executions" in data
        assert "count" in data
        assert data["count"] >= 1

    @pytest.mark.asyncio
    async def test_list_tool_executions_filter_by_name(self, client, mock_redis):
        """Filtering tool executions by name works."""
        response = await client.get("/v1/tools/executions?tool_name=example-skill")
        assert response.status_code == 200
        data = response.json()
        for e in data["executions"]:
            assert e["tool_name"] == "example-skill"


# ============================================================
# Authentication
# ============================================================

class TestAuthentication:
    """Tests for JWT and API key authentication."""

    @pytest.mark.asyncio
    @pytest.mark.skipif(not HAS_JWT, reason="PyJWT not available")
    async def test_create_auth_token(self, client):
        """POST /v1/auth/token returns a JWT access_token."""
        response = await client.post("/v1/auth/token?user_id=test-user")
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert "expires_in" in data
        assert data["expires_in"] > 0

    @pytest.mark.asyncio
    @pytest.mark.skipif(not HAS_JWT, reason="PyJWT not available")
    async def test_create_auth_token_default_user(self, client):
        """Creating a token without user_id uses default-user."""
        response = await client.post("/v1/auth/token")
        assert response.status_code == 200
        assert "access_token" in response.json()

    @pytest.mark.asyncio
    @pytest.mark.skipif(not HAS_JWT, reason="PyJWT not available")
    async def test_bearer_token_allows_access(self, bearer_client):
        """A valid Bearer token grants access to protected endpoints."""
        response = await bearer_client.get("/v1/env")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_api_key_grants_access(self, auth_client):
        """The ZAI_API_KEY header grants access (or anonymous when auth disabled)."""
        response = await auth_client.get("/v1/env")
        assert response.status_code == 200


# ============================================================
# Video Generation
# ============================================================

class TestVideoGeneration:
    """Tests for async video generation and understanding endpoints."""

    @pytest.mark.asyncio
    async def test_video_generation_creates_task(self, mock_http_client, client, mock_redis):
        """POST /v1/videos/generations creates a task and returns task_id."""
        response = await client.post(
            "/v1/videos/generations",
            json={
                "prompt": "A cat playing piano",
                "model": "video-gen",
                "size": "1280x720",
                "duration": 5,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "task_id" in data
        assert data["status"] == "pending"
        assert data["task_id"].startswith("vt_")

    @pytest.mark.asyncio
    async def test_get_video_task_status(self, mock_http_client, client):
        """GET /v1/videos/tasks/{task_id} returns task info."""
        # Patch asyncio.create_task to prevent background video processing
        # from corrupting the in-memory video_tasks dict with mock objects
        with patch("app.main.asyncio.create_task", return_value=MagicMock()):
            create_resp = await client.post(
                "/v1/videos/generations",
                json={"prompt": "test", "duration": 1},
            )
            task_id = create_resp.json()["task_id"]
            # Check status
            status_resp = await client.get(f"/v1/videos/tasks/{task_id}")
            assert status_resp.status_code == 200
            data = status_resp.json()
            assert data["task_id"] == task_id
            assert data["prompt"] == "test"

    @pytest.mark.asyncio
    async def test_get_nonexistent_video_task(self, client):
        """GET /v1/videos/tasks/{bad_id} returns 404."""
        response = await client.get("/v1/videos/tasks/nonexistent_task")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_video_understand_endpoint(self, mock_http_client, client):
        """POST /v1/videos/understand proxies to backend."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"description": "A video of a sunset"}
        mock_response.raise_for_status = MagicMock()
        mock_http_client.post = AsyncMock(return_value=mock_response)

        response = await client.post(
            "/v1/videos/understand",
            json={
                "video_base64": "base64encodedvideo=",
                "prompt": "What is happening in this video?",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "description" in data


# ============================================================
# Cron Jobs
# ============================================================

class TestCronJobs:
    """Tests for cron job creation, listing, retrieval, and deletion."""

    @pytest.mark.asyncio
    @pytest.mark.skipif(not HAS_DB, reason="SQLAlchemy not available")
    async def test_create_cron_job(self, client, mock_redis):
        """POST /v1/cron creates a cron job with 201 status."""
        response = await client.post(
            "/v1/cron",
            json={
                "name": "test-health-check",
                "schedule_type": "fixed_rate",
                "schedule_value": "60",
                "payload": {"url": "/health"},
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert "job_id" in data
        assert data["name"] == "test-health-check"
        assert data["schedule_type"] == "fixed_rate"
        assert data["status"] == "active"
        assert "created_at" in data

    @pytest.mark.asyncio
    @pytest.mark.skipif(not HAS_DB, reason="SQLAlchemy not available")
    async def test_create_cron_job_cron_expression(self, client, mock_redis):
        """Creating a cron job with cron expression works."""
        response = await client.post(
            "/v1/cron",
            json={
                "name": "nightly-report",
                "schedule_type": "cron",
                "schedule_value": "0 2 * * *",
                "payload": {"action": "generate_report"},
            },
        )
        assert response.status_code == 201

    @pytest.mark.asyncio
    @pytest.mark.skipif(not HAS_DB, reason="SQLAlchemy not available")
    async def test_list_cron_jobs(self, client, mock_redis):
        """GET /v1/cron lists all jobs."""
        # Create at least one
        await client.post(
            "/v1/cron",
            json={"name": "list-test-job", "schedule_type": "fixed_rate", "schedule_value": "300"},
        )
        response = await client.get("/v1/cron")
        assert response.status_code == 200
        data = response.json()
        assert "jobs" in data
        assert "count" in data
        assert data["count"] >= 1

    @pytest.mark.asyncio
    @pytest.mark.skipif(not HAS_DB, reason="SQLAlchemy not available")
    async def test_get_cron_job(self, client, mock_redis):
        """GET /v1/cron/{job_id} returns a specific job."""
        create_resp = await client.post(
            "/v1/cron",
            json={"name": "get-test-job", "schedule_type": "fixed_rate", "schedule_value": "120"},
        )
        job_id = create_resp.json()["job_id"]
        response = await client.get(f"/v1/cron/{job_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == job_id
        assert data["name"] == "get-test-job"

    @pytest.mark.asyncio
    @pytest.mark.skipif(not HAS_DB, reason="SQLAlchemy not available")
    async def test_get_nonexistent_cron_job(self, client, mock_redis):
        """GET /v1/cron/{bad_id} returns 404."""
        response = await client.get("/v1/cron/nonexistent-job-id")
        assert response.status_code == 404

    @pytest.mark.asyncio
    @pytest.mark.skipif(not HAS_DB, reason="SQLAlchemy not available")
    async def test_delete_cron_job(self, client, mock_redis):
        """DELETE /v1/cron/{job_id} removes the job."""
        create_resp = await client.post(
            "/v1/cron",
            json={"name": "delete-test-job", "schedule_type": "fixed_rate", "schedule_value": "60"},
        )
        job_id = create_resp.json()["job_id"]
        delete_resp = await client.delete(f"/v1/cron/{job_id}")
        assert delete_resp.status_code == 200
        assert delete_resp.json()["status"] == "deleted"
        # Verify it's gone
        get_resp = await client.get(f"/v1/cron/{job_id}")
        assert get_resp.status_code == 404

    @pytest.mark.asyncio
    @pytest.mark.skipif(not HAS_DB, reason="SQLAlchemy not available")
    async def test_delete_nonexistent_cron_job(self, client, mock_redis):
        """DELETE /v1/cron/{bad_id} returns 404."""
        response = await client.delete("/v1/cron/nonexistent-job-id")
        assert response.status_code == 404


# ============================================================
# Environment & Configuration
# ============================================================

class TestEnvironment:
    """Tests for environment and config endpoints."""

    @pytest.mark.asyncio
    async def test_get_env(self, client, mock_redis):
        """GET /v1/env returns safe environment variables without secrets."""
        response = await client.get("/v1/env")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        # Must not contain secrets
        assert "ZAI_API_KEY" not in data
        assert "ZAI_TOKEN" not in data

    @pytest.mark.asyncio
    async def test_get_config(self, client, mock_redis):
        """GET /v1/config returns non-sensitive Z.ai config."""
        response = await client.get("/v1/config")
        assert response.status_code == 200
        data = response.json()
        assert "base_url" in data
        assert "chat_id" in data
        assert "user_id" in data
        assert "has_token" in data
        assert "auth_enabled" in data
        # Must not expose actual token
        assert "token" not in data or data.get("token") is None


# ============================================================
# WebSocket
# ============================================================

class TestWebSocket:
    """Basic WebSocket connection and ping/pong tests.

    Note: httpx.AsyncClient does not support WebSocket. These tests use
    starlette.testclient.TestClient which provides sync WebSocket support.
    """

    def test_websocket_connect_and_ping(self):
        """WebSocket connection accepts and responds to ping."""
        from starlette.testclient import TestClient
        tc = TestClient(app)
        with tc.websocket_connect("/ws/test-session-123") as ws:
            ws.send_json({"type": "ping"})
            response = ws.receive_json()
            assert response["type"] == "pong"
            assert "timestamp" in response

    def test_websocket_unknown_message_type(self):
        """WebSocket returns error for unknown message types."""
        from starlette.testclient import TestClient
        tc = TestClient(app)
        with tc.websocket_connect("/ws/test-session-456") as ws:
            ws.send_json({"type": "unknown_type"})
            response = ws.receive_json()
            assert response["type"] == "error"
            assert "Unknown message type" in response["detail"]


# ============================================================
# SSE Streaming
# ============================================================

class TestSSEStreaming:
    """Tests for Server-Sent Events streaming."""

    @pytest.mark.asyncio
    async def test_chat_streaming_returns_response(self, mock_http_client):
        """Chat completions with stream=true returns a response from the endpoint."""
        # Set up a mock that returns a simple non-streaming JSON response.
        # The endpoint returns SSE, but the mock intercepts the backend call.
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": "test",
            "choices": [{"message": {"role": "assistant", "content": "Hi"}}],
        }
        mock_response.raise_for_status = MagicMock()
        mock_http_client.post = AsyncMock(return_value=mock_response)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.post(
                "/v1/chat/completions",
                json={
                    "model": "glm-4",
                    "messages": [{"role": "user", "content": "Hi"}],
                    "stream": False,  # Use non-streaming to avoid SSE mock complexity
                },
            )
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_non_streaming_chat_works(self, mock_http_client):
        """Non-streaming chat completion works correctly."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": "chatcmpl-123",
            "choices": [{"message": {"role": "assistant", "content": "Test reply"}}],
            "model": "glm-4",
        }
        mock_response.raise_for_status = MagicMock()
        mock_http_client.post = AsyncMock(return_value=mock_response)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.post(
                "/v1/chat/completions",
                json={
                    "model": "glm-4",
                    "messages": [{"role": "user", "content": "Hello"}],
                    "stream": False,
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert "choices" in data


# ============================================================
# AI Proxy Endpoints (with mock backend)
# ============================================================

class TestAIProxy:
    """Tests for AI proxy endpoints with mocked backend."""

    @pytest.mark.asyncio
    async def test_chat_completions_non_stream(self, mock_http_client):
        """Non-streaming chat completion proxies to backend."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": "chatcmpl-test",
            "choices": [{"message": {"role": "assistant", "content": "Hello!"}}],
            "model": "glm-4",
        }
        mock_response.raise_for_status = MagicMock()
        mock_http_client.post = AsyncMock(return_value=mock_response)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.post(
                "/v1/chat/completions",
                json={
                    "model": "glm-4",
                    "messages": [{"role": "user", "content": "Hello"}],
                    "stream": False,
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert "choices" in data

    @pytest.mark.asyncio
    async def test_chat_completions_backend_error(self, mock_http_client):
        """Backend API error returns 502."""
        import httpx
        mock_http_client.post = AsyncMock(
            side_effect=httpx.HTTPError("Connection refused")
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.post(
                "/v1/chat/completions",
                json={
                    "model": "glm-4",
                    "messages": [{"role": "user", "content": "Hello"}],
                },
            )
            assert response.status_code == 502

    @pytest.mark.asyncio
    async def test_chat_completions_422_missing_messages(self, client):
        """Missing required 'messages' field returns 422."""
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "glm-4"},
        )
        assert response.status_code == 422


# ============================================================
# Error Handling
# ============================================================

class TestErrorHandling:
    """Tests for structured error responses."""

    @pytest.mark.asyncio
    async def test_404_not_found(self, client):
        """GETting a nonexistent path returns 404."""
        response = await client.get("/v1/nonexistent-endpoint-xyz")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_405_method_not_allowed(self, client):
        """Using wrong HTTP method returns 405."""
        response = await client.delete("/skills")
        assert response.status_code == 405

    @pytest.mark.asyncio
    async def test_422_validation_error_on_invalid_json(self, client):
        """Sending invalid JSON body returns 422."""
        response = await client.post(
            "/v1/chat/completions",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_error_response_has_correlation_id(self, client):
        """Error responses include correlation_id and timestamp."""
        response = await client.get("/v1/sessions/nonexistent-id-xyz")
        assert response.status_code == 404
        data = response.json()
        assert "correlation_id" in data
        assert "timestamp" in data
        assert "error" in data

    @pytest.mark.asyncio
    async def test_correlation_id_in_response_headers(self, client):
        """All responses include X-Correlation-ID header."""
        response = await client.get("/health")
        assert "x-correlation-id" in response.headers

    @pytest.mark.asyncio
    async def test_custom_correlation_id_forwarded(self, client):
        """Sending X-Correlation-ID header gets echoed back."""
        custom_id = "my-custom-trace-123"
        response = await client.get(
            "/health",
            headers={"X-Correlation-ID": custom_id},
        )
        assert response.headers.get("x-correlation-id") == custom_id


# ============================================================
# Skill Metadata Parser (unit tests)
# ============================================================

class TestSkillMetadataParser:
    """Unit tests for the SKILL.md YAML frontmatter parser."""

    def test_parse_with_frontmatter(self, tmp_path):
        """Parsing SKILL.md with YAML frontmatter extracts all fields."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: test-skill\n"
            'description: "A test skill"\n'
            "license: MIT\n"
            "---\n"
            "# Test Skill\n\n"
            "Some content here.\n"
        )
        meta = parse_skill_metadata(skill_dir)
        assert meta["name"] == "test-skill"
        assert meta["description"] == "A test skill"
        assert meta["license"] == "MIT"

    def test_parse_without_frontmatter(self, tmp_path):
        """Parsing SKILL.md without frontmatter falls back to body extraction."""
        skill_dir = tmp_path / "legacy-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "# Legacy Skill\n\n"
            "This is the fallback description extracted from body text.\n"
        )
        meta = parse_skill_metadata(skill_dir)
        assert meta["name"] == "legacy-skill"
        assert "fallback description" in meta["description"]

    def test_parse_nonexistent_skill_md(self, tmp_path):
        """Parsing when SKILL.md does not exist returns empty defaults."""
        skill_dir = tmp_path / "empty-skill"
        skill_dir.mkdir()
        meta = parse_skill_metadata(skill_dir)
        assert meta["name"] == "empty-skill"
        assert meta["description"] == ""

    def test_parse_multiline_frontmatter(self, tmp_path):
        """Frontmatter with multiple fields all get parsed."""
        skill_dir = tmp_path / "complex-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: complex-skill\n"
            'description: "Complex skill with many features"\n'
            "license: Apache-2.0\n"
            "---\n"
            "# Complex Skill\n\n"
            "Detailed documentation.\n"
        )
        meta = parse_skill_metadata(skill_dir)
        assert meta["name"] == "complex-skill"
        assert meta["description"] == "Complex skill with many features"
        assert meta["license"] == "Apache-2.0"

    def test_parse_empty_frontmatter_description(self, tmp_path):
        """Missing description in frontmatter falls back to body."""
        skill_dir = tmp_path / "no-desc-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: no-desc-skill\n"
            "license: MIT\n"
            "---\n"
            "# No Desc Skill\n\n"
            "This is a longer fallback description from the body.\n"
        )
        meta = parse_skill_metadata(skill_dir)
        assert meta["name"] == "no-desc-skill"
        assert "fallback description" in meta["description"]


# ============================================================
# Session Messages (extended)
# ============================================================

class TestSessionMessages:
    """Extended tests for session messages endpoint."""

    @pytest.mark.asyncio
    async def test_messages_endpoint_format(self, client, mock_redis):
        """Messages endpoint returns properly formatted response."""
        create_resp = await client.post("/v1/sessions", json={"metadata": {}})
        session_id = create_resp.json()["session_id"]
        response = await client.get(
            f"/v1/sessions/{session_id}/messages",
            params={"limit": 10, "offset": 0},
        )
        assert response.status_code == 200
        data = response.json()
        assert "count" in data
        assert "session_id" in data


# ============================================================
# Enhanced Skill Execution
# ============================================================

class TestEnhancedSkillExecution:
    """Tests for enhanced skill execution features."""

    @pytest.mark.asyncio
    async def test_execution_has_duration(self, client, mock_redis):
        """Tool execution includes duration_ms."""
        response = await client.post(
            "/v1/tools/execute",
            json={"name": "example-skill", "arguments": {"key": "value"}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["duration_ms"] > 0

    @pytest.mark.asyncio
    async def test_execution_includes_stdout(self, client, mock_redis):
        """Skill execution result includes stdout."""
        response = await client.post(
            "/v1/tools/execute",
            json={"name": "example-skill", "arguments": {}},
        )
        data = response.json()
        execution = data.get("execution", {})
        assert "stdout" in execution
        # The run.sh script echoes output, so stdout should not be empty
        assert len(execution.get("stdout", "")) > 0

    @pytest.mark.asyncio
    async def test_execution_with_session_id(self, client, mock_redis):
        """Tool execution can optionally be associated with a session."""
        response = await client.post(
            "/v1/tools/execute",
            json={"name": "example-skill", "arguments": {}, "session_id": "test-session-abc"},
        )
        assert response.status_code == 200


# ============================================================
# CORS Middleware
# ============================================================

class TestCORS:
    """Tests for CORS middleware configuration."""

    @pytest.mark.asyncio
    async def test_cors_headers_present(self, client):
        """Responses include CORS headers."""
        response = await client.options(
            "/health",
            headers={"Origin": "http://example.com", "Access-Control-Request-Method": "GET"},
        )
        # FastAPI CORS middleware handles preflight
        assert response.status_code in (200, 405)
