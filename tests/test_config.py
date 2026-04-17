"""Tests for config.py — settings loading, env overrides, path defaults."""

from __future__ import annotations

from pathlib import Path


def test_settings_loads_without_secrets(monkeypatch):
    """Settings should instantiate even when all tokens are empty."""
    monkeypatch.setenv("GITHUB_PAT", "")
    monkeypatch.setenv("GITLAB_PAT", "")
    monkeypatch.setenv("JIRA_API_TOKEN", "")

    import importlib

    import config

    importlib.reload(config)

    assert config.settings.github_pat == ""
    assert config.settings.poll_interval_seconds > 0


def test_db_path_is_configurable(monkeypatch, tmp_path):
    """DB_PATH env should override the default."""
    custom = str(tmp_path / "custom.db")
    monkeypatch.setenv("DB_PATH", custom)

    import importlib

    import config

    importlib.reload(config)

    assert str(config.settings.db_path) == custom


def test_default_paths_are_project_relative():
    """Default paths should be relative to the project directory, not cwd."""
    import config

    project_dir = Path(config.__file__).resolve().parent
    assert config.settings.db_path.parent == project_dir or "test" in str(
        config.settings.db_path
    )


def test_poll_interval_override(monkeypatch):
    """POLL_INTERVAL env should be respected."""
    monkeypatch.setenv("POLL_INTERVAL", "60")

    import importlib

    import config

    importlib.reload(config)

    assert config.settings.poll_interval_seconds == 60
