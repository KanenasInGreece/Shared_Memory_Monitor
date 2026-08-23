import re
with open('tests/test_system_health.py', 'r') as f:
    text = f.read()

test_code = """
    def test_llm_latency_passthrough_and_join(self):
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
text = text.replace('class RemDrainSignalTests(unittest.TestCase):', test_code + '\nclass RemDrainSignalTests(unittest.TestCase):')
with open('tests/test_system_health.py', 'w') as f:
    f.write(text)
