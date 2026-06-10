import unittest

from sm_telemetry_monitor.analytics import enrich_row
from sm_telemetry_monitor.nrem_backlog import (
    compute_nrem_cycles,
    estimate_nrem_backlog,
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
        self.assertEqual(row["rem_backlog"], 3)
        self.assertEqual(row["dream_backlog"], 6)
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


if __name__ == "__main__":
    unittest.main()