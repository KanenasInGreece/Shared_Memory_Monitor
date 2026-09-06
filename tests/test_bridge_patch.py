"""patch_raw dual-emit shims — new contract homes backfill the legacy keys the
UI still reads, so the dashboard survives the framework's dual-emit drop.

Daemon PID enums are a rename WITHIN /health (framework 0.9.74):
daemon -> nrem_daemon_process, rem_daemon -> rem_daemon_process. The legacy
keys are dual-emitted this release only and leave at the drop.
"""

import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from sm_telemetry_monitor.bridge import get_telemetry, patch_raw, patch_telemetry
from sm_telemetry_monitor import collector
from sm_telemetry_monitor.breakdown import postgres_breakdown_from_telemetry
from sm_telemetry_monitor.consolidation import consolidation_from_payload
from sm_telemetry_monitor.system_health import _join_llm_faults, system_health_snapshot
import sm_telemetry_monitor.system_health as _system_health_mod

# Same convention as tests/test_system_health.py: pool status absent by default.
_system_health_mod.get_pool_status = lambda: {}


class PatchRawDaemonRenameTests(unittest.TestCase):
    def test_backfills_legacy_daemon_keys_from_new_names(self):
        # Post-drop /health: only the new names are present.
        raw = {"status": "ok", "nrem_daemon_process": "running",
               "rem_daemon_process": "stopped"}
        out = patch_raw(raw, {})
        self.assertEqual(out["daemon"], "running")
        self.assertEqual(out["rem_daemon"], "stopped")

    def test_new_names_win_during_dual_emit(self):
        raw = {"status": "ok", "daemon": "stopped", "rem_daemon": "stopped",
               "nrem_daemon_process": "running", "rem_daemon_process": "running"}
        out = patch_raw(raw, {})
        self.assertEqual(out["daemon"], "running")
        self.assertEqual(out["rem_daemon"], "running")

    def test_legacy_only_gateway_untouched(self):
        # Pre-0.9.74 /health: no new names — legacy reads keep working.
        raw = {"status": "ok", "daemon": "running", "rem_daemon": "running"}
        out = patch_raw(raw, {})
        self.assertEqual(out["daemon"], "running")
        self.assertEqual(out["rem_daemon"], "running")


class CollectorDaemonRenameTests(unittest.TestCase):
    def _payload(self):
        return {"status": "success", "telemetry": {"postgres": {}, "neo4j": {}}}

    def test_flatten_snapshot_reads_new_daemon_names(self):
        health = {"status": "ok", "nrem_daemon_process": "running",
                  "rem_daemon_process": "running"}
        row = collector.flatten_snapshot(self._payload(), datetime.now(UTC), health)
        self.assertEqual(row["daemon"], "running")
        self.assertEqual(row["rem_daemon"], "running")

    def test_flatten_snapshot_legacy_names_still_work(self):
        health = {"status": "ok", "daemon": "running", "rem_daemon": "stopped"}
        row = collector.flatten_snapshot(self._payload(), datetime.now(UTC), health)
        self.assertEqual(row["daemon"], "running")
        self.assertEqual(row["rem_daemon"], "stopped")


class SystemHealthDaemonRenameTests(unittest.TestCase):
    """REM/NREM tiles must render from the new /health names after the drop."""

    _HEALTH_POST_DROP = {
        "status": "ok",
        "embedder": "ok",
        "reranker": "ok",
        "llm": "ok",
        "nrem_daemon_process": "running",
        "rem_daemon_process": "running",
        "version": "0.9.75",
        "api_version": 4,
    }

    _TELEMETRY = {
        "status": "success",
        "telemetry": {
            "consolidation": {
                "insight": {"stalled": False, "consecutive_failures": 0},
                "fact_consolidation": {"stalled": False, "consecutive_failures": 0},
            },
        },
    }

    @patch("sm_telemetry_monitor.system_health.get_telemetry", return_value=_TELEMETRY)
    @patch("sm_telemetry_monitor.system_health.live_summary", return_value={"latest": {}})
    @patch("sm_telemetry_monitor.system_health.get_health", return_value=_HEALTH_POST_DROP)
    def test_daemon_tiles_ok_with_new_names_only(self, _health, _summary, _tel):
        snap = system_health_snapshot()
        by_key = {c["key"]: c for c in snap["components"]}
        self.assertEqual(by_key["nrem_daemon"]["process"]["state"], "ok")
        self.assertEqual(by_key["rem_daemon"]["process"]["state"], "ok")
        self.assertEqual(by_key["nrem_daemon"]["process"]["value"], "up")
        self.assertEqual(by_key["rem_daemon"]["process"]["value"], "up")


