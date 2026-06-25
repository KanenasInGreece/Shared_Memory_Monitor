"""Display formatting for ADR-018 consolidation liveness + coverage signals."""

from __future__ import annotations

from datetime import datetime, timezone

from .bridge import get_health, get_telemetry
from .sanitize import sanitize_error

_CYCLE_LABELS = {
    "insight": "Insight",
    "fact_consolidation": "Fact consolidation",
}

_NREM_DENSITY_NOTE = (
    "telemetry.nrem counts density-gate cycles; consolidation.backlog counts "
    "strict-gate eligible clusters — do not conflate"
)


def humanize_age(seconds: int | float | None) -> str:
    if seconds is None:
        return "—"
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return "—"
    if total < 0:
        return "—"
    if total < 60:
        return f"{total}s ago"
    if total < 3600:
        return f"{total // 60}m ago"
    if total < 86400:
        h, m = divmod(total, 3600)
        return f"{h}h {m // 60}m ago" if m else f"{h}h ago"
    d, rem = divmod(total, 86400)
    return f"{d}d {rem // 3600}h ago" if rem else f"{d}d ago"


def _pct(num: int | None, den: int | None) -> int | None:
    if num is None or not den:
        return None
    return round(100 * num / den)


def _fact_coverage(neo4j: dict, summaries: list | None = None) -> dict:
    """Consolidation coverage from the neo4j fact/decision census + summary kinds.

    REM-processed facts = total − awaiting REM. Of those, the ones not yet folded
    into a community summary are 'awaiting' (eligible); the rest are consolidated.
    `summaries` (telemetry.breakdown.summaries) lists produced consolidations by
    kind — the output-side evidence that consolidation has occurred.
    """
    total = neo4j.get("facts_total")
    rem_pending = neo4j.get("facts_rem_pending")
    awaiting = neo4j.get("facts_unconsolidated")

    rem_processed = None
    if isinstance(total, int) and isinstance(rem_pending, int):
        rem_processed = max(total - rem_pending, 0)
    consolidated = None
    if rem_processed is not None and isinstance(awaiting, int):
        consolidated = max(rem_processed - awaiting, 0)

    dec_total = neo4j.get("decisions_total")
    dec_pending = neo4j.get("decisions_rem_pending")
    dec_processed = None
    if isinstance(dec_total, int) and isinstance(dec_pending, int):
        dec_processed = max(dec_total - dec_pending, 0)

    kinds: list[dict] = []
    active_total = superseded_total = 0
    for s in summaries or []:
        if not isinstance(s, dict):
            continue
        active = int(s.get("active") or 0)
        superseded = int(s.get("superseded") or 0)
        kinds.append({"kind": s.get("kind") or "?", "active": active, "superseded": superseded})
        active_total += active
        superseded_total += superseded

    return {
        "facts_total": total,
        "facts_rem_pending": rem_pending,
        "rem_processed": rem_processed,
        "consolidated": consolidated,
        "awaiting": awaiting,
        "coverage_pct": _pct(consolidated, rem_processed),
        "awaiting_pct": _pct(awaiting, rem_processed),
        "decisions_total": dec_total,
        "decisions_rem_pending": dec_pending,
        "decisions_rem_processed": dec_processed,
        "summaries": kinds,
        "summaries_active": active_total,
        "summaries_superseded": superseded_total,
    }


def _cycle_state(cycle: dict) -> str:
    if cycle.get("stalled"):
        return "bad"
    if (cycle.get("consecutive_failures") or 0) > 0:
        return "warn"
    if cycle.get("in_flight"):
        return "ok"
    if cycle.get("last_outcome") == "crashed":
        return "bad"
    # deferred is a benign skip (GPU busy / backup drain); per ADR-018 the
    # actionable signal is `stalled` (handled above), not a single deferral.
    return "ok"


def _normalize_cycle(key: str, raw: dict | None) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    err = raw.get("last_error")
    if isinstance(err, dict):
        last_error = {
            "class": err.get("class"),
            "msg": sanitize_error(str(err.get("msg") or "")) or None,
        }
    else:
        last_error = None

    age = raw.get("last_success_age_seconds")
    backlog = raw.get("backlog")
    if backlog is None:
        backlog = raw.get("eligible_clusters")

    outcome = raw.get("last_outcome")
    # A "deferred" cycle with nothing eligible isn't postponing work — there are
    # no clusters/facts to fold, so present it as idle rather than deferred.
    no_work = not raw.get("eligible_clusters") and not backlog
    outcome_display = "idle" if outcome == "deferred" and no_work else outcome

    cycle = {
        "key": key,
        "label": _CYCLE_LABELS.get(key, key.replace("_", " ").title()),
        "last_outcome": outcome,
        "last_outcome_display": outcome_display,
        "last_success_age_seconds": age,
        "last_success_age_human": humanize_age(age) if age is not None else "—",
        "in_flight": bool(raw.get("in_flight")),
        "consecutive_failures": int(raw.get("consecutive_failures") or 0),
        "backlog": backlog,
        "eligible_clusters": raw.get("eligible_clusters"),
        "eligible_oldest_age_seconds": raw.get("eligible_oldest_age_seconds"),
        "eligible_oldest_age_human": humanize_age(raw.get("eligible_oldest_age_seconds")),
        "stalled": bool(raw.get("stalled")),
        "last_error": last_error,
    }
    cycle["state"] = _cycle_state(cycle)
    return cycle


