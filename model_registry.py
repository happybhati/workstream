"""Model pricing registry with extensible configuration.

Loads default pricing from model_registry.json and allows user overrides
persisted in the main SQLite database.  Adapted from the model-config
pattern in rh-ai-quickstart/ai-observability-summarizer.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

from config import settings

logger = logging.getLogger("dashboard.model_registry")

_REGISTRY_JSON = Path(__file__).resolve().parent / "model_registry.json"

_cache: dict[str, dict] | None = None


def _load_defaults() -> dict[str, dict]:
    try:
        with open(_REGISTRY_JSON) as f:
            data = json.load(f)
        return data.get("models", {})
    except Exception:
        logger.warning("Could not load model_registry.json, using empty defaults")
        return {}


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS model_pricing (
            model_id TEXT PRIMARY KEY,
            provider TEXT NOT NULL DEFAULT '',
            display_name TEXT NOT NULL DEFAULT '',
            cost_input REAL NOT NULL DEFAULT 0.0,
            cost_output REAL NOT NULL DEFAULT 0.0,
            updated_at TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.commit()


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(settings.db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _load_overrides() -> dict[str, dict]:
    try:
        conn = _get_conn()
        _ensure_table(conn)
        rows = conn.execute("SELECT * FROM model_pricing").fetchall()
        conn.close()
        result = {}
        for row in rows:
            result[row["model_id"]] = {
                "provider": row["provider"],
                "display_name": row["display_name"],
                "cost_per_million": {
                    "input": row["cost_input"],
                    "output": row["cost_output"],
                },
            }
        return result
    except Exception:
        logger.debug("Could not load model pricing overrides", exc_info=True)
        return {}


def get_registry() -> dict[str, dict]:
    """Return merged registry: defaults + user overrides."""
    global _cache
    if _cache is not None:
        return _cache
    defaults = _load_defaults()
    overrides = _load_overrides()
    merged = {**defaults, **overrides}
    _cache = merged
    return merged


def invalidate_cache() -> None:
    global _cache
    _cache = None


def get_model_cost(model: str) -> dict[str, float]:
    """Return per-million-token rates for a model, with fuzzy matching."""
    registry = get_registry()

    if model in registry:
        return registry[model]["cost_per_million"]

    for key, entry in registry.items():
        if key in model or model in key:
            return entry["cost_per_million"]

    return {"input": 0.0, "output": 0.0}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate cost in USD from token counts and model pricing."""
    rates = get_model_cost(model)
    return (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000


def list_models() -> list[dict]:
    """Return all models as a list for the API."""
    registry = get_registry()
    result = []
    for model_id, entry in sorted(registry.items()):
        result.append(
            {
                "model_id": model_id,
                "provider": entry.get("provider", ""),
                "display_name": entry.get("display_name", model_id),
                "cost_per_million": entry.get("cost_per_million", {"input": 0, "output": 0}),
            }
        )
    return result


def upsert_model(
    model_id: str,
    provider: str = "",
    display_name: str = "",
    cost_input: float = 0.0,
    cost_output: float = 0.0,
) -> dict:
    """Add or update a model in the user-override table."""
    from datetime import datetime, timezone

    conn = _get_conn()
    _ensure_table(conn)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO model_pricing (model_id, provider, display_name, cost_input, cost_output, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(model_id) DO UPDATE SET
               provider=excluded.provider, display_name=excluded.display_name,
               cost_input=excluded.cost_input, cost_output=excluded.cost_output,
               updated_at=excluded.updated_at""",
        (model_id, provider, display_name or model_id, cost_input, cost_output, now),
    )
    conn.commit()
    conn.close()
    invalidate_cache()
    return {
        "model_id": model_id,
        "provider": provider,
        "display_name": display_name or model_id,
        "cost_per_million": {"input": cost_input, "output": cost_output},
    }


def delete_model(model_id: str) -> bool:
    """Remove a user override (default entries remain from JSON)."""
    conn = _get_conn()
    _ensure_table(conn)
    cursor = conn.execute("DELETE FROM model_pricing WHERE model_id = ?", (model_id,))
    conn.commit()
    conn.close()
    invalidate_cache()
    return cursor.rowcount > 0
