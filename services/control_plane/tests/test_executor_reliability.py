"""Executor reliability: intent-detection, honest failure, non-silent saves."""

import unittest
from unittest import mock

from resolve_control_plane import executor


class IntentDetectionTest(unittest.TestCase):
    def test_narration_flagged_as_intent(self):
        for t in [
            "I'll research the UVA Student Health Center and write it up.",
            "Let me search for that information now.",
            "Sure! I'm going to look into this for you.",
            "First, I will find the founding year.",
            "",  # empty is definitely "no real result"
        ]:
            self.assertTrue(executor._needs_action(t), t)

    def test_promise_ending_after_search_flagged(self):
        # the real failure: model searched, narrated, ended on a promise to compile
        for t in [
            "I'll research the UVA center to find details.\nNow let me search for more "
            "specific information about services and hours.\nPerfect! I now have "
            "comprehensive information. Let me compile this into a thorough summary and "
            "save it to the vault.",
            "I found several sources. Now I'll write up the full summary for you.",
            "Great, I have what I need — let me put together the final answer.",
        ]:
            self.assertTrue(executor._needs_action(t), t)

    def test_real_output_not_flagged(self):
        for t in [
            "The Student Health and Wellness Center is located at 550 Brandon Ave, "
            "Charlottesville. It opened in 2021 and offers primary care, counseling "
            "and psychological services (CAPS), gynecology, and student disability "
            "access. Hours are 8am-5pm weekdays with urgent care on weekends.",
            "1819. The University of Virginia was founded by Thomas Jefferson in 1819.",
        ]:
            self.assertFalse(executor._needs_action(t), t)


class AutosaveTest(unittest.TestCase):
    def test_returns_error_when_vault_unconfigured(self):
        with mock.patch.object(executor.vault_github, "configured", return_value=False):
            url, err = executor._autosave_output("T", "a long enough outcome " * 5)
        self.assertIsNone(url)
        self.assertIn("not configured", err)

    def test_surfaces_github_write_failure(self):
        with mock.patch.object(executor.vault_github, "configured", return_value=True), \
             mock.patch.object(executor.vault_github, "append_log"), \
             mock.patch.object(executor.vault_github, "write_file",
                               side_effect=RuntimeError("403 Forbidden")):
            url, err = executor._autosave_output("T", "x" * 200)
        self.assertIsNone(url)
        self.assertIn("403", err)

    def test_saves_note_and_returns_url(self):
        with mock.patch.object(executor.vault_github, "configured", return_value=True), \
             mock.patch.object(executor.vault_github, "append_log"), \
             mock.patch.object(executor.vault_github, "write_file"), \
             mock.patch.object(executor.artifacts, "record_vault"), \
             mock.patch.object(executor.vault_github, "VAULT_REPO", "u/vault"):
            url, err = executor._autosave_output("UVA Health", "x" * 200)
        self.assertIsNone(err)
        self.assertIn("wiki/output/uva-health.md", url)

    def test_tiny_output_logs_only_no_error(self):
        with mock.patch.object(executor.vault_github, "configured", return_value=True), \
             mock.patch.object(executor.vault_github, "append_log"):
            url, err = executor._autosave_output("T", "1819")  # below SAVE_NOTE_MIN
        self.assertIsNone(url)
        self.assertIsNone(err)


if __name__ == "__main__":
    unittest.main()
