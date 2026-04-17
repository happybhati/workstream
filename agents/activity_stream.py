"""Real-time agent activity stream (AOP-compatible event format).

Emits events via SSE in a format compatible with the Agent Observability
Protocol (AOP). External AOP collectors can consume the /api/agents/stream
endpoint directly.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("agents.activity_stream")

_MAX_HISTORY = 100
_event_history: deque[dict] = deque(maxlen=_MAX_HISTORY)
_subscribers: list[asyncio.Queue] = []


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def emit_event(
    event_type: str,
    agent_name: str,
    *,
    category: str = "operation",
    data: dict[str, Any] | None = None,
) -> dict:
    """Emit an AOP-compatible event to all subscribers.

    Categories (AOP-aligned):
      - session: session.started, session.heartbeat, session.ended
      - cognition: thought, goal, decision, uncertainty
      - operation: tool_start, tool_end, agent_spawn, memory
    """
    event = {
        "id": str(uuid.uuid4())[:12],
        "type": event_type,
        "category": category,
        "agent": agent_name,
        "timestamp": _now(),
        "data": data or {},
    }
    _event_history.append(event)
    for q in _subscribers:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass
    return event


def get_recent_events(limit: int = 50) -> list[dict]:
    """Return the most recent events from memory."""
    items = list(_event_history)
    return items[-limit:]


def subscribe() -> asyncio.Queue:
    """Create a subscriber queue for SSE streaming."""
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _subscribers.append(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    """Remove a subscriber queue."""
    try:
        _subscribers.remove(q)
    except ValueError:
        pass
