import re

t_health = "tests/test_system_health.py"
with open(t_health, 'r') as f:
    text = f.read()

test_llm_lat = """    def test_llm_latency_passthrough_and_join(self):
        \"\"\"llm_latency passed through to config & snapshot, and joined onto pool backends.\"\"\"
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
        \"\"\"Single-backend cloud-only (external) fleet correctly attaches latency & placement.\"\"\"
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
"""

text = text.replace('def test_top_level_graph_invalid_nodes_triggers_warn', test_llm_lat + '\n    def test_top_level_graph_invalid_nodes_triggers_warn')
with open(t_health, 'w') as f:
    f.write(text)

t_doc = "tests/test_doctor.py"
with open(t_doc, 'r') as f:
    text = f.read()

test_doc_lat = """    def test_coordinator_llm_latency_flag(self):
        with patch("sm_telemetry_monitor.doctor.get_health", return_value={
            "status": "ok", "version": "0.9.15", "api_version": 4,
            "llm_pool": {"http://localhost:5000": {"inflight": 0}},
            "llm_latency": {},
        }):
            from sm_telemetry_monitor.doctor import _check_coordinator
            block = _check_coordinator()
        self.assertTrue(block["has_llm_latency"])

    def test_format_report_names_llm_latency(self):
        report = {
            "monitor_root": "/tmp/mon",
            "gateway_client": {
                "mode": "httpx",
                "coordinator_url": "http://localhost:8888",
                "agent_token_source": "monitor",
            },
            "env_sources": [],
            "keys": {"AGENT_TOKEN": "set", "agent_token_source": "monitor"},
            "local_data": {"samples": 0, "last_at": None},
            "connectivity": {
                "coordinator": {
                    "ok": True,
                    "version": "0.9.15",
                    "api_version": 4,
                    "client_api_version": 4,
                    "compat": "ok",
                    "has_llm_pool": True,
                    "has_llm_latency": True,
                },
                "telemetry": {"ok": True},
                "neo4j_breakdown": {"ok": True},
                "read_role": {"ok": True},
            },
            "logs": {
                "log_paths": {"log_dir_exists": True, "log_dir": "/tmp"},
                "journal": {"ok": True, "unit": "x", "scope": "user"},
            },
            "features": [],
        }
        from sm_telemetry_monitor.doctor import format_report
        text = format_report(report)
        self.assertIn("llm_latency", text)
"""

text = text.replace('def test_format_report_names_unauth_allowlist_beacon', test_doc_lat + '\n    def test_format_report_names_unauth_allowlist_beacon')
with open(t_doc, 'w') as f:
    f.write(text)

