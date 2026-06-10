import json
import unittest

from sm_telemetry_monitor.logs_reader import (
    journalctl_cmd,
    journal_unit,
    parse_log_entry,
    _filter_entries,
    _parse_ts,
)


class ParseLogEntryTests(unittest.TestCase):
    def test_journal_keeps_raw_line(self):
        line = (
            "2026-06-10T15:03:37+03:00 workstation uv[1317214]: "
            "2026-06-10 15:03:37,044 [INFO] GET /health"
        )
        entry = parse_log_entry(line, kind="journal")
        self.assertEqual(entry["raw"], line)
        self.assertIn(".044", entry["ts"])

    def test_rem_audit_keeps_raw_json(self):
        snippet = "hello " + ("x" * 120)
        line = json.dumps({
            "ts": "2026-06-09T17:32:03.411719+00:00",
            "outbox_id": 78,
            "pg_id": 112,
            "status": "applied",
            "cypher_params": {"content_snippet": snippet, "entities": ["A", "B"]},
        })
        entry = parse_log_entry(line, kind="jsonl")
        self.assertEqual(entry["raw"], line)
        self.assertEqual(entry["ts"], "2026-06-09T17:32:03.411719+00:00")


class JournalCmdTests(unittest.TestCase):
    def test_journalctl_uses_user_scope(self):
        cmd = journalctl_cmd(lines=5)
        self.assertEqual(cmd[:4], ["journalctl", "--user", "-u", journal_unit()])
        self.assertIn("-n", cmd)
        self.assertEqual(cmd[cmd.index("-n") + 1], "5")


class FilterEntriesTests(unittest.TestCase):
    def test_filters_by_window(self):
        entries = [
            {"ts": "2026-06-10T10:00:00+00:00", "raw": "a"},
            {"ts": "2026-06-10T12:00:00+00:00", "raw": "b"},
            {"ts": "2026-06-10T14:00:00+00:00", "raw": "c"},
        ]
        since = _parse_ts("2026-06-10T11:00:00+00:00")
        until = _parse_ts("2026-06-10T13:00:00+00:00")
        out = _filter_entries(entries, since=since, until=until)
        self.assertEqual([e["raw"] for e in out], ["b"])


if __name__ == "__main__":
    unittest.main()