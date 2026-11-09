import unittest

from datetime import UTC, datetime

from sm_telemetry_monitor.analytics import build_api_payload, enrich_row, story_summary
from sm_telemetry_monitor.collector import flatten_snapshot
from sm_telemetry_monitor.nrem_backlog import (
    compute_nrem_cycles,
    nrem_counts_from_telemetry,
    partition_domain_clusters,
)


class TestPartitionDomainClusters(unittest.TestCase):
    def test_fact_threshold_five(self):
        domain_map = {1: "homelab", 2: "homelab", 3: "homelab", 4: "homelab", 5: "homelab"}
        self.assertEqual(
            partition_domain_clusters([1, 2, 3, 4, 5], domain_map=domain_map, threshold=5),
            1,
        )

    def test_split_domains_below_threshold(self):
        domain_map = {1: "a", 2: "a", 3: "b", 4: "b", 5: "b", 6: "b", 7: "b"}
        self.assertEqual(
            partition_domain_clusters(list(range(1, 8)), domain_map=domain_map, threshold=5),
            1,
        )

    def test_decision_threshold_two(self):
        domain_map = {10: "general", 11: "general"}
        self.assertEqual(
            partition_domain_clusters([10, 11], domain_map=domain_map, threshold=2),
            1,
        )


class TestComputeNremCycles(unittest.TestCase):
    def test_counts_fact_and_decision_cycles(self):
        payload = compute_nrem_cycles(
            fact_clusters=[
                {"entity": "SharedMemory", "pg_ids": [1, 2, 3, 4, 5, 6]},
            ],
            decision_pg_ids=[20, 21, 22, 23],
            domain_map={
                1: "shared-memory", 2: "shared-memory", 3: "shared-memory",
                4: "shared-memory", 5: "shared-memory", 6: "homelab",
                20: "general", 21: "general", 22: "homelab", 23: "homelab",
            },
        )
        self.assertEqual(payload["nrem_fact_cycles"], 1)
        self.assertEqual(payload["nrem_decision_cycles"], 2)
        self.assertEqual(payload["nrem_backlog"], 3)


class TestEnrichRowNrem(unittest.TestCase):
    def test_dream_backlog_uses_cycles_not_raw_facts(self):
        row = enrich_row(
            {
                "facts_rem_pending": 1,
                "decisions_rem_pending": 2,
                "facts_unconsolidated": 24,
                "facts_total": 100,
            },
            nrem_counts={
                "nrem_backlog": 3,
                "nrem_fact_cycles": 2,
                "nrem_decision_cycles": 1,
                "nrem_backlog_source": "telemetry",
            },
        )
        self.assertEqual(row["nrem_backlog"], 3)
        self.assertEqual(row["rem_backlog"], 1)
        self.assertEqual(row["dream_backlog"], 4)
        self.assertEqual(row["decisions_rem_pending"], 2)
        self.assertEqual(row["facts_unconsolidated"], 24)
        self.assertEqual(row["nrem_backlog_source"], "telemetry")

    def test_persisted_telemetry_nrem_on_row(self):
        row = enrich_row({
            "facts_rem_pending": 0,
            "decisions_rem_pending": 0,
            "facts_unconsolidated": 24,
            "facts_total": 100,
            "nrem_backlog": 1,
            "nrem_fact_cycles": 0,
            "nrem_decision_cycles": 1,
            "nrem_backlog_source": "telemetry",
        })
        self.assertEqual(row["nrem_backlog"], 1)
        self.assertEqual(row["nrem_decision_cycles"], 1)

    def test_estimate_when_clusters_unavailable(self):
        row = enrich_row({"facts_unconsolidated": 24, "facts_total": 100})
        self.assertEqual(row["nrem_backlog"], 4)
        self.assertEqual(row["nrem_backlog_source"], "estimate")
        self.assertEqual(row["dream_backlog"], 4)
        self.assertIsNone(row["rem_backlog"])


