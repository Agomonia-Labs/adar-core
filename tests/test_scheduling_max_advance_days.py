"""Regression test for the max_advance_days / lead_time_minutes guardrail fix.

check_availability and get_weekly_availability previously never read a
practice's own lead_time_minutes/max_advance_days back off its Firestore
doc -- they silently fell through to compute_open_slots's hardcoded module
defaults (120 min / 60 days) for every practice, so a practice configured
with a tighter window (e.g. max_advance_days=7 for a dine-in restaurant)
wasn't actually enforced. This test exercises compute_open_slots directly
(pure logic, no Firestore) to confirm that when a caller passes a narrower
max_advance_days, no returned slot falls outside that window.
"""

import unittest
from datetime import datetime, timedelta, timezone

from domains.scheduling.tools.availability_tools import compute_open_slots


class MaxAdvanceDaysTests(unittest.TestCase):
    def test_no_slot_beyond_configured_max_advance_days(self):
        now = datetime(2026, 10, 16, 9, 0, tzinfo=timezone.utc)
        working_hours = [{"weekday": d, "start": "00:00", "end": "23:45"} for d in range(7)]

        slots = compute_open_slots(
            working_hours=working_hours,
            busy_intervals=[],
            duration_minutes=30,
            buffer_minutes=0,
            now=now,
            days_ahead=14,
            lead_time_minutes=0,
            max_advance_days=7,
            slot_step_minutes=15,
            max_results=1000,
        )

        self.assertTrue(slots, "expected at least one open slot")
        latest_allowed = now + timedelta(days=7)
        self.assertTrue(
            all(slot <= latest_allowed for slot in slots),
            f"found a slot beyond the 7-day cap: max slot was {max(slots)}, cap was {latest_allowed}",
        )

    def test_lead_time_minutes_is_respected(self):
        now = datetime(2026, 10, 16, 9, 0, tzinfo=timezone.utc)
        working_hours = [{"weekday": d, "start": "00:00", "end": "23:45"} for d in range(7)]

        slots = compute_open_slots(
            working_hours=working_hours,
            busy_intervals=[],
            duration_minutes=30,
            buffer_minutes=0,
            now=now,
            days_ahead=2,
            lead_time_minutes=180,
            max_advance_days=60,
            slot_step_minutes=15,
            max_results=1000,
        )

        earliest_allowed = now + timedelta(minutes=180)
        self.assertTrue(slots, "expected at least one open slot")
        self.assertTrue(
            all(slot >= earliest_allowed for slot in slots),
            f"found a slot before the lead-time floor: min slot was {min(slots)}, floor was {earliest_allowed}",
        )


if __name__ == "__main__":
    unittest.main()
