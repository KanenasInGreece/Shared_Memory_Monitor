import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sm_telemetry_monitor.analytics import rem_drain_signal
from sm_telemetry_monitor.system_health import (
    _llm_pool_summary,
    _workload_part,
    system_health_snapshot,
)


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


class LlmInferenceBusyTests(unittest.TestCase):
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

    def _snap(self, health):
        with patch("sm_telemetry_monitor.system_health.get_telemetry",
                   return_value=self._telemetry_payload()), \
             patch("sm_telemetry_monitor.system_health.live_summary",
                   return_value={"latest": {}}), \
             patch("sm_telemetry_monitor.system_health.get_health", return_value=health):
            return system_health_snapshot()

    def _llm(self, snap):
        return next(c for c in snap["components"] if c["key"] == "llm")

    def test_inference_busy_renders_llm_busy(self):
        snap = self._snap({**_healthy_gateway(), "inference_busy": "busy"})
        self.assertEqual(snap["inference_busy"], "busy")
        llm = self._llm(snap)
        self.assertEqual(llm["workload"]["value"], "busy")
        self.assertEqual(llm["state"], "ok")
        self.assertNotEqual(snap["status"], "critical")

    def test_inference_idle_renders_llm_idle(self):
        llm = self._llm(self._snap({**_healthy_gateway(), "inference_busy": "idle"}))
        self.assertEqual(llm["workload"]["value"], "idle")
        self.assertEqual(llm["state"], "ok")

    def test_inference_unknown_does_not_claim_idle(self):
        # nvtop absent / SLOT_AWARE=0 — no false "idle".
        llm = self._llm(self._snap({**_healthy_gateway(), "inference_busy": "unknown"}))
        self.assertEqual(llm["workload"]["value"], "ready")
        self.assertEqual(llm["state"], "ok")

    def test_probe_down_but_gpu_busy_is_not_critical(self):
        # The reachability probe timed out under load, but nvtop confirms the GPU
        # is inferring: warn (back-pressure), never critical while it is running.
        snap = self._snap({**_healthy_gateway(), "llm": "down", "inference_busy": "busy"})
        llm = self._llm(snap)
        self.assertEqual(llm["state"], "warn")
        self.assertNotEqual(snap["status"], "critical")

    def test_probe_down_and_gpu_idle_is_critical(self):
        snap = self._snap({**_healthy_gateway(), "llm": "down", "inference_busy": "idle"})
        self.assertEqual(self._llm(snap)["state"], "bad")
        self.assertEqual(snap["status"], "critical")


class RemTileTests(unittest.TestCase):
    """REM tile warns only on a genuine stall (GPU free, backlog not draining)."""

    def _rem(self, backlog, *, inference_busy="idle", rem_trend="insufficient", llm="ok"):
        raw = {"rem_daemon": "running", "llm": llm}
        return _workload_part(
            "rem_daemon", raw, {"rem_backlog": backlog},
            inference_busy=inference_busy, rem_trend=rem_trend,
        )

    def test_caught_up_is_ok(self):
        w = self._rem(0)
        self.assertEqual(w["state"], "ok")
        self.assertEqual(w["value"], "queue idle")

    def test_backlog_with_gpu_busy_defers_not_warns(self):
        # The exact symptom that prompted this: 6 facts, LLM busy → no warning.
        w = self._rem(6, inference_busy="busy")
        self.assertEqual(w["state"], "ok")
        self.assertIn("deferring", w["value"])

    def test_backlog_draining_is_not_warn(self):
        w = self._rem(6, inference_busy="idle", rem_trend="draining")
        self.assertEqual(w["state"], "ok")
        self.assertIn("draining", w["value"])

    def test_backlog_insufficient_history_is_not_warn(self):
        w = self._rem(6, inference_busy="unknown", rem_trend="insufficient")
        self.assertEqual(w["state"], "ok")
        self.assertIn("queued", w["value"])

    def test_free_gpu_not_draining_warns(self):
        w = self._rem(6, inference_busy="idle", rem_trend="flat")
        self.assertEqual(w["state"], "warn")
        self.assertIn("stalled", w["value"])

    def test_no_backlog_data_is_unknown(self):
        self.assertEqual(self._rem(None)["state"], "unknown")

    def test_daemon_down_is_bad(self):
        w = _workload_part("rem_daemon", {"rem_daemon": "stopped", "llm": "ok"},
                           {"rem_backlog": 6}, inference_busy="idle")
        self.assertEqual(w["state"], "bad")


def _pool_gateway(*, s5000="ok", s4000="ok", inflight5000=0, inflight4000=0,
                  cooldown4000=0.0):
    """Two-backend gateway /health as emitted since framework v0.6.1 (LLM pool)."""
    return {
        **_healthy_gateway(),
        "llm_backends": {"http://localhost:5000": s5000, "http://localhost:4000": s4000},
        "llm_pool": {
            "http://localhost:5000": {"weight": 1.0, "inflight": inflight5000,
                                      "routed": 38, "routed_pct": 88.4, "fails": 2,
                                      "cooldown": 0.0, "reserved": False},
            "http://localhost:4000": {"weight": 1.0, "inflight": inflight4000,
                                      "routed": 5, "routed_pct": 11.6, "fails": 0,
                                      "cooldown": cooldown4000, "reserved": False},
        },
    }


