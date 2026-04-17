from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings

_PROJECT_DIR = Path(__file__).resolve().parent


def _csv_list(key: str, default: str = "") -> list[str]:
    raw = os.getenv(key, default)
    return [v.strip() for v in raw.split(",") if v.strip()] if raw else []


class Settings(BaseSettings):
    # --- GitHub ---
    github_pat: str = os.getenv("GITHUB_PAT", "")
    github_username: str = os.getenv("GITHUB_USERNAME", "")

    # --- GitLab ---
    gitlab_pat: str = os.getenv("GITLAB_PAT", "")
    gitlab_url: str = os.getenv("GITLAB_URL", "https://gitlab.com")
    gitlab_username: str = os.getenv("GITLAB_USERNAME", "")

    # --- Jira ---
    jira_url: str = os.getenv("JIRA_URL", "")
    jira_email: str = os.getenv("JIRA_EMAIL", "")
    jira_api_token: str = os.getenv("JIRA_API_TOKEN", "")
    jira_projects: list[str] = _csv_list("JIRA_PROJECTS")
    jira_account_name: str = os.getenv("JIRA_ACCOUNT_NAME", "")
    jira_board_projects: list[str] = _csv_list("JIRA_BOARD_PROJECTS")

    # --- Polling ---
    poll_interval_seconds: int = int(os.getenv("POLL_INTERVAL", "300"))

    # --- Paths (default to project-relative locations) ---
    db_path: Path = Path(os.getenv("DB_PATH", str(_PROJECT_DIR / "data.db")))
    log_dir: Path = Path(os.getenv("LOG_DIR", str(_PROJECT_DIR / "logs")))
    repos_yaml_path: Path = Path(
        os.getenv(
            "REPOS_YAML",
            str(_PROJECT_DIR / "repos.yaml"),
        )
    )

    # --- Google Calendar ---
    google_credentials_path: Path = Path(
        os.getenv(
            "GOOGLE_CREDENTIALS_PATH",
            str(_PROJECT_DIR / "google_credentials.json"),
        )
    )
    google_token_path: Path = Path(
        os.getenv(
            "GOOGLE_TOKEN_PATH",
            str(_PROJECT_DIR / "google_token.json"),
        )
    )
    google_calendar_ids: list[str] = os.getenv("GOOGLE_CALENDAR_IDS", "primary").split(",")

    # --- AI Review Providers (all optional) ---
    ai_ollama_url: str = os.getenv("AI_OLLAMA_URL", "http://localhost:11434")
    ai_ollama_model: str = os.getenv("AI_OLLAMA_MODEL", "llama3")
    ai_claude_api_key: str = os.getenv("AI_CLAUDE_API_KEY", "")
    ai_claude_model: str = os.getenv("AI_CLAUDE_MODEL", "claude-sonnet-4-20250514")
    ai_gemini_api_key: str = os.getenv("AI_GEMINI_API_KEY", "")
    ai_gemini_model: str = os.getenv("AI_GEMINI_MODEL", "gemini-2.0-flash")

    # --- Repo filtering ---
    ignored_repos: list[str] = _csv_list("IGNORED_REPOS")
    intelligence_default_repos: list[str] = _csv_list("INTELLIGENCE_DEFAULT_REPOS")

    # --- Display ---
    display_name: str = os.getenv("DISPLAY_NAME", "")

    model_config = {"env_prefix": "DASHBOARD_"}


settings = Settings()