class TestNewReadingsStayAbsent(unittest.TestCase):
    """A key the gateway did not send stays None. A sent 1490 is kept."""

    def test_missing_new_key_stays_none_and_decisions_are_not_rem(self):
        row = enrich_row(
            {"facts_rem_pending": 1, "decisions_rem_pending": 2, "facts_total": 10},
            nrem_counts={
                "nrem_backlog": 3,
                "nrem_fact_cycles": 3,
                "nrem_decision_cycles": 0,
                "nrem_backlog_source": "telemetry",
            },
        )
        self.assertEqual(row["rem_backlog"], 1)
        self.assertEqual(row["dream_backlog"], 4)
        self.assertNotIn("retrospectives_rem_pending", row)
        self.assertNotIn("rem_backlog_older_prompt", row)
        self.assertNotIn("rem_backlog_withheld", row)
        self.assertNotIn("insight_excluded_pending_rem", row)
        payload = build_api_payload([{
            "collected_at": "2026-11-09T00:00:00+00:00",
            **row,
        }])
        for key in (
            "retrospectives_rem_pending",
            "rem_backlog_older_prompt",
            "rem_backlog_withheld",
            "insight_excluded_pending_rem",
        ):
            self.assertIsNone(payload["series"][key][0])
        stages = {s["key"]: s["value"] for s in payload["pipeline"]}
        self.assertIsNone(stages["rem_backlog_older_prompt"])
        self.assertEqual(stages["decisions_rem_pending"], 2)
        decisions = next(s for s in payload["pipeline"] if s["key"] == "decisions_rem_pending")
        self.assertEqual(decisions["label"], "Decisions not ready")

    def test_present_1490_is_kept(self):
        row = enrich_row({
            "facts_rem_pending": 0,
            "decisions_rem_pending": 7,
            "facts_total": 10,
            "rem_backlog_older_prompt": 1490,
            "rem_backlog_withheld": 0,
            "retrospectives_rem_pending": 4,
            "nrem_backlog": 3,
            "nrem_fact_cycles": 3,
            "nrem_decision_cycles": 0,
            "nrem_backlog_source": "telemetry",
            "insight_excluded_pending_rem": 1490,
        })
        self.assertEqual(row["rem_backlog"], 0)
        self.assertEqual(row["dream_backlog"], 3)
        self.assertEqual(row["rem_backlog_older_prompt"], 1490)
        self.assertEqual(row["rem_backlog_withheld"], 0)
        self.assertEqual(row["insight_excluded_pending_rem"], 1490)
        self.assertEqual(row["retrospectives_rem_pending"], 4)
        payload = build_api_payload([{
            "collected_at": "2026-11-09T00:00:00+00:00",
            **{k: v for k, v in row.items() if k != "rem_backlog"},
        }])
        # enrich runs again. The stored 1490 is still the series point.
        self.assertEqual(payload["series"]["rem_backlog_older_prompt"], [1490])
        self.assertEqual(payload["series"]["insight_excluded_pending_rem"], [1490])
        self.assertEqual(payload["series"]["rem_backlog_withheld"], [0])
        self.assertEqual(payload["latest"]["rem_backlog"], 0)

    def test_nrem_counts_copy_insight_only_when_present(self):
        absent = nrem_counts_from_telemetry({
            "nrem": {"fact_cycles": 1, "decision_cycles": 2, "total_cycles": 3},
        })
        self.assertNotIn("insight_excluded_pending_rem", absent)
        present = nrem_counts_from_telemetry({
            "nrem": {
                "fact_cycles": 0,
                "decision_cycles": 0,
                "total_cycles": 0,
                "insight_excluded_pending_rem": 1490,
            },
        })
        self.assertEqual(present["insight_excluded_pending_rem"], 1490)

    def test_flatten_copies_sent_keys_and_omits_missing_ones(self):
        payload = {
            "status": "success",
            "telemetry": {
                "postgres": {},
                "neo4j": {"facts_rem_pending": 0, "retrospectives_rem_pending": 3},
                "rem": {"backlog_older_prompt": 1490},
                "nrem": {
                    "fact_cycles": 0,
                    "decision_cycles": 0,
                    "total_cycles": 0,
                    "insight_excluded_pending_rem": 0,
                },
            },
        }
        row = flatten_snapshot(payload, datetime.now(UTC), {"status": "ok"})
        self.assertEqual(row["retrospectives_rem_pending"], 3)
        self.assertEqual(row["rem_backlog_older_prompt"], 1490)
        self.assertEqual(row["insight_excluded_pending_rem"], 0)
        self.assertNotIn("rem_backlog_withheld", row)
        bare = flatten_snapshot(
            {"status": "success", "telemetry": {"postgres": {}, "neo4j": {}}},
            datetime.now(UTC),
            {"status": "ok"},
        )
        for key in (
            "retrospectives_rem_pending",
            "rem_backlog_older_prompt",
            "rem_backlog_withheld",
            "insight_excluded_pending_rem",
        ):
            self.assertNotIn(key, bare)


