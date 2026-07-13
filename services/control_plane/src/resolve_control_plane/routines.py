"""Proactive routines — RESOLVE acts without being asked.

The scheduler ticks once a minute; inside the 7:00-7:10am ET window it runs
the morning brief once per day through the normal Sonnet loop, so the brief
streams into the dashboard and lands in the vault like any other goal.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from . import bus

log = logging.getLogger("resolve.routines")

_last_brief_date: str | None = None
_last_ingest_date: str | None = None

BRIEF_PROMPT = (
    "Morning brief: check my calendar for the next 2 days, my open Notion tasks,"
    " and my unread email (skip any connector that errors instead of stopping)."
    " Write a short, warm morning brief with the highlights and anything urgent,"
    " then vault_log it titled 'Morning brief' with today's date."
)


async def run_morning_brief() -> str:
    from .assistant import run_command

    global _last_brief_date
    _last_brief_date = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    await bus.emit("core", "routine.morning_brief",
                   "Morning brief routine kicked off", level="info")
    return await run_command(BRIEF_PROMPT)


async def scheduler_loop() -> None:
    log.info("routine scheduler started")
    while True:
        try:
            now = datetime.now(ZoneInfo("America/New_York"))
            today = now.strftime("%Y-%m-%d")
            # midnight: ingest the prior day's activity into the vault (once/day)
            global _last_ingest_date
            if now.hour == 0 and now.minute < 10 and _last_ingest_date != today:
                _last_ingest_date = today
                from . import ingest
                await ingest.run_daily_ingest()
            if (now.hour == 7 and now.minute < 10
                    and _last_brief_date != today):
                await run_morning_brief()
        except Exception:
            log.exception("routine tick failed")
        try:
            from . import costs
            await asyncio.to_thread(costs.persist)  # flush cost totals to Supabase
        except Exception:
            log.exception("cost flush failed")
        await asyncio.sleep(60)
