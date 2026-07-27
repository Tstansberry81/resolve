"""Realistic API payloads for the tool smoke suite.

These are shaped like what the real services actually return - Composio's `data`
envelope, Google's field names, Spotify's nesting, GitHub's REST bodies, OSRM and
Open-Meteo. Mocking at this layer (the network boundary) rather than at the
connector function means the connector's own field extraction is under test,
which is where the realistic bugs live: a renamed key, a null that isn't
handled, a list that comes back as a dict.
"""

from __future__ import annotations

from typing import Any


# --- Composio ---------------------------------------------------------------

def composio_payload(slug: str, args: dict[str, Any]) -> dict[str, Any]:
    """Stand in for composio.execute(). Returns the `data` payload per slug."""
    if slug.startswith("GOOGLEDOCS_CREATE"):
        return {"documentId": "doc123", "title": args.get("title", "")}
    if slug == "GOOGLEDOCS_GET_DOCUMENT_PLAINTEXT":
        return {"plain_text": "Intro paragraph.\n\nSecond paragraph here.\n"}
    if slug == "GOOGLEDOCS_REPLACE_ALL_TEXT":
        # Composio returns the Docs API's own camelCase count.
        return {"occurrencesChanged": 2}
    if slug == "GOOGLEDOCS_INSERT_TEXT_ACTION":
        return {"documentId": args.get("document_id")}
    if slug.startswith("GOOGLESHEETS_CREATE") or slug.startswith("GOOGLESHEETS_SPREADSHEET_CREATE"):
        return {"spreadsheetId": "sheet123"}
    if slug == "GOOGLESHEETS_VALUES_GET":
        return {"values": [["Item", "Cost"], ["Books", "120"]]}
    if slug == "GOOGLESHEETS_VALUES_UPDATE":
        return {"updatedCells": 4}
    if slug.startswith("GOOGLESLIDES"):
        return {"presentationId": "deck123"}
    if slug.startswith("GOOGLEDRIVE"):
        return {"files": [{"id": "f1", "name": "Q3 report", "mimeType": "application/pdf",
                           "webViewLink": "https://drive.google.com/file/d/f1"}]}
    if slug == "GMAIL_CREATE_EMAIL_DRAFT":
        return {"id": "draft789", "threadId": "t123"}
    if slug == "SPOTIFY_SEARCH_FOR_ITEM":
        kind = (args.get("type") or ["track"])[0]
        return {f"{kind}s": {"items": [
            {"name": "Luna", "uri": f"spotify:{kind}:abc",
             "artists": [{"name": "Feid"}]},
        ]}}
    if slug == "SPOTIFY_GET_PLAYBACK_STATE":
        return {"is_playing": True, "item": {
            "name": "Luna", "artists": [{"name": "Feid"}], "album": {"name": "FERXXO"}}}
    if slug == "SPOTIFY_GET_USER_S_TOP_ARTISTS":
        return {"items": [
            {"name": "Feid", "genres": ["reggaeton", "urbano latino"]},
            {"name": "Bad Bunny", "genres": ["reggaeton", "trap latino"]},
        ]}
    if slug == "SPOTIFY_GET_USER_S_TOP_TRACKS":
        return {"items": [{"name": "Luna", "uri": "spotify:track:1",
                           "artists": [{"name": "Feid"}]}]}
    if slug == "SPOTIFY_GET_RECENTLY_PLAYED_TRACKS":
        return {"items": [{"played_at": "2026-07-26T20:00:00Z", "track": {
            "name": "Luna", "uri": "spotify:track:1", "artists": [{"name": "Feid"}]}}]}
    if slug.startswith("SPOTIFY_"):
        return {}
    if slug.startswith("SERPAPI") or "SHOPPING" in slug or "SEARCH" in slug:
        return {"shopping_results": [
            {"title": "Sony WH-1000XM5", "price": "$328.00", "extracted_price": 328.0,
             "link": "https://example.com/p", "rating": 4.7, "source": "Best Buy"},
        ]}
    return {}


# --- HTTP services ----------------------------------------------------------

def open_meteo_geocode() -> dict:
    return {"results": [{"name": "Charlottesville", "admin1": "Virginia",
                         "country_code": "US", "latitude": 38.03, "longitude": -78.47}]}


def open_meteo_forecast() -> dict:
    return {
        "current": {"temperature_2m": 81.3, "apparent_temperature": 84.0,
                    "weather_code": 3, "wind_speed_10m": 7.2, "precipitation": 0.0},
        "daily": {"time": ["2026-07-26", "2026-07-27"],
                  "weather_code": [3, 61],
                  "temperature_2m_max": [88.0, 79.0],
                  "temperature_2m_min": [68.0, 65.0],
                  "precipitation_probability_max": [10, 80],
                  "sunrise": ["2026-07-26T06:10", "2026-07-27T06:11"],
                  "sunset": ["2026-07-26T20:31", "2026-07-27T20:30"]},
    }


def osrm_route() -> dict:
    return {"routes": [{"duration": 4500.0, "distance": 112000.0}]}