def _post_drop_t(**extra):
    t = {
        "outbox": {
            "pending": 1,
            "applied": 62,
            "failed": 3,
            "rem_reviewed": 548,
            "oldest_failed_age_s": 7200,
            "apply_latency_p50_s": 0.9,
            "drain_rate_per_min": 0.0,
        },
        "rem": {
            "dead_lettered": 2,
            "failing": 4,
            "max_attempts": 5,
            "passed_over": 9,
            "starved_pending": 1,
        },
        "llm": {"faults": {}},
        "postgres": {"pgvector": {"version": "0.8.6"}},
        "neo4j": {"facts_total": 10},
        "breakdown": {},
    }
    t.update(extra)
    return t


class PatchTelemetryDualEmitTests(unittest.TestCase):
    def test_post_drop_fills_snapshot_row(self):
        t = _post_drop_t()
        patch_telemetry(t)
        payload = {"status": "success", "telemetry": t}
        row = collector.flatten_snapshot(payload, datetime.now(UTC), {"status": "ok"})
        self.assertEqual(row["outbox_pending"], 1)
        self.assertEqual(row["outbox_applied"], 62)
        self.assertEqual(row["outbox_failed"], 3)
        self.assertEqual(row["outbox_rem_reviewed"], 548)
        self.assertEqual(row["rem_dead_lettered"], 2)
        self.assertEqual(row["rem_failing"], 4)
        self.assertEqual(row["rem_passed_over_total"], 9)
        self.assertEqual(row["rem_starved_pending"], 1)

    def test_post_drop_consolidation_rem_and_age(self):
        t = _post_drop_t()
        patch_telemetry(t)
        snap = consolidation_from_payload(
            {"status": "ok", "consolidation": {"stalled": False, "fresh": True}},
            {"status": "success", "telemetry": t},
        )
        self.assertEqual(snap["first_write_quality"]["dead_letter_age_seconds"], 7200)
        rr = snap["rem_reliability"]
        self.assertTrue(rr["present"])
        self.assertEqual(rr["dead_lettered"], 2)
        self.assertEqual(rr["failing"], 4)
        self.assertEqual(rr["max_attempts"], 5)
        self.assertEqual(rr["passed_over_total"], 9)
        self.assertEqual(rr["starved_pending"], 1)

    def test_post_drop_llm_faults_key_and_join(self):
        t = _post_drop_t()
        patch_telemetry(t)
        self.assertIn("llm_faults", t)
        self.assertEqual(t["llm_faults"], {})
        pool, _creds = _join_llm_faults(
            {"backends": []},
            {"status": "success", "telemetry": t},
            {"status": "ok"},
        )
        self.assertIsNotNone(pool)

    def test_dual_emit_new_wins_and_breakdown_allowlist(self):
        t = _post_drop_t()
        t["postgres"]["outbox"] = {"applied": 1, "rem_reviewed": 1}
        t["postgres"]["outbox_failed_oldest_age_seconds"] = 1
        t["neo4j"]["rem_failing"] = 99
        t["llm_faults"] = {"old": {}}
        t["llm"] = {"faults": {"http://x": {"gateway": {"count": 1}}}}
        patch_telemetry(t)
        self.assertEqual(t["postgres"]["outbox"]["applied"], 62)
        self.assertEqual(t["postgres"]["outbox_failed_oldest_age_seconds"], 7200)
        self.assertEqual(t["neo4j"]["rem_failing"], 4)
        self.assertEqual(t["llm_faults"], {"http://x": {"gateway": {"count": 1}}})
        bd = postgres_breakdown_from_telemetry(t)
        keys = {row["key"] for row in bd["outbox"]}
        self.assertEqual(keys, {"pending", "applied", "failed", "rem_reviewed"})
        self.assertNotIn("oldest_failed_age_s", keys)
        self.assertNotIn("apply_latency_p50_s", keys)

    def test_legacy_only_untouched(self):
        t = {
            "postgres": {"outbox": {"applied": 7, "rem_reviewed": 3},
                         "outbox_failed_oldest_age_seconds": 11},
            "neo4j": {"rem_dead_lettered": 8, "rem_failing": 1, "rem_max_attempts": 5},
            "llm_faults": {"http://x": {}},
        }
        before = {
            "outbox": dict(t["postgres"]["outbox"]),
            "age": t["postgres"]["outbox_failed_oldest_age_seconds"],
            "failing": t["neo4j"]["rem_failing"],
            "faults": t["llm_faults"],
        }
        patch_telemetry(t)
        self.assertEqual(t["postgres"]["outbox"], before["outbox"])
        self.assertEqual(t["postgres"]["outbox_failed_oldest_age_seconds"], 11)
        self.assertEqual(t["neo4j"]["rem_failing"], 1)
        self.assertEqual(t["llm_faults"], before["faults"])

    def test_null_age_preserved_absent_age_not_written(self):
        t = {"outbox": {"pending": 0, "oldest_failed_age_s": None}, "postgres": {}}
        patch_telemetry(t)
        self.assertIsNone(t["postgres"]["outbox_failed_oldest_age_seconds"])
        self.assertEqual(t["postgres"]["outbox"]["pending"], 0)
        t2 = {"outbox": {"pending": 0}, "postgres": {}}
        patch_telemetry(t2)
        self.assertNotIn("outbox_failed_oldest_age_seconds", t2["postgres"])
        self.assertEqual(t2["postgres"]["outbox"]["pending"], 0)
        t3 = {"outbox": {"oldest_failed_age_s": float("inf")}, "postgres": {}}
        patch_telemetry(t3)
        self.assertNotIn("outbox_failed_oldest_age_seconds", t3["postgres"])

    def test_both_homes_absent_does_not_mint_llm_faults(self):
        t = {"postgres": {}, "neo4j": {}}
        patch_telemetry(t)
        self.assertNotIn("llm_faults", t)

    def test_breakdown_post_drop_count_rows_only(self):
        t = _post_drop_t()
        del t["postgres"]
        patch_telemetry(t)
        bd = postgres_breakdown_from_telemetry(t)
        keys = {row["key"] for row in bd["outbox"]}
        self.assertEqual(keys, {"pending", "applied", "failed", "rem_reviewed"})
        by = {row["key"]: row["count"] for row in bd["outbox"]}
        self.assertEqual(by["pending"], 1)
        self.assertEqual(by["failed"], 3)

    def test_postgres_pgvector_and_neo4j_siblings_survive(self):
        t = _post_drop_t()
        patch_telemetry(t)
        self.assertEqual(t["postgres"]["pgvector"]["version"], "0.8.6")
        self.assertEqual(t["neo4j"]["facts_total"], 10)

    def test_non_dict_new_homes_skipped(self):
        t = {"outbox": "nope", "rem": ["x"], "llm": "ok", "postgres": {"pgvector": 1}}
        patch_telemetry(t)
        self.assertEqual(t["postgres"], {"pgvector": 1})
        self.assertNotIn("neo4j", t)
        self.assertNotIn("llm_faults", t)

    def test_get_telemetry_returns_payload_if_patch_raises(self):
        class Boom(Exception):
            pass

        payload = {"status": "success", "telemetry": {"outbox": {"pending": 1}}}

        class _Resp:
            status_code = 200

            def json(self):
                return payload

        with patch("sm_telemetry_monitor.bridge._http") as http:
            http.return_value.get.return_value = _Resp()
            with patch("sm_telemetry_monitor.bridge.patch_telemetry", side_effect=Boom("x")):
                out = get_telemetry()
        self.assertEqual(out["status"], "success")
        self.assertEqual(out["telemetry"]["outbox"]["pending"], 1)

    def test_get_telemetry_wires_patch_on_post_drop_payload(self):
        payload = {
            "status": "success",
            "telemetry": {
                "outbox": {"pending": 0, "applied": 4},
                "rem": {"failing": 2},
                "llm": {"faults": {}},
            },
        }

        class _Resp:
            status_code = 200

            def json(self):
                return payload

        with patch("sm_telemetry_monitor.bridge._http") as http:
            http.return_value.get.return_value = _Resp()
            out = get_telemetry()
        t = out["telemetry"]
        self.assertEqual(t["postgres"]["outbox"]["pending"], 0)
        self.assertEqual(t["postgres"]["outbox"]["applied"], 4)
        self.assertEqual(t["neo4j"]["rem_failing"], 2)
        self.assertEqual(t["llm_faults"], {})


if __name__ == "__main__":
    unittest.main()
