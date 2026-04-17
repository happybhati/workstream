# Gemini Agent Guide for Workstream

## Overview

Workstream is a Python/FastAPI developer productivity dashboard. It integrates GitHub, GitLab, Jira, and AI-powered code review into a single local tool.

## Project Layout

The codebase follows a modular Python structure:
- **app.py**: Main FastAPI application with all HTTP routes
- **config.py**: Configuration via Pydantic settings and `.env`
- **database.py**: SQLite persistence layer
- **agentic_readiness/**: AI readiness scanning and file generation
- **agents/**: Agent discovery (MCP, A2A protocols)
- **intelligence/**: PR review pattern analysis
- **static/index.html**: Single-page frontend application

## Development

### Setup
```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Configure API tokens
```

### Run
```bash
python app.py  # http://localhost:8080
```

### Test
```bash
python -m pytest tests/ -v
```

### Lint
```bash
ruff check . && black --check .
```

## Conventions

- Python 3.12+ with type annotations
- Conventional commit messages
- AsyncIO throughout (httpx, aiosqlite)
- No frontend build step -- vanilla JS in single HTML file
