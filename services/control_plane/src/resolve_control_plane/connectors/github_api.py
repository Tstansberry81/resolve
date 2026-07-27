"""GitHub as a code host, not just a vault filestore.

`vault_github.py` uses the same GITHUB_TOKEN but only ever commits markdown into
the second brain. That left RESOLVE unable to answer the most ordinary question
Trav has about his own projects — "did CI pass?", "what's open on resolve?" —
even though the credential to answer it was already sitting in Render.

Direct REST rather than Composio: the token exists, it's one hop instead of two,
there's no connected-account ambiguity, and read calls cost nothing.

Repo defaults to GITHUB_DEFAULT_REPO so Trav can say "any failing builds?"
without naming a repo every time.
"""

from __future__ import annotations

import os

import requests

API = "https://api.github.com"


def configured() -> bool:
    return bool(os.getenv("GITHUB_TOKEN"))


def default_repo() -> str:
    return os.getenv("GITHUB_DEFAULT_REPO", "") or os.getenv("GITHUB_VAULT_REPO", "")


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {os.getenv('GITHUB_TOKEN', '')}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _repo(repo: str | None) -> str:
    target = (repo or default_repo() or "").strip().rstrip("/")
    if not target:
        raise ValueError(
            "No repo given and GITHUB_DEFAULT_REPO isn't set — tell me which repo.")
    # accept a full URL and reduce it to owner/name
    if "github.com/" in target:
        target = target.split("github.com/", 1)[1]
    if target.endswith(".git"):
        target = target[:-4]
    if target.count("/") != 1:
        raise ValueError(f"'{target}' doesn't look like owner/repo.")
    return target


def _get(path: str, params: dict | None = None) -> object:
    r = requests.get(f"{API}{path}", headers=_headers(), params=params or {}, timeout=25)
    if r.status_code == 404:
        raise ValueError(f"GitHub says that doesn't exist (or the token can't see it): {path}")
    r.raise_for_status()
    return r.json()


def list_issues(repo: str | None = None, state: str = "open", limit: int = 20) -> dict:
    """Open issues, newest first. Pull requests are filtered out — GitHub returns
    them from the issues endpoint too, which would double-count them against
    list_pull_requests below."""
    target = _repo(repo)
    rows = _get(f"/repos/{target}/issues",
                {"state": state, "per_page": max(1, min(limit, 50)), "sort": "updated"})
    # .get() throughout: a partial body, a proxy-truncated response, or an error
    # object where a list was expected must degrade to a thin row, not a KeyError
    # that takes out the whole listing.
    issues = [{
        "number": i.get("number"), "title": i.get("title") or "(untitled)",
        "state": i.get("state"), "url": i.get("html_url"),
        "labels": [lbl.get("name") for lbl in (i.get("labels") or [])
                   if isinstance(lbl, dict)],
        "updated": (i.get("updated_at") or "")[:10],
    } for i in rows if isinstance(i, dict) and "pull_request" not in i]
    return {"repo": target, "state": state, "count": len(issues), "issues": issues}


def list_pull_requests(repo: str | None = None, state: str = "open", limit: int = 20) -> dict:
    target = _repo(repo)
    rows = _get(f"/repos/{target}/pulls",
                {"state": state, "per_page": max(1, min(limit, 50)), "sort": "updated",
                 "direction": "desc"})
    prs = [{
        "number": p.get("number"), "title": p.get("title") or "(untitled)",
        "state": p.get("state"), "url": p.get("html_url"),
        "draft": p.get("draft", False),
        "branch": (p.get("head") or {}).get("ref", ""),
        "updated": (p.get("updated_at") or "")[:10],
    } for p in rows if isinstance(p, dict)]
    return {"repo": target, "state": state, "count": len(prs), "pullRequests": prs}


def create_issue(title: str, body: str = "", repo: str | None = None,
                 labels: list[str] | None = None) -> dict:
    target = _repo(repo)
    payload: dict = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels
    r = requests.post(f"{API}/repos/{target}/issues", headers=_headers(),
                      json=payload, timeout=25)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"GitHub refused the issue ({r.status_code}): {r.text[:180]}")
    data = r.json() if isinstance(r.json(), dict) else {}
    number, url = data.get("number"), data.get("html_url")
    if not url:
        # A 2xx without a URL means we cannot show Trav the issue. Say so rather
        # than reporting a create he can't verify.
        raise RuntimeError("GitHub accepted the issue but returned no link for it.")
    return {"created": True, "repo": target, "number": number,
            "url": url, "title": title}


def ci_status(repo: str | None = None, limit: int = 10) -> dict:
    """Recent Actions runs, with failures called out.

    This is the "did I break the build?" answer. `conclusion` is null while a run
    is still going, which reads as neither pass nor fail — surfaced as 'running'
    rather than being lumped in with failures.
    """
    target = _repo(repo)
    data = _get(f"/repos/{target}/actions/runs", {"per_page": max(1, min(limit, 30))})
    runs = (data or {}).get("workflow_runs", []) if isinstance(data, dict) else []
    out = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        conclusion = run.get("conclusion")
        out.append({
            "workflow": run.get("name"),
            "branch": run.get("head_branch"),
            "status": conclusion or ("running" if run.get("status") != "completed" else "unknown"),
            # head_commit is null on workflow_dispatch runs.
            "commit": ((run.get("head_commit") or {}).get("message") or "").split("\n")[0][:80],
            "url": run.get("html_url"),
            "when": (run.get("created_at") or "")[:16].replace("T", " "),
        })
    failing = [r for r in out if r["status"] in ("failure", "timed_out", "startup_failure")]
    return {"repo": target, "runs": out, "failingCount": len(failing),
            "failing": failing[:5]}
