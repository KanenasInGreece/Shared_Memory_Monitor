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

    def test_deferred_with_no_work_reads_idle(self):
        # A deferred cycle with nothing eligible is idle, not a postponed job,
        # and must not be flagged as a warning.
        health = {"status": "ok", "consolidation": {"stalled": False, "fresh": True}}
        telemetry = {
            "status": "success",
            "telemetry": {
                "consolidation": {
                    "fact_consolidation": {
                        "last_outcome": "deferred",
                        "in_flight": False,
                        "consecutive_failures": 0,
                        "backlog": 0,
                        "eligible_clusters": None,
                        "stalled": False,
                    },
                },
            },
        }
        snap = consolidation_from_payload(health, telemetry)
        fact = next(c for c in snap["cycles"] if c["key"] == "fact_consolidation")
        self.assertEqual(fact["last_outcome"], "deferred")
        self.assertEqual(fact["last_outcome_display"], "idle")
        self.assertEqual(fact["state"], "ok")

    def test_deferred_with_backlog_stays_deferred(self):
        health = {"status": "ok", "consolidation": {"stalled": False, "fresh": True}}
        telemetry = {
            "status": "success",
            "telemetry": {
                "consolidation": {
                    "fact_consolidation": {
                        "last_outcome": "deferred",
                        "in_flight": False,
                        "consecutive_failures": 0,
                        "eligible_clusters": 3,
                        "stalled": False,
                    },
                },
            },
        }
        snap = consolidation_from_payload(health, telemetry)
        fact = next(c for c in snap["cycles"] if c["key"] == "fact_consolidation")
        self.assertEqual(fact["last_outcome_display"], "deferred")

    def test_deferred_reason_named(self):
        health = {"status": "ok", "consolidation": {"stalled": False, "fresh": True,
                                                    "last_outcome": "deferred"}}
        telemetry = {
            "status": "success",
            "telemetry": {
                "inference_busy": "busy",
                "consolidation": {
                    "last_outcome": "deferred",
                    "last_deferred_reason": "gpu_busy",
                    "fact_consolidation": {
                        "last_outcome": "deferred",
                        "last_deferred_reason": "gpu_busy",
                        "in_flight": False,
                        "eligible_clusters": 3,
                        "stalled": False,
                    },
                },
            },
        }
        snap = consolidation_from_payload(health, telemetry)
        self.assertEqual(snap["inference_busy"], "busy")
        self.assertEqual(snap["last_deferred_reason"], "gpu_busy")
        self.assertEqual(snap["last_deferred_reason_human"], "inference GPU busy")
        self.assertEqual(snap["tile"]["value"], "Deferred — inference GPU busy")
        fact = next(c for c in snap["cycles"] if c["key"] == "fact_consolidation")
        self.assertEqual(fact["last_outcome_display"], "deferred — inference GPU busy")
        self.assertEqual(fact["state"], "ok")

    def test_deferred_reason_pool_busy_named(self):
        # v0.6.1+ multi-backend gateways defer on a full LLM pool, not nvtop.
        health = {"status": "ok", "consolidation": {"stalled": False, "fresh": True,
                                                    "last_outcome": "deferred"}}
        telemetry = {
            "status": "success",
            "telemetry": {
                "consolidation": {
                    "last_outcome": "deferred",
                    "last_deferred_reason": "pool_busy",
                    "fact_consolidation": {
                        "last_outcome": "deferred",
                        "last_deferred_reason": "pool_busy",
                        "in_flight": False,
                        "eligible_clusters": 3,
                        "stalled": False,
                    },
                },
            },
        }
        snap = consolidation_from_payload(health, telemetry)
        self.assertEqual(snap["last_deferred_reason_human"], "LLM pool busy")
        self.assertEqual(snap["tile"]["value"], "Deferred — LLM pool busy")
        fact = next(c for c in snap["cycles"] if c["key"] == "fact_consolidation")
        self.assertEqual(fact["last_outcome_display"], "deferred — LLM pool busy")

    def test_stale_last_error_suppressed_after_completion(self):
        # The gateway keeps the most recent error forever (e.g. OrphanedRun from
        # a recovered daemon restart) — a completed cycle must not display it.
        health = {"status": "ok", "consolidation": {"stalled": False, "fresh": True}}
        telemetry = {
            "status": "success",
            "telemetry": {
                "consolidation": {
                    "fact_consolidation": {
                        "last_outcome": "completed",
                        "consecutive_failures": 0,
                        "stalled": False,
                        "last_error": {"class": "OrphanedRun",
                                       "msg": "daemon restarted while cycle was in-flight"},
                    },
                },
            },
        }
        snap = consolidation_from_payload(health, telemetry)
        fact = next(c for c in snap["cycles"] if c["key"] == "fact_consolidation")
        self.assertIsNone(fact["last_error"])
        self.assertEqual(fact["state"], "ok")

    def test_current_last_error_still_surfaced(self):
        health = {"status": "ok", "consolidation": {"stalled": False, "fresh": True}}
        telemetry = {
            "status": "success",
            "telemetry": {
                "consolidation": {
                    "fact_consolidation": {
                        "last_outcome": "crashed",
                        "consecutive_failures": 2,
                        "stalled": False,
                        "last_error": {"class": "LLMTimeout", "msg": "timed out"},
                    },
                },
            },
        }
        snap = consolidation_from_payload(health, telemetry)
        fact = next(c for c in snap["cycles"] if c["key"] == "fact_consolidation")
        self.assertEqual(fact["last_error"]["class"], "LLMTimeout")

    def test_fact_coverage_computed(self):
        health = {"status": "ok", "consolidation": {"stalled": False, "fresh": True}}
        telemetry = {
            "status": "success",
            "telemetry": {
                "neo4j": {
                    "facts_total": 175,
                    "facts_rem_pending": 0,
                    "facts_unconsolidated": 22,
                },
            },
        }
        snap = consolidation_from_payload(health, telemetry)
        cov = snap["coverage"]
        self.assertEqual(cov["rem_processed"], 175)
        self.assertEqual(cov["consolidated"], 153)
        self.assertEqual(cov["awaiting"], 22)
        self.assertEqual(cov["coverage_pct"], 87)
        self.assertEqual(cov["awaiting_pct"], 13)

    def test_fact_coverage_missing_census(self):
        health = {"status": "ok", "consolidation": {"stalled": False, "fresh": True}}
        snap = consolidation_from_payload(health, {"status": "success", "telemetry": {}})
        cov = snap["coverage"]
        self.assertIsNone(cov["rem_processed"])
        self.assertIsNone(cov["coverage_pct"])

    def test_graph_health_computed(self):
        # v0.6.1 entity_graph shape: orphans are degree-0 dangling, unmentioned
        # entities have edges but no live MENTIONS, alias layer is live.
        health = {"status": "ok", "consolidation": {"stalled": False, "fresh": True}}
        telemetry = {
            "status": "success",
            "telemetry": {
                "neo4j": {"facts_rem_pending": 50, "decisions_rem_pending": 32},
                "entity_graph": {
                    "entities_total": 2385,
                    "orphan_entities": 0,
                    "unmentioned_entities": 1384,
                    "singleton_entities": 538,
                    "alias_edges": 381,
                    "alias_covered_entities": 535,
                    "alias_components": 226,
                    "largest_alias_component": 9,
                    "top_hubs": [
                        {"name": "SharedMemory", "degree": 115},
                        {"name": "Neo4j", "degree": 112},
                    ],
                },
            },
        }
        gh = consolidation_from_payload(health, telemetry)["graph_health"]
        self.assertTrue(gh["present"])
        self.assertEqual(gh["entities_total"], 2385)
        self.assertEqual(gh["orphan_entities"], 0)
        self.assertEqual(gh["orphan_pct"], 0)
        self.assertEqual(gh["unmentioned_entities"], 1384)
        self.assertEqual(gh["unmentioned_pct"], 58)
        self.assertEqual(gh["mentioned_entities"], 1001)
        self.assertEqual(gh["mentioned_pct"], 42)
        self.assertEqual(gh["singleton_pct"], 23)
        self.assertEqual(gh["alias_edges"], 381)
        self.assertEqual(gh["alias_components"], 226)
        self.assertEqual(gh["largest_alias_component"], 9)
        self.assertEqual(gh["alias_coverage_pct"], 22)
        self.assertEqual(gh["max_hub_degree"], 115)
        self.assertEqual(len(gh["top_hubs"]), 2)
        # REM-pending records inflate fragmentation counts → flagged so the share
        # reads as an upper bound, not a settled fragmentation verdict.
        self.assertTrue(gh["rem_pending"])
        self.assertEqual(gh["rem_pending_facts"], 50)
        self.assertEqual(gh["rem_pending_decisions"], 32)

    def test_graph_health_pre_061_gateway_degrades(self):
        # Gateways below 0.6.1 omit unmentioned_entities/alias_components — the
        # new KPIs degrade to None without blanking the rest.
        health = {"status": "ok", "consolidation": {"stalled": False, "fresh": True}}
        telemetry = {
            "status": "success",
            "telemetry": {
                "entity_graph": {"entities_total": 1736, "orphan_entities": 961,
                                 "singleton_entities": 416, "alias_edges": 0,
                                 "top_hubs": []},
            },
        }
        gh = consolidation_from_payload(health, telemetry)["graph_health"]
        self.assertTrue(gh["present"])
        self.assertEqual(gh["orphan_pct"], 55)
        self.assertIsNone(gh["unmentioned_entities"])
        self.assertIsNone(gh["mentioned_entities"])
        self.assertIsNone(gh["alias_components"])
        self.assertEqual(gh["singleton_pct"], 24)

    def test_graph_health_no_rem_pending(self):
        health = {"status": "ok", "consolidation": {"stalled": False, "fresh": True}}
        telemetry = {
            "status": "success",
            "telemetry": {
                "neo4j": {"facts_rem_pending": 0, "decisions_rem_pending": 0},
                "entity_graph": {"entities_total": 100, "orphan_entities": 10,
                                 "singleton_entities": 5, "top_hubs": []},
            },
        }
        gh = consolidation_from_payload(health, telemetry)["graph_health"]
        self.assertTrue(gh["present"])
        self.assertFalse(gh["rem_pending"])

    def test_graph_health_missing(self):
        health = {"status": "ok", "consolidation": {"stalled": False, "fresh": True}}
        gh = consolidation_from_payload(health, {"status": "success", "telemetry": {}})["graph_health"]
        self.assertFalse(gh["present"])
        self.assertIsNone(gh["orphan_pct"])
        self.assertEqual(gh["top_hubs"], [])

    def test_last_success_falls_back_to_freshest_cycle(self):
        # Top-level rollup age is null but a cycle succeeded — use the cycle age.
        health = {
            "status": "ok",
            "consolidation": {"stalled": False, "fresh": True, "last_outcome": "completed",
                              "last_success_age_seconds": None},
        }
        telemetry = {
            "status": "success",
            "telemetry": {
                "consolidation": {
                    "insight": {"last_outcome": "completed", "last_success_age_seconds": None,
                                "eligible_clusters": 0, "stalled": False},
                    "fact_consolidation": {"last_outcome": "completed", "last_success_age_seconds": 16255,
                                           "eligible_clusters": 0, "stalled": False},
                },
            },
        }
        tile = consolidation_from_payload(health, telemetry)["tile"]
        self.assertEqual(tile["last_success_age_seconds"], 16255)
        self.assertTrue(tile["last_success_age_human"])

    def test_last_success_omitted_when_unknown(self):
        health = {
            "status": "ok",
            "consolidation": {"stalled": False, "fresh": True, "last_outcome": "completed",
                              "last_success_age_seconds": None},
        }
        telemetry = {
            "status": "success",
            "telemetry": {
                "consolidation": {
                    "insight": {"last_outcome": "completed", "last_success_age_seconds": None, "stalled": False},
                    "fact_consolidation": {"last_outcome": "deferred", "last_success_age_seconds": None, "stalled": False},
                },
            },
        }
        tile = consolidation_from_payload(health, telemetry)["tile"]
        self.assertIsNone(tile["last_success_age_seconds"])
        self.assertIsNone(tile["last_success_age_human"])

    def test_coverage_decisions_and_summaries(self):
        health = {"status": "ok", "consolidation": {"stalled": False, "fresh": True}}
        telemetry = {
            "status": "success",
            "telemetry": {
                "neo4j": {"facts_total": 175, "facts_rem_pending": 0, "facts_unconsolidated": 22,
                          "decisions_total": 119, "decisions_rem_pending": 0},
                "breakdown": {"summaries": [
                    {"kind": "insight", "active": 13, "superseded": 0},
                    {"kind": "thematic", "active": 7, "superseded": 1},
                ]},
            },
        }
        cov = consolidation_from_payload(health, telemetry)["coverage"]
        self.assertEqual(cov["decisions_total"], 119)
        self.assertEqual(cov["decisions_rem_processed"], 119)
        self.assertEqual(len(cov["summaries"]), 2)
        self.assertEqual(cov["summaries_active"], 20)
        self.assertEqual(cov["summaries_superseded"], 1)

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