class LlmPoolTests(unittest.TestCase):
    """Multi-backend pool (v0.6.1+): per-backend busy on the LLM tile, pool-slot
    gating on the REM tile — global GPU load is no longer the defer signal."""

    def _llm_workload(self, health, *, inference_busy="idle"):
        pool = _llm_pool_summary(health)
        return _workload_part("llm", health, {}, inference_busy=inference_busy,
                              llm_pool=pool), pool

    def test_pool_summary_parsed(self):
        pool = _llm_pool_summary(_pool_gateway(inflight5000=1))
        self.assertEqual(pool["total"], 2)
        self.assertEqual(pool["up"], 2)
        self.assertEqual(pool["busy"], 1)
        self.assertEqual(pool["free"], 1)

    def test_single_backend_health_has_no_pool(self):
        self.assertIsNone(_llm_pool_summary(_healthy_gateway()))

    def test_second_backend_busy_shows_on_tile(self):
        w, _ = self._llm_workload(_pool_gateway(inflight4000=2))
        self.assertEqual(w["value"], "busy 1/2")
        self.assertEqual(w["state"], "ok")

    def test_pool_idle_gpu_idle(self):
        w, _ = self._llm_workload(_pool_gateway())
        self.assertEqual(w["value"], "idle")
        self.assertIn("pool of 2", w["caption"])

    def test_one_backend_down_warns_not_critical(self):
        w, _ = self._llm_workload(_pool_gateway(s4000="down"))
        self.assertEqual(w["value"], "1/2 up")
        self.assertEqual(w["state"], "warn")

    def test_pool_idle_but_gpu_busy_is_direct_load(self):
        # nvtop busy while no pool call is in flight = load outside the gateway
        # (e.g. a direct chat with a backend) — truthful busy, not an alarm.
        w, _ = self._llm_workload(_pool_gateway(), inference_busy="busy")
        self.assertEqual(w["value"], "busy")
        self.assertEqual(w["state"], "ok")
        self.assertIn("no pool call", w["caption"])

    def _rem(self, health, *, inference_busy="idle", rem_trend="insufficient"):
        pool = _llm_pool_summary(health)
        return _workload_part("rem_daemon", {**health, "rem_daemon": "running"},
                              {"rem_backlog": 6}, inference_busy=inference_busy,
                              rem_trend=rem_trend, llm_pool=pool)

    def test_rem_defers_only_when_pool_full(self):
        w = self._rem(_pool_gateway(inflight5000=1, inflight4000=1))
        self.assertEqual(w["state"], "ok")
        self.assertIn("deferring", w["value"])
        self.assertIn("pool busy", w["caption"])

    def test_rem_stall_detected_despite_gpu_busy(self):
        # The pre-pool trap: nvtop reads busy because REM itself (or a direct
        # chat) holds one card, but a pool slot is free — flat backlog is a
        # genuine stall and must warn, not hide behind "GPU busy".
        w = self._rem(_pool_gateway(inflight5000=1), inference_busy="busy",
                      rem_trend="flat")
        self.assertEqual(w["state"], "warn")
        self.assertIn("stalled", w["value"])

    def test_rem_draining_with_free_slot_is_ok(self):
        w = self._rem(_pool_gateway(inflight5000=1), inference_busy="busy",
                      rem_trend="draining")
        self.assertEqual(w["state"], "ok")
        self.assertIn("draining", w["value"])

    def test_snapshot_exposes_pool(self):
        payload = {
            "status": "success",
            "telemetry": {
                "consolidation": {
                    "insight": {"stalled": False, "consecutive_failures": 0},
                    "fact_consolidation": {"stalled": False, "consecutive_failures": 0},
                },
            },
        }
        with patch("sm_telemetry_monitor.system_health.get_telemetry",
                   return_value=payload), \
             patch("sm_telemetry_monitor.system_health.live_summary",
                   return_value={"latest": {}}), \
             patch("sm_telemetry_monitor.system_health.get_health",
                   return_value=_pool_gateway(inflight4000=1)):
            snap = system_health_snapshot()
        self.assertEqual(snap["llm_pool"]["busy"], 1)
        llm = next(c for c in snap["components"] if c["key"] == "llm")
        self.assertEqual(llm["workload"]["value"], "busy 1/2")


class RemDrainSignalTests(unittest.TestCase):
    def _s(self, *pairs):
        return [{"collected_at": t, "rem_backlog": b} for t, b in pairs]

    def test_insufficient_with_single_sample(self):
        s = self._s(("2026-06-26T12:00:00+00:00", 6))
        self.assertEqual(rem_drain_signal(s, window_s=300), "insufficient")

    def test_draining(self):
        s = self._s(("2026-06-26T12:00:00+00:00", 10), ("2026-06-26T12:10:00+00:00", 6))
        self.assertEqual(rem_drain_signal(s, window_s=300), "draining")

    def test_flat_when_held(self):
        s = self._s(("2026-06-26T12:00:00+00:00", 6), ("2026-06-26T12:10:00+00:00", 6))
        self.assertEqual(rem_drain_signal(s, window_s=300), "flat")

    def test_growing_counts_as_flat(self):
        s = self._s(("2026-06-26T12:00:00+00:00", 6), ("2026-06-26T12:10:00+00:00", 9))
        self.assertEqual(rem_drain_signal(s, window_s=300), "flat")

    def test_baseline_within_window_is_insufficient(self):
        # Both samples newer than window_s → no valid baseline → don't judge.
        s = self._s(("2026-06-26T12:00:00+00:00", 10), ("2026-06-26T12:01:00+00:00", 6))
        self.assertEqual(rem_drain_signal(s, window_s=300), "insufficient")


if __name__ == "__main__":
    unittest.main()