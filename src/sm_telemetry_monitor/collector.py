"""Poll loop — fetches gateway telemetry via bridge.py and appends to the poll cache."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from .bridge import get_health, get_telemetry
from .config import DATA_FILE
from .nrem_backlog import nrem_counts_from_telemetry
from .sanitize import sanitize_error
from .store import init_db, insert_snapshot, load_all


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def load_history() -> list[dict]:
    init_db()
    return load_all()


def flatten_snapshot(payload: dict, collected_at: datetime, health: dict) -> dict | None:
    if payload.get("status") != "success":
        return None
    t = payload["telemetry"]
    pg = t.get("postgres", {})
    nj = t.get("neo4j", {})
    cs = pg.get("community_summaries", {})
    ob = pg.get("outbox", {})
    row = {
        "collected_at": collected_at.isoformat(),
        "telemetry_ts": t.get("timestamp"),
        "technical_docs": pg.get("technical_docs"),
        "outbox_pending": ob.get("pending", 0),
        "outbox_applied": ob.get("applied"),
        "outbox_rem_reviewed": ob.get("rem_reviewed"),
        "outbox_failed": ob.get("failed"),
        "summaries_total": cs.get("total"),
        "summaries_superseded": cs.get("superseded"),
        "summaries_insight": cs.get("insight"),
        "facts_total": nj.get("facts_total"),
        "facts_rem_pending": nj.get("facts_rem_pending"),
        "facts_unconsolidated": nj.get("facts_unconsolidated"),
        "decisions_total": nj.get("decisions_total"),
        "decisions_rem_pending": nj.get("decisions_rem_pending"),
        "gateway_status": health.get("status"),
        "gateway_version": health.get("version"),
        "embedder": health.get("embedder"),
        "reranker": health.get("reranker"),
        "llm": health.get("llm"),
        "rem_daemon": health.get("rem_daemon"),
        "daemon": health.get("daemon"),
    }
    nrem = nrem_counts_from_telemetry(t)
    if nrem and nrem.get("nrem_backlog_source") == "telemetry":
        row.update(nrem)
    bd = t.get("breakdown")
    if isinstance(bd, dict) and not bd.get("error"):
        row["telemetry_breakdown"] = bd
    cons_t = t.get("consolidation")
    health_cons = health.get("consolidation") if isinstance(health.get("consolidation"), dict) else {}
    if isinstance(cons_t, dict):
        row["consolidation_stalled"] = bool(health_cons.get("stalled", cons_t.get("stalled")))
        row["consolidation_fresh"] = health_cons.get("fresh")
        row["consolidation_last_outcome"] = health_cons.get("last_outcome") or cons_t.get("last_outcome")
        insight = cons_t.get("insight") if isinstance(cons_t.get("insight"), dict) else {}
        fact = cons_t.get("fact_consolidation") if isinstance(cons_t.get("fact_consolidation"), dict) else {}
        row["consolidation_insight_backlog"] = insight.get("backlog", insight.get("eligible_clusters"))
        row["consolidation_fact_backlog"] = fact.get("backlog", fact.get("eligible_clusters"))
        row["consolidation_insight_failures"] = insight.get("consecutive_failures")
        row["consolidation_fact_failures"] = fact.get("consecutive_failures")
    return row


def append_jsonl(row: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with DATA_FILE.open("a") as f:
        f.write(json.dumps(row) + "\n")


def poll_once() -> dict | None:
    collected_at = utc_now()
    health = get_health()
    payload = get_telemetry()
    row = flatten_snapshot(payload, collected_at, health)
    if row is None:
        status = payload.get("status", "error")
        msg = sanitize_error(payload.get("message") or payload.get("error") or "")
        print(f"[{collected_at.isoformat()}] telemetry error: status={status} {msg}".strip())
        return None

    if insert_snapshot(row):
        append_jsonl(row)
        print(f"[{collected_at.isoformat()}] saved sample #{len(load_history())}")
    else:
        print(f"[{collected_at.isoformat()}] skipped duplicate sample")
    return row