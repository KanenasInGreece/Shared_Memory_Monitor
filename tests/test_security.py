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