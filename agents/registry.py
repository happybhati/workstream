"""Agent registry: discovers MCP servers and A2A agents, tracks health."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("agents.registry")

MCP_CONFIG_PATH = Path(
    os.getenv(
        "MCP_CONFIG_PATH",
        str(Path.home() / ".cursor" / "mcp.json"),
    )
)

STATUS_DB_PATH = Path(
    os.getenv(
        "AGENT_REGISTRY_DB_PATH",
        str(Path(__file__).resolve().parent / "agent_status_history.sqlite"),
    )
)

# In-memory registry updated by polling
_registry: dict[str, dict] = {}
_a2a_agents: dict[str, dict] = {}


def _init_status_db_sync() -> None:
    """Create SQLite schema for agent status history and registered agents (idempotent)."""
    STATUS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(STATUS_DB_PATH)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_status_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                status TEXT NOT NULL,
                checked_at TEXT NOT NULL,
                error TEXT,
                source TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_agent_status_history_agent_time
            ON agent_status_history (agent_id, checked_at DESC)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS registered_agents (
                agent_id TEXT PRIMARY KEY,
                base_url TEXT NOT NULL,
                card_json TEXT NOT NULL,
                registered_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _append_status_history_sync(rows: list[tuple[str, str, str, str | None, str]]) -> None:
    """Insert status snapshots (sync; run via asyncio.to_thread)."""
    if not rows:
        return
    _init_status_db_sync()
    conn = sqlite3.connect(STATUS_DB_PATH)
    try:
        conn.executemany(
            """
            INSERT INTO agent_status_history (agent_id, status, checked_at, error, source)
            VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def _query_status_history_sync(agent_id: str, limit: int) -> list[dict[str, Any]]:
    _init_status_db_sync()
    conn = sqlite3.connect(STATUS_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            """
            SELECT agent_id, status, checked_at, error, source
            FROM agent_status_history
            WHERE agent_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (agent_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


async def record_status_history_batch(
    agents: list[dict],
) -> None:
    """Persist one history row per agent from current in-memory state."""
    rows: list[tuple[str, str, str, str | None, str]] = []
    for info in agents:
        aid = str(info.get("id", ""))
        status = str(info.get("status", "unknown"))
        checked = info.get("last_checked") or datetime.now(timezone.utc).isoformat()
        err = info.get("error")
        err_s = str(err) if err else None
        src = str(info.get("source", ""))
        rows.append((aid, status, checked, err_s, src))
    await asyncio.to_thread(_append_status_history_sync, rows)


def get_agent_status_history(agent_id: str, limit: int = 100) -> list[dict[str, Any]]:
    """Return recent status checks for an agent from SQLite."""
    return _query_status_history_sync(agent_id, limit)


def _detect_server_type(server_cfg: dict) -> str:
    if "url" in server_cfg:
        return "remote"
    if "command" in server_cfg:
        return "local"
    return "unknown"


def _extract_server_info(name: str, cfg: dict) -> dict:
    stype = _detect_server_type(cfg)
    info: dict[str, Any] = {
        "id": f"mcp:{name}",
        "name": name,
        "source": "mcp",
        "type": stype,
        "status": "unknown",
        "last_checked": None,
        "last_seen": None,
        "error": None,
        "capabilities": [],
        "metadata": {},
    }
    if stype == "remote":
        info["endpoint"] = cfg.get("url", "")
        info["metadata"]["auth"] = "token" if cfg.get("headers") else "none"
    elif stype == "local":
        cmd = cfg.get("command", "")
        args = cfg.get("args", [])
        pkg = ""
        for a in args:
            if a.startswith("@") or "/" in a:
                pkg = a
                break
        if not pkg and args:
            pkg = args[-1] if not args[-1].startswith("-") else ""
        info["endpoint"] = f"{cmd} {pkg}".strip()
        info["metadata"]["command"] = cmd
        info["metadata"]["args"] = args
        info["metadata"]["cwd"] = cfg.get("cwd", "")
        env = cfg.get("env", {})
        _SECRET_PATTERNS = {"TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"}
        _SECRET_EXACT = {"GITHUB_PAT", "GITLAB_PAT"}
        safe_env = {}
        for k, v in env.items():
            k_up = k.upper()
            if k_up in _SECRET_EXACT or any(p in k_up for p in _SECRET_PATTERNS):
                safe_env[k] = "***"
            else:
                safe_env[k] = v
        info["metadata"]["env"] = safe_env
    return info


def load_mcp_servers() -> dict[str, dict]:
    """Parse mcp.json and return agent info for each server."""
    if not MCP_CONFIG_PATH.exists():
        logger.warning("MCP config not found at %s", MCP_CONFIG_PATH)
        return {}
    try:
        data = json.loads(MCP_CONFIG_PATH.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to read MCP config: %s", exc)
        return {}
    servers = data.get("mcpServers", {})
    result = {}
    for name, cfg in servers.items():
        info = _extract_server_info(name, cfg)
        result[info["id"]] = info
    return result


async def check_local_server_health(info: dict) -> str:
    """Check if a local MCP server process appears to be running."""
    cmd = info.get("metadata", {}).get("command", "")
    args = info.get("metadata", {}).get("args", [])
    if not cmd:
        return "unknown"
    try:
        search_terms = []
        for a in args:
            if a.startswith("@") or ("mcp" in a.lower()) or ("server" in a.lower()):
                search_terms.append(a)
                break
        if not search_terms:
            search_terms = [cmd.split("/")[-1]]
        proc = await asyncio.create_subprocess_exec(
            "pgrep",
            "-f",
            search_terms[0],
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0 and stdout.strip():
            return "running"
        return "stopped"
    except Exception:
        return "unknown"


async def check_remote_server_health(info: dict) -> str:
    """Check if a remote MCP endpoint is reachable."""
    url = info.get("endpoint", "")
    if not url:
        return "unknown"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            if resp.status_code < 500:
                return "running"
            return "error"
    except httpx.ConnectError:
        return "stopped"
    except Exception:
        return "unknown"


async def check_agent_health(info: dict) -> dict:
    """Run health check on an agent and return updated info."""
    now = datetime.now(timezone.utc).isoformat()
    info["last_checked"] = now
    info["error"] = None
    try:
        if info["source"] == "mcp":
            if info["type"] == "local":
                info["status"] = await check_local_server_health(info)
            elif info["type"] == "remote":
                info["status"] = await check_remote_server_health(info)
            else:
                info["status"] = "unknown"
            if info["status"] == "running":
                info["last_seen"] = now
        elif info["source"] == "a2a":
            info["status"] = await _check_a2a_health(info)
            if info["status"] == "running":
                info["last_seen"] = now
        else:
            info["status"] = "unknown"
    except Exception as exc:  # noqa: BLE001 — health probe should not break refresh
        info["status"] = "error"
        info["error"] = str(exc)
        logger.exception("Health check failed for %s", info.get("id"))
    return info


async def _check_a2a_health(info: dict) -> str:
    """Check A2A agent health by fetching agent card."""
    url = info.get("endpoint", "")
    if not url:
        return "unknown"
    try:
        card_url = url.rstrip("/") + "/.well-known/agent-card.json"
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(card_url)
            if resp.status_code == 200:
                return "running"
            return "error"
    except httpx.ConnectError:
        return "stopped"
    except Exception:
        return "unknown"


async def fetch_a2a_agent_card(base_url: str) -> dict | None:
    """Fetch and parse an A2A Agent Card from a URL."""
    card_url = base_url.rstrip("/") + "/.well-known/agent-card.json"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(card_url)
            if resp.status_code != 200:
                return None
            card = resp.json()
            return card
    except Exception as exc:
        logger.error("Failed to fetch A2A agent card from %s: %s", card_url, exc)
        return None


def _save_registered_agent_sync(agent_id: str, base_url: str, card: dict) -> None:
    _init_status_db_sync()
    conn = sqlite3.connect(STATUS_DB_PATH)
    try:
        conn.execute(
            """INSERT OR REPLACE INTO registered_agents (agent_id, base_url, card_json, registered_at)
               VALUES (?, ?, ?, ?)""",
            (agent_id, base_url, json.dumps(card), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def _delete_registered_agent_sync(agent_id: str) -> None:
    _init_status_db_sync()
    conn = sqlite3.connect(STATUS_DB_PATH)
    try:
        conn.execute("DELETE FROM registered_agents WHERE agent_id = ?", (agent_id,))
        conn.commit()
    finally:
        conn.close()


def _load_registered_agents_sync() -> list[tuple[str, dict]]:
    _init_status_db_sync()
    conn = sqlite3.connect(STATUS_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("SELECT base_url, card_json FROM registered_agents")
        rows = cur.fetchall()
        return [(r["base_url"], json.loads(r["card_json"])) for r in rows]
    finally:
        conn.close()


def register_a2a_agent(base_url: str, card: dict) -> dict:
    """Register an A2A agent from its agent card."""
    name = card.get("name", base_url)
    agent_id = f"a2a:{name}"
    skills = card.get("skills", [])
    capabilities = [s.get("name", s.get("id", "")) for s in skills if isinstance(s, dict)]
    info = {
        "id": agent_id,
        "name": name,
        "source": "a2a",
        "type": "remote",
        "status": "running",
        "last_checked": datetime.now(timezone.utc).isoformat(),
        "last_seen": datetime.now(timezone.utc).isoformat(),
        "error": None,
        "endpoint": base_url,
        "capabilities": capabilities,
        "metadata": {
            "description": card.get("description", ""),
            "version": card.get("version", ""),
            "provider": card.get("provider", {}),
            "auth": card.get("auth", {}).get("type", "none") if isinstance(card.get("auth"), dict) else "none",
            "skills_count": len(skills),
            "input_modes": card.get("defaultInputModes", []),
            "output_modes": card.get("defaultOutputModes", []),
        },
    }
    _a2a_agents[agent_id] = info
    _save_registered_agent_sync(agent_id, base_url, card)
    return info


async def register_a2a_agent_from_card_url(agent_card_url: str) -> dict | None:
    """Fetch an Agent Card from a URL and register the agent (base URL derived from card URL)."""
    url = agent_card_url.rstrip("/")
    if url.endswith("/.well-known/agent-card.json"):
        base = url[: -len("/.well-known/agent-card.json")].rstrip("/") or url
    else:
        base = url
    card = await fetch_a2a_agent_card(base)
    if not card:
        return None
    return register_a2a_agent(base, card)


def _register_builtin_a2a_agents() -> None:
    """Auto-register the built-in local A2A agents if not already present."""
    try:
        from agents.a2a_servers import RELEASE_HEALTH_AGENT_CARD, WORKSTREAM_AGENT_CARD
    except ImportError:
        return
    for card in (WORKSTREAM_AGENT_CARD, RELEASE_HEALTH_AGENT_CARD):
        agent_id = f"a2a:{card['name']}"
        if agent_id not in _a2a_agents:
            name = card["name"]
            skills = card.get("skills", [])
            capabilities = [s.get("name", s.get("id", "")) for s in skills if isinstance(s, dict)]
            _a2a_agents[agent_id] = {
                "id": agent_id,
                "name": name,
                "source": "a2a",
                "type": "local",
                "status": "unknown",
                "last_checked": None,
                "last_seen": None,
                "error": None,
                "endpoint": card["url"],
                "capabilities": capabilities,
                "metadata": {
                    "description": card.get("description", ""),
                    "version": card.get("version", ""),
                    "provider": {},
                    "auth": "none",
                    "skills_count": len(skills),
                    "input_modes": card.get("defaultInputModes", []),
                    "output_modes": card.get("defaultOutputModes", []),
                    "builtin": True,
                },
            }


async def refresh_registry() -> list[dict]:
    """Refresh all agent statuses and return the full list."""
    _restore_registered_agents()
    _register_builtin_a2a_agents()
    mcp = load_mcp_servers()
    _registry.clear()
    _registry.update(mcp)
    _registry.update(_a2a_agents)

    task_infos = list(_registry.values())
    tasks = [check_agent_health(info) for info in task_infos]
    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for info, res in zip(task_infos, results):
            if isinstance(res, Exception):
                info["status"] = "error"
                info["error"] = str(res)
                info["last_checked"] = datetime.now(timezone.utc).isoformat()
                logger.error(
                    "Unexpected failure refreshing %s",
                    info.get("id"),
                    exc_info=(type(res), res, res.__traceback__),
                )

    agents = list(_registry.values())
    await record_status_history_batch(agents)
    return agents


def get_all_agents() -> list[dict]:
    """Return current in-memory agent list (call refresh_registry first)."""
    if not _registry:
        _restore_registered_agents()
        _register_builtin_a2a_agents()
        mcp = load_mcp_servers()
        _registry.update(mcp)
        _registry.update(_a2a_agents)
    return list(_registry.values())


def remove_agent(agent_id: str) -> bool:
    """Remove a manually registered agent."""
    if agent_id in _a2a_agents:
        del _a2a_agents[agent_id]
        _registry.pop(agent_id, None)
        _delete_registered_agent_sync(agent_id)
        return True
    return False


def _restore_registered_agents() -> None:
    """Load persisted A2A agents into memory on startup."""
    for base_url, card in _load_registered_agents_sync():
        name = card.get("name", base_url)
        agent_id = f"a2a:{name}"
        if agent_id not in _a2a_agents:
            skills = card.get("skills", [])
            capabilities = [s.get("name", s.get("id", "")) for s in skills if isinstance(s, dict)]
            _a2a_agents[agent_id] = {
                "id": agent_id,
                "name": name,
                "source": "a2a",
                "type": "remote",
                "status": "unknown",
                "last_checked": None,
                "last_seen": None,
                "error": None,
                "endpoint": base_url,
                "capabilities": capabilities,
                "metadata": {
                    "description": card.get("description", ""),
                    "version": card.get("version", ""),
                    "provider": card.get("provider", {}),
                    "auth": card.get("auth", {}).get("type", "none") if isinstance(card.get("auth"), dict) else "none",
                    "skills_count": len(skills),
                    "input_modes": card.get("defaultInputModes", []),
                    "output_modes": card.get("defaultOutputModes", []),
                },
            }
