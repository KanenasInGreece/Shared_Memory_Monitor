import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sm_telemetry_monitor.backup_reader import latest_backup_manifest


class BackupReaderTests(unittest.TestCase):
    def test_latest_manifest_picks_newest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            older = root / "sm-backup-20260616-030000.manifest.json"
            newer = root / "sm-backup-20260617-030000.manifest.json"
            older.write_text(json.dumps({
                "name": "sm-backup-20260616-030000",
                "created": "2026-06-16T03:00:00+00:00",
            }))
            newer.write_text(json.dumps({
                "name": "sm-backup-20260617-030000",
                "created": "2026-06-17T03:00:00+00:00",
            }))
            with patch("sm_telemetry_monitor.backup_reader.backup_dir", return_value=root):
                got = latest_backup_manifest()
        self.assertEqual(got["name"], "sm-backup-20260617-030000")
        self.assertEqual(got["at"], "2026-06-17T03:00:00+00:00")
        self.assertIsNone(got["quiesced"])
        self.assertIsNone(got["quiesce_mode"])

    def test_fence_fields_pass_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "sm-backup-20261103-030000.manifest.json"
            path.write_text(json.dumps({
                "name": "sm-backup-20261103-030000",
                "created": "2026-11-03T03:00:00+00:00",
                "quiesced": True,
                "quiesce_mode": " full ",
            }))
            with patch("sm_telemetry_monitor.backup_reader.backup_dir", return_value=root):
                got = latest_backup_manifest()
        self.assertTrue(got["quiesced"])
        self.assertEqual(got["quiesce_mode"], "full")

    def test_failed_set_without_manifest_is_not_latest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            older = root / "sm-backup-20261102-030000.manifest.json"
            older.write_text(json.dumps({
                "name": "sm-backup-20261102-030000",
                "created": "2026-11-02T03:00:00+00:00",
                "quiesced": True,
                "quiesce_mode": "full",
            }))
            (root / "sm-backup-failed-latest.pgdump").write_text("not a manifest")
            (root / "sm-backup-failed-latest.cypher.gz").write_bytes(b"")
            with patch("sm_telemetry_monitor.backup_reader.backup_dir", return_value=root):
                got = latest_backup_manifest()
        self.assertEqual(got["name"], "sm-backup-20261102-030000")
        self.assertEqual(got["quiesce_mode"], "full")

    def test_missing_dir_returns_none(self):
        with patch("sm_telemetry_monitor.backup_reader.backup_dir", return_value=Path("/nonexistent-backups")):
            self.assertIsNone(latest_backup_manifest())


if __name__ == "__main__":
    unittest.main()