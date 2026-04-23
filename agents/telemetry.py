"""Lightweight agent telemetry: tracks AI interactions, token usage, and costs."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("agents.telemetry")

_DB_PATH: Path | None = None


def _get_db_path() -> Path:
    global _DB_PATH
    if _DB_PATH is None:
        _DB_PATH = Path(__file__).resolve().parent / "agent_status_history.sqlite"
    return _DB_PATH


def _init_telemetry_schema() -> None:
    db = _get_db_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_telemetry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT NOT NULL,
                operation TEXT NOT NULL,
                provider TEXT DEFAULT '',
                model TEXT DEFAULT '',
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0.0,
                latency_ms INTEGER DEFAULT 0,
                status TEXT DEFAULT 'success',
                error TEXT DEFAULT '',
                metadata TEXT DEFAULT '{}',
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_telemetry_agent_time
            ON agent_telemetry (agent_name, created_at DESC)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_telemetry_time
            ON agent_telemetry (created_at DESC)
        """)
        conn.commit()
    finally:
        conn.close()


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    from model_registry import estimate_cost as _registry_cost

    return _registry_cost(model, input_tokens, output_tokens)


def record_event(
    agent_name: str,
    operation: str,
    *,
    provider: str = "",
    model: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    latency_ms: int = 0,
    status: str = "success",
    error: str = "",
    metadata: dict | None = None,
    feature: str = "",
) -> None:
    """Record a telemetry event (sync, safe to call from anywhere).

    Writes to both the legacy agent_telemetry DB and the unified
    ai_telemetry table in the main database for backward compatibility.
    """
    _init_telemetry_schema()
    total = input_tokens + output_tokens
    cost = estimate_cost(model, input_tokens, output_tokens)
    now = datetime.now(timezone.utc).isoformat()
    meta_json = json.dumps(metadata or {})

    if not feature:
        feature = agent_name

    try:
        conn = sqlite3.connect(_get_db_path())
        try:
            conn.execute(
                """INSERT INTO agent_telemetry
                   (agent_name, operation, provider, model, input_tokens, output_tokens,
                    total_tokens, cost_usd, latency_ms, status, error, metadata, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    agent_name,
                    operation,
                    provider,
                    model,
                    input_tokens,
                    output_tokens,
                    total,
                    cost,
                    latency_ms,
                    status,
                    error,
                    meta_json,
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.exception("Failed to record telemetry event (legacy)")

    try:
        from config import settings as _settings

        main_conn = sqlite3.connect(str(_settings.db_path))
        try:
            main_conn.execute("""
                CREATE TABLE IF NOT EXISTS ai_telemetry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_name TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    provider TEXT DEFAULT '',
                    model TEXT DEFAULT '',
                    input_tokens INTEGER DEFAULT 0,
                    output_tokens INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    cost_usd REAL DEFAULT 0.0,
                    latency_ms INTEGER DEFAULT 0,
                    feature TEXT DEFAULT '',
                    status TEXT DEFAULT 'success',
                    error TEXT DEFAULT '',
                    metadata TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
            """)
            main_conn.execute(
                """INSERT INTO ai_telemetry
                   (agent_name, operation, provider, model, input_tokens,
                    output_tokens, total_tokens, cost_usd, latency_ms,
                    feature, status, error, metadata, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    agent_name,
                    operation,
                    provider,
                    model,
                    input_tokens,
                    output_tokens,
                    total,
                    cost,
                    latency_ms,
                    feature,
                    status,
                    error,
                    meta_json,
                    now,
                ),
            )
            main_conn.commit()
        finally:
            main_conn.close()
    except Exception:
        logger.debug("Failed to write to unified ai_telemetry table", exc_info=True)


def get_telemetry_summary(days: int = 30) -> dict[str, Any]:
    """Return aggregated telemetry stats."""
    _init_telemetry_schema()
    conn = sqlite3.connect(_get_db_path())
    conn.row_factory = sqlite3.Row
    try:
        cutoff = datetime.now(timezone.utc).isoformat()[:10]
        cur = conn.execute("""
            SELECT
                agent_name,
                COUNT(*) as total_ops,
                SUM(total_tokens) as total_tokens,
                SUM(cost_usd) as total_cost,
                AVG(latency_ms) as avg_latency,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success_count,
                SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as error_count
            FROM agent_telemetry
            GROUP BY agent_name
            ORDER BY total_ops DESC
        """)
        by_agent = {}
        for row in cur.fetchall():
            by_agent[row["agent_name"]] = {
                "total_ops": row["total_ops"],
                "total_tokens": row["total_tokens"] or 0,
                "total_cost": round(row["total_cost"] or 0, 6),
                "avg_latency_ms": round(row["avg_latency"] or 0),
                "success_count": row["success_count"],
                "error_count": row["error_count"],
            }

        cur = conn.execute("""
            SELECT
                COUNT(*) as total_events,
                SUM(total_tokens) as all_tokens,
                SUM(cost_usd) as all_cost,
                AVG(latency_ms) as avg_latency
            FROM agent_telemetry
        """)
        totals_row = cur.fetchone()

        cur = conn.execute("""
            SELECT * FROM agent_telemetry ORDER BY id DESC LIMIT 20
        """)
        recent = [dict(r) for r in cur.fetchall()]

        cur = conn.execute("""
            SELECT
                date(created_at) as day,
                COUNT(*) as ops,
                SUM(total_tokens) as tokens,
                SUM(cost_usd) as cost
            FROM agent_telemetry
            GROUP BY date(created_at)
            ORDER BY day DESC
            LIMIT 30
        """)
        daily = [dict(r) for r in cur.fetchall()]

        return {
            "by_agent": by_agent,
            "totals": {
                "total_events": totals_row["total_events"] if totals_row else 0,
                "total_tokens": totals_row["all_tokens"] or 0 if totals_row else 0,
                "total_cost": round(totals_row["all_cost"] or 0, 6) if totals_row else 0,
                "avg_latency_ms": round(totals_row["avg_latency"] or 0) if totals_row else 0,
            },
            "recent_events": recent,
            "daily_stats": daily,
        }
    finally:
        conn.close()
