# Copilot Instructions for Workstream

## Language & Framework
- Python 3.12+ with FastAPI
- Use type hints on all function signatures
- Async/await for I/O operations (httpx, aiosqlite)

## Code Style
- Follow PEP 8 and ruff defaults
- Format with black (line length 100)
- Use conventional commit messages: feat:, fix:, docs:, chore:, test:

## Architecture
- All HTTP routes defined in app.py, grouped by feature section
- Business logic in feature modules (agentic_readiness/, agents/, intelligence/)
- Configuration through config.py (Pydantic BaseSettings)
- Database operations in database.py (SQLite)

## Testing
- Tests in tests/ directory using pytest
- Run: python -m pytest tests/ -v

## Key Patterns
- Background tasks use asyncio.create_task in the FastAPI lifespan
- Frontend is vanilla JS in static/index.html (no build step)
- External API calls use httpx.AsyncClient with proper error handling
