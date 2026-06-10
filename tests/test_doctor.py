import unittest

from sm_telemetry_monitor.doctor import format_report, run_doctor


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


if __name__ == "__main__":
    unittest.main()