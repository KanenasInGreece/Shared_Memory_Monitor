"""Telemetry poll cache (SQLite + JSONL) — copies of GET /memory/telemetry responses."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta

from .analytics import enrich_row
from .config import DATA_FILE, DB_FILE
from .env_loader import get

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collected_at TEXT NOT NULL UNIQUE,
    telemetry_ts TEXT,
    technical_docs INTEGER,
    outbox_pending INTEGER DEFAULT 0,
    outbox_applied INTEGER,
    outbox_rem_reviewed INTEGER,
    outbox_failed INTEGER,
    summaries_total INTEGER,
    summaries_superseded INTEGER,
    summaries_insight INTEGER,
    facts_total INTEGER,
    facts_rem_pending INTEGER,
    facts_unconsolidated INTEGER,
    decisions_total INTEGER,
    decisions_rem_pending INTEGER,
    rem_dead_lettered INTEGER,
    rem_failing INTEGER,
    rem_passed_over_total INTEGER,
    rem_starved_pending INTEGER,
    dream_backlog INTEGER,
    rem_backlog INTEGER,
    facts_consolidated INTEGER,
    gateway_status TEXT,
    raw_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_collected ON snapshots(collected_at);
"""

_COLUMNS = (
    "collected_at", "telemetry_ts", "technical_docs", "outbox_pending",
    "outbox_applied", "outbox_rem_reviewed", "outbox_failed",
    "summaries_total", "summaries_superseded", "summaries_insight",
    "facts_total", "facts_rem_pending", "facts_unconsolidated",
    "decisions_total", "decisions_rem_pending",
    "rem_dead_lettered", "rem_failing", "rem_passed_over_total", "rem_starved_pending",
    "dream_backlog", "rem_backlog", "facts_consolidated",
    "gateway_status", "raw_json",
)


def _connect() -> sqlite3.Connection:
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def _jsonl_row_count() -> int:
    if not DATA_FILE.exists():
        return 0
    return sum(1 for line in DATA_FILE.open() if line.strip())


def sync_jsonl_to_db() -> int:
    """Recover samples the sidecar holds and the table does not.

    Bounded to rows NEWER than the newest row already stored. The sidecar's
    purpose is to survive a crash between the append and the insert, which is
    always the most recent sample; letting it re-import anything older would
    let it undo retention, and would race a thinning pass that has committed
    its DELETE but not yet rewritten the mirror.
    """
    if not DATA_FILE.exists():
        return 0
    with _connect() as conn:
        db_count = conn.execute("SELECT count(*) FROM snapshots").fetchone()[0]
        row = conn.execute("SELECT max(collected_at) FROM snapshots").fetchone()
    # Cheap gate first: init_db() runs on every request that reads history, and
    # parsing the whole sidecar there would put file I/O on the hot path.
    if _jsonl_row_count() <= db_count:
        return 0
    watermark = row[0] if row else None
    if watermark is None:
        return migrate_jsonl()
    imported = 0
    with DATA_FILE.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                sample = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (sample.get("collected_at") or "") <= watermark:
                continue
            if insert_snapshot(sample, skip_dedup=True):
                imported += 1
    return imported


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        count = conn.execute("SELECT count(*) FROM snapshots").fetchone()[0]
        if count == 0 and DATA_FILE.exists():
            migrate_jsonl()
        else:
            sync_jsonl_to_db()


def migrate_jsonl() -> int:
    imported = 0
    with DATA_FILE.open() as f:
        for line in f:
            line = line.strip()
            if line:
                if insert_snapshot(json.loads(line), skip_dedup=True):
                    imported += 1
    return imported


def _row_to_dict(row: sqlite3.Row) -> dict:
    data = json.loads(row["raw_json"])
    data.update({
        "id": row["id"],
        "dream_backlog": row["dream_backlog"],
        "rem_backlog": row["rem_backlog"],
        "facts_consolidated": row["facts_consolidated"],
        "gateway_status": row["gateway_status"],
    })
    return data


def _last_snapshot(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT raw_json FROM snapshots ORDER BY collected_at DESC LIMIT 1"
    ).fetchone()
    if not row:
        return None
    return enrich_row(json.loads(row["raw_json"]))


