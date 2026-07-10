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
    return {"committed": True, "path": LOG_PATH, "title": title}
