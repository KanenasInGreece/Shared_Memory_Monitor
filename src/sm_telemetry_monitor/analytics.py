"""Display formatting of gateway telemetry fields — no extra data fetches."""

from __future__ import annotations

from datetime import datetime, timedelta

from .config import (
    IGNORED_OUTBOX_IDS,
    NREM_DECISION_CLUSTER_MIN,
    NREM_FACT_CLUSTER_MIN,
    POLL_INTERVAL_S,
    REM_BATCH,
    REM_POLL_S,
)
from .nrem_backlog import estimate_nrem_backlog
from .outbox import apply_outbox_ignore

# Pipeline stages in dream-cycle order (matches framework architecture).
PIPELINE_STAGES = (
    ("technical_docs", "Postgres docs", "All saved artifacts"),
    ("outbox_pending", "Outbox pending", "Awaiting Neo4j write"),
    ("outbox_failed", "Outbox failed", "Sync errors — investigate"),
    ("facts_total", "Neo4j facts", "Facts in knowledge graph"),
    ("facts_rem_pending", "REM queue (facts)", "Awaiting LLM enrichment"),
    ("decisions_rem_pending", "REM queue (decisions)", "Awaiting decision enrichment"),
    ("nrem_backlog", "NREM cycles", f"Clusters that met the density gate (≥{NREM_FACT_CLUSTER_MIN} facts or ≥{NREM_DECISION_CLUSTER_MIN} decisions per domain) and are queued for the next consolidation sweep"),
    ("facts_unconsolidated", "Unconsolidated", f"REM-processed facts not yet folded into a summary — they wait until a cluster meets the gate (≥{NREM_FACT_CLUSTER_MIN}/domain). A pool, not a backlog or pending cycles"),
    ("facts_consolidated", "Consolidated facts", "Merged into entity hubs"),
    ("summaries_total", "Tier-3 summaries", "Community narratives"),
)


def rem_items_per_hour() -> float:
    return REM_BATCH * (3600 / REM_POLL_S)


def _apply_nrem_counts(row: dict, nrem_counts: dict | None) -> dict:
    source = (nrem_counts or {}).get("nrem_backlog_source") or row.get("nrem_backlog_source")
    if source in ("clusters", "telemetry"):
        counts = nrem_counts if nrem_counts else row
        row["nrem_backlog"] = counts.get("nrem_backlog") or 0
        row["nrem_fact_cycles"] = counts.get("nrem_fact_cycles") or 0
        row["nrem_decision_cycles"] = counts.get("nrem_decision_cycles") or 0
        row["nrem_backlog_source"] = source
    else:
        row["nrem_backlog"] = estimate_nrem_backlog(row)
        row["nrem_fact_cycles"] = row["nrem_backlog"]
        row["nrem_decision_cycles"] = 0
        row["nrem_backlog_source"] = "estimate"
    return row


def enrich_row(row: dict, *, pg_counts: dict | None = None, nrem_counts: dict | None = None) -> dict:
    """Add derived pipeline metrics to a snapshot."""
    facts_total = row.get("facts_total") or 0
    facts_rem = row.get("facts_rem_pending") or 0
    facts_uncon = row.get("facts_unconsolidated") or 0
    decisions_rem = row.get("decisions_rem_pending") or 0

    row = dict(row)
    row.setdefault("outbox_pending", 0)
    row = apply_outbox_ignore(row, pg_counts=pg_counts)
    row["facts_consolidated"] = max(0, facts_total - facts_rem - facts_uncon)
    row["rem_backlog"] = facts_rem + decisions_rem
    row = _apply_nrem_counts(row, nrem_counts)
    row["dream_backlog"] = row["rem_backlog"] + row["nrem_backlog"]
    row["health"] = "critical" if (row.get("outbox_failed") or 0) > 0 else (
        "warn" if row["dream_backlog"] > 30 else "ok"
    )
    return row


def enrich_history(rows: list[dict]) -> list[dict]:
    return [enrich_row(row) for row in rows]


def compute_deltas(rows: list[dict]) -> list[dict]:
    enriched = enrich_history(rows)
    deltas: list[dict] = []
    for i in range(1, len(enriched)):
        prev, cur = enriched[i - 1], enriched[i]
        t0 = datetime.fromisoformat(prev["collected_at"])
        t1 = datetime.fromisoformat(cur["collected_at"])
        dt_h = max((t1 - t0).total_seconds() / 3600, 1 / 3600)
        deltas.append({
            "time": cur["collected_at"],
            "dt_hours": round(dt_h, 3),
            "dream_backlog_delta": (prev["dream_backlog"] or 0) - (cur["dream_backlog"] or 0),
            "rem_cleared": (prev["rem_backlog"] or 0) - (cur["rem_backlog"] or 0),
            "nrem_cleared": (prev.get("nrem_backlog") or 0) - (cur.get("nrem_backlog") or 0),
            "summaries_added": (cur["summaries_total"] or 0) - (prev["summaries_total"] or 0),
            "rem_rate_per_h": round(((prev["rem_backlog"] or 0) - (cur["rem_backlog"] or 0)) / dt_h, 2),
            "expected_rem_rate": rem_items_per_hour(),
        })
    return deltas


