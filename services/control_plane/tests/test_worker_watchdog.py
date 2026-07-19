"""Worker-offline watchdog: one alert per episode, hard 1/hour cap, silent recovery."""

import asyncio
import time
import unittest
from unittest import mock

from resolve_control_plane import local


def _tick():
    asyncio.run(local.watchdog_tick())


class WatchdogTest(unittest.TestCase):
    def setUp(self):
        local._watch.update({"offline_since": None, "alerted": False, "last_alert": 0.0})
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

    def test_recovery_is_silent_and_rearms(self):
        local._watch.update({"offline_since": time.time() - 999, "alerted": True})
        local._last_poll = time.time()  # worker is back
        _tick()
        self.assertEqual(self.emits, [])  # positive status updates are noise
        self.assertFalse(local._watch["alerted"])
        self.assertIsNone(local._watch["offline_since"])

    def test_flapping_capped_at_one_alert_per_hour(self):
        # episode 1: offline past grace → alerts
        local._watch["offline_since"] = time.time() - local.OFFLINE_ALERT_SECS - 1
        _tick()
        # recovers (silently), then goes down past grace AGAIN within the hour
        local._last_poll = time.time()
        _tick()
        local._last_poll = 0.0
        local._watch["offline_since"] = time.time() - local.OFFLINE_ALERT_SECS - 1
        _tick()
        self.assertEqual(self.emits, ["system.worker_offline"])  # still just one
        # a second episode AFTER the cooldown alerts again
        local._watch.update({"alerted": False,
                             "last_alert": time.time() - local.ALERT_COOLDOWN_SECS - 1,
                             "offline_since": time.time() - local.OFFLINE_ALERT_SECS - 1})
        _tick()
        self.assertEqual(self.emits, ["system.worker_offline", "system.worker_offline"])

    def test_online_and_quiet_stays_quiet(self):
        local._last_poll = time.time()
        _tick()
        self.assertEqual(self.emits, [])


if __name__ == "__main__":
    unittest.main()
