# AGENTS.md

> Agent guidance for **happybhati/workstream**

## Repository Map

```
workstream/
  app.py                  # FastAPI application entry point (uvicorn server on :8080)
  config.py               # Pydantic settings loading from .env
  database.py             # SQLite async database (aiosqlite)
  pollers.py              # Background polling for GitHub/GitLab/Jira
  reviewer.py             # AI-powered code review (Claude, Gemini, Ollama)
  agentic_readiness/      # AI Readiness scanner, scorer, and file generator
    scanner.py            # GitHub API-based repo analysis
    scorer.py             # 5-category scoring algorithm
    generator.py          # AI-ready file generation + draft PR creation
  agents/                 # Agent ecosystem (MCP, A2A, AOP)
    registry.py           # Agent discovery and health checking
    a2a_servers.py        # Local A2A protocol agents
  intelligence/           # Review Intelligence module
    analyzer.py           # PR review pattern extraction
    db.py                 # Intelligence data persistence
  mcp_server/             # Model Context Protocol server
    server.py             # MCP tool definitions for Jira/GitHub
  static/
    index.html            # Single-page dashboard frontend
  docs/                   # Documentation and screenshots
  bin/                    # Utility scripts
  tests/                  # Test suite
```

## Build & Run Commands

```bash
# Setup
make setup              # One-command install
pip install -r requirements.txt

# Run
make run                # Start dashboard on http://localhost:8080
python app.py           # Direct run

# Test
make test               # Run test suite
python -m pytest tests/ -v

# Lint
make lint               # Run ruff + black check
ruff check .
black --check .
```

## Key Conventions

- **Python 3.12+** with type hints throughout
- **FastAPI** for all HTTP endpoints, async handlers
- **Single-page frontend** -- all UI in `static/index.html` (vanilla JS, CSS variables for theming)
- **SQLite** for local persistence via `database.py`
- **Conventional commits** -- `feat:`, `fix:`, `chore:`, `docs:` prefixes
- **No secrets in code** -- all credentials via `.env` file and `config.py`

## Architecture Decisions

- See `docs/adr/` for Architecture Decision Records
- FastAPI chosen for async support and automatic OpenAPI generation
- SQLite chosen for zero-config local deployment
- Single HTML file avoids build tooling complexity for a developer tool

## Environment Variables

Required in `.env`:
- `GITHUB_PAT` -- GitHub personal access token
- `JIRA_URL`, `JIRA_EMAIL`, `JIRA_TOKEN` -- Jira connection (optional)
- `GITLAB_URL`, `GITLAB_TOKEN` -- GitLab connection (optional)
- `ANTHROPIC_API_KEY` -- For Claude-powered review (optional)
