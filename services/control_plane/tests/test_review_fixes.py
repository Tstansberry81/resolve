"""Review-batch fixes: approval rehydration at boot + goal reply long-poll."""

import asyncio
import unittest
from unittest import mock

from resolve_control_plane import api, assistant, bus


class RehydrateTest(unittest.TestCase):
    def setUp(self):
        assistant.pending_actions.clear()

    def tearDown(self):
        assistant.pending_actions.clear()

    def test_pending_rows_restore_across_restart(self):
        rows = [{
            "id": "11111111-1111-1111-1111-111111111111",
            "goal_id": "22222222-2222-2222-2222-222222222222",
            "status": "pending",
            "action_summary": "Send email to x: “hi”",
            "risk_class": "communication_send",
            "request_json": {"tool": "send_email",
                             "args": {"to": "x@y.z", "subject": "hi", "body": "b"}},
            "preview_json": ["to: x@y.z"],
        }]
        with mock.patch.object(assistant.store, "select", return_value=rows):
            n = asyncio.run(assistant.rehydrate_pending())
        self.assertEqual(n, 1)
        act = assistant.pending_actions["11111111-1111-1111-1111-111111111111"]
        self.assertEqual(act["tool"], "send_email")
        self.assertEqual(act["goal_id"], "22222222-2222-2222-2222-222222222222")

    def test_unknown_tool_and_dupes_skipped(self):
        rows = [
            {"id": "a" * 36, "request_json": {"tool": "not_a_tool", "args": {}}},
            {"id": "", "request_json": {"tool": "send_email", "args": {}}},
        ]
        with mock.patch.object(assistant.store, "select", return_value=rows):
            n = asyncio.run(assistant.rehydrate_pending())
        self.assertEqual(n, 0)
        self.assertEqual(assistant.pending_actions, {})

    def test_store_failure_is_soft(self):
        with mock.patch.object(assistant.store, "select", side_effect=RuntimeError("db down")):
            n = asyncio.run(assistant.rehydrate_pending())
        self.assertEqual(n, 0)


class GoalReplyTest(unittest.TestCase):
    def test_returns_reply_when_event_present(self):
        async def run():
            await bus.emit("assistant", "assistant.reply", "short",
                           detail="the full reply", goal_id="goal-reply-test")
            return await api.goal_reply("goal-reply-test", timeout=1)
        out = asyncio.run(run())
        self.assertTrue(out["done"])
        self.assertEqual(out["reply"], "the full reply")

    def test_times_out_clean_without_event(self):
        out = asyncio.run(api.goal_reply("no-such-goal", timeout=1))
        self.assertEqual(out, {"done": False})


if __name__ == "__main__":
    unittest.main()
