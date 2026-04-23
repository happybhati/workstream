"""Import Claude Code CLI usage data into Workstream AI telemetry.

Reads session transcripts from ~/.claude/projects/ and imports per-request
token usage into the ai_telemetry table. Tracks which sessions have already
been imported to avoid duplicates.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from config import settings

logger = logging.getLogger(__name__)

CLAUDE_DIR = Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_DIR / "projects"

SONNET_4_PRICING = {
    "input": 3.0,
    "output": 15.0,
    "cache_read": 0.30,
    "cache_create": 3.75,
}


def _estimate_cost(usage: dict, model: str = "") -> float:
    pricing = SONNET_4_PRICING
    try:
        from model_registry import get_model_cost

        rates = get_model_cost(model)
        if rates["input"] > 0 or rates["output"] > 0:
            pricing = {
                "input": rates["input"],
                "output": rates["output"],
                "cache_read": rates["input"] * 0.1,
                "cache_create": rates["input"] * 1.25,
            }
    except Exception:
        pass

    inp = usage.get("input_tokens", 0)
    out = usage.get("output_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    cache_create = usage.get("cache_creation_input_tokens", 0)

    return (
        inp * pricing["input"]
        + out * pricing["output"]
        + cache_read * pricing["cache_read"]
        + cache_create * pricing["cache_create"]
    ) / 1_000_000


def _get_imported_sessions(db_path: Path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS claude_code_imported ("
            "  session_id TEXT PRIMARY KEY,"
            "  imported_at TEXT NOT NULL,"
            "  event_count INTEGER DEFAULT 0"
            ")"
        )
        conn.commit()
        rows = conn.execute("SELECT session_id FROM claude_code_imported").fetchall()
        return {r[0] for r in rows}
    finally:
        conn.close()


def _mark_imported(db_path: Path, session_id: str, count: int) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT OR REPLACE INTO claude_code_imported (session_id, imported_at, event_count) VALUES (?, ?, ?)",
            (session_id, datetime.now(timezone.utc).isoformat(), count),
        )
        conn.commit()
    finally:
        conn.close()


def discover_sessions() -> list[dict]:
    """Find all Claude Code session JSONL files."""
    sessions = []
    if not PROJECTS_DIR.exists():
        return sessions

    for project_dir in PROJECTS_DIR.iterdir():
        if not project_dir.is_dir() or project_dir.name.startswith("."):
            continue
        project_name = project_dir.name.replace("-", "/").lstrip("/")

        for jsonl_file in project_dir.glob("*.jsonl"):
            session_id = jsonl_file.stem
            size_mb = jsonl_file.stat().st_size / (1024 * 1024)
            sessions.append(
                {
                    "session_id": session_id,
                    "project": project_name,
                    "path": str(jsonl_file),
                    "size_mb": round(size_mb, 2),
                }
            )

        for sub_dir in project_dir.iterdir():
            if sub_dir.is_dir() and not sub_dir.name.startswith("."):
                for jsonl_file in sub_dir.glob("**/*.jsonl"):
                    session_id = jsonl_file.stem
                    size_mb = jsonl_file.stat().st_size / (1024 * 1024)
                    sessions.append(
                        {
                            "session_id": session_id,
                            "project": project_name,
                            "path": str(jsonl_file),
                            "size_mb": round(size_mb, 2),
                        }
                    )

    return sessions


def parse_session(jsonl_path: str) -> list[dict]:
    """Parse a Claude Code session JSONL into telemetry events."""
    events = []
    path = Path(jsonl_path)
    if not path.exists():
        return events

    for line in path.open():
        try:
            entry = json.loads(line.strip())
        except json.JSONDecodeError:
            continue

        if entry.get("type") != "assistant":
            continue

        msg = entry.get("message", {})
        usage = msg.get("usage")
        if not usage:
            continue

        model = msg.get("model", "claude-sonnet-4-20250514")
        inp = usage.get("input_tokens", 0)
        out = usage.get("output_tokens", 0)
        cache_read = usage.get("cache_read_input_tokens", 0)
        cache_create = usage.get("cache_creation_input_tokens", 0)
        total = inp + out + cache_read + cache_create

        cost = _estimate_cost(usage, model)

        ts = entry.get("timestamp", "")
        if isinstance(ts, (int, float)):
            if ts > 1e12:
                ts = ts / 1000
            created_at = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        elif isinstance(ts, str) and ts:
            created_at = ts
        else:
            created_at = datetime.now(timezone.utc).isoformat()

        events.append(
            {
                "agent_name": "claude-code",
                "operation": "chat",
                "provider": "anthropic",
                "model": model,
                "input_tokens": inp + cache_read + cache_create,
                "output_tokens": out,
                "total_tokens": total,
                "cost_usd": round(cost, 6),
                "latency_ms": 0,
                "feature": "claude-code-cli",
                "status": "success",
                "error": "",
                "metadata": json.dumps(
                    {
                        "cache_read_tokens": cache_read,
                        "cache_create_tokens": cache_create,
                        "raw_input_tokens": inp,
                        "source": "claude-code-import",
                    }
                ),
                "created_at": created_at,
            }
        )

    return events


def import_session(session_id: str, jsonl_path: str) -> dict:
    """Import a single session into the ai_telemetry table."""
    db_path = settings.db_path
    already_imported = _get_imported_sessions(db_path)

    if session_id in already_imported:
        return {"status": "skipped", "reason": "already imported", "session_id": session_id}

    events = parse_session(jsonl_path)
    if not events:
        return {"status": "skipped", "reason": "no usage data", "session_id": session_id}

    conn = sqlite3.connect(str(db_path))
    try:
        for ev in events:
            conn.execute(
                """INSERT INTO ai_telemetry
                   (agent_name, operation, provider, model, input_tokens,
                    output_tokens, total_tokens, cost_usd, latency_ms,
                    feature, status, error, metadata, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ev["agent_name"],
                    ev["operation"],
                    ev["provider"],
                    ev["model"],
                    ev["input_tokens"],
                    ev["output_tokens"],
                    ev["total_tokens"],
                    ev["cost_usd"],
                    ev["latency_ms"],
                    ev["feature"],
                    ev["status"],
                    ev["error"],
                    ev["metadata"],
                    ev["created_at"],
                ),
            )
        conn.commit()
    finally:
        conn.close()

    _mark_imported(db_path, session_id, len(events))

    total_cost = sum(e["cost_usd"] for e in events)
    total_tokens = sum(e["total_tokens"] for e in events)

    return {
        "status": "imported",
        "session_id": session_id,
        "events": len(events),
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost, 4),
    }