def rem_drain_signal(samples: list[dict], *, window_s: float) -> str:
    """Is the REM backlog clearing? Client-side stall heuristic over stored samples.

    `samples` are snapshots carrying `collected_at` (ISO) + `rem_backlog`. Returns:
      - "draining"     — backlog fell vs the newest sample at least `window_s`
                         older than the latest (REM is working it down);
      - "flat"         — backlog held or grew across that span (no net drain);
      - "insufficient" — no sample old enough to judge (fresh start / short
                         history). Anchored to the latest sample's own timestamp,
                         so it is robust to the poll-gap lag between snapshots.

    Authoritative stall detection belongs on the gateway (a server-side
    `rem_stalled` field); until then this is the honest interim approximation.
    """
    chrono = sorted(
        (s for s in samples if s.get("collected_at")),
        key=lambda s: s["collected_at"],
    )
    if not chrono:
        return "insufficient"
    latest = chrono[-1]
    latest_b = latest.get("rem_backlog")
    if latest_b is None:
        return "insufficient"
    try:
        cutoff = datetime.fromisoformat(latest["collected_at"]) - timedelta(seconds=window_s)
    except (TypeError, ValueError):
        return "insufficient"
    for s in reversed(chrono[:-1]):
        baseline = s.get("rem_backlog")
        if baseline is None:
            continue
        try:
            ts = datetime.fromisoformat(s["collected_at"])
        except (TypeError, ValueError):
            continue
        if ts <= cutoff:
            return "draining" if latest_b < baseline else "flat"
    return "insufficient"


def burn_down_projection(current_backlog: int, hours_ahead: float = 6) -> list[dict]:
    """Project backlog drain at max REM throughput (batch/120s)."""
    rate = rem_items_per_hour()
    points = []
    for step in range(int(hours_ahead * 6) + 1):  # 10-min steps
        t_h = step / 6
        remaining = max(0, current_backlog - rate * t_h)
        points.append({"hours": round(t_h, 2), "backlog": round(remaining, 1)})
    return points


def pipeline_snapshot(row: dict) -> list[dict]:
    """Ordered funnel values for the current snapshot."""
    if "dream_backlog" not in row:
        row = enrich_row(row)
    keys = [s[0] for s in PIPELINE_STAGES]
    return [
        {"key": key, "label": label, "hint": hint, "value": row.get(key, 0) or 0}
        for key, label, hint in PIPELINE_STAGES
    ]


def story_summary(rows: list[dict]) -> dict:
    """One-line narrative for the dashboard header."""
    if not rows:
        return {
            "headline": "No data yet",
            "detail": "Waiting for first poll.",
            "health": "warn",
            "bottleneck": "none",
            "eta_rem_hours": None,
            "rem_rate_per_hour": round(rem_items_per_hour(), 1),
        }
    latest = enrich_row(rows[-1])
    failed = latest.get("outbox_failed") or 0
    ignored = latest.get("outbox_failed_ignored") or 0
    backlog = latest["dream_backlog"]
    rem = latest["rem_backlog"]
    nrem = latest.get("nrem_backlog") or 0
    uncon_raw = latest.get("facts_unconsolidated") or 0
    nrem_src = latest.get("nrem_backlog_source", "estimate")

    cons_stalled = latest.get("consolidation_stalled")
    cons_fresh = latest.get("consolidation_fresh")
    cons_outcome = latest.get("consolidation_last_outcome")

    if failed:
        headline = f"{failed} outbox failure(s) — pipeline may be stuck"
        detail = "Check gateway logs and neo4j_outbox before trusting backlog metrics."
        if ignored:
            detail += f" ({ignored} known stale failure(s) excluded from this alert.)"
    elif cons_fresh is False:
        headline = "Consolidation signal stale"
        detail = "Cached /health consolidation snapshot is outdated — do not trust stalled."
    elif cons_stalled:
        headline = "Consolidation stalled — eligible backlog not folding"
        detail = (
            f"Last outcome: {cons_outcome or 'unknown'}. "
            "Check gateway journal for CRASHED or deferring lines."
        )
    elif backlog == 0:
        headline = "Dream cycle caught up"
        detail = "No REM or NREM backlog. New saves will re-queue work."
    elif rem >= nrem:
        eta_h = rem / rem_items_per_hour() if rem_items_per_hour() else None
        headline = f"REM-saturated — {rem} items awaiting enrichment"
        detail = (
            f"NREM backlog is {nrem} cycle(s) ({uncon_raw} raw facts). "
            f"At ~{rem_items_per_hour():.0f}/hr max REM rate, ~{eta_h:.1f}h to clear REM."
            if eta_h is not None else
            f"NREM backlog is {nrem} cycle(s) ({uncon_raw} raw facts)."
        )
    else:
        headline = f"NREM-saturated — {nrem} consolidation cycle(s) pending"
        detail = (
            f"REM queue is {rem}. NREM triggers per domain cluster "
            f"(≥{NREM_FACT_CLUSTER_MIN} facts or ≥{NREM_DECISION_CLUSTER_MIN} decisions); "
            f"{uncon_raw} raw unconsolidated facts."
        )
        if nrem_src in ("clusters", "telemetry"):
            fc = latest.get("nrem_fact_cycles") or 0
            dc = latest.get("nrem_decision_cycles") or 0
            if fc or dc:
                detail += f" Clusters: {fc} fact, {dc} decision."

    if len(rows) >= 2:
        first = enrich_row(rows[0])
        cleared = (first["dream_backlog"] or 0) - backlog
        if cleared > 0:
            detail += f" Cleared {cleared} backlog items since monitoring started."

    eta_rem_h = rem / rem_items_per_hour() if rem and rem_items_per_hour() else None
    bottleneck = "rem" if rem >= nrem else ("nrem" if nrem else "none")
    health = latest["health"]
    if cons_stalled and cons_fresh is not False:
        health = "critical"
    elif cons_fresh is False and health == "ok":
        health = "warn"
    return {
        "headline": headline,
        "detail": detail,
        "health": health,
        "bottleneck": bottleneck,
        "eta_rem_hours": round(eta_rem_h, 1) if eta_rem_h is not None else None,
        "rem_rate_per_hour": round(rem_items_per_hour(), 1),
    }