class TestBacklogDoesNotInventHealth(unittest.TestCase):
    """decision:1973 — a backlog count is not a warn or critical badge."""

    def _raw(self, **extra):
        row = {
            "facts_rem_pending": 0,
            "decisions_rem_pending": 0,
            "facts_unconsolidated": 1113,
            "facts_total": 2000,
            "nrem_backlog": 44,
            "nrem_fact_cycles": 22,
            "nrem_decision_cycles": 22,
            "nrem_backlog_source": "telemetry",
            "consolidation_stalled": False,
            "consolidation_fresh": True,
            "outbox_failed": 0,
        }
        row.update(extra)
        return row

    def test_backlog_44_stays_ok_and_states_the_count(self):
        raw = self._raw()
        row = enrich_row(raw)
        self.assertEqual(row["rem_backlog"], 0)
        self.assertEqual(row["nrem_backlog"], 44)
        self.assertEqual(row["dream_backlog"], 44)
        self.assertNotIn("health", row)
        stained = enrich_row({**raw, "health": "warn"})
        self.assertNotIn("health", stained)
        self.assertEqual(stained["dream_backlog"], 44)
        story = story_summary([raw])
        self.assertEqual(story["health"], "ok")
        self.assertNotIn("saturated", story["headline"].lower())
        self.assertNotIn("saturated", story["detail"].lower())
        self.assertIn("44", story["headline"])
        self.assertIn("1113", story["detail"])
        self.assertIn("22 fact", story["detail"])
        self.assertIn("22 decision", story["detail"])

    def test_rem_count_headline_is_not_saturated(self):
        story = story_summary([self._raw(
            facts_rem_pending=5,
            nrem_backlog=0,
            nrem_fact_cycles=0,
            nrem_decision_cycles=0,
            facts_unconsolidated=0,
        )])
        self.assertEqual(story["health"], "ok")
        self.assertNotIn("saturated", story["headline"].lower())
        self.assertIn("5", story["headline"])

    def test_outbox_failed_count_does_not_set_story_health(self):
        story = story_summary([self._raw(outbox_failed=3, nrem_backlog=0)])
        self.assertEqual(story["health"], "ok")
        self.assertIn("outbox failure", story["headline"])
        self.assertNotIn("may be stuck", story["headline"])

    def test_gateway_stall_still_marks_story_critical(self):
        story = story_summary([self._raw(consolidation_stalled=True)])
        self.assertEqual(story["health"], "critical")
        self.assertNotIn("saturated", story["headline"].lower())

    def test_gateway_fresh_false_warns_without_a_count_badge(self):
        story = story_summary([self._raw(consolidation_fresh=False)])
        self.assertEqual(story["health"], "warn")
        self.assertEqual(story["headline"], "Consolidation signal stale")
        self.assertNotIn("saturated", story["headline"].lower())


if __name__ == "__main__":
    unittest.main()