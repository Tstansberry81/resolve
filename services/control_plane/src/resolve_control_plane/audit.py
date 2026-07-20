"""Action audit log — a queryable, human-facing record of what RESOLVE DID.

Every action already lands in agent_events via bus.emit; this module reads that
ledger back and keeps only the security-relevant entries (tools run, approvals
requested/decided, sends/deletes/archives, failures) — the answer to "what has
RESOLVE done for/to me, and what did I approve?". Read-only; no new storage.
"""

from __future__ import annotations

import datetime
from typing import Any

from . import store

# Event types that represent a real action or decision worth auditing. Suffixes
# catch the dynamic "<tool>.executed" / "<tool>.failed" events.
_AUDIT_EXACT = {
    "tool.call", "tool.error", "approval.requested", "action.held",
    "task.failed", "goal.failed", "system.emergency_stop", "system.stopped",
    "finance.budget", "vault.write", "vault.ingest", "health.received",
    "goal.dismissed", "system.rehydrated",
}
_AUDIT_SUFFIXES = (".executed", ".failed")

# Higher-signal events get flagged so a reviewer can filter to "sensitive only".
_SENSITIVE_MARKERS = ("send", "delete", "archive", "executed", "failed",
                      "emergency", "budget", "approval")


def _is_audit(event_type: str) -> bool:
    t = event_type or ""
    return t in _AUDIT_EXACT or t.endswith(_AUDIT_SUFFIXES)


def _is_sensitive(event_type: str) -> bool:
    t = (event_type or "").lower()
    return any(m in t for m in _SENSITIVE_MARKERS)


def recent(hours: int = 24, limit: int = 60, sensitive_only: bool = False) -> dict[str, Any]:
    """Action entries from the last `hours`, newest first."""
    since = (datetime.datetime.now(datetime.timezone.utc)
             - datetime.timedelta(hours=max(1, int(hours)))).isoformat()
    try:
        rows = store.select("agent_events", {
            "created_at": f"gte.{since}",
            "order": "created_at.desc",
            "limit": str(min(int(limit) * 6, 600)),  # over-pull; we filter below
        })
    except Exception as exc:
        return {"error": f"audit read failed: {exc}", "actions": []}
    out: list[dict[str, Any]] = []
    for r in rows or []:
        et = r.get("event_type", "")
        if not _is_audit(et):
            continue
        if sensitive_only and not _is_sensitive(et):
            continue
        payload = r.get("payload") or {}
        if isinstance(payload, str):
            payload = {"summary": payload}
        out.append({
            "at": r.get("created_at"),
            "action": et,
            "actor": r.get("actor"),
            "detail": (payload.get("summary") or payload.get("detail") or "")[:200],
            "level": payload.get("level", "info"),
            "sensitive": _is_sensitive(et),
            "goalId": r.get("goal_id"),
        })
        if len(out) >= int(limit):
            break
    return {"window_hours": hours, "count": len(out), "actions": out}
