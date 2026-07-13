"""In-process daily API cost accounting.

Every model call reports an Anthropic ``usage`` object; we price it per model
and accumulate today's spend per role (assistant / planner / executor). The
snapshot surfaces this so the dashboard's cost tracker shows real numbers
instead of the old hardcoded zeros. Resets at UTC midnight; in-memory only
(good enough for a single-instance personal tool — survives nothing but a
restart, which is fine for a "today" counter).
"""

from __future__ import annotations

import datetime
import threading

from . import store

_ROLLUP_TYPE = "cost.rollup"  # persisted daily totals in agent_events (survive restarts)

# USD per 1,000,000 tokens: (input, output). Matches Anthropic list pricing.
PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
_DEFAULT_PRICE = (5.0, 25.0)  # unknown model → assume Opus-tier, don't under-report

_lock = threading.Lock()
_day = ""
_by_role: dict[str, dict] = {}
_dirty = False


def _today() -> str:
    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


def _roll_locked() -> None:
    global _day, _by_role
    d = _today()
    if d != _day:
        _day = d
        _by_role = {}


def record(role: str, model: str, usage: object) -> None:
    """Price one model response and add it to today's running total for ``role``.

    ``usage`` is an Anthropic Usage object (input_tokens / output_tokens, plus
    cache token fields). Never raises — cost tracking must not break a request.
    """
    try:
        in_tok = int(getattr(usage, "input_tokens", 0) or 0)
        in_tok += int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        in_tok += int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        out_tok = int(getattr(usage, "output_tokens", 0) or 0)
    except Exception:
        return

    p_in, p_out = PRICING.get(model, _DEFAULT_PRICE)
    usd = in_tok / 1_000_000 * p_in + out_tok / 1_000_000 * p_out
    global _dirty
    with _lock:
        _roll_locked()
        row = _by_role.setdefault(
            role, {"model": model, "in": 0, "out": 0, "usd": 0.0, "calls": 0}
        )
        row["model"] = model
        row["in"] += in_tok
        row["out"] += out_tok
        row["usd"] += usd
        row["calls"] += 1
        _dirty = True


def load_seed() -> None:
    """After a restart, reseed today's in-memory totals from the last persisted
    rollup so 'cost today' doesn't drop to zero on every redeploy. Blocking — call
    from a thread, not the event loop."""
    global _by_role, _day
    try:
        rows = store.select("agent_events", {
            "event_type": f"eq.{_ROLLUP_TYPE}", "order": "created_at.desc", "limit": "1",
        })
    except Exception:
        return
    if not rows:
        return
    p = rows[0].get("payload") or {}
    if isinstance(p, str):
        import json
        try:
            p = json.loads(p)
        except Exception:
            return
    if p.get("date") != _today():
        return  # last rollup is from a previous day — start fresh
    with _lock:
        _day = _today()
        _by_role = {r: dict(v) for r, v in (p.get("roles") or {}).items()}


def persist() -> None:
    """Flush today's totals to agent_events if changed. Blocking — call from a
    thread (e.g. the 60s scheduler tick), never the event loop."""
    global _dirty
    with _lock:
        if not _dirty:
            return
        _roll_locked()
        payload = {"date": _day or _today(), "roles": {r: dict(v) for r, v in _by_role.items()}}
        _dirty = False
    try:
        store.insert("agent_events", {"event_type": _ROLLUP_TYPE, "actor": "core", "payload": payload})
    except Exception:
        with _lock:
            _dirty = True  # retry next tick


def snapshot() -> dict:
    """Today's spend per role plus the day total, for the /v1/snapshot vitals."""
    with _lock:
        _roll_locked()
        models = [
            {
                "role": role,
                "model": v["model"],
                "costTodayUsd": round(v["usd"], 4),
                "tokensToday": v["in"] + v["out"],
                "callsToday": v["calls"],
            }
            for role, v in _by_role.items()
        ]
        total_usd = round(sum(v["usd"] for v in _by_role.values()), 4)
        total_tokens = sum(v["in"] + v["out"] for v in _by_role.values())
    return {
        "day": _day or _today(),
        "models": models,
        "totalCostTodayUsd": total_usd,
        "tokensToday": total_tokens,
    }
