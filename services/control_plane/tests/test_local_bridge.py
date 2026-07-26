"""Local-worker bridge honesty.

The trial run exposed four bugs at once: the laptop agent ended a turn with
"Let me compile ... Let me create the writeup now:" and wrote nothing; the dock
stayed silent about it; the worker read offline while it was busy; and the goal
was marked completed the moment the assistant dispatched to the laptop.
"""

import unittest
from unittest import mock

from resolve_control_plane import local


class LivenessTest(unittest.TestCase):
    def setUp(self):
        local._queue.clear()
        local._inflight.clear()
        local._last_poll = 0.0

    tearDown = setUp

    def test_polling_marks_online(self):
        self.assertFalse(local.online())
        local.next_task()  # a poll, even with an empty queue
        self.assertTrue(local.online())

    def test_any_worker_contact_counts_as_alive(self):
        # the poll loop BLOCKS during a task, so a heartbeat/result/event has to
        # keep liveness true — otherwise a busy laptop reads offline after 30s
        # and the executor's local-save path falls back to the vault
        self.assertFalse(local.online())
        local.touch()
        self.assertTrue(local.online())

    def test_busy_until_the_worker_reports_back(self):
        self.assertFalse(local.busy())
        local.enqueue("do a thing", goal_id="g1")
        self.assertTrue(local.busy())          # queued
        job = local.next_task()
        self.assertTrue(local.busy())          # running on the laptop
        local.set_result(job["taskId"], "done")
        self.assertFalse(local.busy())         # finished


class GoalLinkageTest(unittest.TestCase):
    def setUp(self):
        local._queue.clear()
        local._inflight.clear()

    tearDown = setUp

    def test_result_returns_the_goal_it_belonged_to(self):
        local.enqueue("research study spots", goal_id="goal-123")
        job = local.next_task()
        self.assertEqual(local.set_result(job["taskId"], "here it is"), "goal-123")

    def test_untracked_task_returns_no_goal(self):
        self.assertIsNone(local.set_result("never-dispatched", "x"))

    def test_goal_survives_until_the_laptop_finishes(self):
        local.enqueue("long browse", goal_id="g9")
        local.next_task()
        # while the laptop works, busy() keeps the assistant from calling the
        # goal completed just because it finished dispatching
        self.assertTrue(local.busy())


class FileSaveQueueTest(unittest.TestCase):
    def setUp(self):
        local._queue.clear()
        local._inflight.clear()

    tearDown = setUp

    def test_file_save_carries_content_not_a_prompt(self):
        local.enqueue_file_save("notes.md", "# Real content\n\nbody", "Save notes.md")
        job = local.next_task()
        self.assertEqual(job["action"]["kind"], "save_file")
        self.assertEqual(job["action"]["value"], "notes.md")
        self.assertIn("Real content", job["action"]["content"])
        # no LLM in this path — the worker writes exactly these bytes
        self.assertNotIn("task", job["action"])


class FailureReportingTest(unittest.IsolatedAsyncioTestCase):
    """A local task that produced nothing must reach the dock. It didn't — the
    cloud logged 'Local task complete' and the dock showed no row at all."""

    async def test_no_output_result_records_a_failure_artifact(self):
        import resolve_control_plane.api as api

        local._queue.clear()
        local._inflight.clear()
        local.enqueue("write the study spots file", goal_id="g5")
        job = local.next_task()

        body = api.ResultBody(taskId=job["taskId"],
                              summary="NO OUTPUT: a file was promised but none was written to disk.")
        with mock.patch.object(api.artifacts, "record_failure") as rec, \
             mock.patch.object(api.executor, "_settle_goal",
                               new_callable=mock.AsyncMock) as settle, \
             mock.patch.object(api.bus, "emit", new_callable=mock.AsyncMock):
            await api.local_result(body)

        rec.assert_called_once()
        settle.assert_awaited_once()
        self.assertTrue(settle.await_args.kwargs["failed"])

    async def test_real_result_settles_the_goal_as_completed(self):
        import resolve_control_plane.api as api

        local._queue.clear()
        local._inflight.clear()
        local.enqueue("research", goal_id="g6")
        job = local.next_task()

        body = api.ResultBody(taskId=job["taskId"], summary="Clemons, Brown, Shannon — full writeup")
        with mock.patch.object(api.artifacts, "record_failure") as rec, \
             mock.patch.object(api.executor, "_settle_goal",
                               new_callable=mock.AsyncMock) as settle, \
             mock.patch.object(api.bus, "emit", new_callable=mock.AsyncMock):
            await api.local_result(body)

        rec.assert_not_called()
        self.assertFalse(settle.await_args.kwargs["failed"])


if __name__ == "__main__":
    unittest.main()
