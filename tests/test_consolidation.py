import unittest
from unittest.mock import patch

from sm_telemetry_monitor.consolidation import (
    consolidation_from_payload,
    consolidation_snapshot,
    humanize_age,
)


class HumanizeAgeTests(unittest.TestCase):
    def test_none(self):
        self.assertEqual(humanize_age(None), "—")

    def test_seconds(self):
        self.assertEqual(humanize_age(45), "45s ago")

    def test_minutes(self):
        self.assertEqual(humanize_age(125), "2m ago")


class ConsolidationFromPayloadTests(unittest.TestCase):
    def test_healthy_tile(self):
        health = {
            "status": "ok",
            "consolidation": {
                "stalled": False,
                "fresh": True,
                "last_outcome": "completed",
                "last_success_age_seconds": None,
            },
        }
        telemetry = {
            "status": "success",
            "telemetry": {
                "timestamp": "2026-06-25T10:00:00+00:00",
                "consolidation": {
                    "stall_threshold_seconds": 9000,
                    "insight": {
                        "last_outcome": "completed",
                        "in_flight": False,
                        "consecutive_failures": 0,
                        "backlog": 0,
                        "eligible_clusters": 0,
                        "stalled": False,
                    },
                    "fact_consolidation": {
                        "last_outcome": "completed",
                        "in_flight": False,
                        "consecutive_failures": 0,
                        "backlog": 0,
                        "stalled": False,
                    },
                },
                "nrem": {"fact_cycles": 0, "decision_cycles": 1},
            },
        }
        snap = consolidation_from_payload(health, telemetry, fetched_at="2026-06-25T10:01:00+00:00")
        self.assertTrue(snap["reachable"])
        self.assertEqual(snap["tile"]["value"], "Healthy")
        self.assertEqual(snap["tile"]["state"], "ok")
        self.assertFalse(snap["tile"]["stalled"])
        self.assertEqual(len(snap["cycles"]), 2)
        self.assertEqual(snap["cycles"][0]["label"], "Insight")

    def test_stalled_tile(self):
        health = {
            "status": "ok",
            "consolidation": {
                "stalled": True,
                "fresh": True,
                "last_outcome": "deferred",
            },
        }
        snap = consolidation_from_payload(health, {"status": "success", "telemetry": {}})
        self.assertEqual(snap["tile"]["state"], "bad")
        self.assertEqual(snap["tile"]["value"], "Stalled")

    def test_stale_signal(self):
        health = {
            "status": "ok",
            "consolidation": {"stalled": True, "fresh": False},
        }
        snap = consolidation_from_payload(health, {"status": "success", "telemetry": {}})
        self.assertEqual(snap["tile"]["state"], "warn")
        self.assertEqual(snap["tile"]["value"], "Signal stale")

    @patch("sm_telemetry_monitor.consolidation.get_telemetry")
    @patch("sm_telemetry_monitor.consolidation.get_health")
    def test_snapshot_calls_bridge(self, mock_health, mock_telemetry):
        mock_health.return_value = {"status": "ok", "consolidation": {"stalled": False, "fresh": True}}
        mock_telemetry.return_value = {"status": "success", "telemetry": {}}
        snap = consolidation_snapshot()
        self.assertTrue(snap["reachable"])
        mock_health.assert_called_once()
        mock_telemetry.assert_called_once()


if __name__ == "__main__":
    unittest.main()