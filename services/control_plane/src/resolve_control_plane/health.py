"""Apple Watch → RESOLVE health lane.

HealthKit has no cloud API, so an iOS Shortcut on Trav's phone POSTs the
morning's numbers (sleep, resting HR, HRV, steps, …) to /v1/health. The latest
reading feeds a one-line recovery note in the morning brief via the get_health
tool; every reading also lands in agent_events so history accumulates in the
ledger (and the nightly ingest can distill it later if wanted).
"""

from __future__ import annotations

import time
from typing import Any

import anyio

from . import bus, store

EVENT_TYPE = "health.apple"
FRESH_SECS = 36 * 3600  # older than ~1.5 days → treat as no data

_latest: dict[str, Any] | None = None
_latest_ts: float = 0.0

# fields worth keeping if the Shortcut sends them (everything else is dropped)
_FIELDS = {"date", "sleep_hours", "sleep_quality", "time_asleep", "resting_hr",
           "hrv", "steps", "active_kcal", "exercise_minutes", "stand_hours",
           "respiratory_rate", "weight", "note"}


def _sanitize(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (data or {}).items():
        key = str(k).strip().lower().replace(" ", "_")
        if key not in _FIELDS:
            continue
        if isinstance(v, (int, float, bool)):
            out[key] = v
        elif isinstance(v, str):
            s = v.strip()[:200]
            try:
                out[key] = float(s) if s.replace(".", "", 1).replace("-", "", 1).isdigit() else s
            except ValueError:
                out[key] = s
    return out


async def ingest(data: dict[str, Any]) -> dict[str, Any]:
    global _latest, _latest_ts
    clean = _sanitize(data)
    if not clean:
        return {"ok": False, "error": "no recognized health fields",
                "accepted_fields": sorted(_FIELDS)}
    _latest, _latest_ts = clean, time.time()
    try:
        await anyio.to_thread.run_sync(lambda: store.insert(
            "agent_events", {"event_type": EVENT_TYPE, "actor": "health", "payload": clean}))
    except Exception:
        pass  # in-memory copy still serves today's brief
    await bus.emit("health", "health.received",
                   "Apple Watch data landed for today", level="info")
    return {"ok": True, "stored": clean}


def latest() -> dict[str, Any] | None:
    """Freshest reading, or None when stale/absent (callers say 'no data')."""
    if _latest and (time.time() - _latest_ts) < FRESH_SECS:
        return _latest
    return None


def configured() -> bool:
    return latest() is not None


def load_seed() -> None:
    """Rehydrate the latest reading across a deploy (best-effort)."""
    global _latest, _latest_ts
    try:
        rows = store.select("agent_events", {"event_type": f"eq.{EVENT_TYPE}",
                                             "order": "created_at.desc", "limit": "1"})
        if rows:
            payload = rows[0].get("payload") or {}
            if isinstance(payload, dict) and payload:
                created = rows[0].get("created_at") or ""
                # crude ISO → epoch; wrong-parse just means "stale", which is safe
                import datetime as _dt
                try:
                    ts = _dt.datetime.fromisoformat(str(created).replace("Z", "+00:00")).timestamp()
                except ValueError:
                    ts = 0.0
                _latest, _latest_ts = payload, ts
    except Exception:
        pass
