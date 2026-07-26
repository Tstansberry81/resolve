"""Canvas assignments WITHOUT an API key.

UVA doesn't let students mint Canvas API tokens, which kills the normal
`/api/v1/courses/:id/assignments` route the system plan assumed. The workaround
is a Canvas feature that needs no institutional approval at all: every user can
generate a personal **calendar feed** — Canvas → Calendar → "Calendar Feed" —
which is a permanent, secret ICS URL carrying every assignment due date and
calendar event across all enrolled courses.

What this gets us: assignment titles, due dates, and course names — the 90% of
Canvas that actually drives Trav's week, refreshed automatically, no scraping
and no login. What it does NOT get: grades, submission status, announcements,
or rubric detail. Those genuinely need a session, so they route through the
laptop worker's authenticated browser instead (`run_on_laptop`), where he's
already logged in.

Setup: paste the feed URL into CANVAS_ICS_URL. It's a bearer-style secret — the
URL alone reads the calendar — so it belongs in Render's env, not in git.

ICS is parsed by hand here rather than adding an `icalendar` dependency: the
subset Canvas emits (VEVENT with SUMMARY/DTSTART/DTEND/URL/DESCRIPTION, RFC 5545
line folding, backslash escapes) is small and stable.
"""

from __future__ import annotations

import datetime as dt
import os
import re

import requests

# Canvas titles assignment events as "Assignment Title [COURSE CODE]".
_COURSE_SUFFIX = re.compile(r"\s*\[([^\]]+)\]\s*$")


def configured() -> bool:
    return bool(os.getenv("CANVAS_ICS_URL"))


def _unfold(raw: str) -> list[str]:
    """RFC 5545 folds long lines by starting the continuation with a space or
    tab. Unfold before parsing or long assignment titles arrive truncated."""
    out: list[str] = []
    for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line[:1] in (" ", "\t") and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out


def _unescape(value: str) -> str:
    return (value.replace("\\n", "\n").replace("\\,", ",")
                 .replace("\\;", ";").replace("\\\\", "\\"))


def _parse_dt(value: str) -> dt.datetime | None:
    """Canvas emits UTC stamps (20260731T035959Z) for timed due dates and bare
    dates (20260731) for all-day events."""
    value = value.strip()
    for fmt, utc in (("%Y%m%dT%H%M%SZ", True), ("%Y%m%dT%H%M%S", False),
                     ("%Y%m%d", False)):
        try:
            parsed = dt.datetime.strptime(value, fmt)
            return parsed.replace(tzinfo=dt.timezone.utc) if utc else parsed
        except ValueError:
            continue
    return None


def parse_ics(raw: str) -> list[dict]:
    """ICS text -> event dicts. Pure function, so it's testable without network."""
    events: list[dict] = []
    current: dict | None = None
    for line in _unfold(raw):
        if line.startswith("BEGIN:VEVENT"):
            current = {}
            continue
        if line.startswith("END:VEVENT"):
            if current:
                events.append(current)
            current = None
            continue
        if current is None or ":" not in line:
            continue
        name, _, value = line.partition(":")
        key = name.split(";", 1)[0].upper()
        if key == "SUMMARY":
            title = _unescape(value).strip()
            course = ""
            match = _COURSE_SUFFIX.search(title)
            if match:
                course = match.group(1).strip()
                title = _COURSE_SUFFIX.sub("", title).strip()
            current["title"], current["course"] = title, course
        elif key in ("DTSTART", "DTEND"):
            when = _parse_dt(value)
            if when:
                current["due" if key == "DTSTART" else "end"] = when
        elif key == "URL":
            current["url"] = _unescape(value).strip()
        elif key == "UID":
            current["uid"] = value.strip()
    return events


def upcoming(days: int = 14) -> dict:
    """Assignments and Canvas events due in the next `days`, soonest first."""
    url = os.getenv("CANVAS_ICS_URL")
    if not url:
        raise RuntimeError(
            "Canvas isn't connected. In Canvas open Calendar → 'Calendar Feed', copy "
            "the ICS link, and set it as CANVAS_ICS_URL — no API key needed.")
    r = requests.get(url, timeout=25)
    r.raise_for_status()

    now = dt.datetime.now(dt.timezone.utc)
    horizon = now + dt.timedelta(days=max(1, min(int(days or 14), 60)))
    rows = []
    for ev in parse_ics(r.text):
        due = ev.get("due")
        if not due:
            continue
        # All-day events parse naive; treat them as UTC so comparison is valid.
        if due.tzinfo is None:
            due = due.replace(tzinfo=dt.timezone.utc)
        if not (now - dt.timedelta(hours=12) <= due <= horizon):
            continue
        rows.append({
            "title": ev.get("title", "(untitled)"),
            "course": ev.get("course", ""),
            "due": due.astimezone().strftime("%a %b %d, %-I:%M %p"),
            "dueIso": due.isoformat(),
            "url": ev.get("url", ""),
            "overdue": due < now,
        })
    rows.sort(key=lambda r_: r_["dueIso"])
    return {"days": days, "count": len(rows), "assignments": rows[:50]}
