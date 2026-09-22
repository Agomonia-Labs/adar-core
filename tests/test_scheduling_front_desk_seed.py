import json
import unittest
from pathlib import Path

from domains.scheduling.ingestion.seed_front_desk_demo import _validate


class FrontDeskDemoSeedTests(unittest.TestCase):
    def test_fixture_contains_six_valid_practices_and_twelve_bookings(self):
        fixture = Path(__file__).parents[1] / "domains/scheduling/ingestion/front_desk_demo.json"
        practices = json.loads(fixture.read_text(encoding="utf-8"))["practices"]

        _validate(practices)

        self.assertEqual(len(practices), 6)
        self.assertEqual(sum(len(item["appointment_types"]) for item in practices), 18)
        self.assertEqual(sum(len(item["providers"]) for item in practices), 13)
        self.assertEqual(sum(len(item["seed_bookings"]) for item in practices), 12)
        self.assertEqual(len({item["id"] for item in practices}), 6)


if __name__ == "__main__":
    unittest.main()
