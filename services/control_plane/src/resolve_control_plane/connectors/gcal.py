"""Google Calendar — service-account auth, same env names as the vault1 bot
(GOOGLE_SERVICE_ACCOUNT_JSON holds the full key JSON, GOOGLE_CALENDAR_ID the
calendar)."""

from __future__ import annotations

import datetime as dt
import json
import os

from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def configured() -> bool:
    return bool(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON") and os.getenv("GOOGLE_CALENDAR_ID"))


def _service():
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def list_events(days: int = 7) -> list[dict]:
    svc = _service()
    now = dt.datetime.now(dt.timezone.utc)
    resp = (
        svc.events()
        .list(
            calendarId=os.environ["GOOGLE_CALENDAR_ID"],
            timeMin=now.isoformat(),
            timeMax=(now + dt.timedelta(days=days)).isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=25,
        )
        .execute()
    )
    out = []
    for ev in resp.get("items", []):
        start = ev.get("start", {})
        out.append(
            {
                "id": ev.get("id"),
                "title": ev.get("summary", "(untitled)"),
                "start": start.get("dateTime") or start.get("date"),
                "location": ev.get("location"),
            }
        )
    return out


def create_event(title: str, start_iso: str, end_iso: str, description: str = "") -> dict:
    svc = _service()
    body = {
        "summary": title,
        "description": description,
        "start": {"dateTime": start_iso},
        "end": {"dateTime": end_iso},
    }
    ev = svc.events().insert(calendarId=os.environ["GOOGLE_CALENDAR_ID"], body=body).execute()
    return {"id": ev.get("id"), "title": title, "link": ev.get("htmlLink")}


def delete_event(event_id: str) -> dict:
    svc = _service()
    svc.events().delete(calendarId=os.environ["GOOGLE_CALENDAR_ID"], eventId=event_id).execute()
    return {"deleted": True, "id": event_id}
