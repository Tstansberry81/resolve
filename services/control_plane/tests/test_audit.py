"""Audit log: filters agent_events to real actions, flags sensitive ones."""

import unittest
from unittest import mock

from resolve_control_plane import audit


ROWS = [
    {"event_type": "send_email.executed", "actor": "gmail", "created_at": "2026-07-20T10:00:00Z",
     "payload": {"summary": "Approved and executed — Send email to x", "level": "success"}},
    {"event_type": "speak.progress", "actor": "assistant", "created_at": "2026-07-20T10:01:00Z",
     "payload": {"summary": "researching"}},  # chatter — excluded
    {"event_type": "action.held", "actor": "assistant", "created_at": "2026-07-20T10:02:00Z",
     "payload": {"summary": "Rejected — archive 12 emails", "level": "warn"}},
    {"event_type": "tool.call", "actor": "assistant", "created_at": "2026-07-20T10:03:00Z",
     "payload": {"summary": "get_calendar — ok"}},
    {"event_type": "task.failed", "actor": "executor", "created_at": "2026-07-20T10:04:00Z",
     "payload": {"summary": "research failed: 400", "level": "error"}},
]


class AuditTest(unittest.TestCase):
    def test_filters_chatter_keeps_actions(self):
        with mock.patch.object(audit.store, "select", return_value=ROWS):
            res = audit.recent(hours=24)
        actions = {a["action"] for a in res["actions"]}
        self.assertIn("send_email.executed", actions)
        self.assertIn("action.held", actions)
        self.assertIn("tool.call", actions)
        self.assertIn("task.failed", actions)
        self.assertNotIn("speak.progress", actions)  # chatter dropped

    def test_sensitive_only_filter(self):
        with mock.patch.object(audit.store, "select", return_value=ROWS):
            res = audit.recent(hours=24, sensitive_only=True)
        actions = {a["action"] for a in res["actions"]}
        # send/executed, archive-reject (held→approval marker), failed = sensitive;
        # a plain calendar read is NOT
        self.assertIn("send_email.executed", actions)
        self.assertIn("task.failed", actions)
        self.assertNotIn("tool.call", actions)

    def test_sensitive_flag_on_entries(self):
        with mock.patch.object(audit.store, "select", return_value=ROWS):
            res = audit.recent(hours=24)
        by = {a["action"]: a["sensitive"] for a in res["actions"]}
        self.assertTrue(by["send_email.executed"])
        self.assertFalse(by["tool.call"])

    def test_store_failure_soft(self):
        with mock.patch.object(audit.store, "select", side_effect=RuntimeError("db down")):
            res = audit.recent()
        self.assertEqual(res["actions"], [])
        self.assertIn("error", res)


if __name__ == "__main__":
    unittest.main()
