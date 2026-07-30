"""Connector liveness: does a lane actually work, and does the model get told.

The bug this exists to prevent: every connector's configured() is a check that
an env var is a non-empty string, so a revoked token reported healthy while
nothing worked. RESOLVE then planned around lanes that were dead.
"""

from __future__ import annotations

import pytest

from resolve_control_plane import liveness


@pytest.fixture(autouse=True)
def _fresh():
    liveness._cache = {}
    liveness._checked_at = 0.0
    yield
    liveness._cache = {}
    liveness._checked_at = 0.0


def _probes(monkeypatch, **lanes):
    """Install fake probes: value None = live, a string = that failure reason."""
    monkeypatch.setattr(
        liveness, "_probes",
        lambda: {cid: (cid.title(), (lambda r=reason: r)) for cid, reason in lanes.items()})


def test_a_live_lane_says_nothing_to_the_model(monkeypatch):
    """A block listing working tools would ride in every request for no benefit."""
    _probes(monkeypatch, vault=None, notion=None)
    liveness.refresh()
    assert liveness.for_prompt() == ""
    assert liveness.dead() == {}


def test_a_dead_lane_reaches_the_prompt_with_its_reason(monkeypatch):
    _probes(monkeypatch, vault="GITHUB_TOKEN rejected (401) — revoked or expired",
            notion=None)
    liveness.refresh()
    block = liveness.for_prompt()
    assert "vault" in block
    assert "401" in block
    # the behaviour we're buying: deliver the rest, don't blame him
    assert "EVERY PART THAT DOESN'T" in block
    assert "do not blame the user" in block
    # a healthy lane is not named
    assert "notion" not in block


def test_the_prompt_path_never_blocks_on_a_probe(monkeypatch):
    """A cold cache must not make Trav wait behind five HTTP calls."""
    calls: list[str] = []

    def slow():
        calls.append("probed")
        raise AssertionError("for_prompt must never run a probe synchronously")

    monkeypatch.setattr(liveness, "_probes", lambda: {"vault": ("Vault", slow)})
    monkeypatch.setattr(liveness, "_refresh_in_background", lambda: None)
    assert liveness.for_prompt() == ""
    assert calls == []


def test_a_cold_cache_kicks_a_background_refresh(monkeypatch):
    kicked: list[bool] = []
    _probes(monkeypatch, vault=None)
    monkeypatch.setattr(liveness, "_refresh_in_background", lambda: kicked.append(True))
    liveness.for_prompt()
    assert kicked == [True]


def test_a_crashing_probe_is_dead_not_fatal(monkeypatch):
    def boom():
        raise RuntimeError("connection reset")

    monkeypatch.setattr(liveness, "_probes", lambda: {"vault": ("Vault", boom)})
    liveness.refresh()
    assert "vault" in liveness.dead()
    assert "crashed" in liveness.dead()["vault"]


def test_unprobed_lanes_report_unknown_not_healthy(monkeypatch):
    """Silence about a lane must never render as a green light."""
    _probes(monkeypatch, vault=None, notion=None)
    snap = liveness.snapshot(refresh_if_stale=False)
    assert {v["status"] for v in snap.values()} == {"unknown"}


def test_snapshot_reports_live_and_dead_with_detail(monkeypatch):
    _probes(monkeypatch, vault=None, spotify="account ambiguous")
    liveness.refresh()
    snap = liveness.snapshot(refresh_if_stale=False)
    assert snap["vault"]["status"] == "live"
    assert snap["spotify"]["status"] == "dead"
    assert snap["spotify"]["detail"] == "account ambiguous"


def test_results_are_cached_not_reprobed_every_turn(monkeypatch):
    hits: list[int] = []

    def counting():
        hits.append(1)
        return None

    monkeypatch.setattr(liveness, "_probes", lambda: {"vault": ("Vault", counting)})
    liveness.snapshot(refresh_if_stale=True)
    liveness.snapshot(refresh_if_stale=True)
    liveness.snapshot(refresh_if_stale=True)
    assert len(hits) == 1


def test_a_stale_cache_is_reprobed(monkeypatch):
    hits: list[int] = []
    monkeypatch.setattr(liveness, "_probes",
                        lambda: {"vault": ("Vault", lambda: hits.append(1) and None)})
    liveness.snapshot(refresh_if_stale=True)
    liveness._checked_at -= liveness.TTL_SECONDS + 1
    liveness.snapshot(refresh_if_stale=True)
    assert len(hits) == 2


# --- the real probes, with the network mocked -------------------------------

class _R:
    def __init__(self, status: int, payload=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


def test_vault_probe_names_each_github_failure(monkeypatch):
    from resolve_control_plane.connectors import vault_github

    monkeypatch.setenv("GITHUB_TOKEN", "t")
    cases = {
        401: "revoked or expired",
        403: "missing scope",
        404: "invisible to this token",
    }
    for status, expected in cases.items():
        monkeypatch.setattr(vault_github.requests, "get",
                            lambda *a, _s=status, **kw: _R(_s))
        assert expected in (vault_github.probe() or "")


def test_vault_probe_catches_a_read_only_token(monkeypatch):
    """The nastiest case: 200 OK, and every save still fails."""
    from resolve_control_plane.connectors import vault_github

    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setattr(vault_github.requests, "get",
                        lambda *a, **kw: _R(200, {"permissions": {"push": False}}))
    assert "READ-ONLY" in (vault_github.probe() or "")


def test_vault_probe_passes_a_working_token(monkeypatch):
    from resolve_control_plane.connectors import vault_github

    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setattr(vault_github.requests, "get",
                        lambda *a, **kw: _R(200, {"permissions": {"push": True}}))
    assert vault_github.probe() is None


def test_an_unset_token_is_reported_as_unset(monkeypatch):
    from resolve_control_plane.connectors import vault_github

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert "not set" in (vault_github.probe() or "")


def test_notion_probe_catches_a_workspace_shared_with_nothing(monkeypatch):
    """A valid token with zero shared pages authenticates fine and finds nothing."""
    from resolve_control_plane.connectors import notion_api

    monkeypatch.setenv("NOTION_TOKEN", "t")
    monkeypatch.setattr(notion_api.requests, "get", lambda *a, **kw: _R(200, {"id": "u1"}))
    monkeypatch.setattr(notion_api.requests, "post",
                        lambda *a, **kw: _R(200, {"results": []}))
    assert "NO pages are shared" in (notion_api.probe() or "")


def test_notion_probe_passes_when_pages_are_shared(monkeypatch):
    from resolve_control_plane.connectors import notion_api

    monkeypatch.setenv("NOTION_TOKEN", "t")
    monkeypatch.setattr(notion_api.requests, "get", lambda *a, **kw: _R(200, {"id": "u1"}))
    monkeypatch.setattr(notion_api.requests, "post",
                        lambda *a, **kw: _R(200, {"results": [{"id": "p1"}]}))
    assert notion_api.probe() is None


def test_spotify_probe_reuses_the_live_error_translator(monkeypatch):
    """The status page and a failed request must explain a fault identically."""
    from resolve_control_plane.connectors import composio

    monkeypatch.setenv("COMPOSIO_API_KEY", "k")

    def boom(slug, args):
        raise RuntimeError("HTTP 404 multiple connected accounts, selection required")

    monkeypatch.setattr(composio, "execute", boom)
    assert "COMPOSIO_ACCOUNTS" in (composio.probe("spotify") or "")