def insert_snapshot(row: dict, *, skip_dedup: bool = False) -> bool:
    """Insert snapshot; returns False if skipped as duplicate."""
    nrem_counts = None
    if row.get("nrem_backlog_source") == "telemetry":
        nrem_counts = {
            "nrem_backlog": row.get("nrem_backlog"),
            "nrem_fact_cycles": row.get("nrem_fact_cycles"),
            "nrem_decision_cycles": row.get("nrem_decision_cycles"),
            "nrem_backlog_source": "telemetry",
        }
    enriched = enrich_row(row, nrem_counts=nrem_counts)
    gateway_status = enriched.get("gateway_status")

    with _connect() as conn:
        if not skip_dedup:
            last = _last_snapshot(conn)
            if last and _is_duplicate(last, enriched):
                return False

        conn.execute(
            f"INSERT OR REPLACE INTO snapshots ({', '.join(_COLUMNS)}) "
            f"VALUES ({', '.join('?' * len(_COLUMNS))})",
            (
                enriched["collected_at"],
                enriched.get("telemetry_ts"),
                enriched.get("technical_docs"),
                enriched.get("outbox_pending", 0),
                enriched.get("outbox_applied"),
                enriched.get("outbox_rem_reviewed"),
                enriched.get("outbox_failed"),
                enriched.get("summaries_total"),
                enriched.get("summaries_superseded"),
                enriched.get("summaries_insight"),
                enriched.get("facts_total"),
                enriched.get("facts_rem_pending"),
                enriched.get("facts_unconsolidated"),
                enriched.get("decisions_total"),
                enriched.get("decisions_rem_pending"),
                enriched.get("rem_dead_lettered"),
                enriched.get("rem_failing"),
                enriched.get("rem_passed_over_total"),
                enriched.get("rem_starved_pending"),
                enriched["dream_backlog"],
                enriched["rem_backlog"],
                enriched["facts_consolidated"],
                gateway_status,
                json.dumps(enriched),
            ),
        )
        conn.commit()
    return True


try:
    RAW_RETENTION_DAYS = int(get("SM_RAW_RETENTION_DAYS", "14") or "14")
except ValueError:
    # A typo in .env must not stop the monitor from starting at all.
    RAW_RETENTION_DAYS = 14
_THINNED_BUCKET_MINUTES = 60


def thin_old_snapshots(*, retention_days: int | None = None) -> int:
    """Keep one snapshot per hour beyond the raw-retention window.

    Downsampling rather than deleting: the poll history is the one thing the
    monitor holds that the gateway does not, so a reset would throw away the
    long view the charts exist to show. Minute-level detail older than two
    weeks is not something anyone scrubs to; the trend is.
    """
    days = RAW_RETENTION_DAYS if retention_days is None else retention_days
    if days <= 0:
        return 0
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    removed = 0
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, collected_at FROM snapshots WHERE collected_at < ? "
            "ORDER BY collected_at ASC",
            (cutoff,),
        ).fetchall()
        keep: dict[str, int] = {}
        undatable: set[int] = set()
        for row in rows:
            try:
                ts = datetime.fromisoformat(row["collected_at"])
            except (TypeError, ValueError):
                # Cannot place it in an hour, so cannot judge it redundant.
                undatable.add(row["id"])
                continue
            if ts.tzinfo is None:
                # timestamp() would read a naive stamp as LOCAL time, so a
                # half-hour-offset zone would straddle the hour boundaries.
                ts = ts.replace(tzinfo=UTC)
            epoch = int(ts.timestamp())
            bucket = str(epoch - (epoch % (_THINNED_BUCKET_MINUTES * 60)))
            keep[bucket] = row["id"]          # last sample in each hour wins
        kept = set(keep.values()) | undatable
        drop = [row["id"] for row in rows if row["id"] not in kept]
        for i in range(0, len(drop), 500):
            chunk = drop[i:i + 500]
            conn.execute(
                f"DELETE FROM snapshots WHERE id IN ({','.join('?' * len(chunk))})",
                chunk,
            )
            removed += len(chunk)
        conn.commit()

    if removed:
        _rewrite_jsonl_mirror()
    return removed


