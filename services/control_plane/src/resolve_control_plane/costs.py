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
