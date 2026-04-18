"""Tests for the /api/health endpoint and basic app startup."""

from __future__ import annotations

import importlib

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def app_instance(monkeypatch, tmp_path):
    """Create a fresh FastAPI app with isolated config."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("GITHUB_PAT", "")
    monkeypatch.setenv("POLL_INTERVAL", "999999")

    import config

    importlib.reload(config)
    import app as app_module

    importlib.reload(app_module)
    return app_module.app


@pytest.mark.asyncio
async def test_health_returns_ok(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_index_returns_html(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_config_endpoint_no_secrets(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "jira_url" in data
    for key in ("github_pat", "gitlab_pat", "jira_api_token", "ai_claude_api_key"):
        assert key not in data


@pytest.fixture
def authed_app(monkeypatch, tmp_path):
    """App instance with WORKSTREAM_AUTH_TOKEN enabled."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("GITHUB_PAT", "")
    monkeypatch.setenv("POLL_INTERVAL", "999999")
    monkeypatch.setenv("WORKSTREAM_AUTH_TOKEN", "test-secret-token")

    import config

    importlib.reload(config)
    import app as app_module

    importlib.reload(app_module)
    return app_module.app


@pytest.mark.asyncio
async def test_auth_blocks_without_token(authed_app):
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/config")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_auth_allows_health_without_token(authed_app):
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/health")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_auth_allows_bearer_header(authed_app):
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/config",
            headers={"Authorization": "Bearer test-secret-token"},
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_auth_allows_query_param(authed_app):
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/config?token=test-secret-token")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_auth_rejects_wrong_token(authed_app):
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/config",
            headers={"Authorization": "Bearer wrong-token"},
        )
    assert resp.status_code == 401
