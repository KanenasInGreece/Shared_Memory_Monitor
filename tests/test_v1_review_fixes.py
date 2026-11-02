"""Regressions from the v1.0.0 review: layout, outbox counts, env secrets."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sm_telemetry_monitor.env_loader import (
    _FRAMEWORK_KEYS,
    bootstrap_env,
    layout_for,
)
from sm_telemetry_monitor.outbox import apply_outbox_ignore


class LayoutTests(unittest.TestCase):
    def test_source_tree_keeps_data_beside_the_repo(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "src" / "sm_telemetry_monitor").mkdir(parents=True)
            (root / "static").mkdir()
            (root / "pyproject.toml").write_text("name='x'\n", encoding="utf-8")
            pkg = root / "src" / "sm_telemetry_monitor" / "env_loader.py"
            pkg.write_text("", encoding="utf-8")
            layout = layout_for(pkg, home=root / "home", xdg_data_home=None)
        self.assertEqual(layout.monitor_root, root)
        self.assertEqual(layout.data_dir, root / "data")
        self.assertEqual(layout.static_dir, root / "static")

    def test_wheel_writes_under_xdg_and_reads_sibling_static(self):
        with tempfile.TemporaryDirectory() as td:
            site = Path(td) / "site-packages"
            pkg_dir = site / "sm_telemetry_monitor"
            pkg_dir.mkdir(parents=True)
            (site / "static").mkdir()
            (site / "static" / "dashboard.html").write_text("ok", encoding="utf-8")
            pkg = pkg_dir / "env_loader.py"
            pkg.write_text("", encoding="utf-8")
            xdg = Path(td) / "xdg"
            layout = layout_for(pkg, home=Path(td) / "home", xdg_data_home=str(xdg))
        self.assertEqual(layout.static_dir, site / "static")
        self.assertEqual(layout.data_dir, xdg / "sm-telemetry-monitor")
        self.assertNotEqual(layout.data_dir, site)


class OutboxCountTests(unittest.TestCase):
    def test_configured_ids_do_not_shrink_the_aggregate(self):
        row = apply_outbox_ignore({"outbox_failed": 1})
        self.assertEqual(row["outbox_failed"], 1)
        self.assertEqual(row["outbox_failed_ignored"], 0)
        self.assertEqual(row["outbox_failed_raw"], 1)

    def test_per_id_evidence_still_applies(self):
        row = apply_outbox_ignore(
            {"outbox_failed": 3},
            pg_counts={"raw": 3, "actionable": 2, "ignored": 1},
        )
        self.assertEqual(row["outbox_failed"], 2)
        self.assertEqual(row["outbox_failed_ignored"], 1)


class EnvSecretTests(unittest.TestCase):
    def test_database_secrets_are_not_framework_keys(self):
        for key in ("PG_PASSWORD", "PG_CONN", "NEO4J_PASSWORD", "PG_HOST", "PG_USER"):
            self.assertNotIn(key, _FRAMEWORK_KEYS)

    def test_empty_credential_audit_overrides_a_framework_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            framework = root / "framework.env"
            framework.write_text(
                "CREDENTIAL_AUDIT_LOG_PATH=/tmp/from-framework.jsonl\n"
                "PG_PASSWORD=not-loaded\n",
                encoding="utf-8",
            )
            (root / ".env").write_text("CREDENTIAL_AUDIT_LOG_PATH=\n", encoding="utf-8")
            previous_audit = os.environ.get("CREDENTIAL_AUDIT_LOG_PATH")
            previous_pg = os.environ.get("PG_PASSWORD")
            try:
                os.environ.pop("CREDENTIAL_AUDIT_LOG_PATH", None)
                os.environ.pop("PG_PASSWORD", None)
                with mock.patch("sm_telemetry_monitor.env_loader.MONITOR_ROOT", root), \
                        mock.patch(
                            "sm_telemetry_monitor.env_loader._env_file_candidates",
                            return_value=[framework],
                        ):
                    bootstrap_env()
                self.assertEqual(os.environ.get("CREDENTIAL_AUDIT_LOG_PATH"), "")
                self.assertNotIn("PG_PASSWORD", os.environ)
            finally:
                if previous_audit is None:
                    os.environ.pop("CREDENTIAL_AUDIT_LOG_PATH", None)
                else:
                    os.environ["CREDENTIAL_AUDIT_LOG_PATH"] = previous_audit
                if previous_pg is None:
                    os.environ.pop("PG_PASSWORD", None)
                else:
                    os.environ["PG_PASSWORD"] = previous_pg


if __name__ == "__main__":
    unittest.main()
