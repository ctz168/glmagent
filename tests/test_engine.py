"""
GLM Agent Engine - Test Suite
Comprehensive tests for the agent engine API endpoints.
"""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app, parse_skill_metadata
from pathlib import Path


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    """Create an async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ============================================================
# Health & Info
# ============================================================

class TestHealthAndInfo:
    """Tests for health check and info endpoints."""

    @pytest.mark.anyio
    async def test_health_check(self, client):
        """Test the health endpoint returns healthy status."""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert data["version"] == "1.0.0"

    @pytest.mark.anyio
    async def test_info(self, client):
        """Test the info endpoint returns engine metadata."""
        response = await client.get("/info")
        assert response.status_code == 200
        data = response.json()
        assert data["engine"] == "GLM Agent Engine"
        assert data["version"] == "1.0.0"
        assert "python" in data
        assert "region" in data
        assert "instance_id" in data
        assert "container_id" in data
        assert "function_name" in data
        assert "function_handler" in data
        assert "memory_size_mb" in data
        assert "skills_count" >= 0
        assert "kata_container" in data
        assert "uptime_seconds" >= 0


# ============================================================
# Skills
# ============================================================

class TestSkills:
    """Tests for skill listing and detail endpoints."""

    @pytest.mark.anyio
    async def test_list_skills(self, client):
        """Test listing skills returns proper format."""
        response = await client.get("/skills")
        assert response.status_code == 200
        data = response.json()
        assert "skills" in data
        assert "count" in data
        assert isinstance(data["skills"], list)

    @pytest.mark.anyio
    async def test_list_skills_includes_example(self, client):
        """Test that example-skill is listed."""
        response = await client.get("/skills")
        data = response.json()
        names = [s["name"] for s in data["skills"]]
        assert "example-skill" in names

    @pytest.mark.anyio
    async def test_skill_detail(self, client):
        """Test getting skill detail by name."""
        response = await client.get("/skills/example-skill")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "example-skill"
        assert "description" in data
        assert "files" in data
        assert isinstance(data["files"], list)

    @pytest.mark.anyio
    async def test_skill_detail_not_found(self, client):
        """Test getting nonexistent skill returns 404."""
        response = await client.get("/skills/nonexistent-skill")
        assert response.status_code == 404


# ============================================================
# Sessions
# ============================================================

class TestSessions:
    """Tests for session management endpoints."""

    @pytest.mark.anyio
    async def test_create_session(self, client):
        """Test session creation with metadata."""
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

    @pytest.mark.anyio
    async def test_get_session(self, client):
        """Test getting a session by ID."""
        create_resp = await client.post("/v1/sessions", json={"metadata": {}})
        session_id = create_resp.json()["session_id"]

        response = await client.get(f"/v1/sessions/{session_id}")
        assert response.status_code == 200
        assert response.json()["id"] == session_id

    @pytest.mark.anyio
    async def test_get_nonexistent_session(self, client):
        """Test getting a nonexistent session returns 404."""
        response = await client.get("/v1/sessions/nonexistent-id")
        assert response.status_code == 404

    @pytest.mark.anyio
    async def test_delete_session(self, client):
        """Test deleting a session."""
        create_resp = await client.post("/v1/sessions", json={"metadata": {}})
        session_id = create_resp.json()["session_id"]

        delete_resp = await client.delete(f"/v1/sessions/{session_id}")
        assert delete_resp.status_code == 200
        assert delete_resp.json()["status"] == "deleted"

        get_resp = await client.get(f"/v1/sessions/{session_id}")
        assert get_resp.status_code == 404

    @pytest.mark.anyio
    async def test_list_sessions(self, client):
        """Test listing all sessions."""
        # Create two sessions
        await client.post("/v1/sessions", json={"metadata": {"seq": 1}})
        await client.post("/v1/sessions", json={"metadata": {"seq": 2}})

        response = await client.get("/v1/sessions")
        assert response.status_code == 200
        data = response.json()
        assert "sessions" in data
        assert "count" in data
        assert data["count"] >= 2


# ============================================================
# Files
# ============================================================

class TestFiles:
    """Tests for file management endpoints."""

    @pytest.mark.anyio
    async def test_list_files(self, client):
        """Test listing files in download directory."""
        response = await client.get("/v1/files")
        assert response.status_code == 200
        data = response.json()
        assert "files" in data
        assert "count" in data
        assert isinstance(data["files"], list)

    @pytest.mark.anyio
    async def test_download_nonexistent_file(self, client):
        """Test downloading a nonexistent file returns 404."""
        response = await client.get("/v1/files/nonexistent-file.txt")
        assert response.status_code == 404

    @pytest.mark.anyio
    async def test_path_traversal_protection(self, client):
        """Test that path traversal attacks are blocked."""
        response = await client.get("/v1/files/../../../etc/passwd")
        assert response.status_code in (403, 404)


# ============================================================
# Tool Execution
# ============================================================

class TestToolExecution:
    """Tests for tool/skill execution endpoints."""

    @pytest.mark.anyio
    async def test_execute_nonexistent_skill(self, client):
        """Test executing a nonexistent skill returns 404."""
        response = await client.post(
            "/v1/tools/execute",
            json={"name": "nonexistent-skill", "arguments": {}},
        )
        assert response.status_code == 404

    @pytest.mark.anyio
    async def test_execute_example_skill(self, client):
        """Test executing the example skill."""
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

    @pytest.mark.anyio
    async def test_execute_skill_without_arguments(self, client):
        """Test executing a skill with no arguments."""
        response = await client.post(
            "/v1/tools/execute",
            json={"name": "example-skill", "arguments": {}},
        )
        assert response.status_code == 200


# ============================================================
# Environment & Config
# ============================================================

class TestEnvironment:
    """Tests for environment and config endpoints."""

    @pytest.mark.anyio
    async def test_get_env(self, client):
        """Test getting safe environment variables."""
        response = await client.get("/v1/env")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        # Should not contain secrets
        assert "ZAI_API_KEY" not in data
        assert "ZAI_TOKEN" not in data

    @pytest.mark.anyio
    async def test_get_config(self, client):
        """Test getting Z.ai config (non-sensitive)."""
        response = await client.get("/v1/config")
        assert response.status_code == 200
        data = response.json()
        assert "base_url" in data
        assert "chat_id" in data
        assert "user_id" in data
        assert "has_token" in data
        # Should not expose actual token
        assert "token" not in data or data.get("token") is None


# ============================================================
# Skill Metadata Parser
# ============================================================

class TestSkillMetadataParser:
    """Tests for the SKILL.md frontmatter parser."""

    def test_parse_with_frontmatter(self, tmp_path):
        """Test parsing SKILL.md with YAML frontmatter."""
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
        """Test parsing SKILL.md without frontmatter (fallback)."""
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
        """Test parsing when SKILL.md does not exist."""
        skill_dir = tmp_path / "empty-skill"
        skill_dir.mkdir()
        meta = parse_skill_metadata(skill_dir)
        assert meta["name"] == "empty-skill"
        assert meta["description"] == ""
