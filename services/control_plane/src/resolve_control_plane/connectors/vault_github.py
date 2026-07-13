"""Vault (second brain) — appends entries to wiki/log.md in the vault repo via
the GitHub contents API, the same write path the vault1 bot uses. The Mac's
Obsidian pulls these down."""

from __future__ import annotations

import base64
import datetime as dt
import os

import requests

VAULT_REPO = os.getenv("GITHUB_VAULT_REPO", "Tstansberry81/vault")
LOG_PATH = "wiki/log.md"


def configured() -> bool:
    return bool(os.getenv("GITHUB_TOKEN"))


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {os.getenv('GITHUB_TOKEN', '')}",
        "Accept": "application/vnd.github+json",
    }


def append_log(title: str, lines: list[str]) -> dict:
    """Append a dated entry to wiki/log.md (read → append → PUT with sha)."""
    url = f"https://api.github.com/repos/{VAULT_REPO}/contents/{LOG_PATH}"
    r = requests.get(url, headers=_headers(), timeout=15)
    r.raise_for_status()
    meta = r.json()
    content = base64.b64decode(meta["content"]).decode("utf-8")

    today = dt.date.today().isoformat()
    entry = f"\n## [{today}] agent | {title}\n" + "\n".join(f"- {line}" for line in lines) + "\n"
    new_content = content.rstrip("\n") + "\n" + entry

    put = requests.put(
        url,
        headers=_headers(),
        json={
            "message": f"agent: log {title}",
            "content": base64.b64encode(new_content.encode("utf-8")).decode("ascii"),
            "sha": meta["sha"],
        },
        timeout=15,
    )
    put.raise_for_status()
    try:
        from .. import artifacts
        artifacts.record_vault(LOG_PATH, action="updated")
    except Exception:
        pass
    return {"committed": True, "path": LOG_PATH, "title": title}


def read_file(path: str, limit: int = 6000) -> dict:
    """Read one vault file (truncated) so agents can pull second-brain context."""
    url = f"https://api.github.com/repos/{VAULT_REPO}/contents/{path}"
    r = requests.get(url, headers=_headers(), timeout=20)
    r.raise_for_status()
    text = base64.b64decode(r.json().get("content", "")).decode("utf-8", "replace")
    return {"path": path, "content": text[:limit]}


def write_file(path: str, content: str, message: str = "") -> dict:
    """Create or update a vault file (create blob → PUT with sha if it exists).

    Guards the CLAUDE.md schema: `raw/` is IMMUTABLE (source of truth) and
    CLAUDE.md itself is off-limits to automated writes. Everything else in
    `wiki/` and `output/` is fair game — it's all git-versioned/reversible."""
    norm = path.strip().lstrip("/")
    low = norm.lower()
    if low.startswith("raw/") or low == "raw" or low == "claude.md":
        raise ValueError(f"refusing to write to protected path: {path} (raw/ and CLAUDE.md are read-only)")
    url = f"https://api.github.com/repos/{VAULT_REPO}/contents/{norm}"
    sha = None
    existing = requests.get(url, headers=_headers(), timeout=20)
    if existing.status_code == 200:
        sha = existing.json().get("sha")
    body = {
        "message": message or f"agent: write {norm}",
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
    }
    if sha:
        body["sha"] = sha
    put = requests.put(url, headers=_headers(), json=body, timeout=20)
    put.raise_for_status()
    try:
        from .. import artifacts
        artifacts.record_vault(norm, action="updated" if sha else "created")
    except Exception:
        pass
    return {"committed": True, "path": norm, "updated": sha is not None}


def list_tree(prefix: str = "wiki/") -> dict:
    """List vault file paths under a prefix so the ingest can see current structure."""
    url = f"https://api.github.com/repos/{VAULT_REPO}/git/trees/main?recursive=1"
    r = requests.get(url, headers=_headers(), timeout=20)
    r.raise_for_status()
    p = prefix.lower()
    paths = [t["path"] for t in r.json().get("tree", [])
             if t.get("type") == "blob" and t["path"].lower().startswith(p)]
    return {"prefix": prefix, "paths": paths[:200]}


def search_files(query: str) -> dict:
    """List vault file paths whose name contains the query (case-insensitive)."""
    url = f"https://api.github.com/repos/{VAULT_REPO}/git/trees/main?recursive=1"
    r = requests.get(url, headers=_headers(), timeout=20)
    r.raise_for_status()
    q = query.lower()
    paths = [t["path"] for t in r.json().get("tree", [])
             if t.get("type") == "blob" and q in t["path"].lower()]
    return {"matches": paths[:30]}
