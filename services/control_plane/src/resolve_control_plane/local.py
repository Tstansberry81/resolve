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


# ── offline watchdog (ticked once a minute by the routine scheduler) ─────────
OFFLINE_ALERT_SECS = 120
ALERT_COOLDOWN_SECS = 3600  # hard cap: at most ONE worker alert per hour
KICKSTART_HINT = "launchctl kickstart -k gui/$(id -u)/com.resolve.localworker"
_watch: dict[str, Any] = {"offline_since": None, "alerted": False, "last_alert": 0.0}


async def watchdog_tick() -> None:
    """Log a dashboard event when the worker has been offline for a while.
    NO Telegram (per Trav): the event lands in the dashboard event log only;
    the vitals pill shows live status. Still one event max per hour, and
    recovery is silent."""
    if online():
        _watch["offline_since"] = None
        _watch["alerted"] = False
        return
    if _watch["offline_since"] is None:
        _watch["offline_since"] = time.time()
        return
    down = time.time() - _watch["offline_since"]
    if (not _watch["alerted"] and down >= OFFLINE_ALERT_SECS
            and time.time() - _watch["last_alert"] >= ALERT_COOLDOWN_SECS):
        _watch["alerted"] = True
        _watch["last_alert"] = time.time()
        await bus.emit(
            "core", "system.worker_offline",
            f"Local worker offline {int(down // 60)}m — laptop hands are down.",
            detail=("Local worker offline — laptop hands are down.\n"
                    f"On the Mac: {KICKSTART_HINT}"),
            level="warn",
        )


def enqueue(task: str) -> dict[str, Any]:
    task_id = str(uuid.uuid4())
    _queue.append({"taskId": task_id, "task": task})
    return {"taskId": task_id, "queued": True, "workerOnline": online()}


def enqueue_action(kind: str, value: str, label: str) -> dict[str, Any]:
    """Enqueue a structured 'open' action the worker runs directly (no LLM, no
    approval — opening a folder/app/url is safe and non-destructive)."""
    task_id = str(uuid.uuid4())
    _queue.append({"taskId": task_id, "task": label,
                   "action": {"kind": kind, "value": value}})
    return {"taskId": task_id, "queued": True, "workerOnline": online(),
            "dispatched": label if online() else None}


def next_task() -> dict[str, Any] | None:
    global _last_poll
    _last_poll = time.time()
    return _queue.pop(0) if _queue else None


_RESULTS_CAP = 200


def set_result(task_id: str, summary: str) -> None:
    _results[task_id] = summary
    if len(_results) > _RESULTS_CAP:  # bound memory — evict oldest insertions
        for k in list(_results)[:len(_results) - _RESULTS_CAP]:
            _results.pop(k, None)


def get_result(task_id: str) -> str | None:
    return _results.get(task_id)


def pop_result(task_id: str) -> str | None:
    """Read-and-remove — callers that consume a result shouldn't leak it."""
    return _results.pop(task_id, None)


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
