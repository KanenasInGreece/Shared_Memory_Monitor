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
