"""Pins schema-drawer / LLM-pool wording in static/dashboard.html that plain
Python tests cannot otherwise reach (no JS test runner in this repo)."""

import unittest
from pathlib import Path

_DASHBOARD = Path(__file__).resolve().parent.parent / "static" / "dashboard.html"


class PoolWordingTests(unittest.TestCase):
    def setUp(self):
        self.html = _DASHBOARD.read_text()

    def test_free_means_spare_capacity_not_idle(self):
        self.assertIn('line.title = "free = spare capacity', self.html)

    def test_dream_free_slots_stays_labelled_dream_ready(self):
        self.assertIn("dream-ready", self.html)

    def test_graph_paths_empty_states_distinguish_framework_version(self):
        self.assertIn('pathsEmptyMsg = "Needs framework ≥ 1.0.7', self.html)
        self.assertIn('pathsEmptyMsg = "paths: not computed yet (or disabled', self.html)
        self.assertIn('const pathsSupported = "pipelines_as_of" in nj;', self.html)

    def test_kept_paths_show_their_age(self):
        self.assertIn("asOf.textContent = paths.length && nj.pipelines_as_of", self.html)

    def test_count_cells_are_escaped(self):
        self.assertIn("<td>${esc(p.count)}</td>", self.html)
        self.assertIn("<td>${esc(r[2])}</td>", self.html)
        self.assertNotIn("<td>${p.count}</td>", self.html)

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
