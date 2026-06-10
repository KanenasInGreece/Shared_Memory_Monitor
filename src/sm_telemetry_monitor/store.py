from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .analytics import enrich_row
from .config import DATA_FILE, DB_FILE

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
    """Import any JSONL samples missing from SQLite (e.g. after a partial write)."""
    if not DATA_FILE.exists():
        return 0
    with _connect() as conn:
        db_count = conn.execute("SELECT count(*) FROM snapshots").fetchone()[0]
    if _jsonl_row_count() <= db_count:
        return 0
    return migrate_jsonl()


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
                enriched["dream_backlog"],
                enriched["rem_backlog"],
                enriched["facts_consolidated"],
                gateway_status,
                json.dumps(enriched),
            ),
        )
        conn.commit()
    return True


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
    now = datetime.now(timezone.utc)
    unit = range_spec[-1]
    try:
        n = int(range_spec[:-1])
    except ValueError:
        return None
    if unit == "h":
        return now - timedelta(hours=n)
    if unit == "d":
        return now - timedelta(days=n)
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
    sql = f"SELECT * FROM snapshots {where} ORDER BY collected_at ASC"
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
        key = datetime.fromtimestamp(bucket_start, tz=timezone.utc).isoformat()
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