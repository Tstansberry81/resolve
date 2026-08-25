"""A cut tool result has to say it was cut.

Results go back to the model capped at TOOL_RESULT_CHARS. The cap itself is fine
— it is the silence that isn't. On 2026-08-24 a notion_query over the Lectures
database came back chopped mid-record and the model counted 9 lectures out of a
database holding far more, with nothing in the payload to suggest it was looking
at a fragment. Same shape as the 25-row calendar horizon and the "Done." that
actually meant "out of turns": a partial result wearing a complete one's clothes.
"""

from __future__ import annotations

import json

from resolve_control_plane import assistant


def test_small_results_pass_through_untouched():
    payload = {"lectures": [{"course": "PHIL 1730", "topic": "Cultural relativism"}]}
    assert assistant._tool_result_text(payload) == json.dumps(payload)


def test_oversized_results_are_marked():
    payload = [{"assignment": f"Reading {i}", "notes": "x" * 200} for i in range(200)]
    text = assistant._tool_result_text(payload)

    assert "[TRUNCATED" in text, "a chopped result that looks whole is the bug"
    assert "PARTIAL" in text
    # the model needs to know what to do next, not merely that something is wrong
    assert "narrower filter" in text
    # and the real size, so "how much am I missing" is answerable
    assert str(len(json.dumps(payload))) in text


def test_cap_is_honoured_around_the_marker():
    payload = ["y" * 50 for _ in range(500)]
    text = assistant._tool_result_text(payload)
    body = text.split("\n\n[TRUNCATED")[0]
    assert len(body) == assistant.TOOL_RESULT_CHARS


def test_a_result_exactly_at_the_cap_is_not_marked():
    # off-by-one here would stamp "PARTIAL" on complete data — a false alarm that
    # teaches the model to re-query things it already has in full
    payload = "z" * (assistant.TOOL_RESULT_CHARS - 2)  # -2 for the JSON quotes
    text = assistant._tool_result_text(payload)
    assert len(text) == assistant.TOOL_RESULT_CHARS
    assert "TRUNCATED" not in text
