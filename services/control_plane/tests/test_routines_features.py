"""Feature batch: budget guardrail, travel watch, health lane, weekly gather."""

import asyncio
import time
import unittest
from unittest import mock

from resolve_control_plane import health, ingest, routines


class BudgetMathTest(unittest.TestCase):
    def test_spend_mtd_counts_only_this_months_outflows(self):
        txns = [
            {"amount": -50.0, "date": "2026-07-10"},
            {"amount": -25.5, "date": "2026-07-01"},
            {"amount": 500.0, "date": "2026-07-05"},   # income — not spend
            {"amount": -99.0, "date": "2026-06-28"},   # last month
            {"amount": -10.0, "date": ""},             # undated — excluded
        ]
        self.assertEqual(routines._spend_mtd(txns, "2026-07-01"), 75.5)

    def test_budget_levels(self):
        self.assertIsNone(routines._budget_level(49.9))
        self.assertEqual(routines._budget_level(50), 50)
        self.assertEqual(routines._budget_level(79.9), 50)
        self.assertEqual(routines._budget_level(80), 80)
        self.assertEqual(routines._budget_level(101), 100)

    def test_check_budget_noop_without_env(self):
        with mock.patch.dict("os.environ", {"MONTHLY_BUDGET": ""}):
            asyncio.run(routines.check_budget())  # must not raise or call finance


class TravelWatchTest(unittest.TestCase):
    def test_detects_flight_events_today_only(self):
        events = [
            {"title": "Flight to Dublin EI 122", "start": "2026-08-01T17:30:00-04:00"},
            {"title": "Haircut", "start": "2026-08-01T10:00:00-04:00"},
            {"title": "Airport pickup", "start": "2026-08-02T09:00:00-04:00"},
            {"title": "✈ home", "start": "2026-08-01"},
        ]
        hits = routines._travel_events(events, "2026-08-01")
        self.assertEqual([e["title"] for e in hits], ["Flight to Dublin EI 122", "✈ home"])

    def test_no_false_positive_on_normal_days(self):
        events = [{"title": "Date Night", "start": "2026-08-01T19:00:00-04:00"},
                  {"title": "flyer design review", "start": "2026-08-01T12:00:00-04:00"}]
        # "flyer" contains 'fly' but not as a word — must NOT trigger
        self.assertEqual(routines._travel_events(events, "2026-08-01"), [])


class HealthLaneTest(unittest.TestCase):
    def setUp(self):
        health._latest, health._latest_ts = None, 0.0

    def test_ingest_sanitizes_and_serves_latest(self):
        with mock.patch.object(health.store, "insert"), \
             mock.patch.object(health.bus, "emit", mock.AsyncMock()):
            out = asyncio.run(health.ingest({
                "sleep_hours": "7.4", "Resting HR": 52, "hrv": 68.5,
                "junk_field": "ignore me", "note": "slept great",
            }))
        self.assertTrue(out["ok"])
        latest = health.latest()
        self.assertEqual(latest["sleep_hours"], 7.4)
        self.assertEqual(latest["resting_hr"], 52)
        self.assertNotIn("junk_field", latest)

    def test_stale_reading_reports_no_data(self):
        health._latest = {"sleep_hours": 8}
        health._latest_ts = time.time() - health.FRESH_SECS - 10
        self.assertIsNone(health.latest())
        self.assertFalse(health.configured())

    def test_empty_post_rejected(self):
        out = asyncio.run(health.ingest({"junk": 1}))
        self.assertFalse(out["ok"])


class WeeklyGatherTest(unittest.TestCase):
    def test_gather_recent_labels_days_and_skips_empties(self):
        calls = []

        def fake_materials(day):
            calls.append(day)
            return "- COMMAND: did a thing" if len(calls) % 2 else ""
        with mock.patch.object(ingest, "gather_materials", side_effect=fake_materials):
            out = ingest.gather_recent(5)
        self.assertEqual(len(calls), 5)
        self.assertIn(f"=== {calls[0]} ===", out)
        self.assertIn("did a thing", out)
        self.assertEqual(out.count("=== "), 3)  # empties (calls 2 & 4) skipped

    def test_gather_recent_empty_week(self):
        with mock.patch.object(ingest, "gather_materials", return_value=""):
            out = ingest.gather_recent(3)
        self.assertIn("no recorded activity", out)


if __name__ == "__main__":
    unittest.main()
