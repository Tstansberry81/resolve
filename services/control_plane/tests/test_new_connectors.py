"""Canvas (keyless ICS), weather/travel (keyless APIs), Spotify, Gmail drafts,
and real Google editing — plus a wiring guard so a tool can never again be
declared to the model without a policy entry and a dispatch branch."""

from __future__ import annotations

import inspect
import json
import pathlib

import pytest

from resolve_control_plane import assistant
from resolve_control_plane.connectors import canvas, composio, world
from resolve_control_plane.tools_def import TOOL_POLICY, TOOLS

CONFIG = pathlib.Path(__file__).resolve().parents[3] / "config" / "tool_policies.json"


# --- the wiring guard -------------------------------------------------------

def test_every_declared_tool_is_fully_wired():
    """A tool the model can see but the dispatcher can't run is worse than a
    missing tool: it promises Trav something, then errors after he's waited."""
    policies = json.loads(CONFIG.read_text())["overrides"]
    # Most tools dispatch in _connector_call; plan_project is intercepted earlier,
    # inside the turn loop, because it hands off rather than returning a result.
    dispatch = inspect.getsource(assistant._connector_call) + inspect.getsource(assistant._loop)

    for tool in TOOLS:
        name = tool["name"]
        assert name in TOOL_POLICY, f"{name} declared but has no TOOL_POLICY entry"
        action = TOOL_POLICY[name][0]
        assert action in policies, f"{name} maps to '{action}', absent from tool_policies.json"
        assert f'name == "{name}"' in dispatch, f"{name} declared but never dispatched"


def test_unknown_actions_are_denied_not_allowed():
    """Fail closed: the default for an unmapped action must stay 'deny'."""
    assert json.loads(CONFIG.read_text())["defaults"]["unknown_action"] == "deny"


# --- Canvas: the no-API-key workaround --------------------------------------

SAMPLE_ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:event-assignment-1
DTSTART:20260801T035959Z
SUMMARY:Problem Set 4 [APMA 2120]
URL:https://canvas.example.edu/courses/1/assignments/9
END:VEVENT
BEGIN:VEVENT
UID:event-assignment-2
DTSTART:20260802T035959Z
SUMMARY:Reading Response: The Long Nineteenth
  Century [HIST 2002]
END:VEVENT
BEGIN:VEVENT
UID:event-3
DTSTART:20260803
SUMMARY:Lab Report\\, part two [CHEM 1410]
END:VEVENT
END:VCALENDAR
"""


def test_parses_assignments_and_splits_the_course_code():
    events = canvas.parse_ics(SAMPLE_ICS)
    assert len(events) == 3
    assert events[0]["title"] == "Problem Set 4"
    assert events[0]["course"] == "APMA 2120"
    assert events[0]["url"].endswith("/assignments/9")


def test_unfolds_wrapped_titles():
    """RFC 5545 folds long lines; a naive parser truncates the title mid-word."""
    events = canvas.parse_ics(SAMPLE_ICS)
    assert events[1]["title"] == "Reading Response: The Long Nineteenth Century"
    assert events[1]["course"] == "HIST 2002"


def test_unescapes_commas_and_handles_all_day_dates():
    events = canvas.parse_ics(SAMPLE_ICS)
    assert events[2]["title"] == "Lab Report, part two"
    assert events[2]["due"].year == 2026


def test_canvas_explains_how_to_connect_when_unset(monkeypatch):
    """The failure has to teach the workaround, since the obvious path (an API
    key) is the one UVA blocks."""
    monkeypatch.delenv("CANVAS_ICS_URL", raising=False)
    assert not canvas.configured()
    with pytest.raises(RuntimeError) as err:
        canvas.upcoming()
    assert "Calendar Feed" in str(err.value)
    assert "no API key" in str(err.value)


# --- weather + travel: keyless ---------------------------------------------

def test_weather_codes_become_words():
    assert world.describe_code(0) == "clear"
    assert world.describe_code(95) == "thunderstorms"
    assert world.describe_code(None) == "unknown"
    assert world.describe_code(4242) == "unsettled"


def test_geocode_failure_names_the_place(monkeypatch):
    class R:
        def raise_for_status(self): pass
        def json(self): return {"results": []}

    monkeypatch.setattr(world.requests, "get", lambda *a, **k: R())
    with pytest.raises(ValueError) as err:
        world.geocode("Nowherecity")
    assert "Nowherecity" in str(err.value)


def test_travel_time_flags_that_it_ignores_traffic(monkeypatch):
    """The number is free-flow. Handing it over without that caveat makes
    RESOLVE tell Trav to leave too late."""
    def fake_get(url, **kw):
        class R:
            def raise_for_status(self): pass
            def json(self):
                if "geocoding" in url:
                    return {"results": [{"name": "X", "latitude": 1.0,
                                         "longitude": 2.0, "country_code": "US"}]}
                return {"routes": [{"duration": 3600, "distance": 80467}]}
        return R()

    monkeypatch.setattr(world.requests, "get", fake_get)
    out = world.travel_time("Baltimore", "Charlottesville")
    assert out["minutes"] == 60
    assert out["miles"] == 50.0
    assert "traffic" in out["note"]


# --- Google editing: the depth fix -----------------------------------------

def test_replace_uses_uris_shape_for_tracks_and_context_for_albums(monkeypatch):
    """Spotify silently no-ops if a track goes in context_uri or an album in
    uris, so the shape has to be picked from the URI."""
    seen: dict = {}
    monkeypatch.setattr(composio, "_spotify", lambda slug, args=None: seen.update(
        slug=slug, args=args or {}) or {})

    composio.spotify_play(uri="spotify:track:abc")
    assert seen["args"]["uris"] == ["spotify:track:abc"]

    composio.spotify_play(uri="spotify:album:xyz")
    assert seen["args"]["context_uri"] == "spotify:album:xyz"


def test_play_with_nothing_resumes(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(composio, "_spotify", lambda slug, args=None: seen.update(
        slug=slug, args=args or {}) or {})
    composio.spotify_play()
    assert seen["args"] == {}
    assert seen["slug"] == "SPOTIFY_START_RESUME_PLAYBACK"


def test_spotify_errors_become_instructions():
    assert "open Spotify" in composio._spotify_hint("Composio X failed: 404 no active device")
    assert "Premium" in composio._spotify_hint("HTTP 403 premium required")


def test_replace_in_doc_rejects_empty_find():
    with pytest.raises(ValueError):
        composio.replace_in_doc("doc1", "", "new")


def test_replace_reports_occurrences(monkeypatch):
    monkeypatch.setattr(composio, "execute",
                        lambda slug, args: {"occurrences_changed": 0})
    assert composio.replace_in_doc("d", "missing", "x")["replaced"] == 0


def test_zero_replacements_is_reported_as_an_error_not_success():
    """Otherwise the model says 'Fixed it' about a doc it never changed."""
    src = inspect.getsource(assistant._connector_call)
    assert 'res.get("replaced") == 0' in src


def test_draft_reply_omits_subject_to_stay_in_thread(monkeypatch):
    """Gmail forks a new thread if a reply draft carries a subject."""
    seen: dict = {}
    monkeypatch.setattr(composio, "execute",
                        lambda slug, args: seen.update(args=args) or {"id": "d1"})

    composio.create_gmail_draft("a@b.com", "Re: hi", "body", thread_id="t123")
    assert "subject" not in seen["args"]
    assert seen["args"]["thread_id"] == "t123"

    composio.create_gmail_draft("a@b.com", "Fresh", "body")
    assert seen["args"]["subject"] == "Fresh"
