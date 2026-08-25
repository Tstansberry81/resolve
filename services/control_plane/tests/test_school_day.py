"""school_day() is the morning brief's one look at the semester.

On 2026-08-24 the brief opened with "zero open tasks in Notion" on a morning the
Lectures database held that day's topic and readings — because the brief only ever
read the Tasks inbox. get_school_day exists so that stays fixed, which means the
things worth pinning down are: it asks for the right day, it drops finished work,
and a database it cannot read is reported rather than rendered as an empty day.
"""

from __future__ import annotations

import pytest

from resolve_control_plane.connectors import notion_api

LECTURES = "3c56c560-994d-816d-be72-c7ddf2bb5f76"
ASSIGNMENTS = "52d385d1-7894-4f2f-9bc4-2d9cf6d2bd29"
EXAMS = "a7b85bcf-bd26-473b-8a40-860dc4409738"


def _page(props: dict) -> dict:
    """Notion's wire shape for the handful of property types these rows use."""
    out: dict = {}
    for k, v in props.items():
        if k in ("Lecture", "Assignment", "Event"):
            out[k] = {"type": "title", "title": [{"plain_text": v}]}
        elif k in ("Date", "Due Date"):
            out[k] = {"type": "date", "date": {"start": v}}
        elif k == "GCal Synced":
            out[k] = {"type": "checkbox", "checkbox": v}
        elif isinstance(v, str) and k in ("Topic", "Readings", "Unit", "Notes"):
            out[k] = {"type": "rich_text", "rich_text": [{"plain_text": v}]}
        else:
            out[k] = {"type": "select", "select": {"name": v} if v else None}
    return {"id": "p1", "url": "https://notion.so/p1", "properties": out}


@pytest.fixture
def notion(monkeypatch):
    """Record every query and answer from a canned workspace."""
    calls: list[tuple[str, dict]] = []
    rows = {
        LECTURES: [_page({"Lecture": "PHIL 1730 — Why Moral Philosophy?", "Course": "PHIL 1730",
                          "Date": "2026-08-25", "Topic": "Why Moral and Political Philosophy?",
                          "Readings": "Plato, Apology", "Unit": "Unit 1"})],
        ASSIGNMENTS: [
            _page({"Assignment": "Reading response 1", "Due Date": "2026-08-27",
                   "Status": "Not Started", "Type": "Reading", "Priority": "Medium"}),
            _page({"Assignment": "Syllabus quiz", "Due Date": "2026-08-26",
                   "Status": "Submitted", "Type": "Quiz", "Priority": "Low"}),
        ],
        EXAMS: [_page({"Event": "ECON 2010 — Midterm 1", "Date": "2026-09-24",
                       "Type": "Midterm", "Status": "Upcoming", "GCal Synced": True})],
    }
    notion_api._db_ids.clear()

    def fake_req(method: str, path: str, **kw):
        if method == "GET" and path.startswith("/databases/"):
            return {"id": path.split("/")[-1]}          # id resolves — no title lookup
        if method == "POST" and path.endswith("/query"):
            db = path.split("/")[2]
            calls.append((db, kw.get("json") or {}))
            return {"results": rows.get(db, [])}
        raise AssertionError(f"unexpected {method} {path}")

    monkeypatch.setattr(notion_api, "_req", fake_req)
    return calls


def test_asks_for_the_requested_day(notion):
    notion_api.school_day(day="2026-08-25")
    lecture_filter = next(body for db, body in notion if db == LECTURES)["filter"]
    assert lecture_filter == {"property": "Date", "date": {"equals": "2026-08-25"}}


def test_lecture_carries_topic_and_readings(notion):
    out = notion_api.school_day(day="2026-08-25")
    assert len(out["lectures"]) == 1
    lec = out["lectures"][0]
    # the whole point: the calendar knows PHIL is at 3:30, only Notion knows why
    assert lec["course"] == "PHIL 1730"
    assert lec["topic"] == "Why Moral and Political Philosophy?"
    assert lec["readings"] == "Plato, Apology"


def test_finished_work_is_dropped(notion):
    out = notion_api.school_day(day="2026-08-25")
    titles = [a["assignment"] for a in out["assignments_due"]]
    assert titles == ["Reading response 1"], "a submitted quiz should not be nagged about"


def test_horizons_bracket_the_day(notion):
    notion_api.school_day(day="2026-08-25", horizon_days=7)
    by_db = {db: body for db, body in notion}
    assert by_db[ASSIGNMENTS]["filter"]["and"] == [
        {"property": "Due Date", "date": {"on_or_after": "2026-08-25"}},
        {"property": "Due Date", "date": {"on_or_before": "2026-09-01"}},
    ]
    # exams get double the runway — a midterm a fortnight out still deserves warning
    assert by_db[EXAMS]["filter"]["and"][1] == {
        "property": "Date", "date": {"on_or_before": "2026-09-08"}
    }


def test_an_unreadable_database_is_named_not_hidden(monkeypatch, notion):
    real = notion_api._req

    def flaky(method: str, path: str, **kw):
        if path.endswith("/query") and LECTURES in path:
            raise RuntimeError("Notion 404: Could not find database")
        return real(method, path, **kw)

    monkeypatch.setattr(notion_api, "_req", flaky)
    out = notion_api.school_day(day="2026-08-25")

    assert out["lectures"] == []
    assert any("Lectures" in e for e in out["errors"]), (
        "a silent empty lecture list reads as 'no class today' — the exact failure "
        "this tool was added to stop"
    )
    # and the sections that DID load still came back
    assert out["assignments_due"] and out["exams_upcoming"]


def test_stale_id_falls_back_to_title(monkeypatch, notion):
    """A recreated database keeps its title but not its id."""
    real = notion_api._req
    notion_api._db_ids.clear()

    def gone(method: str, path: str, **kw):
        if method == "GET" and path == f"/databases/{LECTURES}":
            raise RuntimeError("Notion 404: Could not find database")
        return real(method, path, **kw)

    monkeypatch.setattr(notion_api, "_req", gone)
    monkeypatch.setattr(notion_api, "search",
                        lambda q, kind=None, limit=25: [{"id": LECTURES, "title": "Lectures"}])

    out = notion_api.school_day(day="2026-08-25")
    assert out["lectures"], "should have re-resolved Lectures by title"
    assert not out["errors"]
