"""Running out of turns must not read as success.

The loop caps at MAX_TURNS. When it was exhausted it simply fell out, and the
tail of _loop says: if there's no text but a tool ran, reply "Done." So a bulk
job that got a third of the way through -- ten of twenty-eight Notion pages, and
none of the calendar events that were also asked for -- came back as "Done."
with nothing marking it partial.

That is the same failure as every silent truncation in this codebase: a cut-off
result presented as a finished one.
"""

from __future__ import annotations

import unittest
from unittest import mock

from resolve_control_plane import assistant


class _Blk:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Usage:
    input_tokens = output_tokens = 0
    cache_read_input_tokens = cache_creation_input_tokens = 0


class _Resp:
    """Always asks for a tool, so the loop can only ever end by exhaustion."""
    stop_reason = "tool_use"
    usage = _Usage()
    content = [_Blk(type="tool_use", id="t1", name="not_a_real_tool", input={})]


class TurnBudgetTest(unittest.IsolatedAsyncioTestCase):
    async def _run(self):
        emitted: list[tuple[str, str, str]] = []

        async def fake_emit(actor, type_, summary, **kw):
            emitted.append((actor, type_, kw.get("detail") or summary))

        client = mock.MagicMock()
        client.messages.create = mock.AsyncMock(return_value=_Resp())

        with mock.patch.object(assistant, "MAX_TURNS", 2), \
             mock.patch.object(assistant.anthropic, "AsyncAnthropic", return_value=client), \
             mock.patch.object(assistant.bus, "emit", side_effect=fake_emit), \
             mock.patch.object(assistant.bus, "set_orb", new=mock.AsyncMock()), \
             mock.patch.object(assistant.costs, "record", mock.Mock()), \
             mock.patch.object(assistant.store, "update", mock.Mock()), \
             mock.patch.object(assistant.store, "insert", mock.Mock(return_value={"id": "1"})):
            await assistant._loop("g1", "add all 28 lectures to notion")
        return emitted

    async def test_exhausting_the_budget_is_reported_not_hidden(self):
        emitted = await self._run()
        types = [t for _, t, _ in emitted]
        self.assertIn("assistant.truncated", types,
                      "no signal that the turn budget ran out")

    async def test_the_reply_says_it_is_partial_and_never_just_done(self):
        emitted = await self._run()
        replies = [d for _, t, d in emitted if t == "assistant.reply"]
        self.assertTrue(replies, "no reply was emitted at all")
        reply = replies[-1]
        self.assertIn("PARTIAL", reply, f"truncated run did not say so: {reply!r}")
        self.assertNotEqual(reply.strip(), "Done.",
                            "a cut-off run reported plain success")


if __name__ == "__main__":
    unittest.main()
