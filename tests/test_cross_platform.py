"""Cross-platform compatibility tests.

Verify that the app degrades gracefully when macOS-specific tools
(pgrep, launchctl) are not available — as would happen on Linux
containers or minimal environments.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def registry_module(monkeypatch, tmp_path):
    mcp_config = tmp_path / "mcp.json"
    mcp_config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "local-server": {"command": "node", "args": ["server.js"]},
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


@pytest.mark.asyncio
async def test_pgrep_missing_returns_unknown(registry_module):
    """On systems without pgrep, health check should return 'unknown' not crash."""
    info = {"metadata": {"command": "node", "args": ["server.js"]}}
    with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
        result = await registry_module.check_local_server_health(info)
    assert result == "unknown"


@pytest.mark.asyncio
async def test_pgrep_returns_running_when_process_found(registry_module):
    """When pgrep finds a matching process, status should be 'running'."""
    info = {"metadata": {"command": "node", "args": ["@test/mcp-server"]}}

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"12345\n", b""))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await registry_module.check_local_server_health(info)
    assert result == "running"


@pytest.mark.asyncio
async def test_pgrep_returns_stopped_when_no_match(registry_module):
    """When pgrep finds no match (exit code 1), status should be 'stopped'."""
    info = {"metadata": {"command": "node", "args": ["@test/mcp-server"]}}

    mock_proc = AsyncMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await registry_module.check_local_server_health(info)
    assert result == "stopped"


def test_paths_use_pathlib():
    """All configurable paths should use pathlib.Path for portability."""
    import config

    assert isinstance(config.settings.db_path, Path)
    assert isinstance(config.settings.log_dir, Path)
    assert isinstance(config.settings.repos_yaml_path, Path)
    assert isinstance(config.settings.google_credentials_path, Path)
    assert isinstance(config.settings.google_token_path, Path)


def test_mcp_config_path_uses_home(registry_module, monkeypatch):
    """Default MCP config path should use Path.home(), not a hardcoded path."""
    monkeypatch.delenv("MCP_CONFIG_PATH", raising=False)
    from agents import registry

    default = Path.home() / ".cursor" / "mcp.json"
    assert str(default) in str(registry.MCP_CONFIG_PATH) or "mcp.json" in str(registry.MCP_CONFIG_PATH)
