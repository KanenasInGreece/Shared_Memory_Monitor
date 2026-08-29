import gzip
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sm_telemetry_monitor import logs_reader
from sm_telemetry_monitor.logs_reader import (
    _AUDIT_CACHE,
    _AUDIT_CACHE_MAX_FILES,
    _audit_agent_id,
    _audit_route,
    _daemon_diagram_node,
    _filter_entries,
    _is_daemon_agent,
    _parse_ts,
    agent_activity,
    classify_agent_audit_io,
    classify_daemon_audit_io,
    classify_gateway_line,
    credential_audit_path,
    is_consolidation_line,
    journal_unit,
    journalctl_cmd,
    list_archives,
    list_sources,
    log_dir,
    parse_log_entry,
    resolve_archive,
    tail_source,
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


class CredentialAuditSourceTests(unittest.TestCase):
    """I6 / I9 — credential_audit source; empty env disables live path."""

    def test_list_sources_includes_credential_audit(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("CREDENTIAL_AUDIT_LOG_PATH", None)
            ids = [s.id for s in list_sources()]
            self.assertIn("credential_audit", ids)
            self.assertNotIn("save_logs", ids)
            self.assertNotIn("gateway_audit", ids)
            self.assertGreater(ids.index("credential_audit"), ids.index("agent_audit"))
            src = next(s for s in list_sources() if s.id == "credential_audit")
            self.assertEqual(src.kind, "jsonl")
            self.assertEqual(src.path, "credential-audit.jsonl")
            self.assertEqual(credential_audit_path(), log_dir() / "credential-audit.jsonl")

    def test_empty_credential_audit_path_disables_live(self):
        """Empty CREDENTIAL_AUDIT_LOG_PATH disables live file (no default invent)."""
        with mock.patch.dict(os.environ, {"CREDENTIAL_AUDIT_LOG_PATH": ""}):
            path = credential_audit_path()
            default = log_dir() / "credential-audit.jsonl"
            # Do not fall back to the default live file when explicitly disabled.
            self.assertNotEqual(path, default)
            self.assertFalse(path.exists())
            ids = [s.id for s in list_sources()]
            self.assertIn("credential_audit", ids)
            result = tail_source("credential_audit", lines=5)
            self.assertEqual(result.get("source"), "credential_audit")
            self.assertEqual(result.get("lines"), [])
            self.assertIn("error", result)
            self.assertIn("not found", result["error"].lower())

    def test_whitespace_credential_audit_path_disables_live(self):
        with mock.patch.dict(os.environ, {"CREDENTIAL_AUDIT_LOG_PATH": "  "}):
            path = credential_audit_path()
            self.assertNotEqual(path, log_dir() / "credential-audit.jsonl")
            self.assertFalse(path.exists())

    def test_credential_audit_keeps_raw_json(self):
        line = json.dumps({
            "ts": "2026-08-15T10:00:00+00:00",
            "event": "llm.credential",
            "origin": "gateway",
            "backend": "http://localhost:5000",
            "request_id": "cred001",
            "status": "failed",
            "error_type": "auth",
        })
        entry = parse_log_entry(line, kind="jsonl")
        self.assertEqual(entry["raw"], line)
        self.assertEqual(entry["ts"], "2026-08-15T10:00:00+00:00")

    @mock.patch("sm_telemetry_monitor.logs_reader.credential_audit_path")
    def test_tail_credential_audit_reads_jsonl(self, mock_path):
        line = json.dumps({
            "ts": "2026-08-15T10:00:00+00:00",
            "event": "llm.credential",
            "origin": "upstream",
            "backend": "http://localhost:4000",
            "request_id": "cred002",
        })
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "credential-audit.jsonl"
            path.write_text(line + "\n", encoding="utf-8")
            mock_path.return_value = path
            with mock.patch("sm_telemetry_monitor.logs_reader._log_root", return_value=Path(td).resolve()):
                result = tail_source("credential_audit", lines=10)
        self.assertEqual(result["source"], "credential_audit")
        self.assertEqual(result["archive"], "live")
        self.assertEqual(result["lines"], [line])
        self.assertEqual(result["lines"][0], line)


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

    @mock.patch("sm_telemetry_monitor.logs_reader.credential_audit_path")
    def test_numbered_rotates_credential_audit(self, mock_cred):
        """I7: .1 uncompressed + .N.gz listed; live excluded from archives."""
        live = self.root / "credential-audit.jsonl"
        live.write_text(json.dumps({"ts": "live"}) + "\n", encoding="utf-8")
        mock_cred.return_value = live
        r1 = self.root / "credential-audit.jsonl.1"
        r1.write_text(json.dumps({"ts": "2026-08-14T00:00:00+00:00"}) + "\n", encoding="utf-8")
        r2 = self.root / "credential-audit.jsonl.2.gz"
        with gzip.open(r2, "wt", encoding="utf-8") as f:
            f.write(json.dumps({"ts": "2026-08-13T00:00:00+00:00"}) + "\n")
        out = list_archives("credential_audit")
        ids = [a["id"] for a in out["archives"]]
        self.assertIn("credential-audit.jsonl.1", ids)
        self.assertIn("credential-audit.jsonl.2.gz", ids)
        self.assertNotIn("credential-audit.jsonl", ids)
        self.assertNotIn("live", ids)
        resolved = resolve_archive("credential_audit", "credential-audit.jsonl.1")
        self.assertEqual(resolved, r1.resolve())
        tailed = tail_source("credential_audit", lines=5, archive="credential-audit.jsonl.1")
        self.assertEqual(len(tailed["lines"]), 1)
        self.assertIn("2026-08-14", tailed["lines"][0])

    @mock.patch("sm_telemetry_monitor.logs_reader.agent_audit_path")
    def test_numbered_rotates_agent_audit(self, mock_agent):
        """I7: gateway-audit live + .1 + .2.gz (host logrotate pattern)."""
        live = self.root / "gateway-audit.jsonl"
        live.write_text(json.dumps({"ts": "live"}) + "\n", encoding="utf-8")
        mock_agent.return_value = live
        r1 = self.root / "gateway-audit.jsonl.1"
        r1.write_text(json.dumps({"ts": "2026-08-14T00:00:00+00:00", "agent": "grok"}) + "\n", encoding="utf-8")
        r2 = self.root / "gateway-audit.jsonl.2.gz"
        with gzip.open(r2, "wt", encoding="utf-8") as f:
            f.write(json.dumps({"ts": "2026-08-13T00:00:00+00:00", "agent": "claude"}) + "\n")
        out = list_archives("agent_audit")
        ids = [a["id"] for a in out["archives"]]
        self.assertIn("gateway-audit.jsonl.1", ids)
        self.assertIn("gateway-audit.jsonl.2.gz", ids)
        self.assertNotIn("gateway-audit.jsonl", ids)
        resolved = resolve_archive("agent_audit", "gateway-audit.jsonl.1")
        self.assertEqual(resolved, r1.resolve())

    @mock.patch("sm_telemetry_monitor.logs_reader.audit_path")
    def test_resolve_numbered_archive_rejects_traversal(self, mock_audit):
        live = self.root / "rem-audit.jsonl"
        live.write_text("{}\n", encoding="utf-8")
        mock_audit.return_value = live
        (self.root / "rem-audit.jsonl.1").write_text("{}\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            resolve_archive("rem_audit", "../rem-audit.jsonl.1")
        with self.assertRaises(ValueError):
            resolve_archive("rem_audit", "/etc/passwd")
        ok = resolve_archive("rem_audit", "rem-audit.jsonl.1")
        self.assertTrue(ok.is_file())


class AgentActivityTests(unittest.TestCase):
    def setUp(self):
        _AUDIT_CACHE.clear()

    def test_classify_memory_io(self):
        self.assertEqual(classify_agent_audit_io("POST", "/memory/save"), "write")
        self.assertEqual(classify_agent_audit_io("POST", "/memory/search"), "read")
        self.assertEqual(classify_agent_audit_io("POST", "/memory/retrospective"), "write")
        self.assertEqual(classify_agent_audit_io("POST", "/memory/supersede"), "write")
        self.assertEqual(classify_agent_audit_io("GET", "/memory/telemetry"), "read")
        self.assertEqual(classify_agent_audit_io("POST", "/memory/graph"), "read")
        self.assertEqual(classify_agent_audit_io("GET", "/memory/status/42"), "read")
        self.assertEqual(classify_agent_audit_io("POST", "/memory/relations/review"), "read")
        self.assertEqual(classify_agent_audit_io("POST", "/memory/relations/label"), "write")
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
        self.assertEqual(out2["agents"]["claude"], {"read": 1, "write": 0})

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

    @mock.patch("sm_telemetry_monitor.logs_reader.agent_audit_path")
    def test_malformed_rows_do_not_break_the_scan(self, mock_path):
        """One MCP client logging JSON where a string is expected must not
        blank the whole diagram: the bad rows are skipped, the good ones count."""
        raw = "\n".join([
            json.dumps({"ts": "2026-06-12T10:00:00+00:00", "agent": ["opencode"],
                        "method": "POST", "path": "/memory/search"}),
            json.dumps({"ts": "2026-06-12T10:01:00+00:00", "agent": "opencode",
                        "method": ["POST"], "path": {"route": "/memory/save"}}),
            json.dumps({"ts": "2026-06-12T10:02:00+00:00", "agent": {"id": "x"},
                        "method": "GET", "path": "/memory/telemetry"}),
            # An epoch int or JSON ts must not brick the scan for every caller.
            json.dumps({"ts": 1749722400, "agent": "codex",
                        "method": "POST", "path": "/memory/save"}),
            json.dumps({"ts": {"at": "2026-06-12T10:02:30+00:00"}, "agent": "codex",
                        "method": "POST", "path": "/memory/save"}),
            json.dumps(["not", "an", "object"]),
            json.dumps("bare string"),
            "{ not json at all",
            json.dumps({"ts": "2026-06-12T10:03:00+00:00", "agent": "grok",
                        "method": "POST", "path": "/memory/save"}),
        ])
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "agent-audit.jsonl"
            path.write_text(raw + "\n", encoding="utf-8")
            mock_path.return_value = path
            with mock.patch("sm_telemetry_monitor.logs_reader._log_root", return_value=Path(td).resolve()):
                out = agent_activity(
                    since="2026-06-12T09:00:00+00:00",
                    until="2026-06-12T11:00:00+00:00",
                )
        self.assertEqual(out["agents"]["grok"], {"read": 0, "write": 1})
        # A JSON-wrapped agent id unwraps to its own chip, not a repr bucket.
        self.assertEqual(out["agents"]["opencode"], {"read": 1, "write": 0})
        # Nothing else is invented: an unattributable row is counted for no one.
        self.assertEqual(set(out["agents"]), {"grok", "opencode"})

    def test_parse_ts_rejects_non_string_stamps(self):
        self.assertIsNone(_parse_ts(1749722400))
        self.assertIsNone(_parse_ts(True))
        self.assertIsNone(_parse_ts({"at": "2026-06-12T10:00:00+00:00"}))
        self.assertIsNone(_parse_ts(["2026-06-12T10:00:00+00:00"]))
        self.assertIsNotNone(_parse_ts("2026-06-12T10:00:00+00:00"))

    def test_audit_cache_is_bounded(self):
        """Rotation mints a new filename each cycle; the key set must not grow
        for the life of the process."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            with mock.patch("sm_telemetry_monitor.logs_reader._log_root", return_value=root):
                for i in range(_AUDIT_CACHE_MAX_FILES + 15):
                    p = root / f"agent-audit.jsonl.{i}"
                    p.write_text(json.dumps({
                        "ts": "2026-06-12T10:00:00+00:00", "agent": "grok",
                        "method": "POST", "path": "/memory/save",
                    }) + "\n", encoding="utf-8")
                    logs_reader._audit_rows(p)
                    self.assertLessEqual(len(_AUDIT_CACHE), _AUDIT_CACHE_MAX_FILES)
        self.assertEqual(len(_AUDIT_CACHE), _AUDIT_CACHE_MAX_FILES)

    def test_audit_agent_id_normalisation(self):
        self.assertEqual(_audit_agent_id("opencode"), "opencode")
        self.assertEqual(_audit_agent_id("  opencode  "), "opencode")
        self.assertEqual(_audit_agent_id(["opencode"]), "opencode")
        self.assertEqual(_audit_agent_id(("opencode",)), "opencode")
        self.assertEqual(_audit_agent_id(None), "")
        # An unattributable shape names no agent — it must not become a chip.
        self.assertEqual(_audit_agent_id(["a", "b"]), "")
        self.assertEqual(_audit_agent_id({"id": "x"}), "")
        self.assertEqual(_audit_agent_id(True), "")

    def test_audit_route_tolerates_non_string_path(self):
        self.assertEqual(_audit_route("/memory/save?x=1"), "/memory/save")
        self.assertEqual(_audit_route(None), "")
        self.assertEqual(_audit_route({"route": "/memory/save"}), "{'route': '/memory/save'}")

    @mock.patch("sm_telemetry_monitor.logs_reader.agent_audit_path")
    def test_audit_parse_is_cached_until_the_file_changes(self, mock_path):
        """The scrubber asks for one window per slider step over the same bytes;
        re-parsing the corpus per request is what starved the dashboard."""
        row = {"ts": "2026-06-12T10:00:00+00:00", "agent": "grok",
               "method": "POST", "path": "/memory/save"}
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "agent-audit.jsonl"
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            mock_path.return_value = path
            real_read = logs_reader._read_audit_lines
            with mock.patch("sm_telemetry_monitor.logs_reader._log_root", return_value=Path(td).resolve()), \
                 mock.patch("sm_telemetry_monitor.logs_reader._read_audit_lines",
                            side_effect=real_read) as spy:
                for _ in range(25):
                    agent_activity(since="2026-06-12T09:00:00+00:00",
                                   until="2026-06-12T11:00:00+00:00")
                self.assertEqual(spy.call_count, 1, "25 scrub steps must parse the file once")

                later = dict(row, ts="2026-06-12T10:30:00+00:00", agent="claude")
                path.write_text(json.dumps(row) + "\n" + json.dumps(later) + "\n",
                                encoding="utf-8")
                out = agent_activity(since="2026-06-12T09:00:00+00:00",
                                     until="2026-06-12T11:00:00+00:00")
                self.assertEqual(spy.call_count, 2, "an appended file must re-parse")
        self.assertEqual(out["agents"]["claude"], {"read": 0, "write": 1})


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

    def test_gpu_busy_backpressure_is_warn_not_error(self):
        # GPU-busy back-pressure during REM/NREM: self-healing deferrals the
        # daemon retries — must read as warnings, not errors, even when the
        # daemon logged them at ERROR or the text contains "failed".
        for line in (
            "WARNING:REMDaemon:REM: inference GPU busy — deferring enrichment cycle",
            "WARNING:REMDaemon:REM: pg_id=374 LLM failed — skipping",
            ('ERROR:REMDaemon:LLM returned 503: {"error": "Backend unreachable: '
             'Connection timeout to host http://localhost:5000/v1/chat/completions"}'),
            "ERROR:ConsolidationDaemon:Insight synthesis error for NREM: ReadTimeout:",
            ("ERROR:ConsolidationDaemon:Failed to synthesise insight for 'NREM' — "
             "ledger rows stay open; next sweep retries."),
            # v0.6.1+ pool gate — replaces the nvtop wording on multi-backend stacks
            "WARNING:REMDaemon:REM: LLM pool has no free slot — deferring enrichment cycle",
            ("WARNING:ConsolidationDaemon:NREM: LLM pool has no free slot — "
             "deferring consolidation; will re-check next cycle."),
        ):
            self.assertEqual(classify_gateway_line(line), "line-warn", line)

    def test_real_failures_still_error(self):
        # A genuine crash or unrelated failure must NOT be downgraded.
        self.assertEqual(
            classify_gateway_line(
                "ERROR:ConsolidationDaemon:consolidation run [insight] crashed after 3 attempts"
            ),
            "line-err",
        )
        self.assertEqual(
            classify_gateway_line("ERROR:Coordinator:Failed to apply outbox row 42: duplicate key"),
            "line-err",
        )
        self.assertEqual(
            classify_gateway_line("ERROR:ConsolidationDaemon:insight write failed: disk full"),
            "line-err",
        )


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