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
