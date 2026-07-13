"""SimpleFIN Bridge — read-only bank data (balances + transactions) for the
finance page. Personal-friendly: Trav connects his banks on the SimpleFIN
Bridge site, gets a one-time Setup Token, and we claim it for a durable Access
URL (basic-auth creds baked in). Bank credentials never touch us — they go to
SimpleFIN/his bank only.

Access URL is stored in Supabase (table `simplefin`) so it survives restarts;
SIMPLEFIN_ACCESS_URL env var takes precedence if set (DB-free option).
"""

from __future__ import annotations

import base64
import datetime
import json
import os
from collections import defaultdict
from typing import Any

import requests

from .. import store

_SNAP_TYPE = "finance.snapshot"
_RAW_TYPE = "finance.raw"  # cached raw SimpleFIN pull (once/day) in agent_events


def _stored_access_url() -> str | None:
    env = os.getenv("SIMPLEFIN_ACCESS_URL")
    if env:
        return env.strip()
    try:
        rows = store.select("simplefin", {"order": "created_at.desc", "limit": "1"})
        if rows:
            return (rows[0].get("access_url") or "").strip() or None
    except Exception:
        pass
    return None


def configured() -> bool:
    return bool(_stored_access_url())


def claim(setup_token: str) -> str:
    """Exchange a one-time SimpleFIN Setup Token for a durable Access URL and
    persist it. Returns the Access URL (a secret — don't surface it).

    Setup tokens are SINGLE-USE, so we verify we can persist BEFORE consuming the
    token — otherwise a claim can succeed while the save fails, wasting the token.
    """
    if not os.getenv("SIMPLEFIN_ACCESS_URL"):
        try:
            store.select("simplefin", {"limit": "1"})  # table must exist + be reachable
        except Exception as exc:
            raise RuntimeError(
                "Storage not ready — create the 'simplefin' table first "
                "(run infra/postgres/002_simplefin.sql in the Supabase SQL editor), "
                "then paste a NEW setup token. "
                f"({exc})"
            )

    token = setup_token.strip()
    claim_url = base64.b64decode(token).decode("utf-8").strip()
    resp = requests.post(claim_url, timeout=20)
    if resp.status_code == 403:
        raise RuntimeError(
            "SimpleFIN rejected this token (403) — it was already used. Setup tokens "
            "are single-use; generate a fresh one on SimpleFIN Bridge and paste that."
        )
    resp.raise_for_status()
    access_url = resp.text.strip()
    if not access_url.startswith("http"):
        raise ValueError("SimpleFIN claim did not return an access URL")
    store.insert("simplefin", {"access_url": access_url})
    return access_url


def _cached_raw(max_age_hours: float = 20.0) -> dict[str, Any] | None:
    """Most recent cached SimpleFIN pull, if it's still fresh enough to reuse."""
    try:
        rows = store.select("agent_events", {
            "event_type": f"eq.{_RAW_TYPE}", "order": "created_at.desc", "limit": "1",
        })
    except Exception:
        return None
    if not rows:
        return None
    ts = rows[0].get("created_at")
    try:
        dt = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        age_h = (datetime.datetime.now(datetime.timezone.utc) - dt).total_seconds() / 3600
        if age_h > max_age_hours:
            return None
    except Exception:
        return None
    p = rows[0].get("payload") or {}
    if isinstance(p, str):
        try:
            p = json.loads(p)
        except Exception:
            return None
    return p.get("data")


def last_fetch_iso() -> str | None:
    try:
        rows = store.select("agent_events", {
            "event_type": f"eq.{_RAW_TYPE}", "order": "created_at.desc", "limit": "1",
        })
        return rows[0].get("created_at") if rows else None
    except Exception:
        return None


