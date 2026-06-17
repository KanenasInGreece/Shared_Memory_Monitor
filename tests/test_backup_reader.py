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

    def test_missing_dir_returns_none(self):
        with patch("sm_telemetry_monitor.backup_reader.backup_dir", return_value=Path("/nonexistent-backups")):
            self.assertIsNone(latest_backup_manifest())


if __name__ == "__main__":
    unittest.main()