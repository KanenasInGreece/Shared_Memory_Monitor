"""The funnel must survive a reading the gateway did not send."""

import unittest

from sm_telemetry_monitor.pipeline_chart import stages_to_plot


class StagesToPlotTests(unittest.TestCase):
    def test_missing_reading_is_left_off_and_does_not_compare(self):
        stages = [
            {"key": "outbox_failed", "value": 0},
            {"key": "insight_excluded_pending_rem", "value": None},
            {"key": "facts_total", "value": 12},
            {"key": "retrospectives_rem_pending", "value": True},
        ]
        plotted = stages_to_plot(stages)
        self.assertEqual(
            [stage["key"] for stage in plotted],
            ["outbox_failed", "facts_total"],
        )
        self.assertEqual(plotted[0]["value"], 0)
        self.assertEqual(plotted[1]["value"], 12)

    def test_real_zero_on_a_new_reading_stays_off_the_funnel(self):
        stages = [{"key": "rem_backlog_withheld", "value": 0}]
        self.assertEqual(stages_to_plot(stages), [])

    def test_positive_new_reading_is_drawn(self):
        stages = [{"key": "rem_backlog_older_prompt", "value": 3}]
        self.assertEqual(stages_to_plot(stages)[0]["value"], 3)


if __name__ == "__main__":
    unittest.main()
