"""Local-worker bridge.

The cloud control plane can't touch Trav's laptop, so the local worker
(apps/local-worker) polls here for tasks that need the machine and executes them
with local tools. This module is the in-memory queue + result store + the
approval bridge (shell approvals reuse the same banner/Telegram flow as
everything else) + a liveness signal so the dashboard knows a worker is online.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from . import bus

_queue: list[dict[str, Any]] = []
_results: dict[str, str] = {}
_approvals: dict[str, dict[str, Any]] = {}
_last_poll: float = 0.0


def online() -> bool:
    """A worker polled within the last 30s."""
    return (time.time() - _last_poll) < 30


def enqueue(task: str) -> dict[str, Any]:
    task_id = str(uuid.uuid4())
    _queue.append({"taskId": task_id, "task": task})
    return {"taskId": task_id, "queued": True, "workerOnline": online()}


def next_task() -> dict[str, Any] | None:
    global _last_poll
    _last_poll = time.time()
    return _queue.pop(0) if _queue else None


def set_result(task_id: str, summary: str) -> None:
    _results[task_id] = summary


# ── shell approvals (reuse the normal approval banner) ──────────────────────
def request_approval(task_id: str, summary: str, detail: str, risk: str = "local_shell") -> str:
    approval_id = str(uuid.uuid4())
    _approvals[approval_id] = {"status": "pending", "summary": summary, "taskId": task_id}
    # surface it in the dashboard banner feed (same shape the assistant uses)
    bus._fanout({
        "kind": "approval",
        "approval": {
            "id": approval_id, "goalId": task_id, "actionSummary": summary,
            "risk": risk, "preview": [detail[:300]], "status": "pending",
        },
    })
    try:
        from .connectors import telegram_notify
        if telegram_notify.configured():
            telegram_notify.send_approval(approval_id, summary, risk)
    except Exception:
        pass
    return approval_id


def approval_status(approval_id: str) -> str:
    a = _approvals.get(approval_id)
    return a["status"] if a else "rejected"


def is_local_approval(approval_id: str) -> bool:
    return approval_id in _approvals


def decide(approval_id: str, decision: str) -> None:
    a = _approvals.get(approval_id)
    if a:
        a["status"] = decision
        bus._fanout({
            "kind": "approval",
            "approval": {"id": approval_id, "goalId": a.get("taskId", ""),
                         "actionSummary": a["summary"], "risk": "local_shell",
                         "preview": [], "status": decision},
        })