def import_all_sessions() -> dict:
    """Discover and import all Claude Code sessions."""
    sessions = discover_sessions()
    results = []
    total_imported = 0
    total_cost = 0.0

    for sess in sessions:
        result = import_session(sess["session_id"], sess["path"])
        result["project"] = sess["project"]
        results.append(result)
        if result["status"] == "imported":
            total_imported += result["events"]
            total_cost += result.get("total_cost_usd", 0)

    return {
        "sessions_found": len(sessions),
        "events_imported": total_imported,
        "total_cost_usd": round(total_cost, 4),
        "details": results,
    }


def get_stats_summary() -> dict:
    """Read the Claude Code stats-cache.json for a quick overview."""
    stats_file = CLAUDE_DIR / "stats-cache.json"
    if not stats_file.exists():
        return {"available": False}

    with open(stats_file) as f:
        data = json.load(f)

    model_usage = data.get("modelUsage", {})
    summary = {
        "available": True,
        "total_sessions": data.get("totalSessions", 0),
        "total_messages": data.get("totalMessages", 0),
        "first_session": data.get("firstSessionDate", ""),
        "models": {},
    }

    for model, usage in model_usage.items():
        summary["models"][model] = {
            "input_tokens": usage.get("inputTokens", 0),
            "output_tokens": usage.get("outputTokens", 0),
            "cache_read_tokens": usage.get("cacheReadInputTokens", 0),
            "cache_create_tokens": usage.get("cacheCreationInputTokens", 0),
        }

    return summary
