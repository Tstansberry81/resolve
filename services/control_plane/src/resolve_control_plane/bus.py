"""In-process event bus. Every emit persists to agent_events (Supabase) and
fans out to live SSE subscribers in the exact AgentEvent shape the dashboard
consumes — swapping the mock engine for this feed changes no components."""

from __future__ import annotations

import asyncio
import itertools
import time
from typing import Any

import anyio

from . import store

_subscribers: set[asyncio.Queue] = set()
_seq = itertools.count(1)
_recent: list[dict[str, Any]] = []
MAX_RECENT = 80

# orb state lives here so snapshot and SSE agree
orb: dict[str, str] = {"state": "idle", "caption": "Sonnet standing by"}
active_nodes: list[str] = []


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _subscribers.discard(q)


def _fanout(msg: dict[str, Any]) -> None:
    for q in list(_subscribers):
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            _subscribers.discard(q)


async def emit(
    actor: str,
    type_: str,
    summary: str,
    *,
    detail: str | None = None,
    level: str = "info",
    edge: dict[str, str] | None = None,
    goal_id: str | None = None,
) -> None:
    event = {
        "id": next(_seq),
        "ts": int(time.time() * 1000),
        "goalId": goal_id,
        "type": type_,
        "actor": actor,
        "summary": summary,
        "detail": detail,
        "level": level,
        "edge": edge,
    }
    _recent.append(event)
    del _recent[:-MAX_RECENT]
    _fanout({"kind": "event", "event": event})
    # persist without blocking the loop; goal_id only when it's a real uuid
    row = {
        "event_type": type_,
        "actor": actor,
        "payload": {"summary": summary, "detail": detail, "level": level, "edge": edge},
    }
    if goal_id and len(goal_id) == 36:
        row["goal_id"] = goal_id
    try:
        await anyio.to_thread.run_sync(lambda: store.insert("agent_events", row))
    except Exception:
        pass  # never let persistence kill the feed


async def set_orb(state: str, caption: str, nodes: list[str] | None = None) -> None:
    orb["state"] = state
    orb["caption"] = caption
    if nodes is not None:
        active_nodes[:] = nodes
    _fanout({"kind": "orb", "orb": dict(orb), "activeNodes": list(active_nodes)})


def recent_events() -> list[dict[str, Any]]:
    return list(_recent)
