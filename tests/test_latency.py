import unittest
from unittest.mock import patch

from sm_telemetry_monitor.latency import latency_from_payload, latency_snapshot


def _payload(latency):
    return {"status": "success", "telemetry": {"timestamp": "2026-07-14T09:00:00Z", "latency": latency}}


class LatencyNremTests(unittest.TestCase):
    def test_nrem_p50_p95_and_spread(self):
        snap = latency_from_payload(_payload({
            "nrem_cycle_seconds": {"window_days": 7, "n": 5, "p50": 62.0, "p95": 571.0,
                                   "note": "synthesis cycles only"},
        }))
        nrem = snap["nrem"]
        self.assertTrue(nrem["present"])
        self.assertEqual(nrem["p50_seconds"], 62.0)
        self.assertEqual(nrem["p95_seconds"], 571.0)
        self.assertEqual(nrem["spread"], 9.2)         # 571 / 62
        self.assertTrue(nrem["low_n"])                # n=5 < 10
        self.assertEqual(nrem["window_days"], 7)

    def test_nrem_absent_when_no_cycles(self):
        snap = latency_from_payload(_payload({"nrem_cycle_seconds": {"window_days": 7, "n": 0}}))
        self.assertFalse(snap["nrem"]["present"])
        self.assertIsNone(snap["nrem"]["spread"])


