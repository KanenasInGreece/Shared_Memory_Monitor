import unittest
from unittest.mock import patch

from sm_telemetry_monitor.env_loader import _parse_env_file
from sm_telemetry_monitor.sanitize import sanitize_error
from sm_telemetry_monitor.server import _safe_static_path


class SecurityTests(unittest.TestCase):
    def test_safe_static_blocks_traversal(self):
        with patch("sm_telemetry_monitor.server.STATIC_DIR") as static_dir:
            static_dir.resolve.return_value = static_dir
            static_dir.__truediv__ = lambda self, other: type("P", (), {
                "resolve": lambda: self,
                "parents": [],
                "__eq__": lambda s, o: False,
            })()
            assert _safe_static_path("/static/../data/telemetry.db") is None
            assert _safe_static_path("/static/foo/../../etc/passwd") is None

    def test_sanitize_strips_connection_strings(self):
        msg = sanitize_error("failed: postgresql://user:sekrit@localhost/db")
        self.assertNotIn("sekrit", msg)
        self.assertIn("postgresql://[redacted]", msg)

    def test_parse_env_strips_quotes(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            env = Path(td) / ".env"
            env.write_text('PG_PASSWORD="quoted"\n')
            parsed = _parse_env_file(env)
            self.assertEqual(parsed["PG_PASSWORD"], "quoted")


if __name__ == "__main__":
    unittest.main()

class SurfacePostureTests(unittest.TestCase):
    """Pin the least-privilege posture so a reintroduction is a failing test,
    not something noticed in a later audit."""

    def test_no_cors_header_is_emitted(self):
        from pathlib import Path
        src = Path("src/sm_telemetry_monitor/server.py").read_text()
        self.assertNotIn('send_header("Access-Control-Allow-Origin"', src)

    def test_only_get_is_implemented(self):
        from sm_telemetry_monitor.server import Handler
        for verb in ("do_POST", "do_PUT", "do_DELETE", "do_PATCH"):
            self.assertFalse(hasattr(Handler, verb), f"{verb} must not exist")

    def test_default_bind_is_loopback(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ):
            os.environ.pop("SERVER_HOST", None)
            import importlib
            from sm_telemetry_monitor import config
            importlib.reload(config)
            self.assertEqual(config.SERVER_HOST, "127.0.0.1")

    def test_host_header_allow_list_rejects_foreign_names(self):
        from sm_telemetry_monitor.server import Handler, _ALLOWED_HOSTS
        self.assertIn("127.0.0.1", _ALLOWED_HOSTS)
        self.assertIn("localhost", _ALLOWED_HOSTS)

        class _Probe:
            def __init__(self, host):
                self.headers = {"Host": host}
        for allowed in ("127.0.0.1:8765", "localhost:8765", "127.0.0.1"):
            self.assertTrue(Handler._host_allowed(_Probe(allowed)), allowed)
        for denied in ("evil.example.com", "attacker.io:8765", "10.0.0.5:8765"):
            self.assertFalse(Handler._host_allowed(_Probe(denied)), denied)

    def test_removed_agent_activity_route_is_not_served(self):
        from pathlib import Path
        src = Path("src/sm_telemetry_monitor/server.py").read_text()
        self.assertNotIn("/api/diagram/agent-activity", src)


class ReadRoleProbeTests(unittest.TestCase):
    """The probe's verdict must not accuse a correctly-denied token."""

    def _verdict(self, telemetry_code, write_code):
        from unittest import mock
        import httpx
        from sm_telemetry_monitor import doctor

        class _Resp:
            def __init__(self, code): self.status_code = code

        class _Client:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def get(self, *a, **k): return _Resp(telemetry_code)
            def post(self, *a, **k): return _Resp(write_code)

        with mock.patch.object(httpx, "Client", lambda *a, **k: _Client()), \
             mock.patch.object(doctor, "get", lambda k, d=None: "tok" if k == "AGENT_TOKEN" else (d or "http://x")):
            return doctor._check_read_role()

    def test_denied_write_is_clean(self):
        for code in (401, 403):
            v = self._verdict(200, code)
            self.assertTrue(v["ok"], code)
            self.assertIsNone(v["error"], f"a denied write must raise no finding (HTTP {code})")

    def test_body_validation_reads_as_over_privileged(self):
        v = self._verdict(200, 400)
        self.assertFalse(v["ok"])
        self.assertIn("over-privileged", v["error"])

    def test_server_error_is_inconclusive_not_an_accusation(self):
        for code in (404, 500, 502):
            v = self._verdict(200, code)
            self.assertIn("inconclusive", v["error"], code)
            self.assertNotIn("over-privileged", v["error"], code)
