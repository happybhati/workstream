# ADR 0001: FastAPI with Single-Page HTML Architecture

## Status
Accepted

## Context
Workstream needs a web UI for developers to view PRs, Jira tasks, and AI analysis results. We need to choose a web framework and frontend approach.

## Decision
We use FastAPI as the backend framework and a single `static/index.html` file for the entire frontend, using vanilla JavaScript with no build step.

## Consequences
- **Positive**: Zero frontend build tooling (no npm, webpack, vite). Single file is easy to deploy and modify. FastAPI provides automatic OpenAPI docs and async support.
- **Negative**: Large single HTML file can be harder to navigate. No component reuse. Limited to what vanilla JS can express cleanly.
- **Mitigation**: Use clear section comments and consistent patterns in the HTML file. CSS variables enable theming without a preprocessor.
