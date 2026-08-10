"""What every tool does when the service answers BADLY.

The happy-path suite (test_tool_smoke.py) has a built-in blind spot: the same
person wrote the code and the fixtures, so they agree by construction. It proves
the wiring, not the resilience.

This suite is the adversarial half. Every case feeds a response that a real
service genuinely can return - an empty envelope, a null where an object was
expected, a key in the other casing, a list that arrived as a dict - and asserts
the tool either succeeds or fails in a way the model can report honestly.

The bar is deliberately not "never raises". A RuntimeError with a clear message
is a fine outcome; the assistant catches it and tells Trav what broke. The
failures that matter are the silent ones:
  - a crash on a shape the API really returns (TypeError/AttributeError/KeyError)
  - a cheerful success dict built out of nothing, which is how "RESOLVE said it
    worked and nothing happened" occurs
"""

from __future__ import annotations

import json

import pytest

from resolve_control_plane import assistant
from resolve_control_plane.connectors import composio, github_api, world

# Exceptions that mean "this crashed on an unexpected shape" rather than
# "this failed and said so".
CRASHES = (TypeError, AttributeError, KeyError, IndexError, UnboundLocalError)


class Resp:
    def __init__(self, payload=None, status=200, text=""):
        self._p = payload if payload is not None else {}
        self.status_code = status
        self.text = text or json.dumps(self._p)
        self.content = self.text.encode()

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _call(tool, args):
    """Run a tool, classifying the outcome."""
    try:
        return "ok", assistant._connector_call(tool, dict(args), goal_id="g")
    except CRASHES as exc:
        return "crash", f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # deliberate, reported failure
        return "handled", str(exc)


# --- Composio-backed tools --------------------------------------------------

EMPTY_SHAPES = [
    ("empty envelope", {}),
    ("nulls throughout", {"items": None, "values": None, "files": None}),
    ("wrong container type", {"items": {}, "values": {}, "files": {}}),
]


@pytest.mark.parametrize("label,payload", EMPTY_SHAPES, ids=[x[0] for x in EMPTY_SHAPES])
@pytest.mark.parametrize("tool,args", [
    ("read_google_doc", {"document_id": "d"}),
    ("read_google_sheet", {"spreadsheet_id": "s"}),
    ("find_google_file", {"query": "q"}),
    ("spotify_search", {"query": "x"}),
    ("spotify_now_playing", {}),
    ("get_music_taste", {}),
    ("spotify_recent", {}),
    ("search_products", {"query": "x"}),
], ids=lambda v: v if isinstance(v, str) else "")
def test_composio_tools_survive_degraded_payloads(monkeypatch, tool, args, label, payload):
    monkeypatch.setattr(composio, "execute", lambda slug, a: payload)
    monkeypatch.setattr(composio, "configured", lambda: True)
    kind, detail = _call(tool, args)
    assert kind != "crash", f"{tool} crashed on {label}: {detail}"


def test_replace_reports_zero_when_the_count_key_is_missing(monkeypatch):
    """Composio is inconsistent about occurrences_changed vs occurrencesChanged,
    and may omit it. Absent must NOT read as a successful edit."""
    monkeypatch.setattr(composio, "execute", lambda slug, a: {})
    monkeypatch.setattr(composio, "configured", lambda: True)
    kind, out = _call("replace_in_google_doc",
                      {"document_id": "d", "find_text": "a", "replace_text": "b"})
    assert kind == "ok"
    assert out.get("replaced") in (None, 0)


@pytest.mark.parametrize("key", ["occurrences_changed", "occurrencesChanged"])
def test_replace_accepts_either_casing(monkeypatch, key):
    monkeypatch.setattr(composio, "execute", lambda slug, a: {key: 3})
    monkeypatch.setattr(composio, "configured", lambda: True)
    kind, out = _call("replace_in_google_doc",
                      {"document_id": "d", "find_text": "a", "replace_text": "b"})
    assert kind == "ok" and out["replaced"] == 3


def test_doc_read_handles_every_plausible_text_key(monkeypatch):
    """Composio has shipped this payload under several names."""
    for key in ("plain_text", "plaintext", "text", "content"):
        monkeypatch.setattr(composio, "execute", lambda slug, a, k=key: {k: "body text"})
        monkeypatch.setattr(composio, "configured", lambda: True)
        kind, out = _call("read_google_doc", {"document_id": "d"})
        assert kind == "ok" and out["content"] == "body text", f"missed key {key}"


