"""Worker-offline watchdog: alerts once after the grace period, recovers once."""

import asyncio
import time
import unittest
from unittest import mock

from resolve_control_plane import local


def _tick():
    asyncio.run(local.watchdog_tick())


class WatchdogTest(unittest.TestCase):
    def setUp(self):
        local._watch.update({"offline_since": None, "alerted": False})
        local._last_poll = 0.0
        self.emits = []

        async def fake_emit(actor, type_, summary, **kw):
            self.emits.append(type_)

        self.emit_patch = mock.patch.object(local.bus, "emit", fake_emit)
        self.emit_patch.start()
        self.addCleanup(self.emit_patch.stop)

    def test_no_alert_inside_grace(self):
        _tick()  # arms offline_since
        _tick()  # still inside the 2-min grace (offline_since is ~now)
        self.assertEqual(self.emits, [])

    def test_alert_fires_once_after_grace(self):
        _tick()
        local._watch["offline_since"] = time.time() - local.OFFLINE_ALERT_SECS - 1
        _tick()
        _tick()  # must not re-alert
        self.assertEqual(self.emits, ["system.worker_offline"])

    def test_recovery_notifies_and_rearms(self):
        local._watch.update({"offline_since": time.time() - 999, "alerted": True})
        local._last_poll = time.time()  # worker is back
        _tick()
        self.assertEqual(self.emits, ["system.worker_online"])
        self.assertFalse(local._watch["alerted"])
        self.assertIsNone(local._watch["offline_since"])

    def test_online_and_quiet_stays_quiet(self):
        local._last_poll = time.time()
        _tick()
        self.assertEqual(self.emits, [])


if __name__ == "__main__":
    unittest.main()
