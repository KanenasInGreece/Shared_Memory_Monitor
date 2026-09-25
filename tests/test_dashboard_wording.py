"""Pins schema-drawer / LLM-pool wording in static/dashboard.html that plain
Python tests cannot otherwise reach (no JS test runner in this repo)."""

import unittest
from pathlib import Path

_DASHBOARD = Path(__file__).resolve().parent.parent / "static" / "dashboard.html"


class PoolWordingTests(unittest.TestCase):
    def setUp(self):
        self.html = _DASHBOARD.read_text()

    def test_free_means_spare_capacity_not_idle(self):
        self.assertIn("spare capacity", self.html)

    def test_dream_free_slots_stays_labelled_dream_ready(self):
        self.assertIn("dream-ready", self.html)

    def test_graph_paths_empty_states_distinguish_framework_version(self):
        self.assertIn("Needs framework", self.html)
        self.assertIn("computing", self.html)
        self.assertIn("pipelines_as_of", self.html)

    def test_fact_decision_meta_rows_use_rem_pending_and_unconsolidated(self):
        self.assertIn('"neo4j Fact", "rem_pending"', self.html)
        self.assertIn('"neo4j Fact", "unconsolidated"', self.html)
        self.assertIn('"neo4j Decision", "rem_pending"', self.html)
        # "REM-processed facts" elsewhere is the unrelated consolidation-coverage
        # KPI (coverage.rem_processed) — only the neo4j meta-row labels rename.
        self.assertNotIn('"neo4j Fact", "rem_processed"', self.html)
        self.assertNotIn('"neo4j Fact", "consolidated"', self.html)


if __name__ == "__main__":
    unittest.main()
