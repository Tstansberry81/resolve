"""Vault (second brain) — writes into the vault repo via the GitHub contents
API. The Mac's Obsidian clone pulls these down.

Logs go to a DATED file (wiki/logs/YYYY-MM-DD.md), not one shared wiki/log.md.
A single append-target had two independent writers — RESOLVE through this API
and Obsidian on disk — so every run dirtied the same file, obsidian-git refused
to pull over the dirty tree, and the vault wedged (13 behind / 4 ahead when we
finally looked). Per-day files mean the two sides almost never touch the same
file, and a stale local copy of an OLD day can't block today's pull."""

from __future__ import annotations

import base64
import datetime as dt
import os

import requests

VAULT_REPO = os.getenv("GITHUB_VAULT_REPO", "Tstansberry81/vault")
LOG_PATH = "wiki/log.md"   # legacy single log: kept for its history, no longer written
LOG_DIR = "wiki/logs"      # today's entries land in LOG_DIR/<date>.md


def log_path_for(day: str | None = None) -> str:
    return f"{LOG_DIR}/{day or dt.date.today().isoformat()}.md"


def configured() -> bool:
    return bool(os.getenv("GITHUB_TOKEN"))


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {os.getenv('GITHUB_TOKEN', '')}",
        "Accept": "application/vnd.github+json",
    }


def probe(timeout: int = 6) -> str | None:
    """Verify the token can actually WRITE the vault. None = live, else why not.

    configured() only proves GITHUB_TOKEN is a non-empty string. A revoked or
    under-scoped token passes that and fails every real call, which is how the
    vault stayed "healthy" on the dashboard for days while nothing could read
    the operator brief or save a note.
    """
    if not configured():
        return "GITHUB_TOKEN not set"
    try:
        r = requests.get(f"https://api.github.com/repos/{VAULT_REPO}",
                         headers=_headers(), timeout=timeout)
    except Exception as exc:
        return f"cannot reach api.github.com ({type(exc).__name__})"
    if r.status_code == 401:
        return "GITHUB_TOKEN rejected (401) — revoked or expired"
    if r.status_code == 403:
        return "GITHUB_TOKEN forbidden (403) — missing scope, or rate limited"
    if r.status_code == 404:
        return (f"{VAULT_REPO} invisible to this token (404) — fine-grained PAT "
                "without this repo selected, or wrong GITHUB_VAULT_REPO")
    if r.status_code != 200:
        return f"GitHub returned {r.status_code}"
    try:
        if not (r.json().get("permissions") or {}).get("push"):
            return f"token is READ-ONLY on {VAULT_REPO} — vault saves will fail"
    except ValueError:
        return "GitHub returned an unreadable response"
    return None


