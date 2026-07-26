"""Vault logging shape.

One shared wiki/log.md had two independent writers — RESOLVE via the GitHub API
and Obsidian on disk — so every prompt dirtied the same file, obsidian-git
wouldn't pull over the dirty tree, and the vault wedged (13 behind / 4 ahead).
Logs are per-day now, and the always-on per-prompt entry is gone entirely: the
day's record is the daily ingest summary, rebuilt from Supabase.
"""

import datetime as dt
import unittest
from unittest import mock

from resolve_control_plane import assistant, executor
from resolve_control_plane.connectors import vault_github


class DatedLogPathTest(unittest.TestCase):
    def test_log_path_is_per_day(self):
        self.assertEqual(vault_github.log_path_for("2026-07-26"), "wiki/logs/2026-07-26.md")

    def test_todays_path_by_default(self):
        self.assertEqual(vault_github.log_path_for(),
                         f"wiki/logs/{dt.date.today().isoformat()}.md")

    def test_two_days_never_share_a_file(self):
        # the whole point: yesterday's stale local copy can't block today's pull
        self.assertNotEqual(vault_github.log_path_for("2026-07-25"),
                            vault_github.log_path_for("2026-07-26"))

    def test_legacy_log_is_no_longer_a_write_target(self):
        self.assertNotIn(vault_github.LOG_PATH, vault_github.log_path_for())


class AppendLogTest(unittest.TestCase):
    def _put_payload(self, get_status):
        get = mock.Mock(status_code=get_status)
        get.json.return_value = {"content": "IyBvbGQK", "sha": "abc123"}  # "# old\n"
        put = mock.Mock(status_code=200)
        with mock.patch.object(vault_github.requests, "get", return_value=get), \
             mock.patch.object(vault_github.requests, "put", return_value=put) as p, \
             mock.patch.dict("os.environ", {"GITHUB_TOKEN": "t"}, clear=False):
            vault_github.append_log("a title", ["line one"])
        return p.call_args.kwargs["json"], p.call_args[0][0]

    def test_creates_the_file_on_the_first_write_of_the_day(self):
        payload, url = self._put_payload(404)
        # GitHub rejects a sha for a file that doesn't exist yet
        self.assertNotIn("sha", payload)
        self.assertIn(dt.date.today().isoformat(), url)

    def test_appends_with_sha_once_it_exists(self):
        payload, _ = self._put_payload(200)
        self.assertEqual(payload["sha"], "abc123")

    def test_writes_to_the_dated_path_not_the_shared_log(self):
        _, url = self._put_payload(200)
        self.assertIn("wiki/logs/", url)
        self.assertNotIn("wiki/log.md", url)


class NoAutomaticLoggingTest(unittest.TestCase):
    """The bloat came from logging that fired without anyone asking for it."""

    def test_per_prompt_logger_is_gone(self):
        self.assertFalse(hasattr(assistant, "_log_task_summary"),
                         "the always-on per-reply vault log is back")

    def test_executor_does_not_log_every_step(self):
        import inspect
        src = inspect.getsource(executor._vault_save)
        self.assertNotIn("append_log", src,
                         "the executor is writing a log line per step again")

    def test_the_explicit_tool_still_exists(self):
        # removing automatic logging must not remove the ability to log on purpose
        from resolve_control_plane.tools_def import TOOL_POLICY
        self.assertIn("vault_log", TOOL_POLICY)


class DailyIngestIsTheRecordTest(unittest.TestCase):
    def test_ingest_reads_from_supabase_not_the_vault_log(self):
        # this is why dropping the per-prompt log loses nothing
        import inspect
        from resolve_control_plane import ingest
        src = inspect.getsource(ingest.gather_materials)
        self.assertIn("agent_events", src)
        self.assertIn("goals", src)
        self.assertNotIn("log.md", src)


if __name__ == "__main__":
    unittest.main()
