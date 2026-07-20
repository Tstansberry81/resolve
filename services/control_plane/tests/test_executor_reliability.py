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

    def test_synthesis_stall_flagged(self):
        # the McIntire-plan step 3 stall: knew research existed, went looking, stopped
        t = ("Based on the context provided in the task and what I found, I need to "
             "gather the complete research information. The task indicates research has "
             "been gathered but I need to locate it. Let me check for any notes or "
             "output files:")
        self.assertTrue(executor._needs_action(t), t)


class PriorContextTest(unittest.TestCase):
    def setUp(self):
        executor._step_outputs.clear()

    def tearDown(self):
        executor._step_outputs.clear()

    def test_prior_context_feeds_earlier_steps(self):
        executor._step_outputs["g1"] = [
            {"title": "Research admission", "outcome": "McIntire opens applications in April."},
            {"title": "Research degree reqs", "outcome": "CoAS needs 120 credits."},
        ]
        ctx = executor._prior_context("g1")
        self.assertIn("Research admission", ctx)
        self.assertIn("McIntire opens applications", ctx)
        self.assertIn("CoAS needs 120 credits", ctx)
        self.assertIn("do NOT", ctx)  # instruction not to re-research

    def test_no_prior_context_empty(self):
        self.assertEqual(executor._prior_context("nope"), "")

    def test_prior_context_bounded(self):
        executor._step_outputs["g1"] = [{"title": "S", "outcome": "x" * 20000}]
        self.assertLessEqual(len(executor._prior_context("g1")), executor._PRIOR_CHARS_CAP + 300)

    def test_goal_accumulator_capped(self):
        for i in range(10):
            executor._step_outputs.setdefault(f"g{i}", []).append({"title": "t", "outcome": "o"})
            while len(executor._step_outputs) > 6:
                executor._step_outputs.pop(next(iter(executor._step_outputs)), None)
        self.assertLessEqual(len(executor._step_outputs), 6)

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
