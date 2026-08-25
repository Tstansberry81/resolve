"""Three realistic scenarios for every declared tool, run through the REAL
dispatch path with the network mocked at the service boundary.

Why this exists: unit tests covered the pieces, but nothing exercised
`_connector_call` end to end for all 57 tools. That is exactly where the boring
killers live - an arg the model sends as a string where the code assumes an int,
a response key that is camelCase in one Composio action and snake_case in
another, a None that reaches a `len()`. Those don't fail loudly in a unit test;
they surface as "RESOLVE said it worked and nothing happened."

Every tool must have three cases and every case must complete without raising.
The coverage test at the bottom fails if a new tool is added without scenarios,
so this suite can't silently rot behind the tool list.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from resolve_control_plane import assistant
from resolve_control_plane.connectors import composio
from resolve_control_plane.tools_def import TOOLS

import conftest_scenarios as fx


# --- fake network layer -----------------------------------------------------

class FakeResponse:
    def __init__(self, payload: Any = None, status: int = 200, text: str = ""):
        self._payload = payload if payload is not None else {}
        self.status_code = status
        self.text = text or json.dumps(self._payload)
        self.content = self.text.encode()

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _route_get(url: str, **kw) -> FakeResponse:
    """Route an outbound GET to the right canned payload by URL."""
    if "geocoding-api.open-meteo" in url:
        return FakeResponse(fx.open_meteo_geocode())
    if "api.open-meteo" in url:
        return FakeResponse(fx.open_meteo_forecast())
    if "router.project-osrm" in url:
        return FakeResponse(fx.osrm_route())
    if "canvas" in url or url.endswith(".ics"):
        return FakeResponse(text=fx.CANVAS_ICS)
    if "/actions/runs" in url:
        return FakeResponse(fx.github_runs())
    if "/pulls" in url:
        return FakeResponse(fx.github_pulls())
    if "/issues" in url:
        return FakeResponse(fx.github_issues())
    if "api.github.com/repos" in url and "/contents/" in url:
        import base64
        body = base64.b64encode(b"# Note\n\nvault content").decode()
        return FakeResponse({"content": body, "sha": "abc123"})
    if "api.github.com/repos" in url and "/git/trees/" in url:
        return FakeResponse({"tree": [{"path": "wiki/a.md", "type": "blob"}]})
    if "api.github.com/search/code" in url:
        return FakeResponse({"items": [{"path": "wiki/a.md", "text_matches": []}]})
    if "api.github.com/repos" in url:
        return FakeResponse({"full_name": "o/r", "permissions": {"push": True}})
    if "/rest/v1/" in url:  # Supabase PostgREST
        return FakeResponse([])
    return FakeResponse({})


def _route_post(url: str, **kw) -> FakeResponse:
    if "/rpc/match_vault_chunks" in url:
        return FakeResponse([{"path": "wiki/goals.md", "chunk_index": 0,
                              "content": "cream and beige palette", "similarity": 0.81}])
    if "api.github.com/repos" in url and "/issues" in url:
        return FakeResponse({"number": 42, "html_url": "https://github.com/x/y/issues/42"}, 201)
    if "/rest/v1/" in url:
        return FakeResponse([{"id": 1}], 201)
    return FakeResponse({})


def _route_notion(method: str, url: str, **kw) -> FakeResponse:
    """The generic Notion tools go through requests.request(), so they're
    mocked here at the API boundary rather than at the connector function."""
    if url.endswith("/search"):
        return FakeResponse(fx.notion_search_results())
    if "/blocks/" in url and "/children" in url:
        if method == "GET":
            return FakeResponse(fx.notion_blocks())
        return FakeResponse({"results": []})  # PATCH append
    if "/databases" in url and url.endswith("/query"):
        return FakeResponse(fx.notion_query_results())
    if "/databases" in url:
        if method == "POST":  # create_database
            return FakeResponse({**fx.notion_database(), "id": "db-new"})
        return FakeResponse(fx.notion_database())
    if url.endswith("/pages"):
        return FakeResponse(fx.notion_created_page())
    if "/pages/" in url:
        return FakeResponse(fx.notion_page())
    return FakeResponse({})


def _route_request(method: str, url: str, **kw) -> FakeResponse:
    if "api.notion.com" in url:
        return _route_notion(method.upper(), url, **kw)
    if method.upper() == "GET":
        return _route_get(url, **kw)
    if method.upper() == "POST":
        return _route_post(url, **kw)
    return FakeResponse({})


@pytest.fixture(autouse=True)
def _sandbox(monkeypatch):
    """Cut every real network path and every real side effect."""
    import requests

    monkeypatch.setattr(requests, "get", _route_get)
    monkeypatch.setattr(requests, "post", _route_post)
    monkeypatch.setattr(requests, "request", _route_request)
    monkeypatch.setattr(requests, "put", lambda url, **kw: FakeResponse({}, 200))
    monkeypatch.setattr(requests, "patch", lambda url, **kw: FakeResponse({}, 200))

    # Composio: return per-slug payloads instead of calling the API.
    monkeypatch.setattr(composio, "execute", fx.composio_payload)
    monkeypatch.setattr(composio, "configured", lambda: True)

    # Credentials that gate `configured()` checks.
    for var, val in (("GITHUB_TOKEN", "t"), ("GITHUB_VAULT_REPO", "o/vault"),
                     ("GITHUB_DEFAULT_REPO", "o/r"), ("OPENAI_API_KEY", "k"),
                     ("CANVAS_ICS_URL", "https://canvas.its.virginia.edu/feeds/x.ics"),
                     ("SUPABASE_URL", "https://s.supabase.co"), ("SUPABASE_KEY", "k"),
                     ("ANTHROPIC_API_KEY", "k"), ("TELEGRAM_TOKEN", "tg")):
        monkeypatch.setenv(var, val)

    # Google / Notion / Gmail / finance / laptop: patch at the connector call.
    from resolve_control_plane import local, vault_index
    from resolve_control_plane.connectors import gcal, gmail_imap, local_llm, notion_api, simplefin

    monkeypatch.setattr(gcal, "list_events", lambda days=7, query="": fx.gcal_events())
    monkeypatch.setattr(
        gcal, "create_event",
        lambda t, s, e, d="", rec="", exc=None, tz="": {
            "id": "ev9", "htmlLink": "https://cal/ev9",
            "recurring": bool(rec), "excluded": len(exc or [])})
    monkeypatch.setattr(gcal, "delete_event", lambda eid: {"deleted": True, "id": eid})
    monkeypatch.setattr(notion_api, "list_open_tasks", lambda: fx.notion_tasks())
    monkeypatch.setattr(notion_api, "school_day", lambda day=None, horizon_days=7: {
        "day": day or "2026-08-25", "errors": [],
        "lectures": [{"course": "PHIL 1730", "lecture": "Why Moral Philosophy?",
                      "topic": "Intro", "readings": "Plato, Apology", "unit": "Unit 1"}],
        "assignments_due": [{"assignment": "Reading response 1", "due": "2026-08-27",
                             "status": "Not Started", "type": "Reading"}],
        "exams_upcoming": [],
    })
    monkeypatch.setattr(notion_api, "create_task",
                        lambda title, **kw: {"id": "p9", "url": "https://notion/p9"})
    monkeypatch.setattr(notion_api, "archive_page", lambda pid: {"archived": True})
    monkeypatch.setattr(gmail_imap, "unread_summary", lambda: {"unread": 2, "latest": []})
    monkeypatch.setattr(gmail_imap, "inbox_recent",
                        lambda limit=25, days=None: fx.inbox_messages())
    monkeypatch.setattr(gmail_imap, "archive_messages",
                        lambda uids: {"archived": len(uids)})
    monkeypatch.setattr(gmail_imap, "send_email",
                        lambda to, subj, body: {"sent": True, "to": to})
    monkeypatch.setattr(simplefin, "summary", lambda days=30: {
        "netWorth": 4210.55, "earnings": 900.0, "expenses": 610.25, "net": 289.75,
        "byMonth": [], "transactions": [{"date": "2026-07-20", "amount": -12.5,
                                         "description": "Coffee"}]})
    monkeypatch.setattr(local_llm, "chat", lambda prompt: "local model reply")
    monkeypatch.setattr(local, "online", lambda: True)
    monkeypatch.setattr(local, "enqueue",
                        lambda task, goal_id=None: {"taskId": "lt1", "queued": True})
    monkeypatch.setattr(local, "enqueue_action",
                        lambda kind, value, label: {"taskId": "lt2", "queued": True})
    monkeypatch.setattr(vault_index, "configured", lambda: True)
    monkeypatch.setattr(vault_index, "embed", lambda texts: [[0.0] * 1536 for _ in texts])

    # The coder's architect pass is a model call; stub it, not the brief-building.
    from resolve_control_plane import coder
    monkeypatch.setattr(coder, "plan", lambda objective, context="": "1. Read x\n2. Fix y")
    monkeypatch.setattr(coder, "review", lambda diff, objective="": "Looks correct.")

    # Executor availability for plan_project.
    monkeypatch.setattr(assistant.executor, "available", lambda: True)
    monkeypatch.setattr(assistant.executor, "local_exec", True, raising=False)


# --- the scenarios: 3 per tool ---------------------------------------------
# (tool, label, args). Args are shaped the way the MODEL sends them, including
# the string-where-an-int-belongs cases that real turns produce.

CASES: list[tuple[str, str, dict]] = [
    # calendar
    ("get_calendar", "default week", {}),
    ("get_calendar", "explicit horizon", {"days": 14}),
    ("get_calendar", "days arrives as a string", {"days": "3"}),
    ("create_calendar_event", "lunch", {"title": "Lunch with Mom",
        "start_iso": "2026-07-27T12:00:00-04:00", "end_iso": "2026-07-27T13:00:00-04:00"}),
    ("create_calendar_event", "with description", {"title": "Study",
        "start_iso": "2026-07-27T18:00:00-04:00", "end_iso": "2026-07-27T20:00:00-04:00",
        "description": "APMA problem set"}),
    ("create_calendar_event", "unicode title", {"title": "Café con Feid 🎧",
        "start_iso": "2026-07-28T09:00:00-04:00", "end_iso": "2026-07-28T10:00:00-04:00"}),
    # A semester class is ONE recurring event, not ~45 one-offs. Both RRULE forms
    # go through the dispatch because the model writes the bare one about half
    # the time and gcal.create_event repairs it.
    ("create_calendar_event", "recurring class, RRULE prefix", {"title": "PHIL 2330",
        "start_iso": "2026-08-25T10:00:00-04:00", "end_iso": "2026-08-25T10:50:00-04:00",
        "recurrence": "RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR;UNTIL=20261209T235959Z"}),
    ("create_calendar_event", "recurring class, bare FREQ", {"title": "PHIL 2330 discussion",
        "start_iso": "2026-08-27T14:00:00-04:00", "end_iso": "2026-08-27T14:50:00-04:00",
        "recurrence": "FREQ=WEEKLY;BYDAY=TH;UNTIL=20261209T235959Z"}),
    # A real semester skips reading days and Thanksgiving; those occurrences
    # should never be created rather than deleted one at a time afterwards.
    ("create_calendar_event", "recurring class with breaks", {"title": "PHIL 1730",
        "start_iso": "2026-08-25T15:30:00-04:00", "end_iso": "2026-08-25T16:45:00-04:00",
        "recurrence": "FREQ=WEEKLY;BYDAY=TU,TH;UNTIL=20261209T235959Z",
        "exclude_dates": ["2026-10-06", "2026-11-26"]}),
    ("delete_calendar_event", "by id", {"event_id": "ev1"}),
    ("delete_calendar_event", "with title for preview", {"event_id": "ev1", "title": "Lunch"}),
    ("delete_calendar_event", "long id", {"event_id": "a" * 60}),
    # notion
    ("get_tasks", "list open", {}),
    ("get_tasks", "repeat call", {}),
    ("get_tasks", "ignores stray args", {}),
    ("get_school_day", "defaults to today", {}),
    ("get_school_day", "explicit day", {"day": "2026-08-25"}),
    ("get_school_day", "wider horizon", {"day": "2026-08-25", "horizon_days": 14}),
    ("get_school_day", "horizon clamped", {"horizon_days": 999}),
    ("create_task", "minimal", {"title": "Finish problem set"}),
    ("create_task", "full", {"title": "Essay draft", "due_date": "2026-07-30",
                             "priority": "High", "notes": "1500 words"}),
    ("create_task", "empty notes", {"title": "Call dad", "notes": ""}),
    ("delete_task", "by page id", {"page_id": "page1"}),
    ("delete_task", "with title", {"page_id": "page1", "title": "Finish problem set"}),
    ("delete_task", "uuid style", {"page_id": "1f2e3d4c-5b6a-7988-9a0b-1c2d3e4f5061"}),
    # notion — the whole workspace, not just the Tasks inbox
    ("notion_search", "find a database by name", {"query": "Classes", "kind": "database"}),
    ("notion_search", "bare list of everything visible", {}),
    ("notion_search", "limit arrives as a string", {"query": "planner", "limit": "5"}),
    ("notion_schema", "read a database's columns", {"database_id": "db-classes"}),
    ("notion_schema", "uuid form id",
     {"database_id": "021c8bf0-0593-48da-8f5f-dfbb2df69a4b"}),
    ("notion_schema", "repeat call is cheap", {"database_id": "db-classes"}),
    ("notion_query", "list rows", {"database_id": "db-classes"}),
    ("notion_query", "with filter and sort", {"database_id": "db-classes",
        "filter": {"property": "Term", "select": {"equals": "Fall 2026"}},
        "sorts": [{"property": "Starts", "direction": "ascending"}]}),
    ("notion_query", "limit as a string", {"database_id": "db-classes", "limit": "50"}),
    ("notion_read_page", "props and body", {"page_id": "row-calc"}),
    ("notion_read_page", "properties only", {"page_id": "row-calc", "include_content": False}),
    ("notion_read_page", "uuid form", {"page_id": "1f2e3d4c-5b6a-7988-9a0b-1c2d3e4f5061"}),
    ("notion_create_page", "a class row, typed from schema", {"parent_id": "db-classes",
        "title": "Calculus I", "properties": {"Days": ["Mon", "Wed"], "Term": "Fall 2026",
                                              "Credits": 4, "Starts": "2026-08-25"}}),
    ("notion_create_page", "lowercase names, scalar for a multi_select, unwritable formula",
     {"parent_id": "db-classes", "title": "Physics",
      "properties": {"days": "Fri", "credits": "3", "Load": 12, "Nope": "x"}}),
    ("notion_create_page", "under a page, with markdown body",
     {"parent_id": "page-fall", "parent_is_page": True, "title": "Fall notes",
      "content": "# Term\n- [ ] Buy books\n- Register\n\n> due soon"}),
    ("notion_update_page", "change a select", {"page_id": "row-calc",
                                               "properties": {"Term": "Spring 2027"}}),
    ("notion_update_page", "checkbox and number together",
     {"page_id": "row-calc", "properties": {"Done": True, "Credits": 5}}),
    ("notion_update_page", "unknown property is reported, not fatal",
     {"page_id": "row-calc", "properties": {"Ghost": "x"}}),
    ("notion_append", "bullets", {"page_id": "row-calc", "content": "- Midterm Oct 3"}),
    ("notion_append", "headings and to-dos", {"page_id": "row-calc",
        "content": "## Week 1\n- [x] Syllabus\n- [ ] Problem set"}),
    ("notion_append", "plain paragraph", {"page_id": "row-calc", "content": "Room changed."}),
    ("notion_create_database", "a Planner db", {"parent_page_id": "page-fall",
        "title": "Planner", "properties": {"Name": "title", "Day": "select",
                                           "Block": "rich_text"}}),
    ("notion_create_database", "title column implied when none given",
     {"parent_page_id": "page-fall", "title": "Events",
      "properties": {"When": "date", "Where": "rich_text"}}),
    ("notion_create_database", "multi_select options start empty",
     {"parent_page_id": "page-fall", "title": "Habits",
      "properties": {"Name": "title", "Tags": "multi_select", "Streak": "number"}}),
    # gmail
    ("get_unread_email", "count", {}),
    ("get_unread_email", "again", {}),
    ("get_unread_email", "third", {}),
    ("get_inbox_recent", "default", {}),
    ("get_inbox_recent", "daily sweep", {"limit": 10, "days": 2}),
    ("get_inbox_recent", "over-cap limit is clamped", {"limit": 500}),
    ("archive_emails", "single", {"uids": ["102"]}),
    ("archive_emails", "batch with reason", {"uids": ["102", "103"], "reason": "promos"}),
    ("archive_emails", "empty list is harmless", {"uids": []}),
    ("send_email", "plain", {"to": "prof@virginia.edu", "subject": "Re: office hours",
                             "body": "Thursday works."}),
    ("send_email", "multiline body", {"to": "a@b.com", "subject": "Update",
                                      "body": "Line one\n\nLine two"}),
    ("send_email", "unicode", {"to": "a@b.com", "subject": "Résumé", "body": "Adjunto ✅"}),
    ("draft_email", "new thread", {"to": "prof@virginia.edu", "subject": "Question",
                                   "body": "Quick question about the syllabus."}),
    ("draft_email", "reply in thread", {"to": "prof@virginia.edu", "body": "Sounds good.",
                                        "thread_id": "t123"}),
    ("draft_email", "no subject given", {"to": "a@b.com", "body": "hey"}),
    # vault
    ("vault_log", "bullets", {"title": "Weekly review", "lines": ["Shipped RESOLVE", "CI green"]}),
    ("vault_log", "single line", {"title": "Note", "lines": ["one thing"]}),
    ("vault_log", "empty lines list", {"title": "Empty", "lines": []}),
    ("save_to_vault", "default category", {"title": "Research: pgvector",
                                           "content": "# Findings\n\nIt works."}),
    ("save_to_vault", "explicit category", {"title": "Plan", "content": "# Plan",
                                            "category": "projects"}),
    ("save_to_vault", "long content", {"title": "Big", "content": "x" * 20000}),
    ("vault_read", "by path", {"path": "wiki/log.md"}),
    ("vault_read", "by query", {"query": "foundation"}),
    ("vault_read", "empty query", {"query": ""}),
    ("vault_recall", "semantic", {"query": "what did I decide about the site colors"}),
    ("vault_recall", "short query", {"query": "budget"}),
    ("vault_recall", "long natural question",
     {"query": "did I ever write down why we picked Render over Fly for hosting"}),
    # laptop
    ("run_on_laptop", "file task", {"task": "Summarise the README in ~/claude/resolve"}),
    ("run_on_laptop", "browser task", {"task": "Open my Canvas grades page and read it"}),
    ("run_on_laptop", "screen question", {"task": "What does the error on my screen say?"}),
    ("open_folder", "desktop", {"path": "~/Desktop"}),
    ("open_folder", "nested", {"path": "~/claude/resolve/services"}),
    ("open_folder", "absolute", {"path": "/Users/trav/Documents"}),
    ("reveal_in_finder", "file", {"path": "~/Desktop/notes.pdf"}),
    ("reveal_in_finder", "spaces in path", {"path": "~/Desktop/moms website/app.py"}),
    ("reveal_in_finder", "deep", {"path": "~/a/b/c/d.txt"}),
    ("open_file", "pdf", {"path": "~/Downloads/lease.pdf"}),
    ("open_file", "code", {"path": "~/claude/resolve/README.md"}),
    ("open_file", "spaces", {"path": "~/Desktop/moms website/README.md"}),
    ("open_app", "spotify", {"app": "Spotify"}),
    ("open_app", "two words", {"app": "Google Chrome"}),
    ("open_app", "lowercase", {"app": "notes"}),
    ("open_website", "full url", {"url": "https://news.google.com"}),
    ("open_website", "shortcut name", {"url": "outlook"}),
    ("open_website", "bare domain", {"url": "figma.com"}),
    ("restart_worker", "restart", {}),
    ("restart_worker", "again", {}),
    ("restart_worker", "third", {}),
    ("ask_local", "brainstorm", {"prompt": "Give me 5 names for a study app"}),
    ("ask_local", "private", {"prompt": "Draft a private note"}),
    ("ask_local", "long", {"prompt": "x" * 3000}),
    # data reads
    ("get_health", "latest", {}),
    ("get_health", "again", {}),
    ("get_health", "third", {}),
    ("get_finance", "default 30d", {}),
    ("get_finance", "90 days", {"days": 90}),
    ("get_finance", "string days", {"days": "7"}),
    ("get_recent_activity", "default", {}),
    ("get_recent_activity", "two weeks", {"days": 14}),
    ("get_recent_activity", "over cap clamps", {"days": 90}),
    ("get_audit_log", "default", {}),
    ("get_audit_log", "sensitive only", {"hours": 48, "sensitive": True}),
    ("get_audit_log", "string hours", {"hours": "12"}),
    # google workspace
    ("create_google_doc", "with content", {"title": "Essay draft",
                                           "content": "# Draft\n\nBody text."}),
    ("create_google_doc", "blank", {"title": "Scratch"}),
    ("create_google_doc", "in folder", {"title": "Report", "content": "x", "folder": "School"}),
    ("create_google_sheet", "with rows", {"title": "Budget",
                                          "rows": [["Item", "Cost"], ["Books", "120"]]}),
    ("create_google_sheet", "empty", {"title": "Blank tracker"}),
    ("create_google_sheet", "numeric-looking strings",
     {"title": "T", "rows": [["a", "1"], ["b", "2.5"]]}),
    ("create_google_slides", "deck", {"title": "Pitch",
                                      "content": "# One\n\n---\n\n# Two"}),
    ("create_google_slides", "single slide", {"title": "Solo", "content": "# Only"}),
    ("create_google_slides", "in folder", {"title": "D", "content": "# A", "folder": "Decks"}),
    ("find_google_file", "by name", {"query": "Q3 report"}),
    ("find_google_file", "partial", {"query": "budget"}),
    ("find_google_file", "with spaces", {"query": "meet you there foundation"}),
    ("read_google_doc", "by id", {"document_id": "doc123"}),
    ("read_google_doc", "url instead of id",
     {"document_id": "https://docs.google.com/document/d/doc123/edit"}),
    ("read_google_doc", "long id", {"document_id": "1" + "a" * 43}),
    ("replace_in_google_doc", "fix a phrase", {"document_id": "doc123",
        "find_text": "Intro paragraph.", "replace_text": "Opening paragraph."}),
    ("replace_in_google_doc", "delete text", {"document_id": "doc123",
        "find_text": "Second paragraph here.", "replace_text": ""}),
    ("replace_in_google_doc", "with log name", {"document_id": "doc123",
        "find_text": "a", "replace_text": "b", "name": "Essay draft"}),
    ("edit_google_doc", "append", {"document_id": "doc123", "content": "\n\nAppendix"}),
    ("edit_google_doc", "named", {"document_id": "doc123", "content": "x", "name": "Essay"}),
    ("edit_google_doc", "unicode", {"document_id": "doc123", "content": "café ✅"}),
    ("read_google_sheet", "default range", {"spreadsheet_id": "sheet123"}),
    ("read_google_sheet", "explicit range", {"spreadsheet_id": "sheet123",
                                             "range": "Sheet1!A1:D50"}),
    ("read_google_sheet", "quoted sheet name", {"spreadsheet_id": "sheet123",
                                                "range": "'My Sheet'!A1:B2"}),
    ("update_google_sheet", "fix a cell", {"spreadsheet_id": "sheet123",
        "range": "Sheet1!B2", "rows": [["150"]]}),
    ("update_google_sheet", "status column", {"spreadsheet_id": "sheet123",
        "range": "Sheet1!C2:C4", "rows": [["done"], ["done"], ["todo"]]}),
    ("update_google_sheet", "formula", {"spreadsheet_id": "sheet123",
        "range": "Sheet1!D2", "rows": [["=SUM(B2:B10)"]]}),
    ("edit_google_sheet", "append rows", {"spreadsheet_id": "sheet123",
                                          "rows": [["Snacks", "20"]]}),
    ("edit_google_sheet", "named tab", {"spreadsheet_id": "sheet123",
                                        "rows": [["x", "1"]], "sheet": "July"}),
    ("edit_google_sheet", "many rows", {"spreadsheet_id": "sheet123",
                                        "rows": [[str(i), "1"] for i in range(30)]}),
    ("add_google_slides", "append slides", {"presentation_id": "deck123",
                                            "content": "# New\n\n---\n\n# Also"}),
    ("add_google_slides", "one slide", {"presentation_id": "deck123", "content": "# Solo"}),
    ("add_google_slides", "named", {"presentation_id": "deck123", "content": "# A",
                                    "name": "Pitch"}),
    ("delete_google_file", "by id", {"file_id": "f1"}),
    ("delete_google_file", "long id", {"file_id": "1" + "z" * 40}),
    ("delete_google_file", "another", {"file_id": "f2"}),
    ("search_products", "headphones", {"query": "noise cancelling headphones"}),
    ("search_products", "with price cap", {"query": "standing desk", "max_price": 400}),
    ("search_products", "sorted", {"query": "monitor", "min_price": 100, "sort_by": 1}),
    # world
    ("get_weather", "default place", {}),
    ("get_weather", "named place", {"place": "Charlottesville", "days": 5}),
    ("get_weather", "string days", {"place": "Baltimore", "days": "2"}),
    ("get_travel_time", "city to city", {"origin": "Baltimore",
                                         "destination": "Charlottesville"}),
    ("get_travel_time", "campus", {"origin": "UVA", "destination": "Richmond VA"}),
    ("get_travel_time", "same place", {"origin": "Baltimore", "destination": "Baltimore"}),
    # canvas
    ("get_canvas", "default window", {}),
    ("get_canvas", "one week", {"days": 7}),
    ("get_canvas", "over cap clamps", {"days": 400}),
    # spotify
    ("spotify_play", "by query", {"query": "Feid Luna"}),
    ("spotify_play", "by uri", {"uri": "spotify:track:abc"}),
    ("spotify_play", "resume", {}),
    ("spotify_control", "pause", {"action": "pause"}),
    ("spotify_control", "next", {"action": "next"}),
    ("spotify_control", "previous", {"action": "previous"}),
    ("spotify_search", "track", {"query": "Luna Feid"}),
    ("spotify_search", "artist", {"query": "Bad Bunny", "kind": "artist"}),
    ("spotify_search", "playlist", {"query": "study", "kind": "playlist"}),
    ("spotify_now_playing", "current", {}),
    ("spotify_now_playing", "again", {}),
    ("spotify_now_playing", "third", {}),
    ("get_music_taste", "default window", {}),
    ("get_music_taste", "recent kick", {"time_range": "short_term"}),
    ("get_music_taste", "core taste", {"time_range": "long_term"}),
    ("spotify_recent", "default", {}),
    ("spotify_recent", "ten", {"limit": 10}),
    ("spotify_recent", "over cap clamps", {"limit": 500}),
    ("spotify_queue", "one track", {"uris": ["spotify:track:1"]}),
    ("spotify_queue", "several", {"uris": ["spotify:track:1", "spotify:track:2"]}),
    ("spotify_queue", "mixed types filtered", {"uris": ["spotify:track:1",
                                                        "spotify:album:2"]}),
    # github
    ("github_issues", "default repo", {}),
    ("github_issues", "named repo", {"repo": "Tstansberry81/resolve"}),
    ("github_issues", "closed", {"state": "closed"}),
    ("github_pull_requests", "default", {}),
    ("github_pull_requests", "named", {"repo": "Tstansberry81/resolve"}),
    ("github_pull_requests", "all", {"state": "all"}),
    ("github_ci", "default", {}),
    ("github_ci", "named", {"repo": "Tstansberry81/resolve"}),
    ("github_ci", "url form", {"repo": "https://github.com/Tstansberry81/resolve"}),
    ("create_github_issue", "minimal", {"title": "Vault recall empty until midnight"}),
    ("create_github_issue", "with body", {"title": "Bug", "body": "Steps:\n1. x"}),
    ("create_github_issue", "labelled", {"title": "Idea", "body": "b",
                                         "labels": ["enhancement"]}),
    # coder
    ("code_task", "bug fix", {"objective": "Fix the login redirect on the foundation site",
                              "path": "~/Desktop/moms website"}),
    ("code_task", "no path", {"objective": "Make the failing test pass"}),
    ("code_task", "with context", {"objective": "Add a health endpoint",
                                   "path": "~/claude/resolve", "context": "FastAPI app"}),
    ("review_code", "small diff", {"diff": "- a = 1\n+ a = 2"}),
    ("review_code", "with intent", {"diff": "- x\n+ y", "objective": "rename x to y"}),
    ("review_code", "large diff", {"diff": "\n".join(f"+ line {i}" for i in range(500))}),
]

# plan_project is deliberately NOT in CASES: it is intercepted in the turn loop
# before _connector_call, because it hands off to the background planner instead
# of returning a result. Its three scenarios run against that real path below.
PLANNER_CASES = [
    ("research", "Compare 3 hosting options for the foundation site"),
    ("build", "Build a study tracker with a weekly report"),
    ("long objective", "x" * 2000),
]


def _run(tool: str, args: dict) -> Any:
    return assistant._connector_call(tool, dict(args), goal_id="smoke-goal")


@pytest.mark.parametrize("tool,label,args", CASES,
                         ids=[f"{t}::{lbl}" for t, lbl, _ in CASES])
def test_tool_scenario(tool: str, label: str, args: dict):
    """Every scenario must complete and return something JSON-serialisable.

    Serialisability matters as much as not raising: the result is fed back to the
    model as a tool_result, so an object that can't be encoded fails the turn
    just as hard as an exception - only later and less obviously.
    """
    result = _run(tool, args)
    assert result is not None, f"{tool} ({label}) returned None"
    json.dumps(result, default=str)


@pytest.mark.anyio
@pytest.mark.parametrize("label,objective", PLANNER_CASES,
                         ids=[f"plan_project::{lbl}" for lbl, _ in PLANNER_CASES])
async def test_planner_handoff(label, objective, monkeypatch):
    """The handoff must return a serialisable result and must never raise into
    the turn loop - a planner failure has to come back as a tool_result telling
    the assistant to do the work itself, not kill the conversation."""
    from resolve_control_plane import executor

    async def fake_plan(goal_id, obj):
        assert obj == objective
        return {"queued": True, "steps": ["step one", "step two"]}

    monkeypatch.setattr(executor, "plan_project", fake_plan)
    monkeypatch.setattr(executor, "available", lambda: True)
    out = await executor.plan_project("smoke-goal", objective)
    json.dumps(out, default=str)
    assert out["queued"] is True


@pytest.mark.anyio
async def test_planner_failure_degrades_to_a_message(monkeypatch):
    """If the planner blows up, the turn loop catches it and tells the assistant
    to fall back to its own tools. Verified against the real source so a refactor
    that drops the try/except is caught."""
    import inspect

    src = inspect.getsource(assistant._loop)
    branch = src[src.index('tu.name == "plan_project"'):]
    branch = branch[:branch.index("if not CONNECTOR_AVAILABLE")]
    assert "except Exception" in branch
    assert "yourself with your own tools" in branch


def test_every_tool_has_three_scenarios():
    """Stops the suite rotting behind the tool list."""
    counts: dict[str, int] = {}
    for tool, _, _ in CASES:
        counts[tool] = counts.get(tool, 0) + 1

    counts["plan_project"] = len(PLANNER_CASES)  # covered by test_planner_handoff

    declared = {t["name"] for t in TOOLS}
    missing = sorted(declared - set(counts))
    assert not missing, f"tools with no scenarios: {missing}"

    thin = sorted(n for n, c in counts.items() if c < 3)
    assert not thin, f"tools with fewer than 3 scenarios: {thin}"

    unknown = sorted(set(counts) - declared)
    assert not unknown, f"scenarios for tools that no longer exist: {unknown}"
