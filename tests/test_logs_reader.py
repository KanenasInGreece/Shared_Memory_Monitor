import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sm_telemetry_monitor.logs_reader import (
    agent_activity,
    classify_agent_audit_io,
    classify_daemon_audit_io,
    classify_gateway_line,
    is_consolidation_line,
    journalctl_cmd,
    journal_unit,
    list_archives,
    list_sources,
    parse_log_entry,
    resolve_archive,
    tail_source,
    _daemon_diagram_node,
    _filter_entries,
    _is_daemon_agent,
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


class AgentAuditSourceTests(unittest.TestCase):
    def test_list_sources_includes_agent_audit(self):
        ids = [s.id for s in list_sources()]
        self.assertIn("agent_audit", ids)
        self.assertNotIn("save_logs", ids)
        self.assertNotIn("gateway_audit", ids)
        src = next(s for s in list_sources() if s.id == "agent_audit")
        self.assertEqual(src.kind, "jsonl")
        self.assertIn("audit", src.path)

    def test_agent_audit_keeps_raw_json(self):
        line = json.dumps({
            "ts": "2026-06-12T18:04:11+00:00",
            "agent": "claude",
            "role": "full",
            "method": "POST",
            "path": "/memory/search",
            "status": 200,
            "latency_ms": 12.3,
            "request_id": "a1b2c3d4e5f6",
        })
        entry = parse_log_entry(line, kind="jsonl")
        self.assertEqual(entry["raw"], line)
        self.assertEqual(entry["ts"], "2026-06-12T18:04:11+00:00")

    @mock.patch("sm_telemetry_monitor.logs_reader.agent_audit_path")
    def test_tail_agent_audit_reads_jsonl(self, mock_path):
        line = json.dumps({
            "ts": "2026-06-12T18:04:11+00:00",
            "agent": "grok",
            "role": "full",
            "method": "GET",
            "path": "/memory/telemetry",
            "status": 200,
            "latency_ms": 4.1,
            "request_id": "req001",
        })
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "agent-audit.jsonl"
            path.write_text(line + "\n", encoding="utf-8")
            mock_path.return_value = path
            with mock.patch("sm_telemetry_monitor.logs_reader._log_root", return_value=Path(td).resolve()):
                result = tail_source("agent_audit", lines=10)
        self.assertEqual(result["source"], "agent_audit")
        self.assertEqual(result["archive"], "live")
        self.assertEqual(result["lines"], [line])


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name).resolve()
        self.patcher = mock.patch(
            "sm_telemetry_monitor.logs_reader._log_root", return_value=self.root,
        )
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.td.cleanup()

    def test_resolve_archive_rejects_traversal(self):
        with self.assertRaises(ValueError):
            resolve_archive("rem_audit", "../../etc/passwd")

    def test_resolve_archive_rejects_unknown(self):
        with self.assertRaises(ValueError):
            resolve_archive("rem_audit", "not-a-real-archive.gz")

    @mock.patch("sm_telemetry_monitor.logs_reader.audit_path")
    def test_lists_rotated_audit_archives(self, mock_audit):
        live = self.root / "rem-audit.jsonl"
        live.write_text("{}\n", encoding="utf-8")
        mock_audit.return_value = live
        rotated = self.root / "rem-audit.jsonl-20260612.gz"
        with gzip.open(rotated, "wt", encoding="utf-8") as f:
            f.write(json.dumps({"ts": "2026-06-12T10:00:00+00:00"}) + "\n")
        out = list_archives("rem_audit")
        self.assertEqual(len(out["archives"]), 1)
        result = tail_source("rem_audit", lines=5, archive=rotated.name)
        self.assertEqual(len(result["lines"]), 1)


