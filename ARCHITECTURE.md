# Architecture

## System Overview

Workstream is a local-first developer productivity dashboard built on FastAPI. It aggregates data from GitHub, GitLab, and Jira into a single interface, enhanced with AI-powered code review and repository analysis capabilities.

```
┌─────────────────────────────────────────────────┐
│                  Browser UI                      │
│            static/index.html (SPA)               │
└──────────────────┬──────────────────────────────┘
                   │ HTTP/REST
┌──────────────────▼──────────────────────────────┐
│              FastAPI (app.py)                     │
│         uvicorn on port 8080                     │
├──────────┬───────────┬───────────┬──────────────┤
│ Pollers  │ Readiness │  Agents   │ Intelligence │
│pollers.py│ agentic_  │ agents/   │intelligence/ │
│          │readiness/ │           │              │
├──────────┴───────────┴───────────┴──────────────┤
│              Database (database.py)              │
│                SQLite + aiosqlite                │
├─────────────────────────────────────────────────┤
│              External APIs                       │
│   GitHub API │ GitLab API │ Jira API │ AI APIs  │
└─────────────────────────────────────────────────┘
```

## Core Modules

### app.py -- Application Entry Point
The FastAPI application defines all HTTP endpoints, manages the application lifecycle (startup/shutdown), and coordinates background polling. Routes are organized by feature area with section comments.

### config.py -- Configuration
Uses Pydantic `BaseSettings` to load configuration from environment variables and `.env` files. All secrets (API tokens, PATs) flow through this module.

### database.py -- Persistence
Async SQLite database using aiosqlite. Stores PR data, Jira tickets, scan history, intelligence patterns, and agent registry. Schema is auto-created on first run.

### pollers.py -- Data Collection
Background async tasks that periodically fetch data from GitHub, GitLab, and Jira APIs. Runs on a configurable interval (default 300s).

### reviewer.py -- AI Code Review
Multi-provider AI review engine supporting Claude (Anthropic), Gemini (Google), and Ollama (local). Analyzes PR diffs and provides structured feedback.

## Feature Modules

### agentic_readiness/ -- AI Readiness Analyzer
Scans GitHub repositories to assess how well they support AI coding agents. Three-stage pipeline:
1. **scanner.py**: Fetches repo tree, key files, CI config, language data via GitHub API
2. **scorer.py**: Evaluates 5 categories (Agent Config, Documentation, CI/CD, Code Structure, Security) producing a 0-100 score
3. **generator.py**: Produces tool-specific context files (AGENTS.md, CLAUDE.md, etc.) and can create draft PRs

### agents/ -- Agent Ecosystem
Implements three open standards for agent interoperability:
- **MCP** (Model Context Protocol): Discovers local MCP servers from Cursor/Claude config
- **A2A** (Agent-to-Agent): Registers and health-checks A2A protocol agents
- **AOP** (Agent Observability Protocol): Real-time activity streaming

### intelligence/ -- Review Intelligence
Analyzes historical PR review data to extract patterns: common review comments, reviewer preferences, code quality trends. Stored in SQLite for dashboard display.

### mcp_server/ -- MCP Server
Workstream's own MCP server implementation providing tools for Jira queries and GitHub operations to AI agents.

## Frontend Architecture

The entire UI lives in `static/index.html` -- a single-page application using vanilla JavaScript and CSS custom properties for theming (dark/light mode). This avoids build tooling complexity while keeping the tool self-contained. Tabs: My PRs, Assigned, Reviews, Jira, Activity, Intelligence, AI Readiness, Agents.

## Design Decisions

- **Local-first**: No cloud backend; all data stays on the developer's machine
- **Single binary feel**: One `python app.py` command starts everything
- **No frontend build step**: Vanilla JS avoids npm/webpack complexity
- **SQLite over Postgres**: Zero configuration for a personal developer tool
- **Multi-provider AI**: Supports cloud and local LLMs to respect org policies

See `docs/adr/` for formal Architecture Decision Records.