def _fetch(force: bool = False) -> dict[str, Any]:
    """Pull the full 90-day window, but at most once/day: served from the Supabase
    cache unless it's stale or a refresh is forced. Cuts SimpleFIN calls to ~1/day."""
    if not force:
        cached = _cached_raw()
        if cached is not None:
            return cached
    access_url = _stored_access_url()
    if not access_url:
        raise RuntimeError("SimpleFIN not connected")
    start = int(
        (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=90)).timestamp()
    )
    r = requests.get(
        f"{access_url.rstrip('/')}/accounts",
        params={"start-date": start},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    try:
        store.insert("agent_events", {
            "event_type": _RAW_TYPE, "actor": "core",
            "payload": {"data": data, "fetched": datetime.datetime.now(datetime.timezone.utc).isoformat()},
        })
    except Exception:
        pass
    return data


def _classify(accounts: list[dict[str, Any]]):
    """Split accounts into (checking, savings, others) by name, with a fallback
    for a simple setup: checking = the busiest account, savings = the next."""
    checking = savings = None
    others: list[dict] = []
    for a in accounts:
        n = (a.get("name") or "").lower()
        if savings is None and "sav" in n:
            savings = a
        elif checking is None and any(
            k in n for k in ("check", "chk", "advantage", "adv plus", "core", "spending")
        ):
            checking = a
        else:
            others.append(a)
    pool = sorted(others, key=lambda a: len(a.get("_txns", [])), reverse=True)
    if checking is None and pool:
        checking = pool.pop(0)
    if savings is None and pool:
        savings = pool.pop(0)
    return checking, savings, pool


def _load_snapshots() -> dict[str, dict[str, float]]:
    """date_iso -> balances, from agent_events (reuses the existing table — no
    migration needed). Latest row per date wins."""
    out: dict[str, dict[str, float]] = {}
    try:
        rows = store.select("agent_events", {
            "event_type": f"eq.{_SNAP_TYPE}", "order": "created_at.asc", "limit": "500",
        })
    except Exception:
        return out
    for r in rows:
        p = r.get("payload") or {}
        if isinstance(p, str):
            try:
                p = json.loads(p)
            except Exception:
                continue
        d = p.get("date")
        if d:
            out[d] = {
                "checking": float(p.get("checking") or 0),
                "savings": float(p.get("savings") or 0),
                "net_worth": float(p.get("net_worth") or 0),
            }
    return out


def _record_snapshot(day: str, checking: float, savings: float, net_worth: float) -> None:
    try:
        store.insert("agent_events", {
            "event_type": _SNAP_TYPE,
            "actor": "core",
            "payload": {"date": day, "checking": round(checking, 2),
                        "savings": round(savings, 2), "net_worth": round(net_worth, 2)},
        })
    except Exception:
        pass


def summary(days: int = 30, refresh: bool = False) -> dict[str, Any]:
    """Simplified money view: checking + savings balances, checking net P/L over
    the window, a net-worth line series (reconstructed from ≤90d of transactions,
    extended over time by daily snapshots), and recent transactions.

    Reads from the once/day Supabase cache unless `refresh` is set."""
    data = _fetch(force=refresh)  # cached; SimpleFIN caps history at 90 days
    parsed: list[dict[str, Any]] = []
    txns_out: list[dict[str, Any]] = []
    day_delta: dict[str, float] = defaultdict(float)  # date -> net amount that day (all accounts)

    for acct in data.get("accounts", []):
        try:
            bal = float(acct.get("balance", 0) or 0)
        except (TypeError, ValueError):
            bal = 0.0
        name = acct.get("name") or acct.get("id")
        atx: list[dict[str, Any]] = []
        for t in acct.get("transactions", []):
            try:
                amt = float(t.get("amount", 0) or 0)
            except (TypeError, ValueError):
                continue
            posted = int(t.get("posted") or t.get("transacted_at") or 0)
            iso = (datetime.datetime.fromtimestamp(posted, datetime.timezone.utc).date().isoformat()
                   if posted else "")
            atx.append({"amount": amt, "date": iso})
            if iso:
                day_delta[iso] += amt
            txns_out.append({
                "id": t.get("id"), "account": name, "amount": amt,
                "description": (t.get("description") or t.get("payee") or "").strip(),
                "date": iso, "pending": bool(t.get("pending")),
            })
        parsed.append({"id": acct.get("id"), "name": name, "balance": bal, "_txns": atx})

    checking, savings, others = _classify(parsed)
    net_worth = round(sum(a["balance"] for a in parsed), 2)
    today = datetime.datetime.now(datetime.timezone.utc).date()
    today_iso = today.isoformat()

    win = min(days, 90)  # transactions only reach 90 days back
    cutoff = (today - datetime.timedelta(days=win)).isoformat()
    checking_pl = round(
        sum(t["amount"] for t in (checking or {}).get("_txns", []) if t["date"] >= cutoff), 2
    )
    earnings = round(sum(t["amount"] for a in parsed for t in a["_txns"]
                         if t["amount"] > 0 and t["date"] >= cutoff), 2)
    expenses = round(-sum(t["amount"] for a in parsed for t in a["_txns"]
                          if t["amount"] < 0 and t["date"] >= cutoff), 2)

    # one snapshot per day, stored so the net-worth line extends past 90 days over time
    snaps = _load_snapshots()
    if today_iso not in snaps:
        _record_snapshot(today_iso, checking["balance"] if checking else 0.0,
                         savings["balance"] if savings else 0.0, net_worth)
        snaps[today_iso] = {"checking": checking["balance"] if checking else 0.0,
                            "savings": savings["balance"] if savings else 0.0,
                            "net_worth": net_worth}

    # reconstruct daily net worth for the last ≤90 days (walk backwards from today)
    recon: dict[str, float] = {today_iso: net_worth}
    bal = net_worth
    d = today
    for _ in range(win):
        bal -= day_delta.get(d.isoformat(), 0.0)  # remove that day's txns -> prior day's close
        d = d - datetime.timedelta(days=1)
        recon[d.isoformat()] = round(bal, 2)

    start_iso = (today - datetime.timedelta(days=days)).isoformat()
    merged: dict[str, float] = {ds: v["net_worth"] for ds, v in snaps.items() if ds >= start_iso}
    merged.update({ds: v for ds, v in recon.items() if ds >= start_iso})
    series = [{"date": ds, "value": merged[ds]} for ds in sorted(merged)]

    txns_out.sort(key=lambda x: x["date"], reverse=True)
    acct_out = lambda a: ({"name": a["name"], "balance": round(a["balance"], 2)} if a else None)

    return {
        "days": days,
        "capped": days > 90,
        "lastFetch": last_fetch_iso(),
        "checking": acct_out(checking),
        "savings": acct_out(savings),
        "other": [acct_out(a) for a in others],
        "netWorth": net_worth,
        "checkingPL": checking_pl,
        "earnings": earnings,
        "expenses": expenses,
        "netWorthSeries": series,
        "transactions": txns_out[:60],
    }