def append_log(title: str, lines: list[str]) -> dict:
    """Append an entry to TODAY's log file, creating it on the first write of
    the day (read → append → PUT with sha; PUT without sha when it's new)."""
    today = dt.date.today().isoformat()
    path = log_path_for(today)
    url = f"https://api.github.com/repos/{VAULT_REPO}/contents/{path}"

    r = requests.get(url, headers=_headers(), timeout=15)
    if r.status_code == 404:
        # 404 is also what a missing repo / wrong GITHUB_VAULT_REPO / unscoped
        # token returns. Check the repo itself so a real access failure doesn't
        # masquerade as "first write of the day" and fail confusingly on the PUT.
        probe = requests.get(f"https://api.github.com/repos/{VAULT_REPO}",
                             headers=_headers(), timeout=15)
        if probe.status_code != 200:
            raise RuntimeError(
                f"vault repo {VAULT_REPO} unreachable ({probe.status_code}) — "
                "check GITHUB_TOKEN scope and GITHUB_VAULT_REPO")
        content, sha = f"# RESOLVE log — {today}\n", None
    else:
        r.raise_for_status()
        meta = r.json()
        content = base64.b64decode(meta["content"]).decode("utf-8")
        sha = meta["sha"]

    stamp = dt.datetime.now().strftime("%H:%M")
    entry = f"\n## {stamp} — {title}\n" + "\n".join(f"- {line}" for line in lines) + "\n"
    payload = {
        "message": f"agent: log {title[:60]}",
        "content": base64.b64encode(
            (content.rstrip("\n") + "\n" + entry).encode("utf-8")).decode("ascii"),
    }
    if sha:  # omitted on create — GitHub rejects a sha for a file that doesn't exist
        payload["sha"] = sha

    put = requests.put(url, headers=_headers(), json=payload, timeout=15)
    put.raise_for_status()
    try:
        from .. import artifacts
        artifacts.record_vault(path, action="updated" if sha else "created")
    except Exception:
        pass
    return {"committed": True, "path": path, "title": title}


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
    `wiki/` and `output/` is fair game — it's all git-versioned/reversible.

    The operator brief is protected for a sharper reason than convention: it is
    loaded into the assistant's SYSTEM PROMPT with operator authority, so a
    writable brief would let any prompt injection that reaches an ingested email
    or web page permanently rewrite RESOLVE's own instructions. Only Trav edits
    it, by hand, in Obsidian."""
    import os

    norm = path.strip().lstrip("/")
    low = norm.lower()
    guide_path = os.getenv("RESOLVE_GUIDE_PATH", "wiki/RESOLVE.md").strip().lstrip("/").lower()
    if low.startswith("raw/") or low == "raw" or low == "claude.md":
        raise ValueError(f"refusing to write to protected path: {path} (raw/ and CLAUDE.md are read-only)")
    if low == guide_path:
        raise ValueError(
            f"refusing to write to {path}: the operator brief is read-only to RESOLVE. "
            "It goes into my system prompt, so only Trav edits it — by hand, in Obsidian.")
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
    """Search the vault by FILENAME and by CONTENT (GitHub code search). Content
    search is best-effort (needs indexing); filename always works."""
    q = (query or "").strip()
    ql = q.lower()
    by_name: list[str] = []
    try:
        url = f"https://api.github.com/repos/{VAULT_REPO}/git/trees/main?recursive=1"
        r = requests.get(url, headers=_headers(), timeout=20)
        r.raise_for_status()
        by_name = [t["path"] for t in r.json().get("tree", [])
                   if t.get("type") == "blob" and ql in t["path"].lower()]
    except Exception:
        pass
    by_content: list[str] = []
    fragments: dict[str, list[str]] = {}
    content_status = "ok"
    try:
        sr = requests.get(
            "https://api.github.com/search/code",
            headers={**_headers(), "Accept": "application/vnd.github.text-match+json"},
            params={"q": f"{q} repo:{VAULT_REPO}", "per_page": 20},
            timeout=20,
        )
        if sr.status_code == 200:
            for it in sr.json().get("items", []):
                path = it.get("path", "")
                if not path:
                    continue
                by_content.append(path)
                # text-match fragments show WHY a page matched, so the agent can
                # pick the right page instead of vault_reading every candidate
                frags = [tm.get("fragment", "").strip()[:220]
                         for tm in (it.get("text_matches") or [])][:2]
                if frags:
                    fragments[path] = frags
            if not by_content:
                content_status = "no content hits"
        else:
            # surface WHY content search failed (403 = token type/scope,
            # 422 = repo not indexed/query issue) instead of failing silent
            content_status = f"http {sr.status_code}: {sr.text[:160]}"
    except Exception as exc:
        content_status = f"error: {exc}"
    seen: set[str] = set()
    merged: list[str] = []
    for p in by_name + by_content:  # filename hits first
        if p and p not in seen:
            seen.add(p)
            merged.append(p)
    return {"matches": merged[:30], "byName": by_name[:15], "byContent": by_content[:15],
            "fragments": fragments, "contentSearch": content_status}