def _rewrite_jsonl_mirror() -> None:
    """Re-point the JSONL sidecar at what the database now holds.

    The sidecar is append-only and is imported back whenever it holds more rows
    than the table (sync_jsonl_to_db). Left alone, it would re-insert every row
    thinning had just removed on the next start — thinning would undo itself,
    and the sidecar would keep growing besides. Rewritten atomically so a crash
    mid-write cannot leave a truncated recovery file.
    """
    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT raw_json FROM snapshots ORDER BY collected_at ASC"
            ).fetchall()
        tmp = DATA_FILE.with_suffix(DATA_FILE.suffix + ".tmp")
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        with tmp.open("w") as fh:
            for row in rows:
                fh.write(row["raw_json"] + "\n")
        tmp.replace(DATA_FILE)
    except (OSError, sqlite3.Error):
        # The database is the store; a stale sidecar is recoverable, so a
        # failure here must not take the poll loop down with it.
        pass


def _is_duplicate(last: dict, cur: dict) -> bool:
    """Skip if polled within 60s with identical pipeline metrics."""
    try:
        t0 = datetime.fromisoformat(last["collected_at"])
        t1 = datetime.fromisoformat(cur["collected_at"])
    except (TypeError, ValueError):
        return False
    if (t1 - t0).total_seconds() > 60:
        return False
    keys = (
        "dream_backlog", "rem_backlog", "nrem_backlog", "facts_unconsolidated",
        "outbox_failed", "summaries_total", "outbox_applied",
    )
    return all((last.get(k) or 0) == (cur.get(k) or 0) for k in keys)


def parse_range(range_spec: str | None) -> datetime | None:
    if not range_spec or range_spec == "all":
        return None
    now = datetime.now(UTC)
    unit = range_spec[-1]
    try:
        n = int(range_spec[:-1])
    except ValueError:
        return None
    # The spec comes off a query string, so an absurd count must read as "no
    # lower bound" rather than raise OverflowError out of the request.
    try:
        if unit == "h":
            return now - timedelta(hours=n)
        if unit == "d":
            return now - timedelta(days=n)
    except (OverflowError, ValueError):
        return None
    return None


def load_history(
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    bucket_minutes: int | None = None,
) -> list[dict]:
    init_db()
    clauses: list[str] = []
    params: list[str] = []
    if since:
        clauses.append("collected_at >= ?")
        params.append(since.isoformat())
    if until:
        clauses.append("collected_at <= ?")
        params.append(until.isoformat())
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM snapshots {where} ORDER BY collected_at ASC"  # nosec B608
    with _connect() as conn:
        rows = [_row_to_dict(r) for r in conn.execute(sql, params)]

    if bucket_minutes and bucket_minutes > 0:
        return _downsample(rows, bucket_minutes)
    return rows


def _downsample(rows: list[dict], bucket_minutes: int) -> list[dict]:
    """Keep the last snapshot in each time bucket (suitable for long ranges)."""
    if not rows:
        return []
    buckets: dict[str, dict] = {}
    for row in rows:
        ts = datetime.fromisoformat(row["collected_at"])
        # Floor to bucket
        epoch = int(ts.timestamp())
        bucket_start = epoch - (epoch % (bucket_minutes * 60))
        key = datetime.fromtimestamp(bucket_start, tz=UTC).isoformat()
        buckets[key] = row
    return [buckets[k] for k in sorted(buckets)]


def meta() -> dict:
    init_db()
    with _connect() as conn:
        count = conn.execute("SELECT count(*) FROM snapshots").fetchone()[0]
        first = conn.execute(
            "SELECT collected_at FROM snapshots ORDER BY collected_at ASC LIMIT 1"
        ).fetchone()
        last = conn.execute(
            "SELECT collected_at FROM snapshots ORDER BY collected_at DESC LIMIT 1"
        ).fetchone()
    return {
        "count": count,
        "first_at": first[0] if first else None,
        "last_at": last[0] if last else None,
    }


def load_all() -> list[dict]:
    return load_history()