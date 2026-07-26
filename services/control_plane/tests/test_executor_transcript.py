"""Transcript well-formedness in the executor loop.

The McIntire research plan died on a real 400: "messages.2: `tool_use` ids were
found without `tool_result` blocks immediately after". The model's turn was cut
off by max_tokens mid-tool_use, so stop_reason was "max_tokens" rather than
"tool_use", the loop treated it as "the model stopped", and appended a plain
nudge after a dangling tool_use. Every assistant turn carrying tool_use must be
answered with a tool_result for each id, whatever stop_reason says.
"""

import unittest
from unittest import mock

from resolve_control_plane import executor


class _Block:
    def __init__(self, type, text=None, id=None, name=None, input=None):
        self.type, self.text, self.id, self.name, self.input = type, text, id, name, input


class _Resp:
    def __init__(self, content, stop_reason):
        self.content, self.stop_reason = content, stop_reason
        self.usage = mock.Mock(input_tokens=10, output_tokens=10)


def _text(t):
    return _Block("text", text=t)


def _tool(id="tu_1", name="vault_read"):
    return _Block("tool_use", id=id, name=name, input={"path": "x"})


def _assert_wellformed(case, messages):
    """Every tool_use id must be answered by a tool_result in the NEXT message —
    this is precisely what the API 400s on."""
    for i, m in enumerate(messages):
        content = m.get("content")
        if not isinstance(content, list):
            continue
        ids = {b.id for b in content if getattr(b, "type", None) == "tool_use"}
        if not ids:
            continue
        case.assertLess(i + 1, len(messages), f"dangling tool_use at end: {ids}")
        nxt = messages[i + 1]
        case.assertEqual(nxt["role"], "user", f"tool_use at {i} not followed by a user turn")
        answered = {b.get("tool_use_id") for b in nxt["content"]
                    if isinstance(b, dict) and b.get("type") == "tool_result"}
        case.assertEqual(ids, ids & answered, f"unanswered tool_use ids at {i}: {ids - answered}")
        case.assertNotIsInstance(nxt["content"], str)


class TranscriptTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.sent = []          # messages as handed to the API, per turn
        self.dispatched = []

    async def _run(self, responses):
        """Drive _execute_opus over a scripted list of API responses."""
        seq = list(responses)

        async def fake_create(**kw):
            self.sent.append([dict(m) for m in kw["messages"]])
            return seq.pop(0) if seq else _Resp([_text("done, here is the answer " * 30)],
                                                "end_turn")

        async def fake_dispatch(name, args, goal_id):
            self.dispatched.append(name)
            return "{}", False

        client = mock.Mock()
        client.messages.create = fake_create
        with mock.patch.object(executor.anthropic, "AsyncAnthropic", return_value=client), \
             mock.patch.object(executor, "_dispatch_tool", fake_dispatch), \
             mock.patch.object(executor.costs, "record"), \
             mock.patch.dict("sys.modules", {}):
            with mock.patch("resolve_control_plane.assistant.TOOLS", []):
                return await executor._execute_opus(
                    {"goal_id": "g1", "title": "Research McIntire"}, "ctx")

    async def test_truncated_tool_use_is_answered_not_nudged(self):
        # the exact McIntire failure: max_tokens mid-tool_use, and the text so far
        # is bare narration, so the old code took the nudge path and poisoned the
        # transcript
        await self._run([
            _Resp([_text("I'll research McIntire now."), _tool()], "max_tokens"),
            _Resp([_text("The McIntire School requires… " * 40)], "end_turn"),
        ])
        for turn in self.sent:
            _assert_wellformed(self, turn)
        # a truncated call must NOT be executed — its input JSON is unreliable
        self.assertEqual(self.dispatched, [])

    async def test_truncated_tool_result_is_flagged_as_error(self):
        await self._run([
            _Resp([_text("I'll look."), _tool()], "max_tokens"),
            _Resp([_text("Real findings. " * 40)], "end_turn"),
        ])
        results = [b for turn in self.sent for m in turn
                   if isinstance(m.get("content"), list)
                   for b in m["content"]
                   if isinstance(b, dict) and b.get("type") == "tool_result"]
        self.assertTrue(results)
        self.assertTrue(all(r.get("is_error") for r in results))
        self.assertIn("cut off", results[0]["content"])

    async def test_normal_tool_use_still_executes(self):
        await self._run([
            _Resp([_tool(name="vault_read")], "tool_use"),
            _Resp([_text("Findings from the vault. " * 40)], "end_turn"),
        ])
        self.assertEqual(self.dispatched, ["vault_read"])
        for turn in self.sent:
            _assert_wellformed(self, turn)

    async def test_pause_turn_carrying_tool_use_is_answered(self):
        # server search paused AND the model asked for a client tool in the same
        # turn — bouncing it straight back would leave the tool_use dangling
        await self._run([
            _Resp([_text("searching"), _tool()], "pause_turn"),
            _Resp([_text("Findings. " * 40)], "end_turn"),
        ])
        for turn in self.sent:
            _assert_wellformed(self, turn)

    async def test_plain_pause_turn_still_resumes_without_tool_result(self):
        await self._run([
            _Resp([_text("searching the web")], "pause_turn"),
            _Resp([_text("Findings. " * 40)], "end_turn"),
        ])
        self.assertEqual(self.dispatched, [])
        for turn in self.sent:
            _assert_wellformed(self, turn)

    async def test_narration_only_still_gets_nudged(self):
        # the nudge path must survive the restructure
        out = await self._run([
            _Resp([_text("I'll research that for you.")], "end_turn"),
            _Resp([_text("UVA McIntire requires ECON 2010, ACCT 2010… " * 30)], "end_turn"),
        ])
        self.assertIn("McIntire requires", out)
        nudged = any("have NOT delivered" in str(m.get("content"))
                     for turn in self.sent for m in turn)
        self.assertTrue(nudged)

    async def test_empty_content_turn_never_sends_empty_assistant_block(self):
        await self._run([
            _Resp([], "end_turn"),
            _Resp([_text("Real findings. " * 40)], "end_turn"),
        ])
        for turn in self.sent:
            for m in turn:
                self.assertTrue(m.get("content"), "empty content block is itself a 400")


if __name__ == "__main__":
    unittest.main()
