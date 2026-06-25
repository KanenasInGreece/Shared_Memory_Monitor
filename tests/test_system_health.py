import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sm_telemetry_monitor.system_health import system_health_snapshot


def _healthy_gateway(*, backup_in_progress=False):
    return {
        "status": "ok",
        "embedder": "ok",
        "reranker": "ok",
        "llm": "ok",
        "daemon": "running",
        "rem_daemon": "running",
        "version": "0.4.12",
        "api_version": 1,
        "backup_in_progress": backup_in_progress,
    }


class SystemHealthBackupTests(unittest.TestCase):
    def _telemetry_payload(self):
        return {
            "status": "success",
            "telemetry": {
                "consolidation": {
                    "insight": {"stalled": False, "consecutive_failures": 0},
                    "fact_consolidation": {"stalled": False, "consecutive_failures": 0},
                },
            },
        }

    @patch("sm_telemetry_monitor.system_health.get_telemetry")
    @patch("sm_telemetry_monitor.system_health.live_summary", return_value={"latest": {}})
    @patch("sm_telemetry_monitor.system_health.get_health", return_value=_healthy_gateway())
    def test_backup_idle_by_default(self, _health, _summary, mock_telemetry):
        mock_telemetry.return_value = self._telemetry_payload()
        snap = system_health_snapshot()
        self.assertFalse(snap["backup"]["in_progress"])
        self.assertEqual(snap["backup"]["state"], "idle")
        self.assertEqual(snap["backup"]["value"], "idle")

    @patch("sm_telemetry_monitor.system_health.get_telemetry")
    @patch("sm_telemetry_monitor.system_health.live_summary", return_value={"latest": {}})
    @patch(
        "sm_telemetry_monitor.system_health.get_health",
        return_value=_healthy_gateway(backup_in_progress=True),
    )
    def test_backup_active_when_in_progress(self, _health, _summary, mock_telemetry):
        mock_telemetry.return_value = self._telemetry_payload()
        snap = system_health_snapshot()
        self.assertTrue(snap["backup"]["in_progress"])
        self.assertEqual(snap["backup"]["state"], "active")
        self.assertEqual(snap["backup"]["value"], "underway")
        self.assertEqual(snap["summary"], "backup underway")

    @patch("sm_telemetry_monitor.system_health.get_telemetry")
    @patch("sm_telemetry_monitor.system_health.live_summary", return_value={"latest": {}})
    @patch(
        "sm_telemetry_monitor.system_health.get_health",
        return_value={"status": "unreachable", "error": "connection refused"},
    )
    def test_backup_unknown_when_gateway_unreachable(self, _health, _summary, mock_telemetry):
        mock_telemetry.return_value = {"status": "error"}
        snap = system_health_snapshot()
        self.assertIsNone(snap["backup"]["in_progress"])
        self.assertEqual(snap["backup"]["state"], "unknown")
        self.assertFalse(snap["reachable"])

    @patch("sm_telemetry_monitor.system_health.get_telemetry")
    @patch("sm_telemetry_monitor.system_health.live_summary", return_value={"latest": {}})
    @patch("sm_telemetry_monitor.system_health.get_health", return_value=_healthy_gateway())
    def test_last_backup_from_manifest(self, _health, _summary, mock_telemetry):
        mock_telemetry.return_value = self._telemetry_payload()
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "sm-backup-20260617-030000.manifest.json"
            manifest.write_text(json.dumps({
                "name": "sm-backup-20260617-030000",
                "created": "2026-06-17T03:00:00+00:00",
            }))
            with patch("sm_telemetry_monitor.backup_reader.backup_dir", return_value=Path(tmp)):
                snap = system_health_snapshot()
        self.assertEqual(snap["backup"]["last_at"], "2026-06-17T03:00:00+00:00")
        self.assertEqual(snap["backup"]["last_name"], "sm-backup-20260617-030000")
        self.assertEqual(snap["backup"]["last_source"], "manifest")

    @patch("sm_telemetry_monitor.system_health.get_telemetry")
    @patch("sm_telemetry_monitor.system_health.live_summary", return_value={"latest": {}})
    @patch(
        "sm_telemetry_monitor.system_health.get_health",
        return_value={**_healthy_gateway(), "last_backup_at": "2026-06-16T12:00:00Z"},
    )
    def test_last_backup_prefers_health_field(self, _health, _summary, mock_telemetry):
        mock_telemetry.return_value = self._telemetry_payload()
        snap = system_health_snapshot()
        self.assertEqual(snap["backup"]["last_at"], "2026-06-16T12:00:00+00:00")
        self.assertEqual(snap["backup"]["last_source"], "health")

    @patch("sm_telemetry_monitor.system_health.get_telemetry")
    @patch("sm_telemetry_monitor.system_health.live_summary", return_value={"latest": {}})
    @patch(
        "sm_telemetry_monitor.system_health.get_health",
        return_value={
            **_healthy_gateway(),
            "consolidation": {"stalled": True, "fresh": True, "last_outcome": "deferred"},
        },
    )
    def test_consolidation_stalled_raises_critical(self, _health, _summary, mock_telemetry):
        mock_telemetry.return_value = self._telemetry_payload()
        snap = system_health_snapshot()
        self.assertEqual(snap["status"], "critical")
        self.assertEqual(snap["summary"], "consolidation stalled")
        self.assertIn("consolidation", snap)
        self.assertTrue(snap["consolidation"]["tile"]["stalled"])


if __name__ == "__main__":
    unittest.main()