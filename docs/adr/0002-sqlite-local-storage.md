# ADR 0002: SQLite for Local Storage

## Status
Accepted

## Context
Workstream stores PR data, Jira tickets, scan history, and intelligence patterns. As a local developer tool, we need a database that requires zero configuration.

## Decision
Use SQLite via aiosqlite for all persistent storage.

## Consequences
- **Positive**: No database server to install or configure. Single file database. Excellent read performance for a single-user tool. Async support via aiosqlite.
- **Negative**: Not suitable for multi-user concurrent writes. No network access from other tools.
- **Mitigation**: Workstream is designed as a single-user local tool, so concurrency is not a concern.
