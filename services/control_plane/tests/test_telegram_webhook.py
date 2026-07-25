"""The in-process Telegram bridge that replaces the legacy vault1 bot.

Covers the two things vault1 was still load-bearing for — inline approval button
taps and `/resolve <text>` — plus the gate that keeps the route from being an
open command endpoint.
"""

import importlib
import unittest
from unittest import mock

from fastapi import HTTPException
from fastapi.testclient import TestClient

SECRET = "hook-secret"
CHAT = "5550001"
ENV = {"TELEGRAM_WEBHOOK_SECRET": SECRET, "TELEGRAM_CHAT_ID": CHAT,
       "TELEGRAM_TOKEN": "t", "ANTHROPIC_API_KEY": "k", "CP_TOKEN": "cp"}

_patch = None


def setUpModule():
    # env must stay live for the REQUEST, not just the reload: chat_allowed()
    # reads TELEGRAM_CHAT_ID at call time, so a scoped patch around the import
    # alone leaves every update silently ignored.
    global _patch
    _patch = mock.patch.dict("os.environ", ENV, clear=False)
    _patch.start()


def tearDownModule():
    _patch.stop()
    import resolve_control_plane.api as api
    importlib.reload(api)  # restore ambient env for the rest of the suite


def _reload_api(**over):
    with mock.patch.dict("os.environ", {**ENV, **over}, clear=False):
        import resolve_control_plane.api as api
        importlib.reload(api)
        return api


def _post(api, update, secret=SECRET):
    headers = {} if secret is None else {"X-Telegram-Bot-Api-Secret-Token": secret}
    return TestClient(api.app).post("/v1/telegram/webhook", json=update, headers=headers)


def _tap(approve=True, chat=CHAT, data=None):
    verb = "ok" if approve else "no"
    return {"callback_query": {
        "id": "cb1", "data": data if data is not None else f"rslv:{verb}:abc-123",
        "message": {"message_id": 7, "text": "🔔 Approval needed", "chat": {"id": chat}}}}


class WebhookGateTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        import resolve_control_plane.api as api
        importlib.reload(api)

    def test_missing_secret_env_fails_closed(self):
        api = _reload_api(TELEGRAM_WEBHOOK_SECRET="")
        with self.assertRaises(HTTPException) as cm:
            api._telegram_gate(mock.Mock(headers={}))
        self.assertEqual(cm.exception.status_code, 503)

    def test_wrong_secret_rejected(self):
        api = _reload_api()
        self.assertEqual(_post(api, _tap(), secret="nope").status_code, 401)
        self.assertEqual(_post(api, _tap(), secret=None).status_code, 401)

    def test_foreign_chat_ignored_not_executed(self):
        api = _reload_api()
        with mock.patch.object(api, "decide_approval") as decide:
            r = _post(api, _tap(chat="9999999"))
        self.assertEqual(r.status_code, 200)  # 200 or Telegram redelivers forever
        decide.assert_not_called()


class ApprovalTapTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        import resolve_control_plane.api as api
        importlib.reload(api)

    def setUp(self):
        self.api = _reload_api()
        self.tg = mock.patch.object(self.api, "telegram_webhook", wraps=None)

    def _run(self, update, decide_result=None):
        from resolve_control_plane.connectors import telegram_notify
        async def fake_decide(aid, decision):
            self.seen = (aid, decision)
            return decide_result if decide_result is not None else {"ok": True}
        with mock.patch.object(self.api, "decide_approval", fake_decide), \
             mock.patch.object(telegram_notify, "answer_callback") as ack, \
             mock.patch.object(telegram_notify, "edit_message_text") as edit:
            r = _post(self.api, update)
        return r, ack, edit

    def test_approve_tap_decides_and_acknowledges(self):
        self.seen = None
        r, ack, edit = self._run(_tap(approve=True))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.seen, ("abc-123", "approved"))
        ack.assert_called_once()
        edit.assert_called_once()  # keyboard stripped so it can't be tapped twice

    def test_reject_tap_decides_rejected(self):
        self.seen = None
        self._run(_tap(approve=False))
        self.assertEqual(self.seen, ("abc-123", "rejected"))

    def test_already_decided_reports_error_without_crashing(self):
        self.seen = None
        r, ack, _ = self._run(_tap(), decide_result={"ok": False, "error": "already decided"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("already decided", ack.call_args[0][1])

    def test_unknown_callback_payload_ignored(self):
        self.seen = None
        r, ack, _ = self._run(_tap(data="something:else"))
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(self.seen)
        ack.assert_not_called()


class ResolveCommandTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        import resolve_control_plane.api as api
        importlib.reload(api)

    def _msg(self, text, chat=CHAT):
        return {"message": {"message_id": 3, "chat": {"id": chat}, "text": text}}

    def _send(self, text, chat=CHAT):
        """Post a message with the actual command runner stubbed out — patching
        asyncio.get_running_loop instead would replace the real event loop and
        hang the test client."""
        api = _reload_api()
        with mock.patch.object(api, "_run_and_reply", new_callable=mock.AsyncMock) as run:
            r = _post(api, self._msg(text, chat))
        return r, run

    def test_resolve_command_queues_the_command(self):
        r, run = self._send("/resolve what's on my calendar")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json().get("queued"))
        run.assert_called_once()
        self.assertEqual(run.call_args[0][1], "what's on my calendar")  # prefix stripped

    def test_ask_alias_also_works(self):
        _, run = self._send("/ask when is my flight")
        self.assertEqual(run.call_args[0][1], "when is my flight")

    def test_plain_chatter_is_not_a_command(self):
        r, run = self._send("hey what's up")
        self.assertEqual(r.status_code, 200)
        run.assert_not_called()

    def test_bare_command_with_no_body_ignored(self):
        _, run = self._send("/resolve")
        run.assert_not_called()

    def test_command_from_foreign_chat_ignored(self):
        _, run = self._send("/resolve do a thing", chat="9999999")
        run.assert_not_called()


class ChatAllowlistTest(unittest.TestCase):
    def test_allowlist_requires_configured_chat(self):
        from resolve_control_plane.connectors import telegram_notify
        with mock.patch.dict("os.environ", {"TELEGRAM_CHAT_ID": ""}, clear=False):
            self.assertFalse(telegram_notify.chat_allowed("123"))
        with mock.patch.dict("os.environ", {"TELEGRAM_CHAT_ID": "123"}, clear=False):
            self.assertTrue(telegram_notify.chat_allowed(123))   # int from Telegram
            self.assertTrue(telegram_notify.chat_allowed("123"))
            self.assertFalse(telegram_notify.chat_allowed("1234"))


if __name__ == "__main__":
    unittest.main()