def _tile_state(*, stalled: bool, fresh: bool, reachable: bool, cycles: list[dict]) -> str:
    if not reachable:
        return "unknown"
    if fresh is False:
        return "warn"
    if stalled:
        return "bad"
    if any(c.get("consecutive_failures", 0) > 0 for c in cycles):
        return "warn"
    if any(c.get("in_flight") for c in cycles):
        return "ok"
    return "ok"


def _tile_value(*, stalled: bool, fresh: bool, reachable: bool, last_outcome: str | None) -> str:
    if not reachable:
        return "—"
    if fresh is False:
        return "Signal stale"
    if stalled:
        return "Stalled"
    if last_outcome == "deferred":
        return "Deferred"
    if last_outcome == "crashed":
        return "Crashed"
    if last_outcome == "completed":
        return "Healthy"
    return last_outcome or "—"


def _tile_caption(
    *,
    fresh: bool,
    last_outcome: str | None,
    age_human: str | None,
    stalled: bool,
) -> str:
    if fresh is False:
        return "cached snapshot stale — do not trust stalled"
    bits = []
    if last_outcome:
        bits.append(f"last {last_outcome}")
    if age_human and age_human != "—":
        bits.append(f"success {age_human}")
    elif last_outcome == "completed":
        bits.append("caught up")
    if stalled:
        bits.append("actionable backlog")
    return " · ".join(bits) if bits else "consolidation signal"


def consolidation_from_payload(
    health: dict,
    telemetry_payload: dict | None,
    *,
    fetched_at: str | None = None,
) -> dict:
    """Build tile + drill-down from /health and GET /memory/telemetry responses."""
    fetched_at = fetched_at or datetime.now(timezone.utc).isoformat()
    reachable = health.get("status") not in ("unreachable", "error")

    health_cons = health.get("consolidation") if isinstance(health.get("consolidation"), dict) else {}
    telemetry = {}
    telemetry_at = None
    nrem_density = {}
    rollup = {}
    neo4j_census = {}
    summaries_by_kind: list = []

    if isinstance(telemetry_payload, dict) and telemetry_payload.get("status") == "success":
        t = telemetry_payload.get("telemetry") or {}
        telemetry_at = t.get("timestamp")
        if isinstance(t.get("consolidation"), dict):
            rollup = t["consolidation"]
        if isinstance(t.get("nrem"), dict):
            nrem_density = t["nrem"]
        if isinstance(t.get("neo4j"), dict):
            neo4j_census = t["neo4j"]
        breakdown = t.get("breakdown")
        if isinstance(breakdown, dict) and isinstance(breakdown.get("summaries"), list):
            summaries_by_kind = breakdown["summaries"]

    cycles = [
        _normalize_cycle("insight", rollup.get("insight")),
        _normalize_cycle("fact_consolidation", rollup.get("fact_consolidation")),
    ]

    stalled = bool(health_cons.get("stalled"))
    fresh = health_cons.get("fresh")
    if fresh is None and reachable:
        fresh = True
    fresh = bool(fresh) if fresh is not None else None

    last_outcome = health_cons.get("last_outcome") or rollup.get("last_outcome")
    age = health_cons.get("last_success_age_seconds")
    if age is None:
        age = rollup.get("last_success_age_seconds")
    if age is None:
        # The top-level rollup can be null even when a cycle has succeeded; fall
        # back to the freshest per-cycle success so we never claim "never" when a
        # fold has actually happened.
        cycle_ages = [
            c["last_success_age_seconds"]
            for c in cycles
            if c.get("last_success_age_seconds") is not None
        ]
        if cycle_ages:
            age = min(cycle_ages)
    # No timestamp anywhere → leave it unset (the UI omits the field) rather than
    # asserting "never"; the Coverage section carries the evidence of past folds.
    age_human = humanize_age(age) if age is not None else None

    tile_state = _tile_state(
        stalled=stalled,
        fresh=fresh is not False,
        reachable=reachable,
        cycles=cycles,
    )

    return {
        "reachable": reachable,
        "fetched_at": fetched_at,
        "telemetry_at": telemetry_at,
        "tile": {
            "state": tile_state,
            "value": _tile_value(
                stalled=stalled,
                fresh=fresh is not False,
                reachable=reachable,
                last_outcome=last_outcome,
            ),
            "stalled": stalled,
            "fresh": fresh,
            "last_outcome": last_outcome,
            "last_success_age_seconds": age,
            "last_success_age_human": age_human,
            "caption": _tile_caption(
                fresh=fresh is not False,
                last_outcome=last_outcome,
                age_human=age_human,
                stalled=stalled,
            ),
        },
        "rollup": {
            "stalled": bool(rollup.get("stalled", stalled)),
            "last_outcome": rollup.get("last_outcome", last_outcome),
            "last_success_age_seconds": rollup.get("last_success_age_seconds", age),
            "stall_threshold_seconds": rollup.get("stall_threshold_seconds"),
        },
        "cycles": cycles,
        "coverage": _fact_coverage(neo4j_census, summaries_by_kind),
        "nrem_density": {
            **nrem_density,
            "note": _NREM_DENSITY_NOTE,
        },
        "error": sanitize_error(health.get("error")) if not reachable else None,
    }


def consolidation_snapshot() -> dict:
    """Live consolidation panel — fetches gateway /health + /memory/telemetry."""
    return consolidation_from_payload(get_health(), get_telemetry())