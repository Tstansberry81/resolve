"""GitHub as a code host: repo parsing, the PR/issue split, and CI status."""

from __future__ import annotations

import pytest

from resolve_control_plane.connectors import github_api


def test_accepts_urls_and_bare_slugs(monkeypatch):
    monkeypatch.setenv("GITHUB_DEFAULT_REPO", "")
    assert github_api._repo("Tstansberry81/resolve") == "Tstansberry81/resolve"
    assert github_api._repo("https://github.com/Tstansberry81/resolve") == "Tstansberry81/resolve"
    assert github_api._repo("https://github.com/Tstansberry81/resolve.git") == "Tstansberry81/resolve"
    assert github_api._repo("Tstansberry81/resolve/") == "Tstansberry81/resolve"


def test_rejects_something_that_isnt_a_repo(monkeypatch):
    monkeypatch.setenv("GITHUB_DEFAULT_REPO", "")
    with pytest.raises(ValueError):
        github_api._repo("resolve")


def test_missing_repo_asks_rather_than_guessing(monkeypatch):
    monkeypatch.delenv("GITHUB_DEFAULT_REPO", raising=False)
    monkeypatch.delenv("GITHUB_VAULT_REPO", raising=False)
    with pytest.raises(ValueError) as err:
        github_api._repo(None)
    assert "which repo" in str(err.value)


def test_pull_requests_are_not_counted_as_issues(monkeypatch):
    """GitHub's issues endpoint returns PRs too; without the filter every PR is
    double-reported as both an issue and a PR."""
    monkeypatch.setattr(github_api, "_get", lambda path, params=None: [
        {"number": 1, "title": "a bug", "state": "open", "html_url": "u1",
         "labels": [], "updated_at": "2026-07-01T00:00:00Z"},
        {"number": 2, "title": "a PR", "state": "open", "html_url": "u2",
         "labels": [], "updated_at": "2026-07-02T00:00:00Z",
         "pull_request": {"url": "x"}},
    ])
    out = github_api.list_issues("o/r")
    assert out["count"] == 1
    assert out["issues"][0]["title"] == "a bug"


def test_ci_separates_running_from_failing(monkeypatch):
    """conclusion is null mid-run; treating that as a failure would cry wolf."""
    monkeypatch.setattr(github_api, "_get", lambda path, params=None: {"workflow_runs": [
        {"name": "checks", "conclusion": "failure", "status": "completed",
         "head_branch": "main", "html_url": "u", "created_at": "2026-07-26T10:00:00Z",
         "head_commit": {"message": "broke it\n\nbody"}},
        {"name": "checks", "conclusion": None, "status": "in_progress",
         "head_branch": "main", "html_url": "u2", "created_at": "2026-07-26T11:00:00Z",
         "head_commit": {"message": "wip"}},
        {"name": "checks", "conclusion": "success", "status": "completed",
         "head_branch": "main", "html_url": "u3", "created_at": "2026-07-26T09:00:00Z",
         "head_commit": {"message": "fine"}},
    ]})
    out = github_api.ci_status("o/r")
    assert out["failingCount"] == 1
    assert out["failing"][0]["commit"] == "broke it"
    assert [r["status"] for r in out["runs"]] == ["failure", "running", "success"]