def test_taste_survives_artists_without_genres(monkeypatch):
    """Plenty of Spotify artists carry no genre tags at all."""
    def fake(slug, a=None):
        if "ARTISTS" in slug:
            return {"items": [{"name": "Someone"}, {"name": None, "genres": None}]}
        return {"items": [{"name": "T", "artists": None}]}

    monkeypatch.setattr(composio, "execute", fake)
    monkeypatch.setattr(composio, "configured", lambda: True)
    kind, out = _call("get_music_taste", {})
    assert kind != "crash", out
    assert out["topGenres"] == []


def test_now_playing_handles_an_advert_or_podcast(monkeypatch):
    """Spotify returns item: null between tracks and during ads."""
    monkeypatch.setattr(composio, "execute",
                        lambda slug, a=None: {"is_playing": True, "item": None})
    monkeypatch.setattr(composio, "configured", lambda: True)
    kind, out = _call("spotify_now_playing", {})
    assert kind == "ok" and out["playing"] is False


def test_play_reports_honestly_when_nothing_matches(monkeypatch):
    """A search miss must not report that music started."""
    monkeypatch.setattr(composio, "execute", lambda slug, a=None: {"tracks": {"items": []}})
    monkeypatch.setattr(composio, "configured", lambda: True)
    kind, out = _call("spotify_play", {"query": "asdkjhasd"})
    assert kind == "ok" and out.get("played") is False


# --- keyless HTTP services --------------------------------------------------

def test_weather_survives_a_partial_forecast(monkeypatch):
    """Open-Meteo omits blocks when a field is unavailable for a location."""
    def fake_get(url, **kw):
        if "geocoding" in url:
            return Resp({"results": [{"name": "X", "latitude": 1.0, "longitude": 2.0}]})
        return Resp({"current": {}, "daily": {}})

    monkeypatch.setattr(world.requests, "get", fake_get)
    kind, out = _call("get_weather", {"place": "X"})
    assert kind != "crash", out
    assert out["forecast"] == []


def test_weather_daily_arrays_of_unequal_length(monkeypatch):
    """A shorter parallel array is the classic index-out-of-range here."""
    def fake_get(url, **kw):
        if "geocoding" in url:
            return Resp({"results": [{"name": "X", "latitude": 1.0, "longitude": 2.0}]})
        return Resp({"current": {"weather_code": 0},
                     "daily": {"time": ["2026-07-26", "2026-07-27", "2026-07-28"],
                               "weather_code": [0],
                               "temperature_2m_max": [88.0]}})

    monkeypatch.setattr(world.requests, "get", fake_get)
    kind, out = _call("get_weather", {"place": "X"})
    assert kind != "crash", out


def test_travel_time_when_no_route_exists(monkeypatch):
    """OSRM returns an empty routes list for unreachable pairs (islands)."""
    def fake_get(url, **kw):
        if "geocoding" in url:
            return Resp({"results": [{"name": "X", "latitude": 1.0, "longitude": 2.0}]})
        return Resp({"routes": []})

    monkeypatch.setattr(world.requests, "get", fake_get)
    kind, detail = _call("get_travel_time", {"origin": "A", "destination": "B"})
    assert kind == "handled", f"expected a clear failure, got {kind}: {detail}"


# --- Canvas -----------------------------------------------------------------

@pytest.mark.parametrize("body,label", [
    ("", "empty feed"),
    ("BEGIN:VCALENDAR\nEND:VCALENDAR\n", "no events"),
    ("BEGIN:VEVENT\nSUMMARY:No date at all\nEND:VEVENT\n", "event with no DTSTART"),
    ("BEGIN:VEVENT\nDTSTART:garbage\nSUMMARY:Bad date\nEND:VEVENT\n", "unparseable date"),
    ("<html>Login required</html>", "html instead of ics"),
], ids=lambda v: v if isinstance(v, str) and len(v) < 30 else "")
def test_canvas_survives_a_malformed_feed(monkeypatch, body, label):
    """A stale or revoked feed URL returns an HTML login page, not ICS."""
    from resolve_control_plane.connectors import canvas

    monkeypatch.setenv("CANVAS_ICS_URL", "https://canvas/x.ics")
    monkeypatch.setattr(canvas.requests, "get", lambda url, **kw: Resp(text=body))
    kind, out = _call("get_canvas", {})
    assert kind != "crash", f"{label}: {out}"
    if kind == "ok":
        assert out["assignments"] == []


# --- GitHub -----------------------------------------------------------------

@pytest.mark.parametrize("payload,label", [
    ([], "no issues"),
    ({"message": "Not Found"}, "error object where a list belongs"),
    ([{"number": 1}], "issue missing every optional field"),
], ids=lambda v: v if isinstance(v, str) else "")
def test_github_issue_listing_survives(monkeypatch, payload, label):
    monkeypatch.setattr(github_api, "_get", lambda p, params=None: payload)
    kind, out = _call("github_issues", {"repo": "o/r"})
    assert kind != "crash", f"{label}: {out}"


