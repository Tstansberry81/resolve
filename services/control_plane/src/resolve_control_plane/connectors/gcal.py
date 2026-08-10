"""Google Calendar — service-account auth, same env names as the vault1 bot
(GOOGLE_SERVICE_ACCOUNT_JSON holds the full key JSON, GOOGLE_CALENDAR_ID the
calendar)."""

from __future__ import annotations

import datetime as dt
import json
import os
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def configured() -> bool:
    return bool(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON") and os.getenv("GOOGLE_CALENDAR_ID"))


def _service():
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


MAX_EVENTS = int(os.getenv("GCAL_MAX_EVENTS", "250"))


def list_events(days: int = 7) -> list[dict]:
    """Events in the next ``days``, paginated.

    This used to ask for a single page of maxResults=25 and return whatever came
    back. Because singleEvents=True expands every recurring event into one row
    per occurrence, a few weekly classes burn 25 rows inside two days -- so the
    horizon silently collapsed to a couple of days regardless of ``days``, and a
    class further out simply did not exist as far as the model could tell. It had
    no way to know it was looking at a truncated list, so it reasonably concluded
    the events weren't there.

    Rows also carry ``end`` and ``series_id`` now. Without an end time there was
    no way to answer "when does that class finish", and with singleEvents=True
    ``id`` is the OCCURRENCE -- deleting it removes one meeting and leaves the
    series. ``series_id`` (recurringEventId) is what a "delete the class" has to
    target.
    """
    svc = _service()
    now = dt.datetime.now(dt.timezone.utc)
    horizon = now + dt.timedelta(days=days)
    out: list[dict] = []
    page_token: str | None = None
    truncated = False

    while True:
        resp = (
            svc.events()
            .list(
                calendarId=os.environ["GOOGLE_CALENDAR_ID"],
                timeMin=now.isoformat(),
                timeMax=horizon.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=250,
                pageToken=page_token,
            )
            .execute()
        )
        for ev in resp.get("items", []):
            if len(out) >= MAX_EVENTS:
                truncated = True
                break
            start, end = ev.get("start", {}), ev.get("end", {})
            out.append(
                {
                    "id": ev.get("id"),
                    "title": ev.get("summary", "(untitled)"),
                    "start": start.get("dateTime") or start.get("date"),
                    "end": end.get("dateTime") or end.get("date"),
                    "location": ev.get("location"),
                    # Present only on occurrences of a recurring series. Delete
                    # THIS to remove the whole class; delete `id` for one meeting.
                    "series_id": ev.get("recurringEventId"),
                }
            )
        page_token = resp.get("nextPageToken")
        if truncated or not page_token:
            break

    if truncated:
        # In-band, because a silently short list is what caused the original
        # confusion -- the model has to be able to see its own horizon.
        out.append({
            "id": None,
            "title": (f"[TRUNCATED — first {MAX_EVENTS} events only; the {days}-day "
                      "window holds more. Ask again with a shorter `days`.]"),
            "start": None, "end": None, "location": None, "series_id": None,
        })
    return out


DEFAULT_TZ = os.getenv("RESOLVE_TIMEZONE", "America/New_York")


def _wall_time(start_iso: str) -> str:
    """"HHMMSS" of the first occurrence, for EXDATE stamps."""
    try:
        return dt.datetime.fromisoformat(start_iso.replace("Z", "+00:00")).strftime("%H%M%S")
    except ValueError:
        return "000000"


def create_event(
    title: str,
    start_iso: str,
    end_iso: str,
    description: str = "",
    recurrence: str = "",
    exclude_dates: list[str] | None = None,
    time_zone: str = "",
) -> dict:
    """Create an event. ``recurrence`` is an RFC 5545 RRULE for a repeating one.

    Without it a semester-long class had to be booked as ~45 separate one-off
    events: 45 API calls, 45 rows, and 45 deletions when the room changes.
    Google takes the whole series as one field, so a class is one event:

        RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR;UNTIL=20261209T235959Z

    ``start_iso``/``end_iso`` are the FIRST meeting; the rule repeats it. UNTIL
    is UTC and must end in Z. Editing or deleting the returned id hits the whole
    series, which is the point.

    ``exclude_dates`` are YYYY-MM-DD days the series skips -- breaks, holidays,
    reading days -- emitted as EXDATE so they never exist rather than being
    deleted one at a time afterwards.

    A named ``timeZone`` is ALWAYS sent. Google rejects a recurring event without
    one ("Missing time zone definition for start time") no matter what offset the
    dateTime carries, because expanding an RRULE across a DST boundary needs a
    zone, not a fixed offset. Filed as resolve#1 after every recurring create
    404'd -- both -04:00 and Z forms.
    """
    svc = _service()
    tz = time_zone or DEFAULT_TZ
    body: dict[str, Any] = {
        "summary": title,
        "description": description,
        "start": {"dateTime": start_iso, "timeZone": tz},
        "end": {"dateTime": end_iso, "timeZone": tz},
    }
    rules: list[str] = []
    if recurrence:
        rule = recurrence.strip()
        # Accept a bare "FREQ=..." too. The model writes it that way about half
        # the time and Google rejects it without the prefix -- cheaper to repair
        # here than to lose a turn to a 400.
        if not rule.upper().startswith("RRULE:"):
            rule = f"RRULE:{rule}"
        rules.append(rule)
    if exclude_dates:
        # EXDATE has to name the same wall-clock time as the occurrence it kills;
        # a bare date silently matches nothing and the class still appears.
        hhmmss = _wall_time(start_iso)
        stamps = [f"{d.replace('-', '').strip()}T{hhmmss}" for d in exclude_dates if d and d.strip()]
        if stamps:
            rules.append(f"EXDATE;TZID={tz}:" + ",".join(stamps))
    if rules:
        body["recurrence"] = rules
    ev = svc.events().insert(calendarId=os.environ["GOOGLE_CALENDAR_ID"], body=body).execute()
    return {"id": ev.get("id"), "title": title, "link": ev.get("htmlLink"),
            "recurring": bool(recurrence)}


def delete_event(event_id: str) -> dict:
    svc = _service()
    svc.events().delete(calendarId=os.environ["GOOGLE_CALENDAR_ID"], eventId=event_id).execute()
    return {"deleted": True, "id": event_id}
