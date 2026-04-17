"""Shared fixtures for Workstream tests.

All external API calls are mocked — tests run with zero secrets.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Ensure every test gets isolated paths and no real tokens."""
    monkeypatch.setenv("GITHUB_PAT", "")
    monkeypatch.setenv("GITHUB_USERNAME", "testuser")
    monkeypatch.setenv("GITLAB_PAT", "")
    monkeypatch.setenv("JIRA_URL", "")
    monkeypatch.setenv("JIRA_API_TOKEN", "")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("POLL_INTERVAL", "9999")
    monkeypatch.setenv("AI_CLAUDE_API_KEY", "")
    monkeypatch.setenv("AI_GEMINI_API_KEY", "")


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """Return a path to a temporary database file."""
    return tmp_path / "test.db"
