"""The anti-hallucination nudge must tell "I did it" from "it does it".

_claims_action gates a hard STOP re-prompt. A false positive is not harmless:
on 2026-08-10 Trav asked RESOLVE to explain a shell script, the honest
explanation said "this creates a venv ... then builds the DMG", the bare-verb
regex read that as a false claim, and the nudge fired on a turn where nothing
was ever meant to happen. RESOLVE then argued with the instruction in the reply
("Fair cop on the rule, but there was nothing to create here"), which is how an
internal guardrail ended up addressed to the user.

So both directions are load-bearing: describing an action must stay quiet, and
claiming one must still fire.
"""

from __future__ import annotations

import pytest

from resolve_control_plane.assistant import _claims_action

# Talking ABOUT things that create/build/save — no claim is being made.
DESCRIBES = [
    "The script creates a venv, then builds the DMG and saves it to dist/.",
    "Line 12 generates the RRULE and line 20 updates the calendar entry.",
    "It's constructed in three parts: setup, a build step, and a run step.",
    "This function added retries last year, which is why it looks odd.",
    "Here's the breakdown you asked for.",
    "That flag removes the quarantine attribute.",
    "The paperclip sends attachments; RUN submits the turn.",
    "Google requires a named timezone before it will accept a recurring event.",
    "Do you want me to create that?",  # a question is a clarification, never a claim
]

# Claiming work happened (or is about to) in THIS turn.
CLAIMS = [
    "Done — created the doc.",
    "I've created the doc and shared it.",
    "I'll add that to your calendar now.",
    "I'll send the email in a moment.",
    "I'm generating it now.",
    "I just saved that to the vault.",
    "On it, one sec.",
    "Created the task in Notion.",
    "Here's your doc: https://docs.google.com/x",
    "All set.",
]


@pytest.mark.parametrize("text", DESCRIBES)
def test_describing_an_action_is_not_claiming_one(text):
    assert not _claims_action(text), f"false positive would fire the STOP nudge: {text!r}"


@pytest.mark.parametrize("text", CLAIMS)
def test_real_claims_still_fire(text):
    assert _claims_action(text), f"a bare claim slipped through: {text!r}"