CANVAS_ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:assignment-1
DTSTART:20260801T035959Z
SUMMARY:Problem Set 4 [APMA 2120]
URL:https://canvas.its.virginia.edu/courses/1/assignments/9
END:VEVENT
BEGIN:VEVENT
UID:assignment-2
DTSTART:20260730T035959Z
SUMMARY:Essay Draft [ENWR 1510]
END:VEVENT
END:VCALENDAR
"""


def github_issues() -> list:
    return [
        {"number": 12, "title": "Vault recall returns nothing", "state": "open",
         "html_url": "https://github.com/x/y/issues/12", "labels": [{"name": "bug"}],
         "updated_at": "2026-07-26T10:00:00Z"},
        {"number": 13, "title": "A PR not an issue", "state": "open",
         "html_url": "u", "labels": [], "updated_at": "2026-07-26T11:00:00Z",
         "pull_request": {"url": "..."}},
    ]


def github_pulls() -> list:
    return [{"number": 14, "title": "Add Canvas feed", "state": "open",
             "html_url": "https://github.com/x/y/pull/14", "draft": False,
             "head": {"ref": "canvas-feed"}, "updated_at": "2026-07-26T09:00:00Z"}]


def github_runs() -> dict:
    return {"workflow_runs": [
        {"name": "control-plane checks", "conclusion": "success", "status": "completed",
         "head_branch": "main", "html_url": "u1", "created_at": "2026-07-26T22:47:00Z",
         "head_commit": {"message": "Fix CI\n\nbody"}},
        {"name": "control-plane checks", "conclusion": None, "status": "in_progress",
         "head_branch": "main", "html_url": "u2", "created_at": "2026-07-26T23:00:00Z",
         "head_commit": {"message": "wip"}},
    ]}


# --- Google Calendar / Notion / Gmail ---------------------------------------

def gcal_events() -> list:
    return [{"id": "ev1", "summary": "Lunch with Mom",
             "start": "2026-07-27T12:00:00-04:00", "end": "2026-07-27T13:00:00-04:00",
             "location": "Charlottesville"}]


def notion_tasks() -> list:
    return [{"id": "page1", "title": "Finish problem set", "due": "2026-07-28",
             "priority": "High"}]


# --- Notion (raw API shapes, for the generic workspace tools) ---------------
# These are the real nested payloads, not pre-flattened, so the connector's own
# property coercion and flattening are what's under test.

def notion_rich(text: str) -> list:
    return [{"type": "text", "plain_text": text, "text": {"content": text}}]


def notion_search_results() -> dict:
    return {"results": [
        {"object": "database", "id": "db-classes", "url": "https://notion.so/db-classes",
         "title": notion_rich("Classes"), "parent": {"type": "workspace"},
         "last_edited_time": "2026-07-25T10:00:00.000Z"},
        {"object": "page", "id": "page-fall", "url": "https://notion.so/page-fall",
         "parent": {"type": "workspace"}, "last_edited_time": "2026-07-24T10:00:00.000Z",
         "properties": {"Name": {"type": "title", "title": notion_rich("Fall 2026")}}},
    ]}


def notion_database() -> dict:
    """A Classes database — the case that started this: not the Tasks inbox."""
    return {
        "object": "database", "id": "db-classes", "url": "https://notion.so/db-classes",
        "title": notion_rich("Classes"),
        "properties": {
            "Name": {"type": "title", "title": {}},
            "Days": {"type": "multi_select", "multi_select": {"options": [
                {"name": "Mon"}, {"name": "Tue"}, {"name": "Wed"},
                {"name": "Thu"}, {"name": "Fri"}]}},
            "Term": {"type": "select", "select": {"options": [
                {"name": "Fall 2026"}, {"name": "Spring 2027"}]}},
            "Credits": {"type": "number", "number": {}},
            "Starts": {"type": "date", "date": {}},
            "Room": {"type": "rich_text", "rich_text": {}},
            "Done": {"type": "checkbox", "checkbox": {}},
            "Load": {"type": "formula", "formula": {}},  # computed: must be skipped
        },
    }


def notion_query_results() -> dict:
    return {"results": [{
        "id": "row-calc", "url": "https://notion.so/row-calc",
        "properties": {
            "Name": {"type": "title", "title": notion_rich("Calculus I")},
            "Days": {"type": "multi_select", "multi_select": [{"name": "Mon"}, {"name": "Wed"}]},
            "Term": {"type": "select", "select": {"name": "Fall 2026"}},
            "Credits": {"type": "number", "number": 4},
            "Starts": {"type": "date", "date": {"start": "2026-08-25"}},
            "Room": {"type": "rich_text", "rich_text": notion_rich("Clark 107")},
            "Done": {"type": "checkbox", "checkbox": False},
            "Load": {"type": "formula", "formula": {"type": "number", "number": 12}},
            "Prof": {"type": "people", "people": [{"name": "Dr. Reid"}]},
        },
    }]}


def notion_page() -> dict:
    return {
        "object": "page", "id": "row-calc", "url": "https://notion.so/row-calc",
        "parent": {"type": "database_id", "database_id": "db-classes"},
        "properties": notion_query_results()["results"][0]["properties"],
    }


def notion_blocks() -> dict:
    return {"results": [
        {"type": "heading_2", "heading_2": {"rich_text": notion_rich("Syllabus")}},
        {"type": "bulleted_list_item",
         "bulleted_list_item": {"rich_text": notion_rich("Midterm Oct 3")}},
        {"type": "to_do", "to_do": {"rich_text": notion_rich("Buy textbook"), "checked": False}},
        {"type": "paragraph", "paragraph": {"rich_text": []}},  # empty block: skipped
    ]}


def notion_created_page() -> dict:
    return {"object": "page", "id": "new-page", "url": "https://notion.so/new-page",
            "properties": {"Name": {"type": "title", "title": notion_rich("Calculus I")}}}


def inbox_messages() -> dict:
    return {"messages": [
        {"uid": "101", "from": "prof@virginia.edu", "subject": "Office hours moved",
         "unread": True, "snippet": "Moving to Thursday 2pm"},
        {"uid": "102", "from": "deals@store.com", "subject": "50% OFF",
         "unread": True, "snippet": "Sale ends soon"},
    ], "count": 2}
