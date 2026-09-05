"""patch_raw dual-emit shims — new contract homes backfill the legacy keys the
UI still reads, so the dashboard survives the framework's dual-emit drop.

Daemon PID enums are a rename WITHIN /health (framework 0.9.74):
daemon -> nrem_daemon_process, rem_daemon -> rem_daemon_process. The legacy
keys are dual-emitted this release only and leave at the drop.
"""

import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from sm_telemetry_monitor.bridge import patch_raw
from sm_telemetry_monitor import collector
import sm_telemetry_monitor.system_health as _system_health_mod
from sm_telemetry_monitor.system_health import system_health_snapshot

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


if __name__ == "__main__":
    unittest.main()