def range_stats(rows: list[dict]) -> dict:
    if not rows:
        return {}
    enriched = enrich_history(rows)
    first, last = enriched[0], enriched[-1]
    backlog_vals = [r["dream_backlog"] for r in enriched]
    return {
        "start_at": first["collected_at"],
        "end_at": last["collected_at"],
        "dream_backlog_start": first["dream_backlog"],
        "dream_backlog_end": last["dream_backlog"],
        "dream_backlog_delta": first["dream_backlog"] - last["dream_backlog"],
        "dream_backlog_min": min(backlog_vals),
        "dream_backlog_max": max(backlog_vals),
        "rem_cleared_total": max(0, first["rem_backlog"] - last["rem_backlog"]),
        "nrem_cleared_total": max(0, (first.get("nrem_backlog") or 0)
                                 - (last.get("nrem_backlog") or 0)),
        "summaries_added_total": max(0, (last.get("summaries_total") or 0)
                                     - (first.get("summaries_total") or 0)),
    }


def cumulative_cleared(rows: list[dict]) -> list[int]:
    """Running total of dream-backlog reduction since range start."""
    enriched = enrich_history(rows)
    if not enriched:
        return []
    baseline = enriched[0]["dream_backlog"] or 0
    return [max(0, baseline - (r["dream_backlog"] or 0)) for r in enriched]


def build_api_payload(
    rows: list[dict],
    *,
    range_spec: str = "all",
    bucket_minutes: int | None = None,
) -> dict:
    enriched = enrich_history(rows)
    latest = enriched[-1] if enriched else {}
    deltas = compute_deltas(enriched)
    stats = range_stats(enriched)
    labels = [r["collected_at"][5:16].replace("T", " ") for r in enriched]

    series = {k: [r.get(k, 0) for r in enriched] for k in (
        "dream_backlog", "rem_backlog", "nrem_backlog", "facts_rem_pending", "facts_unconsolidated",
        "decisions_rem_pending", "facts_consolidated", "summaries_total", "facts_total",
        "outbox_pending", "outbox_applied", "outbox_rem_reviewed", "technical_docs",
    )}
    series["outbox_failed"] = [r.get("outbox_failed", 0) for r in enriched]
    if IGNORED_OUTBOX_IDS:
        series["outbox_failed_ignored"] = [r.get("outbox_failed_ignored", 0) for r in enriched]
    series["cumulative_cleared"] = cumulative_cleared(enriched)

    return {
        "range": range_spec,
        "bucket_minutes": bucket_minutes,
        "samples": len(enriched),
        "labels": labels,
        "timestamps": [r["collected_at"] for r in enriched],
        "series": series,
        "latest": latest,
        "story": story_summary(enriched),
        "pipeline": pipeline_snapshot(latest) if enriched else [],
        "deltas": deltas,
        "stats": stats,
        "projection": burn_down_projection(latest.get("dream_backlog", 0)) if enriched else [],
    }