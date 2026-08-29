import json
import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock


class ThinOldSnapshotsTests(unittest.TestCase):
    """Retention downsamples rather than resets: the poll history is the one
    thing the monitor holds that the gateway does not."""

    def _store(self, td):
        """Patch BOTH paths. thin_old_snapshots() rewrites the JSONL sidecar,
        so patching only DB_FILE let the suite overwrite the operator's real
        data/telemetry.jsonl."""
        from sm_telemetry_monitor import store
        db = Path(td) / "t.db"
        jsonl = Path(td) / "t.jsonl"
        return store, mock.patch.multiple(
            store, DB_FILE=db, DATA_FILE=jsonl)

    def _seed(self, store, stamps):
        with store._connect() as conn:
            conn.executescript(store._SCHEMA)
            for ts in stamps:
                conn.execute(
                    "INSERT INTO snapshots (collected_at, dream_backlog, rem_backlog, "
                    "facts_consolidated, gateway_status, raw_json) VALUES (?,?,?,?,?,?)",
                    (ts.isoformat(), 0, 0, 0, "ok",
                     json.dumps({"collected_at": ts.isoformat()})),
                )
            conn.commit()

    def test_recent_rows_are_untouched_and_old_ones_go_hourly(self):
        # Anchored to an exact hour: 36 ten-minute samples straddle 6 or 7
        # buckets depending on where "now" falls, which made this clock-flaky.
        now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        recent = [now - timedelta(minutes=10 * i) for i in range(12)]        # ~2h raw
        old = [now - timedelta(days=30) + timedelta(minutes=10 * i) for i in range(36)]  # 6h
        with tempfile.TemporaryDirectory() as td:
            store, patcher = self._store(td)
            with patcher:
                self._seed(store, recent + old)
                removed = store.thin_old_snapshots(retention_days=14)
                with store._connect() as conn:
                    kept = [r[0] for r in conn.execute(
                        "SELECT collected_at FROM snapshots ORDER BY collected_at")]
        cutoff = now - timedelta(days=14)
        kept_dt = [datetime.fromisoformat(k) for k in kept]
        self.assertEqual(len([k for k in kept_dt if k >= cutoff]), len(recent),
                         "rows inside the retention window must not be touched")
        old_kept = [k for k in kept_dt if k < cutoff]
        self.assertEqual(len(old_kept), 6, "6 hours of old samples -> 6 hourly rows")
        self.assertEqual(removed, len(old) - 6)
        self.assertEqual(len({(k.year, k.timetuple().tm_yday, k.hour) for k in old_kept}),
                         len(old_kept), "one row per hour")

    def test_history_is_never_emptied(self):
        now = datetime.now(UTC)
        old = [now - timedelta(days=60) + timedelta(minutes=10 * i) for i in range(6)]
        with tempfile.TemporaryDirectory() as td:
            store, patcher = self._store(td)
            with patcher:
                self._seed(store, old)
                store.thin_old_snapshots(retention_days=14)
                with store._connect() as conn:
                    n = conn.execute("SELECT count(*) FROM snapshots").fetchone()[0]
        self.assertGreaterEqual(n, 1, "thinning must never leave an empty history")

    def test_rows_with_an_unreadable_timestamp_are_kept(self):
        """If we cannot place a row in an hour we cannot call it redundant."""
        now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        old = [now - timedelta(days=30) + timedelta(minutes=10 * i) for i in range(6)]
        with tempfile.TemporaryDirectory() as td:
            store, patcher = self._store(td)
            with patcher:
                self._seed(store, old)
                with store._connect() as conn:
                    conn.execute(
                        "INSERT INTO snapshots (collected_at, dream_backlog, rem_backlog,"
                        " facts_consolidated, gateway_status, raw_json) VALUES (?,?,?,?,?,?)",
                        ("not-a-timestamp", 0, 0, 0, "ok", json.dumps({})))
                    conn.commit()
                store.thin_old_snapshots(retention_days=14)
                with store._connect() as conn:
                    left = [r[0] for r in conn.execute(
                        "SELECT collected_at FROM snapshots")]
        self.assertIn("not-a-timestamp", left)

    def test_disabled_by_zero(self):
        now = datetime.now(UTC)
        old = [now - timedelta(days=60) + timedelta(minutes=10 * i) for i in range(6)]
        with tempfile.TemporaryDirectory() as td:
            store, patcher = self._store(td)
            with patcher:
                self._seed(store, old)
                self.assertEqual(store.thin_old_snapshots(retention_days=0), 0)
                with store._connect() as conn:
                    self.assertEqual(
                        conn.execute("SELECT count(*) FROM snapshots").fetchone()[0], 6)

    def test_thinning_survives_a_restart(self):
        """The JSONL sidecar is imported back whenever it holds more rows than
        the table, so thinning must re-point it or it undoes itself."""
        now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        old = [now - timedelta(days=30) + timedelta(minutes=10 * i) for i in range(36)]
        with tempfile.TemporaryDirectory() as td:
            store, patcher = self._store(td)
            jsonl = Path(td) / "t.jsonl"
            with patcher:
                self._seed(store, old)
                # sidecar mirrors the table, as append_jsonl would leave it
                with store._connect() as conn:
                    raws = [r[0] for r in conn.execute(
                        "SELECT raw_json FROM snapshots ORDER BY collected_at")]
                jsonl.write_text("".join(r + "\n" for r in raws))

                store.thin_old_snapshots(retention_days=14)
                with store._connect() as conn:
                    after_thin = conn.execute(
                        "SELECT count(*) FROM snapshots").fetchone()[0]
                # what init_db() does on the next start
                store.sync_jsonl_to_db()
                with store._connect() as conn:
                    after_restart = conn.execute(
                        "SELECT count(*) FROM snapshots").fetchone()[0]
        self.assertEqual(after_thin, 6)
        self.assertEqual(after_restart, after_thin,
                         "restart re-imported the rows thinning removed")

    def test_is_idempotent(self):
        now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        old = [now - timedelta(days=30) + timedelta(minutes=10 * i) for i in range(36)]
        with tempfile.TemporaryDirectory() as td:
            store, patcher = self._store(td)
            with patcher:
                self._seed(store, old)
                store.thin_old_snapshots(retention_days=14)
                self.assertEqual(store.thin_old_snapshots(retention_days=14), 0,
                                 "a second pass must find nothing left to thin")


class BreakdownNotPersistedTests(unittest.TestCase):
    def test_collector_does_not_store_the_breakdown_blob(self):
        """It was ~88% of every row and nothing read it back. Asserted on the
        produced row, not on the source text."""
        from sm_telemetry_monitor import collector
        payload = {
            "status": "success",
            "telemetry": {
                "technical_docs": 1, "facts_total": 1, "decisions_total": 1,
                "breakdown": {"record_types": [{"key": "fact", "count": 1}]},
            },
        }
        row = collector.flatten_snapshot(payload, datetime.now(UTC), {})
        self.assertIsNotNone(row)
        self.assertNotIn("telemetry_breakdown", row)


if __name__ == "__main__":
    unittest.main()
