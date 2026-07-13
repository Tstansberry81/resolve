"""Artifact registry — every file RESOLVE creates or changes gets logged here
so the dashboard's Artifacts dock can show it with a **clickable link to the
actual file**: GitHub blob URL for vault files, `file://` for local files on
Trav's Mac, and a provider web URL later for Google Drive / OneDrive.

Persists to `agent_events` (event_type='artifact') like costs/finance, so no
new Supabase table is needed. Recent list is rebuilt from there on restart."""

from __future__ import annotations

import itertools
import os
import time
from typing import Any

from . import bus, store

VAULT_REPO = os.getenv("GITHUB_VAULT_REPO", "Tstansberry81/vault")
_ARTIFACT_TYPE = "artifact"
_seq = itertools.count(1)
_recent: list[dict[str, Any]] = []
MAX_RECENT = 40


def _kind_for(name: str, location: str) -> str:
    low = name.lower()
    if location == "vault" or low.endswith((".md", ".txt", ".pdf", ".doc", ".docx")):
        return "report"
    if low.endswith((".mp3", ".wav", ".m4a", ".ogg", ".flac")):
        return "audio"
    return "file"


def vault_href(path: str) -> str:
    """Clickable GitHub blob URL for a vault-relative path."""
    return f"https://github.com/{VAULT_REPO}/blob/main/{path.lstrip('/')}"


def _build(name: str, path: str, *, location: str, href: str,
           action: str, goal_id: str | None) -> dict[str, Any]:
    return {
        "id": f"art-{next(_seq)}-{int(time.time() * 1000)}",
        "goalId": goal_id or "",
        "kind": _kind_for(name, location),
        "name": name,
        "meta": f"{location} · {action}",
        "location": location,
        "href": href,
        "path": path,
        "action": action,
        "ts": int(time.time() * 1000),
    }


def record(name: str, path: str, *, location: str = "local",
           href: str | None = None, action: str = "created",
           goal_id: str | None = None) -> dict[str, Any]:
    """Log one file change. `location`: local | vault | gdrive | onedrive."""
    if href is None:
        href = vault_href(path) if location == "vault" else f"file://{path}"
    art = _build(name, path, location=location, href=href, action=action, goal_id=goal_id)
    _recent.insert(0, art)
    del _recent[MAX_RECENT:]
    bus._fanout({"kind": "artifact", "artifact": art})
    try:
        row = {"event_type": _ARTIFACT_TYPE, "actor": "resolve", "payload": art}
        if goal_id and len(str(goal_id)) == 36:
            row["goal_id"] = goal_id
        store.insert("agent_events", row)
    except Exception:
        pass  # persistence is best-effort; the live dock already has it
    return art


def record_vault(path: str, *, action: str = "created",
                 goal_id: str | None = None) -> dict[str, Any]:
    """Convenience: log a vault file with a GitHub-clickable href."""
    return record(path.split("/")[-1], path, location="vault",
                  href=vault_href(path), action=action, goal_id=goal_id)


def recent() -> list[dict[str, Any]]:
    return list(_recent)


def load_seed() -> None:
    """Rebuild the recent list from agent_events after a restart (dedup by href)."""
    try:
        rows = store.select("agent_events", {
            "event_type": "eq.artifact",
            "order": "created_at.desc",
            "limit": str(MAX_RECENT),
        })
    except Exception:
        return
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in rows:
        art = r.get("payload") or {}
        if not art.get("name"):
            continue
        key = str(art.get("href") or art.get("path") or art.get("id"))
        if key in seen:
            continue
        seen.add(key)
        out.append(art)
    _recent[:] = out
