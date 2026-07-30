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
