"""Connector liveness: does a lane actually work, and does the model get told.

The bug this exists to prevent: every connector's configured() is a check that
an env var is a non-empty string, so a revoked token reported healthy while
nothing worked. RESOLVE then planned around lanes that were dead.
"""

from __future__ import annotations

import pytest

from resolve_control_plane import liveness

# Captured before any fixture patches it, so a test can put the real one back and
# exercise its internal error handling.
_REAL_NOTIFY = liveness._notify


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


# --- proactive alerting ------------------------------------------------------

@pytest.fixture
def watchdog(monkeypatch):
    """Reset watchdog state and capture every alert instead of sending it."""
    liveness._prev_state = None
    liveness._last_alert_at = {}
    liveness._last_watchdog_run = 0.0
    pushes: list[str] = []
    events: list[tuple] = []

    monkeypatch.setattr(liveness, "_notify",
                        lambda text, level="warn": pushes.append(text))

    async def fake_emit(source, kind, msg, detail=None, level="info"):
        events.append((kind, msg, detail))

    import resolve_control_plane.bus as bus
    monkeypatch.setattr(bus, "emit", fake_emit)
    return pushes, events


def _tick(monkeypatch, **lanes):
    _probes(monkeypatch, **lanes)
    liveness._last_watchdog_run = 0.0
    import asyncio
    asyncio.run(liveness.watchdog_tick())


def test_startup_with_everything_healthy_is_silent(monkeypatch, watchdog):
    pushes, events = watchdog
    _tick(monkeypatch, vault=None, notion=None)
    assert pushes == []
    assert events == []


def test_startup_reports_what_is_already_broken_once(monkeypatch, watchdog):
    pushes, events = watchdog
    _tick(monkeypatch, vault="GITHUB_TOKEN rejected (401)", notion=None)
    assert len(pushes) == 1
    assert "401" in pushes[0]
    assert "GITHUB_TOKEN" in pushes[0]  # the fix hint
    assert events[0][0] == "system.connectors_down"


def test_a_lane_going_down_pushes_exactly_once(monkeypatch, watchdog):
    """The alert Trav actually wants: the moment it breaks."""
    pushes, _ = watchdog
    _tick(monkeypatch, vault=None)              # baseline: healthy
    assert pushes == []
    _tick(monkeypatch, vault="GITHUB_TOKEN rejected (401)")
    assert len(pushes) == 1
    assert "lost vault" in pushes[0]
    # still down ten minutes later — must NOT push again
    _tick(monkeypatch, vault="GITHUB_TOKEN rejected (401)")
    _tick(monkeypatch, vault="GITHUB_TOKEN rejected (401)")
    assert len(pushes) == 1


def test_recovery_is_announced(monkeypatch, watchdog):
    pushes, _ = watchdog
    _tick(monkeypatch, vault=None)
    _tick(monkeypatch, vault="dead")
    _tick(monkeypatch, vault=None)
    assert "back up" in pushes[-1]


def test_a_flapping_lane_is_not_a_pager(monkeypatch, watchdog):
    """Down/up/down inside the cooldown must not push twice."""
    pushes, _ = watchdog
    _tick(monkeypatch, vault=None)
    _tick(monkeypatch, vault="rate limited")
    _tick(monkeypatch, vault=None)
    _tick(monkeypatch, vault="rate limited")
    downs = [p for p in pushes if "lost" in p]
    assert len(downs) == 1


def test_it_probes_at_most_every_ten_minutes(monkeypatch, watchdog):
    """Once a minute from the scheduler must not mean once a minute to GitHub."""
    hits: list[int] = []
    monkeypatch.setattr(liveness, "_probes",
                        lambda: {"vault": ("Vault", lambda: hits.append(1) and None)})
    import asyncio
    liveness._last_watchdog_run = 0.0
    asyncio.run(liveness.watchdog_tick())
    for _ in range(5):
        asyncio.run(liveness.watchdog_tick())   # simulated minute ticks
    assert len(hits) == 1


def test_a_telegram_outage_never_breaks_the_tick(monkeypatch, watchdog):
    """Patches the REAL dependency, not _notify itself — replacing _notify would
    step over the very guard this is meant to prove."""
    _pushes, events = watchdog
    monkeypatch.setattr(liveness, "_notify", _REAL_NOTIFY)

    from resolve_control_plane.connectors import telegram_notify

    monkeypatch.setattr(telegram_notify, "configured", lambda: True)

    def boom(text):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(telegram_notify, "send", boom)

    _tick(monkeypatch, vault=None)
    _tick(monkeypatch, vault="dead")          # must not raise
    assert any(k == "system.connector_down" for k, _m, _d in events)


def test_no_telegram_configured_is_not_an_error(monkeypatch, watchdog):
    _pushes, events = watchdog
    monkeypatch.setattr(liveness, "_notify", _REAL_NOTIFY)

    from resolve_control_plane.connectors import telegram_notify

    monkeypatch.setattr(telegram_notify, "configured", lambda: False)
    _tick(monkeypatch, vault=None)
    _tick(monkeypatch, vault="dead")
    assert any(k == "system.connector_down" for k, _m, _d in events)
