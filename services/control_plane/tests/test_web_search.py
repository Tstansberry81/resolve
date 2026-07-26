"""The assistant's own web search: tool wiring, the pause_turn resume, and the
prompt no longer claiming it can't look things up."""

from __future__ import annotations

import inspect

from resolve_control_plane import assistant
from resolve_control_plane.tools_def import SYSTEM


def test_search_tool_is_shaped_for_direct_calls():
    """web_search defaults to expecting a call from inside code execution; without
    the pin every assistant turn that searches would 400 — the same bug that once
    killed the executor's research steps."""
    tool = assistant.ASSISTANT_WEB_SEARCH
    assert tool["type"] == "web_search_20260209"
    assert tool["allowed_callers"] == ["direct"]


def test_search_use_is_capped():
    """An uncapped search loop is an uncapped bill."""
    assert 1 <= assistant.ASSISTANT_WEB_SEARCH["max_uses"] <= 5


def test_search_is_attached_to_every_turn():
    src = inspect.getsource(assistant._loop)
    assert "ASSISTANT_WEB_SEARCH" in src


def test_pause_turn_resumes_instead_of_being_nudged():
    """A paused turn has no tool_use block, so without explicit handling it falls
    into the 'you did nothing' nudge and the paid-for search is discarded."""
    src = inspect.getsource(assistant._loop)
    assert 'stop_reason == "pause_turn"' in src
    pause_at = src.index('stop_reason == "pause_turn"')
    nudge_at = src.index("STOP. You did NOT call any tool")
    assert pause_at < nudge_at, "pause_turn must be handled before the nudge path"


def test_attachment_turn_is_cache_marked():
    """Images are re-sent on every turn of the tool loop; without a breakpoint
    they are billed in full up to MAX_TURNS times."""
    src = inspect.getsource(assistant._loop)
    assert "cache_control" in src


def test_prompt_no_longer_claims_it_cannot_search():
    assert "NO web-search tool" not in SYSTEM
    assert "web_search" in SYSTEM


def test_prompt_stops_routing_questions_to_the_planner():
    """The old prompt sent every current-info question to plan_project. That was
    the single most expensive instruction in the file."""
    assert "plan_project is NOT for questions" in SYSTEM


def test_search_is_not_a_dispatchable_client_tool():
    """It runs server-side and comes back inline, so it must NOT be in the client
    tool list or the policy map — a policy entry would imply we dispatch it."""
    from resolve_control_plane.tools_def import TOOL_POLICY, TOOLS

    assert "web_search" not in TOOL_POLICY
    assert all(t["name"] != "web_search" for t in TOOLS)
