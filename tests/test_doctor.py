import unittest
from unittest.mock import patch

from sm_telemetry_monitor.bridge import API_VERSION
from sm_telemetry_monitor.doctor import _feature_readiness, format_report, run_doctor


class DoctorTests(unittest.TestCase):
    def test_report_has_no_credential_patterns(self):
        report = run_doctor()
        text = format_report(report)
        self.assertNotIn("tok_", text)
        self.assertNotIn("postgresql://", text)
        self.assertIn("Monitor root:", text)
        self.assertIn("Feature readiness:", text)

    def test_keys_are_presence_only(self):
        report = run_doctor()
        for key, state in report["keys"].items():
            if key == "agent_token_source":
                self.assertTrue(state)
            else:
                self.assertIn(state, ("missing", "set"))

    def test_client_api_version_matches_bridge(self):
        self.assertEqual(API_VERSION, 3)
        with patch("sm_telemetry_monitor.doctor.get_health", return_value={
            "status": "ok", "version": "0.7.0", "api_version": 3,
        }):
            from sm_telemetry_monitor.doctor import _check_coordinator
            block = _check_coordinator()
        self.assertEqual(block["client_api_version"], 3)
        self.assertEqual(block["api_version"], 3)
        self.assertEqual(block["compat"], "ok")
        self.assertFalse(block["has_llm_placement"])

    def test_coordinator_llm_placement_from_config(self):
        with patch("sm_telemetry_monitor.doctor.get_health", return_value={
            "status": "ok",
            "version": "0.8.9",
            "api_version": 3,
            "config": {
                "llm_backends": [
                    {"url": "http://localhost:5000", "weight": 1.0,
                     "has_credential": False, "model": None},
                    {"url": "https://api.example/v1", "weight": 1.0,
                     "has_credential": True, "model": "cloud"},
                ],
            },
            "llm_pool": {
                "http://localhost:5000": {"inflight": 0},
                "https://api.example/v1": {"inflight": 0},
            },
        }):
            from sm_telemetry_monitor.doctor import _check_coordinator
            block = _check_coordinator()
        self.assertTrue(block["has_llm_config"])
        self.assertTrue(block["has_llm_pool"])
        self.assertTrue(block["has_llm_placement"])
        self.assertEqual(block["llm_backend_count"], 2)
        self.assertEqual(block["llm_local_count"], 1)
        self.assertEqual(block["llm_external_count"], 1)

    def test_telemetry_panel_flags(self):
        with patch("sm_telemetry_monitor.doctor.get_telemetry", return_value={
            "status": "success",
            "telemetry": {
                "nrem": {"pending_cycles": 1},
                "breakdown": {"by_type": {}},
                "consolidation": {"stalled": False},
                "entity_graph": {"entities_total": 10},
                "latency": {"rem_ms": {}},
                "spine": {"facts": {}},
                "compliance": {"label_compliance": 1.0},
            },
        }):
            from sm_telemetry_monitor.doctor import _check_telemetry
            block = _check_telemetry()
        self.assertTrue(block["has_nrem"])
        self.assertTrue(block["has_breakdown"])
        self.assertTrue(block["has_consolidation"])
        self.assertTrue(block["has_entity_graph"])
        self.assertTrue(block["has_latency"])
        self.assertTrue(block["has_spine"])
        self.assertTrue(block["has_compliance"])

    def test_dashboard_history_ready_when_samples(self):
        checks = {
            "keys": {"AGENT_TOKEN": "set", "agent_token_source": "monitor"},
            "connectivity": {
                "coordinator": {"ok": True},
                "telemetry": {"ok": True, "has_breakdown": True},
                "neo4j_breakdown": {"ok": True},
            },
            "logs": {
                "log_paths": {"log_dir_exists": True, "log_dir": "/tmp"},
                "journal": {"ok": True},
            },
            "local_data": {"samples": 10, "last_at": "2026-07-16T00:00:00Z"},
        }
        features = {f["id"]: f for f in _feature_readiness(checks)}
        self.assertTrue(features["dashboard_history"]["ok"])
        self.assertEqual(features["dashboard_history"]["reason"], "ok")

    def test_dashboard_history_needs_samples(self):
        checks = {
            "keys": {"AGENT_TOKEN": "set", "agent_token_source": "monitor"},
            "connectivity": {
                "coordinator": {"ok": True},
                "telemetry": {"ok": True, "has_breakdown": True},
                "neo4j_breakdown": {"ok": True},
            },
            "logs": {
                "log_paths": {"log_dir_exists": True, "log_dir": "/tmp"},
                "journal": {"ok": True},
            },
            "local_data": {"samples": 0, "last_at": None},
        }
        features = {f["id"]: f for f in _feature_readiness(checks)}
        self.assertFalse(features["dashboard_history"]["ok"])
        self.assertIn("poll loop", features["dashboard_history"]["reason"])


if __name__ == "__main__":
    unittest.main()
