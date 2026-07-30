"""Does each connector actually WORK — not just "is a credential present".

Every connector's `configured()` is a string-presence check:

    def configured() -> bool:
        return bool(os.getenv("GITHUB_TOKEN"))

So a revoked token, an under-scoped PAT, a Notion integration with nothing
shared to it, and two ambiguous Composio accounts ALL report healthy. That is
the whole reason RESOLVE kept failing on first contact: it believed every lane
was live, committed to the task, and only discovered the truth mid-flight — by
which point the honest move (deliver the unblocked parts, name the real cause)
was already off the table.

This module answers the harder question with one cheap authenticated read per
lane, and puts the answer where it changes behaviour: into the system prompt,
before the model plans.

Two rules it must never break:

1. **A user's turn never waits on a probe.** `for_prompt()` reads cache only. A
   cold cache kicks a background refresh and returns nothing, so the worst case
   is one turn with no health data — never a turn that hangs behind five HTTP
   calls.

2. **Silence when healthy.** A block listing everything that works would ride in
   every request for no benefit. Only failures are worth prompt tokens.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger("resolve.liveness")

TTL_SECONDS = 300
# A probe is a health check, not a feature: better to call a lane unknown than to
# add six seconds to a status page.
PROBE_TIMEOUT = 6

_cache: dict[str, tuple[bool, str | None]] = {}
_checked_at: float = 0.0
_lock = threading.Lock()
_refreshing = False


def _probes() -> dict[str, tuple[str, object]]:
    """id -> (label, callable returning None when live, else the reason).

    Imported lazily so this module can't create an import cycle and so a broken
    connector import can't take the status page down with it.
    """
    from .connectors import composio, notion_api, vault_github

    return {
        "vault": ("Vault (GitHub)", vault_github.probe),
        "notion": ("Notion", notion_api.probe),
        "google": ("Google (Composio)", lambda: composio.probe("google")),
        "spotify": ("Spotify (Composio)", lambda: composio.probe("spotify")),
        "calendar": ("Calendar", _probe_calendar),
    }


def _probe_calendar() -> str | None:
    from .connectors import gcal

    if not gcal.configured():
        return "Google Calendar credentials not set"
    try:
        gcal.list_events(1)
    except Exception as exc:
        return f"{type(exc).__name__}: {str(exc)[:120]}"
    return None


def _run_one(item: tuple[str, tuple[str, object]]) -> tuple[str, bool, str | None]:
    cid, (_label, fn) = item
    try:
        reason = fn()  # type: ignore[operator]
    except Exception as exc:  # a probe must never raise into the caller
        reason = f"probe crashed: {type(exc).__name__}"
    return cid, reason is None, reason


def refresh() -> dict[str, tuple[bool, str | None]]:
    """Probe every lane concurrently and cache the result. Blocks; ~one probe's
    latency total rather than the sum, which is why this is threaded."""
    global _cache, _checked_at
    probes = _probes()
    results: dict[str, tuple[bool, str | None]] = {}
    with ThreadPoolExecutor(max_workers=len(probes) or 1) as pool:
        for cid, ok, reason in pool.map(_run_one, probes.items()):
            results[cid] = (ok, reason)
            if not ok:
                log.warning("connector %s is DEAD: %s", cid, reason)
    with _lock:
        _cache = results
        _checked_at = time.time()
    return results


def _refresh_in_background() -> None:
    """Warm the cache without making anyone wait. At most one at a time."""
    global _refreshing
    with _lock:
        if _refreshing:
            return
        _refreshing = True

    def run() -> None:
        global _refreshing
        try:
            refresh()
        except Exception:
            log.debug("background liveness refresh failed", exc_info=True)
        finally:
            with _lock:
                _refreshing = False

    threading.Thread(target=run, name="liveness-refresh", daemon=True).start()


def _stale() -> bool:
    return time.time() - _checked_at > TTL_SECONDS


def snapshot(refresh_if_stale: bool = True) -> dict[str, dict]:
    """Current status per lane, for the dashboard and the status endpoint."""
    if refresh_if_stale and _stale():
        refresh()
    labels = {cid: label for cid, (label, _) in _probes().items()}
    with _lock:
        cached = dict(_cache)
    out: dict[str, dict] = {}
    for cid, label in labels.items():
        if cid not in cached:
            out[cid] = {"label": label, "status": "unknown", "detail": "not probed yet"}
            continue
        ok, reason = cached[cid]
        out[cid] = {"label": label,
                    "status": "live" if ok else "dead",
                    "detail": reason}
    return out


def dead() -> dict[str, str]:
    """Lanes known to be broken, id -> reason. Cache only; never probes."""
    with _lock:
        return {cid: (reason or "unknown failure")
                for cid, (ok, reason) in _cache.items() if not ok}


# --- proactive alerting ------------------------------------------------------
# Trav found out his GitHub token had died by asking for work and getting a wrong
# explanation. The point of this half is that he hears it from RESOLVE first.
#
# The existing worker watchdog is deliberately dashboard-only ("NO Telegram, per
# Trav"). This one does push, because he asked for it — so it earns that by never
# repeating itself: only STATE CHANGES are announced, never the ongoing fact of a
# lane being down.

CHECK_INTERVAL_SECONDS = 600
# A flapping lane (rate limits, a wobbly upstream) must not become a pager.
ALERT_COOLDOWN_SECONDS = 3600

_prev_state: dict[str, bool] | None = None   # None = no baseline taken yet
_last_alert_at: dict[str, float] = {}
_last_watchdog_run: float = 0.0

_FIXES = {
    "vault": "Render → GITHUB_TOKEN (needs repo scope on vault + resolve)",
    "notion": "Render → NOTION_TOKEN, and share a parent page with the integration",
    "google": "Composio → reconnect Google",
    "spotify": "Render → COMPOSIO_ACCOUNTS={\"spotify\":\"spotify_acture-borago\"}",
    "calendar": "Render → Google service-account credentials",
}


def _notify(text: str, level: str = "warn") -> None:
    """Telegram push. Best-effort: a Telegram blip must never break the tick, and
    the dashboard event is emitted separately so the record survives either way."""
    from .connectors import telegram_notify

    try:
        if telegram_notify.configured():
            telegram_notify.send(text)
    except Exception:
        log.warning("liveness telegram push failed", exc_info=True)


async def watchdog_tick() -> None:
    """Announce connector state CHANGES. Called once a minute by the scheduler;
    probes at most every CHECK_INTERVAL_SECONDS.

    Silent by design when nothing changed — a message every ten minutes saying
    the same lane is still down is how an alert channel gets muted, and a muted
    channel is worse than none.
    """
    global _prev_state, _last_watchdog_run

    import asyncio

    from . import bus

    now = time.time()
    if now - _last_watchdog_run < CHECK_INTERVAL_SECONDS:
        return
    _last_watchdog_run = now

    try:
        results = await asyncio.to_thread(refresh)
    except Exception:
        log.exception("liveness probe failed during watchdog tick")
        return

    current = {cid: ok for cid, (ok, _reason) in results.items()}
    reasons = {cid: reason for cid, (_ok, reason) in results.items()}

    # First tick after a boot or deploy: no baseline to compare against. Report
    # anything already broken ONCE, then fall through to change-only reporting.
    if _prev_state is None:
        _prev_state = current
        broken = {cid: reasons[cid] for cid, ok in current.items() if not ok}
        if broken:
            for cid in broken:
                _last_alert_at[cid] = now
            lines = "\n".join(
                f"• {cid}: {broken[cid]}\n  fix: {_FIXES.get(cid, 'check its credentials')}"
                for cid in sorted(broken))
            await bus.emit("core", "system.connectors_down",
                           f"{len(broken)} connector(s) down at startup",
                           detail=lines, level="warn")
            _notify(f"⚠️ RESOLVE started with {len(broken)} connector(s) down:\n\n{lines}")
        return

    for cid, ok in current.items():
        was = _prev_state.get(cid)
        if was is None or was == ok:
            continue
        if not ok:
            if now - _last_alert_at.get(cid, 0.0) < ALERT_COOLDOWN_SECONDS:
                continue  # flap guard
            _last_alert_at[cid] = now
            reason = reasons.get(cid) or "unknown failure"
            fix = _FIXES.get(cid, "check its credentials")
            await bus.emit("core", "system.connector_down",
                           f"{cid} just went down: {reason}",
                           detail=f"{reason}\nfix: {fix}", level="warn")
            _notify(f"⚠️ RESOLVE lost {cid}\n\n{reason}\n\nFix: {fix}")
        else:
            await bus.emit("core", "system.connector_up", f"{cid} is back up",
                           level="info")
            _notify(f"✅ RESOLVE: {cid} is back up.", level="info")

    _prev_state = current


def for_prompt() -> str:
    """The system-prompt block. "" when everything's fine or nothing is known yet.

    Never blocks: reads the cache and kicks a background refresh if it's cold or
    stale, so the cost of health-awareness is never paid by the person waiting
    for a reply.
    """
    if _stale():
        _refresh_in_background()
    broken = dead()
    if not broken:
        return ""
    lines = "\n".join(f"- {cid}: {reason}" for cid, reason in sorted(broken.items()))
    return (
        "CONNECTOR STATUS — these lanes were verified BROKEN just now, by a real "
        "authenticated call, not a guess:\n"
        f"{lines}\n"
        "Treat this as fact about your own tools. Do not plan around a broken lane "
        "and do not blame the user for it. If a request needs one of these, DO "
        "EVERY PART THAT DOESN'T FIRST and deliver it in the same reply, then state "
        "which part is blocked and quote the reason above. If several failures share "
        "one cause, say it once. Everything not listed here is working — don't "
        "pre-emptively apologise for tools that are fine."
    )
