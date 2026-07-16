import unittest

from sm_telemetry_monitor.breakdown import postgres_breakdown_from_telemetry


class BreakdownFromTelemetryTests(unittest.TestCase):
    def test_maps_breakdown_and_outbox(self):
        pg = postgres_breakdown_from_telemetry({
            "breakdown": {
                "record_types": [{"key": "fact", "count": 10}],
                "agents": [{"key": "grok", "count": 5}],
                "sources": [],
                "domains": [],
                "summaries": [{"kind": "community_summary", "active": 3, "superseded": 1}],
            },
            "postgres": {
                "technical_docs": 682,
                "technical_docs_superseded": 10,
                "outbox": {"applied": 100, "failed": 1},
            },
        })
        self.assertIsNone(pg["error"])
        self.assertEqual(pg["record_types"][0]["count"], 10)
        self.assertEqual(pg["outbox"], [{"key": "applied", "count": 100}, {"key": "failed", "count": 1}])
        self.assertEqual(pg["technical_docs"], 682)
        self.assertEqual(pg["technical_docs_superseded"], 10)

    def test_breakdown_error(self):
        pg = postgres_breakdown_from_telemetry({"breakdown": {"error": "db down"}})
        self.assertIn("db down", pg["error"])


if __name__ == "__main__":
    unittest.main()
