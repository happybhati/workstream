"""Tests for configuration loading."""


def test_config_defaults():
    """Config should have sensible defaults even without .env."""
    from config import settings

    assert settings.poll_interval_seconds > 0
    assert settings.dashboard_port > 0


def test_config_env_override(monkeypatch):
    """Config should respect environment variable overrides."""
    monkeypatch.setenv("DASHBOARD_PORT", "9999")
    # Re-import to pick up the new env
    import importlib

    import config

    importlib.reload(config)
    assert config.settings.dashboard_port == 9999
