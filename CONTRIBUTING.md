# Contributing to Workstream

## Welcome

Thank you for your interest in contributing to Workstream. We appreciate your time and effort.

To find something to work on, browse the open issues for this repository on GitHub.

## Development Setup

1. **Clone the repository**

   ```bash
   git clone <repository-url>
   cd dashboard
   ```

2. **Create a virtual environment**

   ```bash
   python3 -m venv venv && source venv/bin/activate
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment**

   Copy `.env.example` to `.env` and fill in at minimum `GITHUB_PAT` and `GITHUB_USERNAME`. Add other variables as needed for your setup.

5. **Run the application**

   ```bash
   python app.py
   ```

   Or:

   ```bash
   ./run.sh
   ```

6. **Open the dashboard**

   Visit [http://localhost:8080](http://localhost:8080) in your browser.

## Project Structure

| Path | Purpose |
|------|---------|
| `app.py` | FastAPI application and API routes |
| `config.py` | Environment-based configuration |
| `database.py` | SQLite schema and queries |
| `pollers.py` | Background data fetching from external APIs |
| `reviewer.py` | AI code review engine |
| `static/index.html` | Single-page frontend (HTML, CSS, and JavaScript) |
| `intelligence/` | Historical PR review collection and analysis |
| `agentic_readiness/` | AI readiness scanning, scoring, and file generation |
| `mcp_server/` | Model Context Protocol (MCP) server |
| `bin/workstream` | CLI script for service management |

## Making Changes

- Create a branch from `main`.
- Keep changes focused: one feature or fix per pull request.
- Test locally before submitting.
- Preserve the single-file frontend pattern: `index.html` should contain all HTML, CSS, and JavaScript for the dashboard UI unless there is a documented exception.

## Pull Request Guidelines

- Use a clear title and description so reviewers understand intent and scope.
- Reference any related issues (e.g. `Fixes #123` or `See #456`).
- Include testing notes: what you ran, what you verified, and any manual steps.

## Code Style

- **Python:** Follow existing patterns in the codebase; type hints are encouraged where they add clarity.
- **Frontend:** Vanilla JavaScript; use CSS variables for theming; no build step required.
- **Secrets:** Do not commit credentials or tokens. All sensitive configuration belongs in `.env` (and must never be committed).

## License

By contributing, you agree that your contributions will be licensed under the same terms as the project: **Apache License 2.0**.
