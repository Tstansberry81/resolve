"""Supabase persistence via PostgREST — same SUPABASE_URL/SUPABASE_KEY the
vault1 bot already uses on Render. Falls back to in-memory when unset so the
API still runs locally without credentials."""

from __future__ import annotations

import itertools
import logging
import os
import time
from typing import Any

import requests

log = logging.getLogger("resolve.store")

SUPABASE_URL = (os.getenv("SUPABASE_URL", "") or "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")


def configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_KEY)


def _headers() -> dict[str, str]:
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


# in-memory fallback (local dev without Supabase)
_mem: dict[str, list[dict]] = {"agent_events": [], "goals": [], "approvals": [], "artifacts": []}
_mem_seq = itertools.count(1)


def insert(table: str, row: dict[str, Any]) -> dict[str, Any]:
    if not configured():
        row = dict(row)
        row.setdefault("id", next(_mem_seq))
        row.setdefault("created_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        _mem.setdefault(table, []).append(row)
        return row
    r = requests.post(f"{SUPABASE_URL}/rest/v1/{table}", headers=_headers(), json=row, timeout=10)
    if r.status_code not in (200, 201):
        log.error("supabase insert %s failed: %s %s", table, r.status_code, r.text[:200])
        raise RuntimeError(f"supabase insert failed ({r.status_code})")
    data = r.json()
    return data[0] if isinstance(data, list) and data else row


def select(table: str, params: dict[str, str] | None = None) -> list[dict[str, Any]]:
    if not configured():
        return list(_mem.get(table, []))
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/{table}", headers=_headers(), params=params or {}, timeout=10
    )
    if r.status_code != 200:
        log.error("supabase select %s failed: %s %s", table, r.status_code, r.text[:200])
        return []
    return r.json()


def update(table: str, match: dict[str, str], patch: dict[str, Any]) -> None:
    if not configured():
        for row in _mem.get(table, []):
            if all(str(row.get(k)) == v.removeprefix("eq.") for k, v in match.items()):
                row.update(patch)
        return
    r = requests.patch(
        f"{SUPABASE_URL}/rest/v1/{table}", headers=_headers(), params=match, json=patch, timeout=10
    )
    if r.status_code not in (200, 204):
        log.error("supabase update %s failed: %s %s", table, r.status_code, r.text[:200])
