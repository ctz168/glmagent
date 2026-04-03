"""
GLM Agent Engine - Test Suite
Basic tests for the agent engine API.
"""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    """Create an async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.anyio
async def test_health_check(client):
    """Test the health endpoint."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "timestamp" in data


@pytest.mark.anyio
async def test_info(client):
    """Test the info endpoint."""
    response = await client.get("/info")
    assert response.status_code == 200
    data = response.json()
    assert data["engine"] == "GLM Agent Engine"
    assert "version" in data


@pytest.mark.anyio
async def test_list_skills(client):
    """Test listing skills."""
    response = await client.get("/skills")
    assert response.status_code == 200
    data = response.json()
    assert "skills" in data
    assert "count" in data


@pytest.mark.anyio
async def test_create_session(client):
    """Test session creation."""
    response = await client.post(
        "/v1/sessions",
        json={"metadata": {"test": True}},
    )
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert data["status"] == "active"


@pytest.mark.anyio
async def test_get_session(client):
    """Test getting a session."""
    create_resp = await client.post("/v1/sessions", json={"metadata": {}})
    session_id = create_resp.json()["session_id"]

    response = await client.get(f"/v1/sessions/{session_id}")
    assert response.status_code == 200
    assert response.json()["id"] == session_id


@pytest.mark.anyio
async def test_get_nonexistent_session(client):
    """Test getting a nonexistent session returns 404."""
    response = await client.get("/v1/sessions/nonexistent-id")
    assert response.status_code == 404


@pytest.mark.anyio
async def test_delete_session(client):
    """Test deleting a session."""
    create_resp = await client.post("/v1/sessions", json={"metadata": {}})
    session_id = create_resp.json()["session_id"]

    delete_resp = await client.delete(f"/v1/sessions/{session_id}")
    assert delete_resp.status_code == 200

    get_resp = await client.get(f"/v1/sessions/{session_id}")
    assert get_resp.status_code == 404


@pytest.mark.anyio
async def test_list_files(client):
    """Test listing files."""
    response = await client.get("/v1/files")
    assert response.status_code == 200
    data = response.json()
    assert "files" in data
    assert "count" in data


@pytest.mark.anyio
async def test_get_env(client):
    """Test getting environment info."""
    response = await client.get("/v1/env")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)


@pytest.mark.anyio
async def test_tool_execute_nonexistent(client):
    """Test executing a nonexistent tool returns 404."""
    response = await client.post(
        "/v1/tools/execute",
        json={"name": "nonexistent-skill", "arguments": {}},
    )
    assert response.status_code == 404


@pytest.mark.anyio
async def test_tool_execute_example(client):
    """Test executing the example skill."""
    response = await client.post(
        "/v1/tools/execute",
        json={"name": "example-skill", "arguments": {"test": True}},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["tool"] == "example-skill"
    assert data["status"] == "recognized"
