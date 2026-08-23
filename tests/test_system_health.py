import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sm_telemetry_monitor.analytics import rem_drain_signal
from sm_telemetry_monitor.system_health import (
    _gateway_config,
    _llm_pool_summary,
    _workload_part,
    system_health_snapshot,
)
import sm_telemetry_monitor.system_health as _system_health_mod

# Existing snapshot tests do not patch get_pool_status; default is absent.
_system_health_mod.get_pool_status = lambda: {}


def _healthy_gateway(*, backup_in_progress=False):
    return {
        "status": "ok",
        "embedder": "ok",
        "reranker": "ok",
        "llm": "ok",
        "daemon": "running",
        "rem_daemon": "running",
        "version": "0.9.0",
        "api_version": 4,
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
        self.assertEqual(snap["status"], "warn")

    def test_probe_down_and_gpu_idle_is_critical(self):
        snap = self._snap({**_healthy_gateway(), "llm": "down", "inference_busy": "idle"})
        self.assertEqual(self._llm(snap)["state"], "bad")
        self.assertEqual(snap["status"], "critical")

    def test_healthy_gateway_with_rem_backlog_is_status_ok(self):
        # Live false-positive class (fact 902): gateway ok + REM queue must not
        # paint /api/health status=warn — hero owns "upcoming" narrative.
        health = {
            **_pool_gateway(inflight5000=1),
            "inference_busy": "busy",
            "consolidation": {
                "stalled": False, "fresh": True, "stalled_types": [],
                "last_outcome": "completed",
            },
        }
        with patch("sm_telemetry_monitor.system_health._rem_trend", return_value="flat"), \
             patch("sm_telemetry_monitor.system_health.get_telemetry",
                   return_value=self._telemetry_payload()), \
             patch("sm_telemetry_monitor.system_health.live_summary",
                   return_value={"latest": {
                       "rem_backlog": 2,
                       "facts_rem_pending": 2,
                       "decisions_rem_pending": 0,
                       "nrem_backlog": 2,
                   }}), \
             patch("sm_telemetry_monitor.system_health.get_health", return_value=health):
            snap = system_health_snapshot()
        self.assertEqual(snap["status"], "ok")
        rem = next(c for c in snap["components"] if c["key"] == "rem_daemon")
        self.assertEqual(rem["state"], "ok")
        self.assertIn("queued", rem["workload"]["value"])


class RemTileTests(unittest.TestCase):
    """REM backlog is a process variable (decision 903) — never deck-elevating warn."""

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

    def test_free_gpu_flat_backlog_is_queued_not_warn(self):
        # Client rem_drain flat is not rem_stalled telemetry — ok process variable.
        w = self._rem(6, inference_busy="idle", rem_trend="flat")
        self.assertEqual(w["state"], "ok")
        self.assertIn("queued", w["value"])
        self.assertIn("no net drain", w["caption"])

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


class GatewayConfigTests(unittest.TestCase):
    """/health.config (v0.6.1+) — always-on non-secret effective setup echo."""

    def test_config_parsed_from_single_backend_health(self):
        health = {
            **_healthy_gateway(),
            "version": "0.7.0",
            "api_version": 3,
            "config": {
                "llm_backends": [{"url": "http://localhost:4000", "weight": 1.0}],
                "llm_pool_tuning": {
                    "fail_threshold": 2,
                    "fail_window_s": 60.0,
                    "cooldown_s": 300.0,
                    "max_tries": 3,
                },
                "llm_affinity": {
                    "prefix_chars": 6144,
                    "ttl_s": 600.0,
                    "max_inflight": 4,
                },
                "embed_max_chars": 24000,
            },
        }
        cfg = _gateway_config(health)
        self.assertTrue(cfg["present"])
        self.assertEqual(cfg["backend_count"], 1)
        self.assertEqual(cfg["backends"][0]["label"], "localhost:4000")
        self.assertIsNone(cfg["backends"][0]["has_credential"])
        self.assertIsNone(cfg["backends"][0]["placement"])
        self.assertEqual(cfg["embed_max_chars"], 24000)
        self.assertIn("1 LLM backend", cfg["summary"])
        self.assertIn("embed 24k", cfg["summary"])
        self.assertNotIn("local", cfg["summary"])
        self.assertEqual(cfg["pool_tuning"]["cooldown_s"], 300.0)
        self.assertEqual(cfg["affinity"]["prefix_chars"], 6144)

    def test_config_placement_local_and_external(self):
        """Framework ≥0.8.9: has_credential + model on config.llm_backends (no secrets)."""
        health = {
            **_healthy_gateway(),
            "version": "0.8.9",
            "api_version": 3,
            "config": {
                "llm_backends": [
                    {"url": "http://localhost:5000", "weight": 1.0,
                     "has_credential": False, "model": None},
                    {"url": "https://api.deepseek.com/v1", "weight": 1.0,
                     "has_credential": True, "model": "deepseek-chat"},
                ],
                "embed_max_chars": 24000,
            },
        }
        cfg = _gateway_config(health)
        self.assertEqual(cfg["local_count"], 1)
        self.assertEqual(cfg["external_count"], 1)
        by_url = {b["url"]: b for b in cfg["backends"]}
        self.assertEqual(by_url["http://localhost:5000"]["placement"], "local")
        self.assertFalse(by_url["http://localhost:5000"]["has_credential"])
        self.assertEqual(by_url["https://api.deepseek.com/v1"]["placement"], "external")
        self.assertTrue(by_url["https://api.deepseek.com/v1"]["has_credential"])
        self.assertEqual(by_url["https://api.deepseek.com/v1"]["model"], "deepseek-chat")
        self.assertIn("1 local · 1 external", cfg["summary"])
        self.assertIn("embed 24k", cfg["summary"])

    def test_config_all_local_summary(self):
        health = {
            **_healthy_gateway(),
            "config": {
                "llm_backends": [
                    {"url": "http://localhost:5000", "weight": 1.0, "has_credential": False},
                    {"url": "http://localhost:4000", "weight": 1.0, "has_credential": False},
                ],
            },
        }
        cfg = _gateway_config(health)
        self.assertEqual(cfg["local_count"], 2)
        self.assertEqual(cfg["external_count"], 0)
        self.assertIn("2 LLM backends", cfg["summary"])
        self.assertIn("local", cfg["summary"])
        self.assertNotIn("external", cfg["summary"])

    def test_config_absent_on_legacy_health(self):
        self.assertIsNone(_gateway_config(_healthy_gateway()))

    @patch("sm_telemetry_monitor.system_health.get_telemetry")
    @patch("sm_telemetry_monitor.system_health.live_summary", return_value={"latest": {}})
    def test_snapshot_exposes_config(self, _summary, mock_telemetry):
        mock_telemetry.return_value = {
            "status": "success",
            "telemetry": {
                "consolidation": {
                    "insight": {"stalled": False, "consecutive_failures": 0},
                    "fact_consolidation": {"stalled": False, "consecutive_failures": 0},
                },
            },
        }
        health = {
            **_healthy_gateway(),
            "version": "0.8.33",
            "api_version": 4,
            "config": {
                "llm_backends": [{"url": "http://localhost:4000", "weight": 1.0}],
                "embed_max_chars": 24000,
            },
        }
        with patch("sm_telemetry_monitor.system_health.get_health", return_value=health):
            snap = system_health_snapshot()
        self.assertEqual(snap["version"], "0.8.33")
        self.assertEqual(snap["api_version"], 4)
        self.assertTrue(snap["config"]["present"])
        self.assertEqual(snap["config"]["backend_count"], 1)

    def test_i16_descriptors_copied_including_explicit_null(self):
        """I16: roles/n_ctx/private_ok/max_inflight/prices copy when present.

        Mutation: checking only private_ok=True still passes if roles is dropped
        when null — pin roles is None with the key kept.
        """
        health = {
            **_pool_gateway(),
            "config": {
                "llm_backends": [
                    {
                        "url": "http://localhost:5000",
                        "weight": 1.0,
                        "has_credential": False,
                        "model": None,
                        "private_ok": True,
                        "roles": None,
                        "n_ctx": None,
                        "max_inflight": None,
                        "price_per_mtok_in": None,
                        "price_per_mtok_out": None,
                    },
                    {
                        "url": "http://localhost:4000",
                        "weight": 1.0,
                        "has_credential": False,
                        "private_ok": True,
                        "roles": None,
                        "n_ctx": 8192,
                        "max_inflight": 2,
                        "price_per_mtok_in": 0.14,
                        "price_per_mtok_out": 0.28,
                    },
                ],
            },
        }
        cfg = _gateway_config(health)
        by_url = {b["url"]: b for b in cfg["backends"]}
        b5000 = by_url["http://localhost:5000"]
        self.assertTrue(b5000["private_ok"])
        self.assertIn("roles", b5000)
        self.assertIsNone(b5000["roles"])
        self.assertIn("n_ctx", b5000)
        self.assertIsNone(b5000["n_ctx"])
        self.assertIn("max_inflight", b5000)
        self.assertIsNone(b5000["max_inflight"])
        self.assertIn("price_per_mtok_in", b5000)
        self.assertIsNone(b5000["price_per_mtok_in"])
        self.assertIn("price_per_mtok_out", b5000)
        self.assertIsNone(b5000["price_per_mtok_out"])
        b4000 = by_url["http://localhost:4000"]
        self.assertEqual(b4000["n_ctx"], 8192)
        self.assertEqual(b4000["max_inflight"], 2)
        self.assertEqual(b4000["price_per_mtok_in"], 0.14)
        self.assertEqual(b4000["price_per_mtok_out"], 0.28)

        pool = _llm_pool_summary(health)
        p_by_url = {b["url"]: b for b in pool["backends"]}
        self.assertTrue(p_by_url["http://localhost:5000"]["private_ok"])
        self.assertIn("roles", p_by_url["http://localhost:5000"])
        self.assertIsNone(p_by_url["http://localhost:5000"]["roles"])
        self.assertEqual(p_by_url["http://localhost:4000"]["n_ctx"], 8192)
        self.assertEqual(p_by_url["http://localhost:4000"]["price_per_mtok_in"], 0.14)

    def test_i16_pre_0913_fixture_has_no_invented_descriptors(self):
        """I16: older config backends must not gain invented descriptor keys."""
        health = {
            **_pool_gateway(),
            "config": {
                "llm_backends": [
                    {"url": "http://localhost:5000", "weight": 1.0,
                     "has_credential": False, "model": None},
                    {"url": "http://localhost:4000", "weight": 1.0,
                     "has_credential": True, "model": "cloud-model"},
                ],
            },
        }
        descriptor_keys = (
            "roles", "n_ctx", "private_ok", "max_inflight",
            "price_per_mtok_in", "price_per_mtok_out",
        )
        cfg = _gateway_config(health)
        for b in cfg["backends"]:
            for key in descriptor_keys:
                self.assertNotIn(key, b)
        pool = _llm_pool_summary(health)
        for b in pool["backends"]:
            for key in descriptor_keys:
                self.assertNotIn(key, b)

    def test_i17_allow_unauthenticated_only_when_sent(self):
        """I17: allow_unauthenticated_provider_keys appears only when gateway sent it."""
        base_cfg = {
            "llm_backends": [{"url": "http://localhost:4000", "weight": 1.0}],
        }
        cfg_absent = _gateway_config({**_healthy_gateway(), "config": dict(base_cfg)})
        self.assertNotIn("allow_unauthenticated_provider_keys", cfg_absent)

        cfg_true = _gateway_config({
            **_healthy_gateway(),
            "config": {**base_cfg, "allow_unauthenticated_provider_keys": True},
        })
        self.assertTrue(cfg_true["allow_unauthenticated_provider_keys"])

        cfg_false = _gateway_config({
            **_healthy_gateway(),
            "config": {**base_cfg, "allow_unauthenticated_provider_keys": False},
        })
        self.assertIn("allow_unauthenticated_provider_keys", cfg_false)
        self.assertFalse(cfg_false["allow_unauthenticated_provider_keys"])

        # Top-level health boolean of the same name also counts.
        cfg_top = _gateway_config({
            **_healthy_gateway(),
            "allow_unauthenticated_provider_keys": True,
            "config": dict(base_cfg),
        })
        self.assertTrue(cfg_top["allow_unauthenticated_provider_keys"])


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
        # Full /health.llm_pool pass-through for the pool panel (no invented stats).
        by_label = {b["label"]: b for b in pool["backends"]}
        self.assertEqual(by_label["localhost:5000"]["inflight"], 1)
        self.assertEqual(by_label["localhost:5000"]["routed"], 38)
        self.assertEqual(by_label["localhost:5000"]["routed_pct"], 88.4)
        self.assertEqual(by_label["localhost:5000"]["fails"], 2)
        self.assertEqual(by_label["localhost:5000"]["weight"], 1.0)
        self.assertFalse(by_label["localhost:5000"]["available"])
        self.assertTrue(by_label["localhost:4000"]["available"])
        # Pre-0.8.9 config: no placement invent from URL
        self.assertIsNone(by_label["localhost:5000"]["placement"])
        self.assertEqual(pool["local"], 0)
        self.assertEqual(pool["external"], 0)

    def test_pool_joins_config_placement(self):
        health = {
            **_pool_gateway(inflight5000=1),
            "config": {
                "llm_backends": [
                    {"url": "http://localhost:5000", "weight": 1.0,
                     "has_credential": False, "model": None},
                    {"url": "http://localhost:4000", "weight": 1.0,
                     "has_credential": True, "model": "cloud-model"},
                ],
            },
        }
        pool = _llm_pool_summary(health)
        by_label = {b["label"]: b for b in pool["backends"]}
        self.assertEqual(by_label["localhost:5000"]["placement"], "local")
        self.assertFalse(by_label["localhost:5000"]["has_credential"])
        self.assertEqual(by_label["localhost:4000"]["placement"], "external")
        self.assertTrue(by_label["localhost:4000"]["has_credential"])
        self.assertEqual(by_label["localhost:4000"]["model"], "cloud-model")
        self.assertEqual(pool["local"], 1)
        self.assertEqual(pool["external"], 1)

    def test_single_backend_health_has_no_pool_without_config(self):
        self.assertIsNone(_llm_pool_summary(_healthy_gateway()))

    def test_synthetic_pool_from_config_idle(self):
        health = {
            **_healthy_gateway(),
            "inference_busy": "idle",
            "config": {
                "llm_backends": [
                    {"url": "http://localhost:5000", "weight": 1.0,
                     "has_credential": False, "model": "local-model"},
                ],
            },
        }
        pool = _llm_pool_summary(health)
        self.assertIsNotNone(pool)
        self.assertEqual(pool["total"], 1)
        self.assertEqual(pool["up"], 1)
        self.assertEqual(pool["busy"], 0)
        self.assertEqual(pool["free"], 1)
        self.assertEqual(pool["local"], 1)
        self.assertEqual(pool["external"], 0)
        b = pool["backends"][0]
        self.assertEqual(b["url"], "http://localhost:5000")
        self.assertEqual(b["label"], "localhost:5000")
        self.assertEqual(b["status"], "ok")
        self.assertEqual(b["inflight"], 0)
        self.assertTrue(b["available"])
        self.assertEqual(b["placement"], "local")
        self.assertEqual(b["model"], "local-model")

    def test_synthetic_pool_from_config_busy(self):
        health = {
            **_healthy_gateway(),
            "inference_busy": "busy",
            "config": {
                "llm_backends": [
                    {"url": "https://api.openai.com/v1", "weight": 1.0,
                     "has_credential": True, "model": "gpt-4o",
                     "n_ctx": 128000, "private_ok": False},
                ],
            },
        }
        pool = _llm_pool_summary(health)
        self.assertIsNotNone(pool)
        self.assertEqual(pool["total"], 1)
        self.assertEqual(pool["up"], 1)
        self.assertEqual(pool["busy"], 1)
        self.assertEqual(pool["free"], 0)
        self.assertEqual(pool["local"], 0)
        self.assertEqual(pool["external"], 1)
        b = pool["backends"][0]
        self.assertEqual(b["url"], "https://api.openai.com/v1")
        self.assertEqual(b["status"], "ok")
        self.assertEqual(b["inflight"], 1)
        self.assertFalse(b["available"])
        self.assertEqual(b["placement"], "external")
        self.assertEqual(b["model"], "gpt-4o")
        self.assertEqual(b["n_ctx"], 128000)
        self.assertFalse(b["private_ok"])

    def test_synthetic_pool_backend_down_status(self):
        health = {
            **_healthy_gateway(),
            "llm": "down",
            "config": {
                "llm_backends": [
                    {"url": "http://localhost:5000", "weight": 1.0},
                ],
            },
        }
        pool = _llm_pool_summary(health)
        self.assertIsNotNone(pool)
        self.assertEqual(pool["total"], 1)
        self.assertEqual(pool["up"], 0)
        self.assertEqual(pool["busy"], 0)
        self.assertEqual(pool["free"], 0)
        b = pool["backends"][0]
        self.assertEqual(b["status"], "down")
        self.assertFalse(b["available"])

    def test_second_backend_busy_shows_on_tile(self):
        w, _ = self._llm_workload(_pool_gateway(inflight4000=2))
        self.assertEqual(w["value"], "busy 1/2")
        self.assertEqual(w["state"], "ok")
        self.assertIn("localhost:4000", w["caption"])

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

    def test_rem_flat_with_free_slot_is_queued_not_warn(self):
        # Pool free + flat backlog: upcoming work / slow drain, not deck warn
        # (decision 903 — no gateway rem_stalled yet).
        w = self._rem(_pool_gateway(inflight5000=1), inference_busy="busy",
                      rem_trend="flat")
        self.assertEqual(w["state"], "ok")
        self.assertIn("queued", w["value"])
        self.assertIn("no net drain", w["caption"])

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

    def test_snapshot_exposes_age_affinity_wedge(self):
        payload = {
            "status": "success",
            "telemetry": {
                "consolidation": {
                    "insight": {"stalled": False, "consecutive_failures": 0},
                    "fact_consolidation": {"stalled": False, "consecutive_failures": 0},
                },
            },
        }
        health = {
            **_pool_gateway(inflight4000=1),
            "llm_oldest_inflight_age_s": 125.4,
            "llm_suspect_wedged": ["http://localhost:4000"],
            "llm_affinity": {
                "hits": 3,
                "misses": 1,
                "hit_rate": 0.75,
                "hot_prefixes": {
                    "abc123ef": {"backend": "http://localhost:4000", "hits": 3},
                },
            },
        }
        with patch("sm_telemetry_monitor.system_health.get_telemetry",
                   return_value=payload), \
             patch("sm_telemetry_monitor.system_health.live_summary",
                   return_value={"latest": {}}), \
             patch("sm_telemetry_monitor.system_health.get_health", return_value=health):
            snap = system_health_snapshot()
        self.assertEqual(snap["llm_oldest_inflight_age_s"], 125.4)
        self.assertEqual(snap["llm_suspect_wedged"], ["localhost:4000"])
        aff = snap["llm_affinity_live"]
        self.assertEqual(aff["hits"], 3)
        self.assertEqual(aff["hit_rate"], 0.75)
        self.assertEqual(aff["hot_prefixes"][0]["backend"], "localhost:4000")
        llm = next(c for c in snap["components"] if c["key"] == "llm")
        self.assertEqual(llm["state"], "warn")  # wedge suspect elevates
        self.assertIn("oldest in-flight 2m", llm["workload"]["caption"])
        self.assertIn("wedge suspect", llm["workload"]["caption"])

    def test_single_backend_still_exposes_oldest_age(self):
        payload = {
            "status": "success",
            "telemetry": {
                "consolidation": {
                    "insight": {"stalled": False, "consecutive_failures": 0},
                    "fact_consolidation": {"stalled": False, "consecutive_failures": 0},
                },
            },
        }
        health = {**_healthy_gateway(), "inference_busy": "busy",
                  "llm_oldest_inflight_age_s": 45.0}
        with patch("sm_telemetry_monitor.system_health.get_telemetry",
                   return_value=payload), \
             patch("sm_telemetry_monitor.system_health.live_summary",
                   return_value={"latest": {}}), \
             patch("sm_telemetry_monitor.system_health.get_health", return_value=health):
            snap = system_health_snapshot()
        self.assertEqual(snap["llm_oldest_inflight_age_s"], 45.0)
        self.assertIsNone(snap["llm_pool"])
        self.assertIsNone(snap["llm_affinity_live"])
        llm = next(c for c in snap["components"] if c["key"] == "llm")
        self.assertIn("oldest in-flight 45s", llm["workload"]["caption"])


class LlmFaultsCredentialsJoinTests(unittest.TestCase):
    """I1–I5: join telemetry.llm_faults / credentials onto pool backends."""

    def _base_telemetry(self, **extra):
        t = {
            "consolidation": {
                "insight": {"stalled": False, "consecutive_failures": 0},
                "fact_consolidation": {"stalled": False, "consecutive_failures": 0},
            },
        }
        t.update(extra)
        return {"status": "success", "telemetry": t}

    def _snap(self, health, telemetry_payload):
        with patch("sm_telemetry_monitor.system_health.get_telemetry",
                   return_value=telemetry_payload), \
             patch("sm_telemetry_monitor.system_health.live_summary",
                   return_value={"latest": {}}), \
             patch("sm_telemetry_monitor.system_health.get_health", return_value=health):
            return system_health_snapshot()

    def test_i1_no_llm_faults_key_omits_faults_on_backends(self):
        snap = self._snap(_pool_gateway(), self._base_telemetry())
        for b in snap["llm_pool"]["backends"]:
            self.assertNotIn("faults", b)

    def test_i1_empty_llm_faults_attaches_null_faults(self):
        snap = self._snap(_pool_gateway(), self._base_telemetry(llm_faults={}))
        for b in snap["llm_pool"]["backends"]:
            self.assertIn("faults", b)
            self.assertEqual(
                b["faults"],
                {"gateway": None, "credential": None, "transient": None},
            )

    def test_i1_populated_faults_join_by_url(self):
        gw_last = {"ts": "2026-08-15T10:00:00+00:00", "class": "TimeoutError"}
        cred_last = {
            "ts": "2026-08-15T10:01:00+00:00",
            "status": 401,
            "error_type": "auth",
        }
        trans_last = {
            "ts": "2026-08-15T10:02:00+00:00",
            "status": 529,
            "error_type": "overloaded",
        }
        faults = {
            "http://localhost:5000": {
                "gateway": {"count": 1, "last": gw_last},
                "llm": {
                    "credential": {"count": 1, "last": cred_last},
                    "transient": {"count": 2, "last": trans_last},
                },
            },
        }
        snap = self._snap(_pool_gateway(), self._base_telemetry(llm_faults=faults))
        by_url = {b["url"]: b for b in snap["llm_pool"]["backends"]}
        f5000 = by_url["http://localhost:5000"]["faults"]
        self.assertEqual(f5000["gateway"]["count"], 1)
        self.assertEqual(f5000["gateway"]["last"], gw_last)
        self.assertEqual(f5000["credential"]["count"], 1)
        self.assertEqual(f5000["credential"]["last"], cred_last)
        self.assertEqual(f5000["transient"]["count"], 2)
        self.assertEqual(f5000["transient"]["last"], trans_last)
        # Other pool backend has the key but empty fault slots
        f4000 = by_url["http://localhost:4000"]["faults"]
        self.assertIsNone(f4000["gateway"])
        self.assertIsNone(f4000["credential"])
        self.assertIsNone(f4000["transient"])
        # Existing pool fields unchanged
        self.assertEqual(by_url["http://localhost:5000"]["status"], "ok")
        self.assertEqual(by_url["http://localhost:5000"]["fails"], 2)

    def test_i2_faults_do_not_change_overall_status(self):
        faults = {
            "http://localhost:5000": {
                "gateway": {"count": 3, "last": {"ts": "t", "class": "TimeoutError"}},
                "llm": {
                    "credential": {"count": 5, "last": {"ts": "t", "status": 401}},
                    "transient": {"count": 1, "last": {"ts": "t", "status": 529}},
                },
            },
        }
        snap = self._snap(
            _pool_gateway(),
            self._base_telemetry(
                llm_faults=faults,
                credentials={
                    "token_verify_failed": 3,
                    "token_verify_failed_last_ts": "2026-08-16T20:59:00Z",
                    "daemon_tokens_issued": 0,
                    "daemon_tokens_issued_last_ts": None,
                    "audit_log_dropped": 2,
                    "audit_log_dropped_last_ts": "2026-08-16T21:00:00Z",
                },
            ),
        )
        self.assertEqual(snap["status"], "ok")

    def test_i3_credentials_top_level_not_on_backend(self):
        snap = self._snap(
            _pool_gateway(),
            self._base_telemetry(
                llm_faults={},
                credentials={
                    "token_verify_failed": 4,
                    "daemon_tokens_issued": 1,
                    "audit_log_dropped": 2,
                },
            ),
        )
        self.assertEqual(snap["credentials"]["audit_log_dropped"], 2)
        self.assertEqual(snap["credentials"]["token_verify_failed"], 4)
        for b in snap["llm_pool"]["backends"]:
            self.assertNotIn("token_verify_failed", b)
            self.assertNotIn("audit_log_dropped", b)
            dumped = json.dumps(b.get("faults") or {})
            self.assertNotIn("token_verify_failed", dumped)
            self.assertNotIn("audit_log_dropped", dumped)

    def test_i3_credentials_absent_not_invented(self):
        snap = self._snap(_pool_gateway(), self._base_telemetry(llm_faults={}))
        # omit or null — never invent zero counters
        creds = snap.get("credentials")
        self.assertTrue(creds is None or creds == {})

    def test_i10_last_ts_siblings_passthrough_unchanged(self):
        """I10: snapshot credentials keeps 0.9.8 last_ts siblings as-is.

        Mutation: checking only token_verify_failed still passes if last_ts
        is dropped — pin each last_ts value (including explicit null).
        Passthrough already holds — _join_llm_faults does not strip the dict.
        """
        verify_ts = "2026-08-16T20:59:00Z"
        issued_ts = "2026-08-16T21:12:04Z"
        snap = self._snap(
            _pool_gateway(),
            self._base_telemetry(
                llm_faults={},
                credentials={
                    "token_verify_failed": 2,
                    "token_verify_failed_last_ts": verify_ts,
                    "daemon_tokens_issued": 2,
                    "daemon_tokens_issued_last_ts": issued_ts,
                    "audit_log_dropped": 0,
                    "audit_log_dropped_last_ts": None,
                },
            ),
        )
        creds = snap["credentials"]
        self.assertEqual(creds["token_verify_failed_last_ts"], verify_ts)
        self.assertEqual(creds["daemon_tokens_issued_last_ts"], issued_ts)
        self.assertIn("audit_log_dropped_last_ts", creds)
        self.assertIsNone(creds["audit_log_dropped_last_ts"])
        self.assertEqual(creds["token_verify_failed"], 2)
        self.assertEqual(creds["daemon_tokens_issued"], 2)
        self.assertEqual(creds["audit_log_dropped"], 0)

    def test_i10_absent_last_ts_not_invented(self):
        """I10: older credentials blobs stay without invented last_ts keys."""
        snap = self._snap(
            _pool_gateway(),
            self._base_telemetry(
                llm_faults={},
                credentials={
                    "token_verify_failed": 0,
                    "daemon_tokens_issued": 2,
                    "audit_log_dropped": 0,
                },
            ),
        )
        creds = snap["credentials"]
        self.assertNotIn("token_verify_failed_last_ts", creds)
        self.assertNotIn("daemon_tokens_issued_last_ts", creds)
        self.assertNotIn("audit_log_dropped_last_ts", creds)

    def test_i11_own_door_keys_never_on_backends(self):
        """I11: own-door credential keys (incl. route denied) stay off backends[]."""
        own_door_keys = (
            "token_verify_failed",
            "token_verify_failed_last_ts",
            "daemon_tokens_issued",
            "daemon_tokens_issued_last_ts",
            "audit_log_dropped",
            "audit_log_dropped_last_ts",
            "credentialed_route_denied",
            "credentialed_route_denied_last_ts",
        )
        snap = self._snap(
            _pool_gateway(),
            self._base_telemetry(
                llm_faults={},
                credentials={
                    "token_verify_failed": 4,
                    "token_verify_failed_last_ts": "2026-08-16T20:59:00Z",
                    "daemon_tokens_issued": 1,
                    "daemon_tokens_issued_last_ts": "2026-08-16T21:12:04Z",
                    "audit_log_dropped": 2,
                    "audit_log_dropped_last_ts": None,
                    "credentialed_route_denied": 2,
                    "credentialed_route_denied_last_ts": "2026-08-18T16:00:00+00:00",
                },
            ),
        )
        for b in snap["llm_pool"]["backends"]:
            for key in own_door_keys:
                self.assertNotIn(key, b)
            dumped = json.dumps(b)
            for key in own_door_keys:
                self.assertNotIn(key, dumped)

    def test_i14_credentialed_route_denied_passthrough(self):
        """I14: credentialed_route_denied + last_ts survive (including null)."""
        denied_ts = "2026-08-18T15:50:00+00:00"
        snap = self._snap(
            _pool_gateway(),
            self._base_telemetry(
                llm_faults={},
                credentials={
                    "token_verify_failed": 0,
                    "token_verify_failed_last_ts": None,
                    "daemon_tokens_issued": 0,
                    "daemon_tokens_issued_last_ts": None,
                    "audit_log_dropped": 0,
                    "audit_log_dropped_last_ts": None,
                    "credentialed_route_denied": 2,
                    "credentialed_route_denied_last_ts": denied_ts,
                },
            ),
        )
        creds = snap["credentials"]
        self.assertEqual(creds["credentialed_route_denied"], 2)
        self.assertEqual(creds["credentialed_route_denied_last_ts"], denied_ts)

        snap_null = self._snap(
            _pool_gateway(),
            self._base_telemetry(
                llm_faults={},
                credentials={
                    "credentialed_route_denied": 0,
                    "credentialed_route_denied_last_ts": None,
                },
            ),
        )
        self.assertEqual(snap_null["credentials"]["credentialed_route_denied"], 0)
        self.assertIn("credentialed_route_denied_last_ts", snap_null["credentials"])
        self.assertIsNone(snap_null["credentials"]["credentialed_route_denied_last_ts"])

        snap_absent = self._snap(
            _pool_gateway(),
            self._base_telemetry(
                llm_faults={},
                credentials={"token_verify_failed": 0, "audit_log_dropped": 0},
            ),
        )
        self.assertNotIn("credentialed_route_denied", snap_absent["credentials"])
        self.assertNotIn("credentialed_route_denied_last_ts", snap_absent["credentials"])

    def test_i12_llm_routing_passthrough_pins_values(self):
        """I12: llm_routing is the raw /health dict — pin every counter + last_ts."""
        llm_routing = {
            "routed_role_extract": 4,
            "routed_role_extract_last_ts": "2026-08-18T16:12:40.809531+00:00",
            "routed_role_verify": 0,
            "routed_role_verify_last_ts": None,
            "routed_role_judge": 0,
            "routed_role_judge_last_ts": None,
            "routing_no_eligible_backend": 0,
            "routing_no_eligible_backend_last_ts": None,
            "routing_fit_rejected": 0,
            "routing_fit_rejected_last_ts": None,
            "routing_backend_at_capacity": 0,
            "routing_backend_at_capacity_last_ts": None,
        }
        health = {**_pool_gateway(), "llm_routing": llm_routing}
        snap = self._snap(health, self._base_telemetry(llm_faults={}))
        self.assertEqual(snap["llm_routing"], llm_routing)
        # Pin values individually so a rewrite of zeros would fail.
        r = snap["llm_routing"]
        self.assertEqual(r["routed_role_extract"], 4)
        self.assertEqual(
            r["routed_role_extract_last_ts"],
            "2026-08-18T16:12:40.809531+00:00",
        )
        self.assertEqual(r["routed_role_verify"], 0)
        self.assertIsNone(r["routed_role_verify_last_ts"])
        self.assertEqual(r["routed_role_judge"], 0)
        self.assertIsNone(r["routed_role_judge_last_ts"])
        self.assertEqual(r["routing_no_eligible_backend"], 0)
        self.assertIsNone(r["routing_no_eligible_backend_last_ts"])
        self.assertEqual(r["routing_fit_rejected"], 0)
        self.assertIsNone(r["routing_fit_rejected_last_ts"])
        self.assertEqual(r["routing_backend_at_capacity"], 0)
        self.assertIsNone(r["routing_backend_at_capacity_last_ts"])

    def test_i12_llm_routing_absent_not_invented(self):
        """I12: absent llm_routing → snapshot key absent or null, never zeros."""
        snap = self._snap(_pool_gateway(), self._base_telemetry(llm_faults={}))
        routing = snap.get("llm_routing")
        self.assertTrue(routing is None or "llm_routing" not in snap)
        if isinstance(routing, dict):
            self.fail("invented llm_routing dict must not appear when gateway omitted it")

    def test_i13_llm_token_usage_passthrough_and_join(self):
        """I13: per-URL token totals preserved; join onto matching pool backend only."""
        llm_token_usage = {
            "http://localhost:5000": {
                "tokens_prompt_total": 5711,
                "tokens_completion_total": 2003,
                "tokens_last_ts": "2026-08-18T16:12:39.677154+00:00",
            },
            "http://localhost:4000": {
                "tokens_prompt_total": 0,
                "tokens_completion_total": 0,
                "tokens_last_ts": None,
            },
        }
        health = {**_pool_gateway(), "llm_token_usage": llm_token_usage}
        snap = self._snap(health, self._base_telemetry(llm_faults={}))
        self.assertEqual(snap["llm_token_usage"], llm_token_usage)
        usage = snap["llm_token_usage"]
        self.assertEqual(usage["http://localhost:5000"]["tokens_prompt_total"], 5711)
        self.assertEqual(usage["http://localhost:5000"]["tokens_completion_total"], 2003)
        self.assertEqual(
            usage["http://localhost:5000"]["tokens_last_ts"],
            "2026-08-18T16:12:39.677154+00:00",
        )
        self.assertEqual(usage["http://localhost:4000"]["tokens_prompt_total"], 0)
        self.assertIsNone(usage["http://localhost:4000"]["tokens_last_ts"])

        by_url = {b["url"]: b for b in snap["llm_pool"]["backends"]}
        self.assertEqual(
            by_url["http://localhost:5000"]["tokens"],
            {
                "prompt_total": 5711,
                "completion_total": 2003,
                "last_ts": "2026-08-18T16:12:39.677154+00:00",
            },
        )
        self.assertEqual(
            by_url["http://localhost:4000"]["tokens"],
            {"prompt_total": 0, "completion_total": 0, "last_ts": None},
        )

    def test_i13_backend_without_usage_entry_has_no_tokens(self):
        """I13: do not invent tokens or backends for URLs missing from usage."""
        llm_token_usage = {
            "http://localhost:5000": {
                "tokens_prompt_total": 100,
                "tokens_completion_total": 20,
                "tokens_last_ts": "2026-08-18T16:00:00+00:00",
            },
        }
        health = {**_pool_gateway(), "llm_token_usage": llm_token_usage}
        snap = self._snap(health, self._base_telemetry(llm_faults={}))
        by_url = {b["url"]: b for b in snap["llm_pool"]["backends"]}
        self.assertIn("tokens", by_url["http://localhost:5000"])
        self.assertNotIn("tokens", by_url["http://localhost:4000"])
        # Never invent a usage backend that was not in the pool.
        self.assertNotIn("https://missing.example/v1", by_url)
        self.assertEqual(len(snap["llm_token_usage"]), 1)

    def test_i13_llm_token_usage_absent_not_invented(self):
        snap = self._snap(_pool_gateway(), self._base_telemetry(llm_faults={}))
        usage = snap.get("llm_token_usage")
        self.assertTrue(usage is None or "llm_token_usage" not in snap)
        for b in snap["llm_pool"]["backends"]:
            self.assertNotIn("tokens", b)

    def test_i18_dream_free_slots_passthrough(self):
        """I18: dream_free_slots pins the gateway int; bool rejected; {} omits."""
        status = {
            "free_slots": 3,
            "backends": {
                "http://localhost:5000": {
                    "available": True, "serves_all": True, "counts_free_slot": True,
                },
                "http://localhost:4000": {
                    "available": True, "serves_all": True, "counts_free_slot": True,
                },
            },
        }
        with patch("sm_telemetry_monitor.system_health.get_pool_status",
                   return_value=status):
            snap = self._snap(_pool_gateway(), self._base_telemetry(llm_faults={}))
        self.assertEqual(snap["dream_free_slots"], 3)

        with patch("sm_telemetry_monitor.system_health.get_pool_status",
                   return_value={"free_slots": True}):
            snap_bool = self._snap(_pool_gateway(), self._base_telemetry(llm_faults={}))
        self.assertNotIn("dream_free_slots", snap_bool)

        with patch("sm_telemetry_monitor.system_health.get_pool_status",
                   return_value={}):
            snap_empty = self._snap(_pool_gateway(), self._base_telemetry(llm_faults={}))
        self.assertNotIn("dream_free_slots", snap_empty)

    def test_i19_serves_all_joined_not_invented(self):
        """I19: serves_all / counts_free_slot only on matching backends."""
        status = {
            "free_slots": 1,
            "backends": {
                "http://localhost:5000": {
                    "serves_all": True, "counts_free_slot": True,
                },
            },
        }
        with patch("sm_telemetry_monitor.system_health.get_pool_status",
                   return_value=status):
            snap = self._snap(_pool_gateway(), self._base_telemetry(llm_faults={}))
        by_url = {b["url"]: b for b in snap["llm_pool"]["backends"]}
        self.assertIs(by_url["http://localhost:5000"]["serves_all"], True)
        self.assertIs(by_url["http://localhost:5000"]["counts_free_slot"], True)
        self.assertNotIn("serves_all", by_url["http://localhost:4000"])
        self.assertNotIn("counts_free_slot", by_url["http://localhost:4000"])

    def test_i20_idle_free_unchanged_when_dream_slots_present(self):
        """I20: llm_pool.free stays inflight-idle, not free_slots."""
        health = _pool_gateway(inflight5000=1)
        status = {"free_slots": 3, "backends": {}}
        with patch("sm_telemetry_monitor.system_health.get_pool_status",
                   return_value=status):
            snap = self._snap(health, self._base_telemetry(llm_faults={}))
        self.assertEqual(snap["dream_free_slots"], 3)
        self.assertEqual(snap["llm_pool"]["busy"], 1)
        self.assertEqual(snap["llm_pool"]["free"], 1)

    def test_i2_dream_free_slots_do_not_change_status(self):
        status = {"free_slots": 0, "backends": {
            "http://localhost:5000": {"serves_all": False, "counts_free_slot": False},
        }}
        with patch("sm_telemetry_monitor.system_health.get_pool_status",
                   return_value=status):
            snap = self._snap(_pool_gateway(), self._base_telemetry(llm_faults={}))
        self.assertEqual(snap["status"], "ok")
        self.assertEqual(snap["dream_free_slots"], 0)

    def test_i2_routing_tokens_route_denied_do_not_change_status(self):
        """I2: routing refuses, tokens, credentialed_route_denied leave status ok."""
        llm_routing = {
            "routed_role_extract": 4,
            "routed_role_extract_last_ts": "2026-08-18T16:12:40.809531+00:00",
            "routed_role_verify": 0,
            "routed_role_verify_last_ts": None,
            "routed_role_judge": 0,
            "routed_role_judge_last_ts": None,
            "routing_no_eligible_backend": 3,
            "routing_no_eligible_backend_last_ts": "2026-08-18T16:10:00+00:00",
            "routing_fit_rejected": 1,
            "routing_fit_rejected_last_ts": "2026-08-18T16:09:00+00:00",
            "routing_backend_at_capacity": 2,
            "routing_backend_at_capacity_last_ts": "2026-08-18T16:08:00+00:00",
        }
        llm_token_usage = {
            "http://localhost:5000": {
                "tokens_prompt_total": 5711,
                "tokens_completion_total": 2003,
                "tokens_last_ts": "2026-08-18T16:12:39.677154+00:00",
            },
        }
        health = {
            **_pool_gateway(),
            "llm_routing": llm_routing,
            "llm_token_usage": llm_token_usage,
        }
        snap = self._snap(
            health,
            self._base_telemetry(
                llm_faults={},
                credentials={
                    "token_verify_failed": 0,
                    "audit_log_dropped": 0,
                    "credentialed_route_denied": 5,
                    "credentialed_route_denied_last_ts": "2026-08-18T16:00:00+00:00",
                },
            ),
        )
        self.assertEqual(snap["status"], "ok")
        self.assertEqual(snap["llm_routing"]["routing_no_eligible_backend"], 3)
        self.assertEqual(snap["credentials"]["credentialed_route_denied"], 5)

    def test_i4_fault_url_absent_from_pool_synthesises_backend(self):
        remote = "https://api.example/v1"
        faults = {
            remote: {
                "gateway": None,
                "llm": {
                    "credential": {
                        "count": 1,
                        "last": {"ts": "t", "status": 401, "error_type": "auth"},
                    },
                },
            },
        }
        health = {
            **_pool_gateway(),
            "config": {
                "llm_backends": [
                    {"url": "http://localhost:5000", "weight": 1.0,
                     "has_credential": False},
                    {"url": "http://localhost:4000", "weight": 1.0,
                     "has_credential": False},
                    {"url": remote, "weight": 1.0,
                     "has_credential": True, "model": "cloud"},
                ],
            },
        }
        snap = self._snap(health, self._base_telemetry(llm_faults=faults))
        by_url = {b["url"]: b for b in snap["llm_pool"]["backends"]}
        self.assertIn(remote, by_url)
        synth = by_url[remote]
        self.assertEqual(synth["label"], "api.example/v1")
        self.assertEqual(synth["status"], "unknown")
        self.assertEqual(synth["inflight"], 0)
        self.assertEqual(synth["placement"], "external")
        self.assertEqual(synth["faults"]["credential"]["count"], 1)
        self.assertEqual(snap["llm_pool"]["total"], 3)

    def test_i5_backends_sort_local_external_unknown(self):
        health = {
            **_healthy_gateway(),
            "llm_backends": {
                "https://api.example/v1": "ok",
                "http://localhost:5000": "ok",
                "http://orphan:9": "ok",
            },
            "llm_pool": {
                "https://api.example/v1": {
                    "weight": 1.0, "inflight": 0, "routed": 0, "routed_pct": 0,
                    "fails": 0, "cooldown": 0.0, "reserved": False,
                },
                "http://localhost:5000": {
                    "weight": 1.0, "inflight": 0, "routed": 0, "routed_pct": 0,
                    "fails": 0, "cooldown": 0.0, "reserved": False,
                },
                "http://orphan:9": {
                    "weight": 1.0, "inflight": 0, "routed": 0, "routed_pct": 0,
                    "fails": 0, "cooldown": 0.0, "reserved": False,
                },
            },
            "config": {
                "llm_backends": [
                    # external first in config — sort must still put local first
                    {"url": "https://api.example/v1", "weight": 1.0,
                     "has_credential": True},
                    {"url": "http://localhost:5000", "weight": 1.0,
                     "has_credential": False},
                    # orphan: no has_credential → unknown placement
                    {"url": "http://orphan:9", "weight": 1.0},
                ],
            },
        }
        snap = self._snap(health, self._base_telemetry(llm_faults={}))
        placements = [b.get("placement") for b in snap["llm_pool"]["backends"]]
        self.assertEqual(placements, ["local", "external", None])



    def test_llm_latency_passthrough_and_join(self):
        """llm_latency passed through to config & snapshot, and joined onto pool backends."""
        llm_latency = {
            "http://localhost:5000": {
                "latency_sum_s": 24.5,
                "latency_max_s": 3.2,
                "requests_total": 10,
                "requests_failed_total": 1,
            },
            "http://localhost:4000": {
                "latency_sum_s": 0.0,
                "latency_max_s": 0.0,
                "requests_total": 0,
                "requests_failed_total": 0,
            },
        }
        health = {
            **_pool_gateway(),
            "llm_latency": llm_latency,
            "config": {
                "llm_backends": [
                    {"url": "http://localhost:5000", "weight": 1.0, "has_credential": False},
                    {"url": "http://localhost:4000", "weight": 1.0, "has_credential": True},
                ],
            },
        }
        snap = self._snap(health, self._base_telemetry(llm_faults={}))
        self.assertEqual(snap["llm_latency"], llm_latency)
        self.assertEqual(snap["config"]["llm_latency"], llm_latency)
        by_url = {b["url"]: b for b in snap["llm_pool"]["backends"]}
        self.assertEqual(
            by_url["http://localhost:5000"]["latency"],
            {
                "latency_sum_s": 24.5,
                "latency_max_s": 3.2,
                "requests_total": 10,
                "requests_failed_total": 1,
                "latency_last_ts": None,
            },
        )

    def test_single_backend_cloud_only_renders_pool_and_latency(self):
        """Single-backend cloud-only (external) fleet correctly attaches latency & placement."""
        health = {
            **_healthy_gateway(),
            "config": {
                "llm_backends": [
                    {
                        "url": "https://api.deepseek.com/v1",
                        "weight": 1.0,
                        "has_credential": True,
                        "model": "deepseek-chat",
                    },
                ],
                "llm_latency": {
                    "https://api.deepseek.com/v1": {
                        "latency_sum_s": 12.0,
                        "latency_max_s": 2.4,
                        "requests_total": 5,
                        "requests_failed_total": 0,
                        "latency_last_ts": None,
                    },
                },
            },
        }
        snap = self._snap(health, self._base_telemetry(llm_faults={}))
        self.assertEqual(snap["config"]["external_count"], 1)
        self.assertEqual(snap["config"]["local_count"], 0)
        self.assertEqual(snap["llm_pool"]["total"], 1)
        b = snap["llm_pool"]["backends"][0]
        self.assertEqual(b["placement"], "external")
        self.assertEqual(b["latency"]["requests_total"], 5)
        self.assertEqual(b["latency"]["latency_sum_s"], 12.0)

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


class GraphIntegrityHealthTests(unittest.TestCase):
    def _telemetry_payload(self, integrity=None):
        t = {
            "consolidation": {
                "insight": {"stalled": False, "consecutive_failures": 0},
                "fact_consolidation": {"stalled": False, "consecutive_failures": 0},
            },
        }
        if integrity is not None:
            t["graph_integrity"] = integrity
        return {"status": "success", "telemetry": t}

    @patch("sm_telemetry_monitor.system_health.get_telemetry")
    @patch("sm_telemetry_monitor.system_health.live_summary", return_value={"latest": {}})
    @patch("sm_telemetry_monitor.system_health.get_health")
    def test_top_level_graph_invalid_nodes_triggers_warn(self, mock_health, _summary, mock_telemetry):
        mock_health.return_value = {**_healthy_gateway(), "graph_invalid_nodes": 3}
        mock_telemetry.return_value = self._telemetry_payload({
            "invalid_nodes": 3, "by_reason": {"label_mismatch:Fact!=Decision": 3}, "clean": False
        })
        snap = system_health_snapshot()
        self.assertEqual(snap["status"], "warn")
        self.assertEqual(snap["graph_invalid_nodes"], 3)
        self.assertIsNotNone(snap["graph_integrity"])
        self.assertFalse(snap["graph_integrity"]["clean"])

    @patch("sm_telemetry_monitor.system_health.get_telemetry")
    @patch("sm_telemetry_monitor.system_health.live_summary", return_value={"latest": {}})
    @patch("sm_telemetry_monitor.system_health.get_health")
    def test_clean_graph_integrity_stays_ok(self, mock_health, _summary, mock_telemetry):
        mock_health.return_value = {**_healthy_gateway(), "graph_invalid_nodes": 0}
        mock_telemetry.return_value = self._telemetry_payload({
            "invalid_nodes": 0, "by_reason": {}, "by_label": {}, "clean": True
        })
        snap = system_health_snapshot()
        self.assertEqual(snap["status"], "ok")
        self.assertEqual(snap["graph_invalid_nodes"], 0)
        self.assertTrue(snap["graph_integrity"]["clean"])


if __name__ == "__main__":
    unittest.main()