class LatencyRemTests(unittest.TestCase):
    def test_empty_by_model_degrades(self):
        snap = latency_from_payload(_payload({
            "rem_ms": {"note": "service_ms = model/hardware; contention_ms = capacity", "by_model": []},
            "nrem_cycle_seconds": {"n": 5, "p50": 10, "p95": 20},
        }))
        self.assertTrue(snap["present"])              # block exists
        self.assertFalse(snap["rem"]["present"])      # but no models measured
        self.assertEqual(snap["rem"]["models"], [])
        self.assertIsNone(snap["rem"]["max_contention_pct"])
        self.assertIsNone(snap["chip"])

    def test_service_vs_contention_split(self):
        snap = latency_from_payload(_payload({
            "rem_ms": {"by_model": [
                {"model": "gemma-4", "service_ms": 820, "contention_ms": 180, "n": 42},
            ]},
        }))
        m = snap["rem"]["models"][0]
        self.assertEqual(m["total_ms"], 1000)
        self.assertEqual(m["service_frac"], 82)
        self.assertEqual(m["contention_frac"], 18)
        self.assertEqual(m["contention_pct"], 18)
        self.assertFalse(m["low_n"])                  # n=42 >= 10
        self.assertIsNone(snap["chip"])               # 18% < 30% threshold

    def test_percentile_dict_fields_anchor_on_p50(self):
        snap = latency_from_payload(_payload({
            "rem_ms": {"by_model": [
                {"model": "qwen3", "service_ms": {"p50": 310, "p95": 900},
                 "contention_ms": {"p50": 290}, "n": 6},
            ]},
        }))
        m = snap["rem"]["models"][0]
        self.assertEqual(m["service_ms"], 310)
        self.assertEqual(m["contention_ms"], 290)
        self.assertEqual(m["contention_pct"], 48)     # 290 / 600
        self.assertTrue(m["low_n"])                   # n=6 < 10
        self.assertEqual(m["service_ms_p95"], 900)
        self.assertIsNone(m["contention_ms_p95"])     # p95 omitted on that field

    def test_p95_and_max_batch_passthrough(self):
        snap = latency_from_payload(_payload({
            "rem_ms": {"by_model": [
                {
                    "model": "gemma-4-12B-it-Q4_K_M.gguf",
                    "n": 2,
                    "max_batch_size": 2,
                    "service_ms": {"p50": 1100.0, "p95": 2200.0},
                    "contention_ms": {"p50": 90.0, "p95": 120.0},
                },
            ]},
        }))
        m = snap["rem"]["models"][0]
        self.assertEqual(m["service_ms"], 1100.0)
        self.assertEqual(m["service_ms_p95"], 2200.0)
        self.assertEqual(m["contention_ms_p95"], 120.0)
        self.assertEqual(m["max_batch_size"], 2)
        self.assertEqual(m["service_frac"], 92)       # 1100 / 1190

    def test_chip_promoted_above_threshold(self):
        snap = latency_from_payload(_payload({
            "rem_ms": {"by_model": [
                {"model": "a", "service_ms": 100, "contention_ms": 20, "n": 30},   # 17%
                {"model": "b", "service_ms": 100, "contention_ms": 400, "n": 30},  # 80%
            ]},
        }))
        self.assertEqual(snap["rem"]["max_contention_pct"], 80)
        self.assertIsNotNone(snap["chip"])
        self.assertEqual(snap["chip"]["contention_pct"], 80)

    def test_wall_only_deepseek_shape(self):
        snap = latency_from_payload(_payload({
            "rem_ms": {"by_model": [
                {
                    "model": "deepseek-v4-flash",
                    "n": 15,
                    "n_service": 0,
                    "timing_source": "wall",
                    "backend": "https://api.deepseek.com",
                    "max_batch_size": 2,
                    "service_ms": {"p50": None, "p95": None},
                    "contention_ms": {"p50": None, "p95": None},
                    "wall_ms": {"p50": 4905.1, "p95": 6283.3},
                },
            ]},
        }))
        self.assertTrue(snap["rem"]["present"])
        m = snap["rem"]["models"][0]
        self.assertEqual(m["model"], "deepseek-v4-flash")
        self.assertIsNone(m["service_ms"])
        self.assertIsNone(m["contention_ms"])
        self.assertEqual(m["wall_ms"], 4905.1)
        self.assertEqual(m["wall_ms_p95"], 6283.3)
        self.assertEqual(m["n_service"], 0)
        self.assertEqual(m["timing_source"], "wall")
        self.assertEqual(m["backend"], "https://api.deepseek.com")
        self.assertIsNone(m["service_frac"])
        self.assertIsNone(m["contention_frac"])
        self.assertEqual(m["max_batch_size"], 2)
        self.assertIsNone(snap["chip"])

    def test_mixed_timing_source(self):
        snap = latency_from_payload(_payload({
            "rem_ms": {"by_model": [
                {
                    "model": "mixed-model",
                    "n": 500,
                    "n_service": 1,
                    "timing_source": "mixed",
                    "service_ms": {"p50": 100, "p95": 200},
                    "contention_ms": {"p50": 10, "p95": 20},
                    "wall_ms": {"p50": 4000, "p95": 8000},
                    "backend": None,
                },
            ]},
        }))
        m = snap["rem"]["models"][0]
        self.assertEqual(m["n"], 500)
        self.assertEqual(m["n_service"], 1)
        self.assertEqual(m["timing_source"], "mixed")
        self.assertIsNone(m["backend"])
        self.assertEqual(m["service_ms"], 100)
        self.assertEqual(m["wall_ms"], 4000)
        self.assertEqual(m["wall_ms_p95"], 8000)
        self.assertEqual(m["total_ms"], 110)
        self.assertEqual(m["service_frac"], 91)       # round(100 * 100 / 110) = 91
        self.assertEqual(m["contention_frac"], 9)     # round(100 * 10 / 110) = 9
        self.assertEqual(m["contention_pct"], 9)

    def test_server_row_with_wall_and_timing_source(self):
        snap = latency_from_payload(_payload({
            "rem_ms": {"by_model": [
                {
                    "model": "qwen-local",
                    "n": 40,
                    "n_service": 40,
                    "timing_source": "server",
                    "backend": "http://ollama:11434",
                    "max_batch_size": 1,
                    "service_ms": {"p50": 800, "p95": 1200},
                    "contention_ms": {"p50": 200, "p95": 400},
                    "wall_ms": {"p50": 1050.0, "p95": 1650.0},
                },
            ]},
        }))
        m = snap["rem"]["models"][0]
        self.assertEqual(m["model"], "qwen-local")
        self.assertEqual(m["service_ms"], 800)
        self.assertEqual(m["contention_ms"], 200)
        self.assertEqual(m["total_ms"], 1000)
        self.assertEqual(m["service_frac"], 80)
        self.assertEqual(m["contention_frac"], 20)
        self.assertEqual(m["wall_ms"], 1050.0)
        self.assertEqual(m["wall_ms_p95"], 1650.0)
        self.assertEqual(m["timing_source"], "server")
        self.assertEqual(m["n_service"], 40)
        self.assertEqual(m["backend"], "http://ollama:11434")

    def test_pre_0960_row_defaults(self):
        snap = latency_from_payload(_payload({
            "rem_ms": {"by_model": [
                {"model": "gemma-legacy", "service_ms": 500, "contention_ms": 100, "n": 20},
            ]},
        }))
        m = snap["rem"]["models"][0]
        self.assertEqual(m["model"], "gemma-legacy")
        self.assertEqual(m["service_ms"], 500)
        self.assertEqual(m["contention_ms"], 100)
        self.assertIsNone(m.get("wall_ms"))
        self.assertIsNone(m.get("wall_ms_p95"))
        self.assertIsNone(m.get("n_service"))
        self.assertIsNone(m.get("timing_source"))
        self.assertIsNone(m.get("backend"))

    def test_name_fallback_never_uses_backend_url(self):
        # Entry with NO model, backend is a URL -> name must be "?" (never the URL)
        snap = latency_from_payload(_payload({
            "rem_ms": {"by_model": [
                {"backend": "https://api.deepseek.com", "n": 10},
            ]},
        }))
        m = snap["rem"]["models"][0]
        self.assertEqual(m["model"], "?")
        self.assertEqual(m["backend"], "https://api.deepseek.com")

        # Entry with 'name' key used if present
        snap2 = latency_from_payload(_payload({
            "rem_ms": {"by_model": [
                {"name": "custom-named-model", "backend": "https://api.openai.com", "n": 5},
            ]},
        }))
        m2 = snap2["rem"]["models"][0]
        self.assertEqual(m2["model"], "custom-named-model")
        self.assertEqual(m2["backend"], "https://api.openai.com")


class LatencyEnvelopeTests(unittest.TestCase):
    def test_missing_latency_block_pre_063_gateway(self):
        snap = latency_from_payload({"status": "success", "telemetry": {"neo4j": {}}})
        self.assertFalse(snap["present"])
        self.assertTrue(snap["reachable"])
        self.assertFalse(snap["rem"]["present"])
        self.assertFalse(snap["nrem"]["present"])

    def test_unreachable_gateway(self):
        snap = latency_from_payload({"status": "error", "message": "coordinator unreachable"})
        self.assertFalse(snap["reachable"])
        self.assertFalse(snap["present"])
        self.assertEqual(snap["error"], "coordinator unreachable")

    @patch("sm_telemetry_monitor.latency.get_telemetry")
    def test_snapshot_calls_bridge(self, mock_telemetry):
        mock_telemetry.return_value = _payload({"nrem_cycle_seconds": {"n": 3, "p50": 5, "p95": 9}})
        snap = latency_snapshot()
        mock_telemetry.assert_called_once()
        self.assertTrue(snap["nrem"]["present"])


if __name__ == "__main__":
    unittest.main()
