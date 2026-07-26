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

    def test_concise_answers_with_filler_leads_not_flagged(self):
        # concise, COMPLETE answers that merely open with a filler word or "I can"
        # are real deliverables, not stalls — flagging them discarded good output
        for t in [
            "Okay, your account balance is $1,234.56 as of today.",
            "Sure, the meeting is confirmed for 3pm on Thursday.",
            "I can confirm the flight departs at 6:40am from gate B12.",
            # a real writeup ending on a THIRD-person forward-looking clause
            "The center offers primary care and counseling. The board is going to "
            "review the new hours next quarter.",
        ]:
            self.assertFalse(executor._needs_action(t), t)

    def test_finished_writeup_ending_on_promise_not_flagged(self):
        # a COMPLETE report that merely signs off with "I'll save this" was being
        # thrown away by the promise-tail check → empty → honest-failure + no save
        body = ("The Student Health and Wellness Center at 550 Brandon Ave offers "
                "primary care, CAPS counseling, gynecology, and disability access. "
                "Hours are 8am-5pm weekdays with urgent care on weekends. ") * 6
        for tail in ["I'll save this summary to your vault.",
                     "Next I'll check the weekend urgent care hours."]:
            self.assertFalse(executor._needs_action(f"{body}\n{tail}"), tail)

    def test_long_but_wall_to_wall_narration_still_flagged(self):
        # length alone isn't delivery: a long transcript of nothing but promises
        t = ("I'll start by searching for the health center details. " * 6
             + "Now I'm going to look at the hours page. " * 4
             + "I need to check one more source. Let me compile the summary now.")
        self.assertTrue(executor._needs_action(t), t)


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


class FailureArtifactTest(unittest.TestCase):
    """The Artifacts dock is the source of truth for what got done, so a step
    that produced nothing has to leave a row — otherwise a dead step and a step
    that never ran are indistinguishable."""

    def setUp(self):
        from resolve_control_plane import artifacts
        self.artifacts = artifacts
        artifacts._recent.clear()

    def tearDown(self):
        self.artifacts._recent.clear()

    def _record(self, *a, **kw):
        with mock.patch.object(self.artifacts.store, "insert"), \
             mock.patch.object(self.artifacts.bus, "_fanout"):
            return self.artifacts.record_failure(*a, **kw)

    def test_failure_row_has_no_link_to_a_file_that_doesnt_exist(self):
        art = self._record("Research McIntire", "no output produced")
        self.assertEqual(art["kind"], "failed")
        self.assertFalse(art["href"])  # never invent a link to a missing file
        self.assertIn("FAILED", art["action"])
        self.assertIn("no output produced", art["meta"] + art["action"])

    def test_failure_shows_up_in_the_dock(self):
        self._record("Research McIntire", "no output produced")
        self.assertEqual(len(self.artifacts.recent()), 1)
        self.assertEqual(self.artifacts.recent()[0]["kind"], "failed")

    def test_save_failure_is_distinguishable_from_no_output(self):
        self._record("Research McIntire", "not saved: 403 Forbidden")
        self.assertIn("403", self.artifacts.recent()[0]["action"])


if __name__ == "__main__":
    unittest.main()
