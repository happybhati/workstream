"""Tests for agents/registry.py — MCP discovery, A2A registration, health checks."""

from __future__ import annotations

import importlib
import json
from unittest.mock import patch

import pytest


@pytest.fixture
def registry_module(monkeypatch, tmp_path):
    """Reload registry with isolated paths."""
    mcp_config = tmp_path / "mcp.json"
    mcp_config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "test-remote": {"url": "http://localhost:9999/sse"},
                    "test-local": {
                        "command": "npx",
                        "args": ["-y", "@test/mcp-server"],
                    },
                }
            }
        )
    )
    monkeypatch.setenv("MCP_CONFIG_PATH", str(mcp_config))
    monkeypatch.setenv("AGENT_REGISTRY_DB_PATH", str(tmp_path / "agents.sqlite"))

    from agents import registry

    importlib.reload(registry)
    registry.MCP_CONFIG_PATH = mcp_config
    registry.STATUS_DB_PATH = tmp_path / "agents.sqlite"
    registry._registry.clear()
    registry._a2a_agents.clear()
    return registry


def test_load_mcp_servers_parses_config(registry_module):
    servers = registry_module.load_mcp_servers()
    assert "mcp:test-remote" in servers
    assert "mcp:test-local" in servers
    assert servers["mcp:test-remote"]["type"] == "remote"
    assert servers["mcp:test-local"]["type"] == "local"


def test_load_mcp_servers_missing_file(registry_module, tmp_path):
    registry_module.MCP_CONFIG_PATH = tmp_path / "nonexistent.json"
    servers = registry_module.load_mcp_servers()
    assert servers == {}


def test_extract_server_info_masks_secrets(registry_module):
    info = registry_module._extract_server_info(
        "secret-server",
        {
            "command": "node",
            "args": ["server.js"],
            "env": {
                "GITHUB_PAT": "ghp_secret123",
                "API_TOKEN": "tok_secret",
                "NORMAL_VAR": "visible",
            },
        },
    )
    env = info["metadata"]["env"]
    assert env["GITHUB_PAT"] == "***"
    assert env["API_TOKEN"] == "***"
    assert env["NORMAL_VAR"] == "visible"


@pytest.mark.asyncio
async def test_check_local_health_pgrep_not_found(registry_module):
    """When pgrep fails (e.g. not installed), health should return 'unknown'."""
    info = {
        "metadata": {"command": "npx", "args": ["@test/mcp-server"]},
    }
    with patch(
        "asyncio.create_subprocess_exec", side_effect=FileNotFoundError("pgrep")
    ):
        result = await registry_module.check_local_server_health(info)
    assert result == "unknown"


@pytest.mark.asyncio
async def test_check_remote_health_unreachable(registry_module):
    """Unreachable remote server should return 'stopped'."""
    info = {"endpoint": "http://localhost:1/sse"}
    result = await registry_module.check_remote_server_health(info)
    assert result in ("stopped", "unknown")


def test_register_a2a_agent(registry_module):
    card = {
        "name": "test-agent",
        "description": "A test agent",
        "version": "1.0",
        "skills": [{"name": "do-thing", "id": "do-thing"}],
    }
    info = registry_module.register_a2a_agent("http://localhost:5000", card)
    assert info["id"] == "a2a:test-agent"
    assert info["source"] == "a2a"
    assert "do-thing" in info["capabilities"]


def test_remove_agent(registry_module):
    card = {"name": "removable", "skills": []}
    registry_module.register_a2a_agent("http://localhost:5001", card)
    assert registry_module.remove_agent("a2a:removable") is True
    assert registry_module.remove_agent("a2a:removable") is False