def test_ci_status_with_no_runs(monkeypatch):
    monkeypatch.setattr(github_api, "_get", lambda p, params=None: {"workflow_runs": []})
    kind, out = _call("github_ci", {"repo": "o/r"})
    assert kind == "ok" and out["failingCount"] == 0


def test_ci_status_when_a_run_has_no_commit(monkeypatch):
    """head_commit is null on runs triggered by workflow_dispatch."""
    monkeypatch.setattr(github_api, "_get", lambda p, params=None: {"workflow_runs": [
        {"name": "x", "conclusion": "success", "status": "completed",
         "head_branch": None, "html_url": None, "created_at": None, "head_commit": None}]})
    kind, out = _call("github_ci", {"repo": "o/r"})
    assert kind != "crash", out


# --- vault recall -----------------------------------------------------------

def test_vault_recall_with_no_matches(monkeypatch):
    from resolve_control_plane import vault_index

    monkeypatch.setattr(vault_index, "configured", lambda: True)
    monkeypatch.setattr(vault_index, "embed", lambda t: [[0.0] * 1536])
    monkeypatch.setattr(vault_index.requests, "post", lambda url, **kw: Resp([]))
    kind, out = _call("vault_recall", {"query": "nothing like this exists"})
    assert kind == "ok"
    assert out["matches"] == []
    assert "Nothing" in out["note"], "an empty result must say so, not look like a hit"


def test_vault_recall_when_the_rpc_is_missing(monkeypatch):
    """Before the SQL migration is applied, PostgREST 404s the function."""
    from resolve_control_plane import vault_index

    monkeypatch.setattr(vault_index, "configured", lambda: True)
    monkeypatch.setattr(vault_index, "embed", lambda t: [[0.0] * 1536])
    monkeypatch.setattr(vault_index.requests, "post",
                        lambda url, **kw: Resp({"message": "not found"}, 404))
    kind, detail = _call("vault_recall", {"query": "x"})
    assert kind == "handled", f"expected a clear failure, got {kind}: {detail}"


# --- malformed arguments from the model -------------------------------------
# A schema says {"type": "integer"}; a model still sends null, "a week", or 7.5.
# Every one of these was a raw TypeError/ValueError reaching Trav before the
# _arg_int/_arg_list helpers existed.

@pytest.mark.parametrize("bad", [None, "a week", "", "seven", 7.9, True, [], {}],
                         ids=lambda v: repr(v))
def test_numeric_args_never_crash(monkeypatch, bad):
    from resolve_control_plane.connectors import gcal

    monkeypatch.setattr(gcal, "list_events", lambda days=7, query="": {"days": days, "events": []})
    kind, out = _call("get_calendar", {"days": bad})
    assert kind == "ok", f"days={bad!r} -> {out}"
    assert isinstance(out["days"], int)
    assert 1 <= out["days"] <= 60, f"days={bad!r} produced {out['days']}"


@pytest.mark.parametrize("bad", [None, "spotify:track:1", 5, {}], ids=lambda v: repr(v))
def test_list_args_never_crash(monkeypatch, bad):
    seen: dict = {}
    monkeypatch.setattr(composio, "_spotify",
                        lambda slug, a=None: seen.setdefault("calls", []).append(a) or {})
    kind, out = _call("spotify_queue", {"uris": bad})
    assert kind == "ok", f"uris={bad!r} -> {out}"


def test_a_bare_string_becomes_a_one_element_list(monkeypatch):
    """Models routinely send a single label as a string, not a list of one."""
    from resolve_control_plane import assistant as a

    assert a._arg_list({"labels": "bug"}, "labels") == ["bug"]
    assert a._arg_list({"labels": ["bug", "p1"]}, "labels") == ["bug", "p1"]
    assert a._arg_list({}, "labels") == []
    assert a._arg_list({"labels": None}, "labels") == []


def test_numeric_clamping_protects_the_inbox():
    """limit=0 once sliced the WHOLE inbox; the floor is not cosmetic."""
    from resolve_control_plane import assistant as a

    assert a._arg_int({"limit": 0}, "limit", 25, 1, 50) == 1
    assert a._arg_int({"limit": -5}, "limit", 25, 1, 50) == 1
    assert a._arg_int({"limit": 9999}, "limit", 25, 1, 50) == 50
    assert a._arg_int({"limit": "30"}, "limit", 25, 1, 50) == 30
