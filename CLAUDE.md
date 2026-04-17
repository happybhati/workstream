# CLAUDE.md

## Setup

Always run `pip install -r requirements.txt` in a virtual environment before working.
Python 3.12+ is required.

## Running

Start the dashboard: `python app.py` (serves on http://localhost:8080).
For development: `make run`.

## Testing

Run tests: `python -m pytest tests/ -v`
Run with coverage: `python -m pytest tests/ --cov=. --cov-report=term`

## Linting

Check: `ruff check .`
Format: `black --check .`
Auto-fix: `ruff check --fix . && black .`

## Project Structure

- `app.py` -- FastAPI app with all route definitions
- `config.py` -- Pydantic settings, loads `.env`
- `database.py` -- SQLite schema and queries (async)
- `agentic_readiness/` -- AI readiness scanner/scorer/generator
- `agents/` -- MCP server discovery, A2A agent registry
- `intelligence/` -- PR review pattern analysis
- `static/index.html` -- Entire frontend (single-page app)

## Conventions

Follow conventional commits: `feat:`, `fix:`, `docs:`, `chore:`, `test:`.
Use type hints on all function signatures.
Keep functions under 50 lines where possible.
All API endpoints go in `app.py` grouped by section comments.
Frontend changes go in `static/index.html` -- JS at the bottom, CSS in `<style>`.

## Key APIs

- `POST /api/readiness/scan` -- Scan a GitHub repo for AI readiness
- `POST /api/readiness/generate` -- Generate AI-ready files
- `POST /api/readiness/create-pr` -- Create a draft PR with generated files
- `GET /api/agents` -- List discovered agents
- `POST /api/agents/refresh` -- Refresh agent health status
- `POST /api/review` -- AI-powered code review
