"""Pushes selected bus events to Trav's Telegram through the existing bot —
the platform notifies proactively, like the prior hardcoded version did."""

from __future__ import annotations

import os

import requests


def configured() -> bool:
    return bool(os.getenv("TELEGRAM_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))


def send(text: str) -> None:
    requests.post(
        f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/sendMessage",
        json={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": text[:4000]},
        timeout=10,
    )


def send_approval(approval_id: str, summary: str, risk: str) -> None:
    """Push an approval request with inline Approve/Reject buttons. The vault1
    bot handles the button tap and POSTs the decision back to
    /v1/approvals/{id}/decide — so Trav can approve from his phone, not just the
    dashboard. callback_data stays under Telegram's 64-byte cap."""
    text = f"🔔 Approval needed\n{summary}\n\nRisk: {risk.replace('_', ' ')}"
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Approve", "callback_data": f"rslv:ok:{approval_id}"},
            {"text": "🚫 Reject", "callback_data": f"rslv:no:{approval_id}"},
        ]]
    }
    requests.post(
        f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/sendMessage",
        json={
            "chat_id": os.environ["TELEGRAM_CHAT_ID"],
            "text": text[:4000],
            "reply_markup": keyboard,
        },
        timeout=10,
    )
