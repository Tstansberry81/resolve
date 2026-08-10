"""The Coder + Reviewer pair: model routing off the previously-dead config
routes, an independent review context, and a brief that forbids the failure
modes this repo already hit once."""

from __future__ import annotations

import inspect

from resolve_control_plane import assistant, coder


def test_uses_the_configured_coding_routes(monkeypatch):
    """These routes sat unread in model_routes.json since day one — the point of
    this module is that they're now load-bearing. Pinned to the config's current
    values, so a route edit has to come here too rather than drifting silently."""
    monkeypatch.delenv("CODER_ARCHITECT_MODEL", raising=False)
    monkeypatch.delenv("CODER_REVIEWER_MODEL", raising=False)
    assert coder.architect_model() == "claude-opus-5"
    assert coder.reviewer_model() == "claude-opus-5"


def test_env_overrides_the_route(monkeypatch):
    monkeypatch.setenv("CODER_ARCHITECT_MODEL", "claude-opus-5")
    assert coder.architect_model() == "claude-opus-5"


def test_a_broken_config_does_not_kill_a_coding_request(monkeypatch):
    def boom(role, *a, **k):
        raise KeyError(role)

    monkeypatch.delenv("CODER_ARCHITECT_MODEL", raising=False)
    monkeypatch.setattr(coder, "model_choice", boom)
    assert coder.architect_model() == "claude-opus-5"


def test_reviewer_is_told_it_did_not_write_the_code():
    """Independent review is the whole reason code_reviewer is its own route;
    a reviewer that thinks it authored the diff rationalises it."""
    assert "did not write" in coder.REVIEWER_SYSTEM
    assert "adversarial" in coder.REVIEWER_SYSTEM.lower()


def test_reviewer_is_told_not_to_invent_findings():
    assert "do not invent findings" in coder.REVIEWER_SYSTEM.lower()


def test_architect_is_told_to_demand_verification():
    assert "VERIFIED" in coder.ARCHITECT_SYSTEM
    assert "read before it edits" in coder.ARCHITECT_SYSTEM


def test_brief_forbids_claiming_untested_success():
    brief = coder.build_brief("fix the parser", "1. read parser.py\n2. fix it", "~/proj")
    assert "Do not claim it passes without running it" in brief
    assert "~/proj" in brief
    assert "fix the parser" in brief


def test_brief_forbids_unrequested_commits_and_refactors():
    brief = coder.build_brief("x", "y")
    assert "Do not commit or push unless Trav asked" in brief
    assert "No opportunistic refactors" in brief


def test_brief_tells_the_agent_the_repo_beats_the_plan():
    """The architect never saw the code, so its file guesses must lose to reality."""
    brief = coder.build_brief("x", "y")
    assert "the repo is the truth" in brief


def test_code_task_refuses_cleanly_when_the_laptop_is_offline():
    """Planning first would spend an architect call on work that cannot run."""
    src = inspect.getsource(assistant._connector_call)
    start = src.index('name == "code_task"')
    end = src.index('name == "review_code"')
    body = src[start:end]
    assert "local.online()" in body
    assert body.index("local.online()") < body.index("coder.plan")


def test_coder_calls_are_synchronous():
    """Dispatch already runs in a worker thread; an async client there would
    nest an event loop inside a thread for no benefit."""
    assert not inspect.iscoroutinefunction(coder.plan)
    assert not inspect.iscoroutinefunction(coder.review)