class AgentActivityTests(unittest.TestCase):
    def test_classify_memory_io(self):
        self.assertEqual(classify_agent_audit_io("POST", "/memory/save"), "write")
        self.assertEqual(classify_agent_audit_io("POST", "/memory/search"), "write")
        self.assertEqual(classify_agent_audit_io("GET", "/memory/telemetry"), "read")
        self.assertEqual(classify_agent_audit_io("POST", "/memory/graph"), "read")
        self.assertIsNone(classify_agent_audit_io("POST", "/v1/chat/completions"))

    def test_daemon_agents_excluded(self):
        self.assertTrue(_is_daemon_agent("monitor"))
        self.assertTrue(_is_daemon_agent("rem_daemon"))
        self.assertTrue(_is_daemon_agent("consolidation"))
        self.assertFalse(_is_daemon_agent("grok"))

    def test_classify_daemon_audit_io(self):
        self.assertEqual(classify_daemon_audit_io("/v1/chat/completions"), "chat")
        self.assertEqual(classify_daemon_audit_io("/v1/embeddings"), "embeddings")
        self.assertEqual(classify_daemon_audit_io("/v1/reranking"), "proxy")
        self.assertIsNone(classify_daemon_audit_io("/memory/save"))

    def test_daemon_diagram_node_mapping(self):
        self.assertEqual(_daemon_diagram_node("rem_daemon"), "rem_daemon")
        self.assertEqual(_daemon_diagram_node("consolidation"), "nrem_daemon")
        self.assertIsNone(_daemon_diagram_node("monitor"))

    @mock.patch("sm_telemetry_monitor.logs_reader.agent_audit_path")
    def test_agent_activity_window(self, mock_path):
        lines = [
            {
                "ts": "2026-06-12T10:00:00+00:00",
                "agent": "grok",
                "method": "POST",
                "path": "/memory/save",
                "status": 200,
            },
            {
                "ts": "2026-06-12T10:05:00+00:00",
                "agent": "grok",
                "method": "GET",
                "path": "/memory/telemetry",
                "status": 200,
            },
            {
                "ts": "2026-06-12T10:10:00+00:00",
                "agent": "monitor",
                "method": "GET",
                "path": "/memory/telemetry",
                "status": 200,
            },
            {
                "ts": "2026-06-12T10:15:00+00:00",
                "agent": "consolidation",
                "method": "POST",
                "path": "/v1/chat/completions",
                "status": 200,
            },
            {
                "ts": "2026-06-12T11:00:00+00:00",
                "agent": "claude",
                "method": "POST",
                "path": "/memory/search",
                "status": 200,
            },
        ]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "agent-audit.jsonl"
            path.write_text("\n".join(json.dumps(row) for row in lines) + "\n", encoding="utf-8")
            mock_path.return_value = path
            with mock.patch("sm_telemetry_monitor.logs_reader._log_root", return_value=Path(td).resolve()):
                out = agent_activity(
                    since="2026-06-12T10:00:00+00:00",
                    until="2026-06-12T10:30:00+00:00",
                )
                out2 = agent_activity(
                    since="2026-06-12T10:00:00+00:00",
                    until="2026-06-12T12:00:00+00:00",
                )
        self.assertEqual(out["agents"], {"grok": {"read": 1, "write": 1}})
        self.assertEqual(out["daemon_logic"], {
            "nrem_daemon": {"chat": 1, "embeddings": 0, "proxy": 0},
        })
        self.assertEqual(out2["agents"]["claude"], {"read": 0, "write": 1})

    @mock.patch("sm_telemetry_monitor.logs_reader.agent_audit_path")
    def test_daemon_logic_activity(self, mock_path):
        lines = [
            {
                "ts": "2026-06-12T10:00:00+00:00",
                "agent": "rem_daemon",
                "method": "POST",
                "path": "/v1/chat/completions",
                "status": 200,
            },
            {
                "ts": "2026-06-12T10:05:00+00:00",
                "agent": "consolidation",
                "method": "POST",
                "path": "/v1/embeddings",
                "status": 200,
            },
        ]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "agent-audit.jsonl"
            path.write_text("\n".join(json.dumps(row) for row in lines) + "\n", encoding="utf-8")
            mock_path.return_value = path
            with mock.patch("sm_telemetry_monitor.logs_reader._log_root", return_value=Path(td).resolve()):
                out = agent_activity(
                    since="2026-06-12T09:00:00+00:00",
                    until="2026-06-12T11:00:00+00:00",
                )
        self.assertEqual(out["daemon_logic"]["rem_daemon"]["chat"], 1)
        self.assertEqual(out["daemon_logic"]["nrem_daemon"]["embeddings"], 1)
        self.assertEqual(out["agents"], {})


class GatewayLogClassifyTests(unittest.TestCase):
    def test_is_consolidation_line(self):
        self.assertTrue(is_consolidation_line(
            "INFO:ConsolidationDaemon:Consolidation run [insight] completed: folds 0/0"
        ))
        self.assertTrue(is_consolidation_line(
            "WARNING:ConsolidationDaemon:NREM: inference GPU busy — deferring consolidation"
        ))
        self.assertFalse(is_consolidation_line("INFO: GET /health"))

    def test_classify_gateway_crash(self):
        line = "ERROR:Consolidation run [insight] CRASHED after 1/2 folds: ValueError: boom"
        self.assertEqual(classify_gateway_line(line), "line-err")

    def test_classify_health_refresh_failed(self):
        line = "2026-06-25 12:41:40,325 [WARNING] consolidation health refresh failed: column missing"
        self.assertEqual(classify_gateway_line(line), "line-warn")

    def test_classify_completed_run(self):
        line = "INFO:ConsolidationDaemon:Consolidation run [fact_consolidation] completed: folds 1/1"
        self.assertEqual(classify_gateway_line(line), "line-info")


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