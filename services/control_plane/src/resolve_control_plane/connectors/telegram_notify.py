"""Trav's Telegram channel — outbound pushes AND the inbound half.

Outbound (send/send_approval) talks straight to the Bot API with TELEGRAM_TOKEN,
so it needs the bot *token*, never the legacy vault1 bot's code. Inbound (button
taps and /resolve) used to be vault1's job; the webhook in api.py handles it now
using the reply helpers below, which is what lets that service be retired.
"""

from __future__ import annotations

import os

import requests

API = "https://api.telegram.org/bot{token}/{method}"


def configured() -> bool:
    return bool(os.getenv("TELEGRAM_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))


def _call(method: str, payload: dict) -> None:
    """Fire a Bot API method. Best-effort: a Telegram blip must never take down
    an approval decision or a bus emit that already happened."""
    requests.post(API.format(token=os.environ["TELEGRAM_TOKEN"], method=method),
                  json=payload, timeout=10)


def chat_allowed(chat_id: object) -> bool:
    """Only Trav's own chat may drive the webhook. The bot token alone is not an
    authorization boundary — anyone who finds the bot can message it."""
    expected = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    return bool(expected) and str(chat_id).strip() == expected


def send(text: str) -> None:
    _call("sendMessage", {"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": text[:4000]})


def send_approval(approval_id: str, summary: str, risk: str) -> None:
    """Push an approval request with inline Approve/Reject buttons, so Trav can
    approve from his phone and not only from the dashboard. The tap comes back
    to POST /v1/telegram/webhook. callback_data stays under Telegram's 64-byte
    cap, which is why the payload is a bare `rslv:ok|no:<uuid>`."""
    text = f"🔔 Approval needed\n{summary}\n\nRisk: {risk.replace('_', ' ')}"
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Approve", "callback_data": f"rslv:ok:{approval_id}"},
            {"text": "🚫 Reject", "callback_data": f"rslv:no:{approval_id}"},
        ]]
    }
    _call("sendMessage", {"chat_id": os.environ["TELEGRAM_CHAT_ID"],
                          "text": text[:4000], "reply_markup": keyboard})


def answer_callback(callback_id: str, text: str) -> None:
    """Acknowledge a button tap. Telegram spins the button until this lands."""
    _call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:200]})


def edit_message_text(chat_id: object, message_id: int, text: str) -> None:
    """Rewrite the approval message in place after a decision — drops the inline
    keyboard so a stale card can't be tapped twice."""
    _call("editMessageText", {"chat_id": chat_id, "message_id": message_id,
                              "text": text[:4000]})


def reply_to(chat_id: object, text: str) -> None:
    """Send into a specific chat (the webhook's caller) rather than the pinned
    TELEGRAM_CHAT_ID."""
    _call("sendMessage", {"chat_id": chat_id, "text": text[:4000]})
