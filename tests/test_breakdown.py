import re
import unittest
from pathlib import Path

from sm_telemetry_monitor.breakdown import fetch_neo4j_breakdown, postgres_breakdown_from_telemetry

_SRC = Path(__file__).resolve().parent.parent / "src" / "sm_telemetry_monitor"


class Neo4jBreakdownFromTelemetryTests(unittest.TestCase):
    """fetch_neo4j_breakdown is a pure mapping of ONE telemetry payload (fact:2771,
    the 1.0.7 graph-shape note) — no gateway call of its own."""

    def test_full_payload(self):
        t = {
            "compliance": {
                "label_distribution": {"Fact": 1773, "Entity": 782, "Decision": 515},
                "predicate_distribution": {"SUMMARIZED_BY": 21339, "MENTIONS": 2933},
                "top_paths": [
                    {"from": "Retrospective", "rel": "SUMMARIZED_BY",
                     "to": "CommunitySummary", "count": 10958},
                ],
                "top_paths_as_of": "2026-09-25T20:21:58.937340+00:00",
            },
            "neo4j": {
                "facts_total": 1768, "facts_rem_pending": 0, "facts_unconsolidated": 750,
                "decisions_total": 515, "decisions_rem_pending": 0,
            },
        }
        out = fetch_neo4j_breakdown(t)
        self.assertEqual(out["nodes"][0], {"label": "Fact", "count": 1773})
        # sorted by count descending
        self.assertEqual([n["count"] for n in out["nodes"]], [1773, 782, 515])
        self.assertIn({"type": "SUMMARIZED_BY", "count": 21339}, out["relationships"])
        self.assertEqual(out["pipelines"][0]["from"], "Retrospective")
        self.assertEqual(out["pipelines"][0]["count"], 10958)
        self.assertEqual(out["pipelines_as_of"], "2026-09-25T20:21:58.937340+00:00")
        self.assertIsNone(out["pipelines_error"])
        self.assertEqual(out["facts"], {"total": 1768, "rem_pending": 0, "unconsolidated": 750})
        self.assertEqual(out["decisions"], {"total": 515, "rem_pending": 0})
        # deliberately NOT reconciled against label_distribution["Fact"] (1773 vs 1768)
        self.assertNotEqual(out["nodes"][0]["count"], out["facts"]["total"])

    def test_empty_graph_keys_absent_gives_empty_lists_no_computing_marker(self):
        # An empty graph: compliance present, but the element keys are absent.
        out = fetch_neo4j_breakdown({"compliance": {}, "neo4j": {}})
        self.assertEqual(out["nodes"], [])
        self.assertEqual(out["relationships"], [])
        self.assertEqual(out["pipelines"], [])
        # top_paths key itself was never sent -> no pipelines_as_of at all, not even null.
        self.assertNotIn("pipelines_as_of", out)
        self.assertIsNone(out["facts"])
        self.assertIsNone(out["decisions"])

    def test_null_as_of_with_empty_paths_means_computing(self):
        t = {"compliance": {"top_paths": [], "top_paths_as_of": None}}
        out = fetch_neo4j_breakdown(t)
        self.assertEqual(out["pipelines"], [])
        self.assertIn("pipelines_as_of", out)
        self.assertIsNone(out["pipelines_as_of"])

    def test_non_null_as_of_with_empty_paths_means_no_paths(self):
        t = {"compliance": {"top_paths": [], "top_paths_as_of": "2026-09-25T00:00:00+00:00"}}
        out = fetch_neo4j_breakdown(t)
        self.assertEqual(out["pipelines"], [])
        self.assertEqual(out["pipelines_as_of"], "2026-09-25T00:00:00+00:00")

    def test_top_paths_error_keeps_previous_rows(self):
        t = {
            "compliance": {
                "top_paths": [{"from": "Fact", "rel": "MENTIONS", "to": "Entity", "count": 5}],
                "top_paths_as_of": "2026-09-24T00:00:00+00:00",
                "top_paths_error": "refresh timed out",
            },
        }
        out = fetch_neo4j_breakdown(t)
        self.assertEqual(len(out["pipelines"]), 1)
        self.assertIn("refresh timed out", out["pipelines_error"])

    def test_non_int_counts_give_no_invented_numbers(self):
        t = {
            "compliance": {
                "label_distribution": {"Fact": 10, "Bad": "many", "Weird": True},
                "predicate_distribution": {"REL": "lots"},
            },
        }
        out = fetch_neo4j_breakdown(t)
        self.assertEqual(out["nodes"], [{"label": "Fact", "count": 10}])
        self.assertEqual(out["relationships"], [])

    def test_non_dict_telemetry_gives_defaults(self):
        out = fetch_neo4j_breakdown(None)
        self.assertEqual(out["nodes"], [])
        self.assertEqual(out["relationships"], [])
        self.assertEqual(out["pipelines"], [])
        self.assertIsNone(out["error"])


class NoQueryGraphReferencesTests(unittest.TestCase):
    """Section A removes bridge.query_graph and every POST /memory/graph call."""

    def test_zero_query_graph_references_in_src(self):
        hits = []
        for path in _SRC.rglob("*.py"):
            text = path.read_text()
            if re.search(r"\bquery_graph\b", text):
                hits.append(str(path))
        self.assertEqual(hits, [])


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
