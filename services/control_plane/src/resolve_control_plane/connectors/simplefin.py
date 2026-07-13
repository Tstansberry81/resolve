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
import os
from collections import defaultdict
from typing import Any

import requests

from .. import store


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


def _fetch(days: int) -> dict[str, Any]:
    access_url = _stored_access_url()
    if not access_url:
        raise RuntimeError("SimpleFIN not connected")
    start = int(
        (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)).timestamp()
    )
    r = requests.get(
        f"{access_url.rstrip('/')}/accounts",
        params={"start-date": start},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def summary(days: int = 90) -> dict[str, Any]:
    """Aggregate accounts + transactions into earnings vs expenses for the page.
    SimpleFIN amounts: positive = money in (earnings), negative = money out."""
    data = _fetch(days)
    accounts_out: list[dict[str, Any]] = []
    txns_out: list[dict[str, Any]] = []
    earnings = 0.0
    expenses = 0.0
    by_month: dict[str, dict[str, float]] = defaultdict(lambda: {"earnings": 0.0, "expenses": 0.0})

    for acct in data.get("accounts", []):
        try:
            bal = float(acct.get("balance", 0) or 0)
        except (TypeError, ValueError):
            bal = 0.0
        accounts_out.append({
            "id": acct.get("id"),
            "name": acct.get("name") or acct.get("id"),
            "org": (acct.get("org") or {}).get("name"),
            "balance": bal,
            "currency": acct.get("currency", "USD"),
        })
        for t in acct.get("transactions", []):
            try:
                amt = float(t.get("amount", 0) or 0)
            except (TypeError, ValueError):
                continue
            posted = int(t.get("posted") or t.get("transacted_at") or 0)
            iso = (
                datetime.datetime.fromtimestamp(posted, datetime.timezone.utc).date().isoformat()
                if posted else ""
            )
            month = iso[:7]
            if amt >= 0:
                earnings += amt
                if month:
                    by_month[month]["earnings"] += amt
            else:
                expenses += -amt
                if month:
                    by_month[month]["expenses"] += -amt
            txns_out.append({
                "id": t.get("id"),
                "account": acct.get("name") or acct.get("id"),
                "amount": amt,
                "description": (t.get("description") or t.get("payee") or "").strip(),
                "date": iso,
                "pending": bool(t.get("pending")),
            })

    txns_out.sort(key=lambda x: x["date"], reverse=True)
    months = [
        {"month": m, "earnings": round(v["earnings"], 2), "expenses": round(v["expenses"], 2)}
        for m, v in sorted(by_month.items())
    ]
    return {
        "days": days,
        "netWorth": round(sum(a["balance"] for a in accounts_out), 2),
        "earnings": round(earnings, 2),
        "expenses": round(expenses, 2),
        "net": round(earnings - expenses, 2),
        "accounts": accounts_out,
        "byMonth": months,
        "transactions": txns_out[:60],
    }
