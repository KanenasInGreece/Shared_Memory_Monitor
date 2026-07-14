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

# telemetry.consolidation[.cycle].last_deferred_reason — why a cycle deferred
# instead of folding. All are benign back-pressure, not failures (ADR-018).
# "gpu_busy" is the pre-pool nvtop gate (single-backend stacks still emit it);
# "pool_busy" replaces it on multi-backend gateways, where REM/NREM defer only
# when no LLM backend in the pool has a free slot.
_DEFER_REASONS = {
    "gpu_busy": "inference GPU busy",
    "pool_busy": "LLM pool busy",
    "backup_in_progress": "backup in progress",
}


def humanize_defer_reason(reason: str | None) -> str | None:
    if not reason:
        return None
    return _DEFER_REASONS.get(str(reason).lower(), str(reason).replace("_", " "))


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


def _graph_health(entity_graph: dict | None, neo4j: dict | None = None) -> dict:
    """Input-side consolidation quality from telemetry.entity_graph.

    ADR-017/018 frame consolidation quality on two axes: the *output* side
    (coverage — facts folded into summaries, see ``_fact_coverage``) and the
    *input* side (entity resolution — how well the graph is connected before
    consolidation runs). A heavily fragmented entity graph (many singletons /
    unmentioned entities) is the "garbage-in" leading indicator: weakly
    connected entities are never pulled into a cluster, so they never
    consolidate regardless of cycle liveness.

    Gateway v0.6.1 corrected the field semantics (the old "no live MENTIONS"
    orphan count overstated ~500x): ``orphan_entities`` is now truly dangling
    (degree 0 — a hygiene defect, expected 0); ``unmentioned_entities`` is the
    honest coverage proxy (has edges — typed REM edges, summary links — but no
    live fact/decision MENTIONS); and the alias layer is live —
    ``alias_edges`` / ``alias_components`` / ``largest_alias_component`` track
    the ADR-017 alias-writer's surface-form grouping. Every field degrades to
    None on missing input (one absent metric never blanks the rest), so
    pre-0.6.1 gateways simply omit the new KPIs.

    **REM-pending caveat (anti-bloat).** ``entity_graph`` counts *every* entity
    node, including those extracted from facts/decisions still awaiting REM — but
    REM is the stage that builds an entity's relationships. Pre-REM entities are
    therefore counted as unmentioned/singletons purely because they haven't been
    processed yet, inflating the fragmentation share. We surface
    ``rem_pending_facts`` / ``rem_pending_decisions`` and flag ``rem_pending`` so
    the operator reads those counts as an *upper bound* on true fragmentation
    until REM catches up — never as a settled quality verdict.
    """
    eg = entity_graph if isinstance(entity_graph, dict) else {}
    census = neo4j if isinstance(neo4j, dict) else {}
    total = eg.get("entities_total")
    orphans = eg.get("orphan_entities")
    unmentioned = eg.get("unmentioned_entities")
    singletons = eg.get("singleton_entities")
    alias_edges = eg.get("alias_edges")
    alias_covered = eg.get("alias_covered_entities")

    hubs = []
    for h in eg.get("top_hubs") or []:
        if isinstance(h, dict) and h.get("name") is not None:
            hubs.append({"name": h.get("name"), "degree": h.get("degree")})

    # Entities carrying at least one live fact/decision MENTIONS — the share
    # that can actually seed a consolidation cluster.
    mentioned = None
    if isinstance(total, int) and isinstance(orphans, int) and isinstance(unmentioned, int):
        mentioned = max(total - orphans - unmentioned, 0)

    rem_pending_facts = census.get("facts_rem_pending")
    rem_pending_decisions = census.get("decisions_rem_pending")
    pending_total = sum(
        v for v in (rem_pending_facts, rem_pending_decisions) if isinstance(v, int)
    )

    present = isinstance(total, int) and total > 0
    return {
        "present": present,
        "entities_total": total,
        "orphan_entities": orphans,
        "orphan_pct": _pct(orphans, total),
        "unmentioned_entities": unmentioned,
        "unmentioned_pct": _pct(unmentioned, total),
        "singleton_entities": singletons,
        "singleton_pct": _pct(singletons, total),
        "mentioned_entities": mentioned,
        "mentioned_pct": _pct(mentioned, total),
        "alias_edges": alias_edges,
        "alias_components": eg.get("alias_components"),
        "largest_alias_component": eg.get("largest_alias_component"),
        "alias_covered_entities": alias_covered,
        "alias_coverage_pct": _pct(alias_covered, total),
        "max_hub_degree": hubs[0]["degree"] if hubs and hubs[0].get("degree") is not None else None,
        "top_hubs": hubs[:5],
        # REM-pending context: unmentioned/singleton counts overstate true
        # fragmentation while records still await entity extraction.
        "rem_pending_facts": rem_pending_facts,
        "rem_pending_decisions": rem_pending_decisions,
        "rem_pending": pending_total > 0,
    }


def _first_write_quality(spine: dict | None, postgres: dict | None = None) -> dict:
    """First-write quality — how complete a record is the moment it is written.

    Sourced from ``telemetry.spine`` (gateway v0.6.2+; the block is omitted with
    no error on older gateways — no new data path, per the read-only sourcing
    principle). This is the *upstream* quality gate for the two consolidation
    axes already shown: a record folds and resolves well downstream only if it
    arrived complete. The framework's own finding — "graph quality begins at the
    first write" — is that weak first writes are not repaired by later graph
    combing, so this reads before Coverage (output) and Graph health (input).

    Three signals, presented left-to-right as one story:

    * **Completeness** — the fill-rate of the high-signal fields the write path
      asks for (decisions: sources cited, alternatives weighed, confidence;
      facts: a citation). Low completeness means records enter thin, which
      bounds how much the later enrichment pass can add.
    * **Schema growth** — metadata keys that records carry but the schema does
      not yet formally capture. A high count is not a fault; it is the schema
      signalling what it wants to become (promotion candidates).
    * **Integrity** — the write path's housekeeping: how many duplicate-entity
      merges it adjudicated (keeping one concept from fragmenting across many
      spellings), and whether any write has been abandoned before reaching the
      graph (``outbox_failed_oldest_age_seconds`` — a growing age means writes
      are being dropped, the one alert here).
    """
    sp = spine if isinstance(spine, dict) else {}
    pg = postgres if isinstance(postgres, dict) else {}
    dec = sp.get("decisions") if isinstance(sp.get("decisions"), dict) else {}
    fac = sp.get("facts") if isinstance(sp.get("facts"), dict) else {}

    emergent: list[dict] = []
    for e in sp.get("emergent_unprojected_fields") or []:
        if isinstance(e, dict) and e.get("key") is not None:
            emergent.append({"key": e.get("key"), "n": e.get("n")})

    alias = sp.get("alias") if isinstance(sp.get("alias"), dict) else {}
    verdict = alias.get("by_verdict") if isinstance(alias.get("by_verdict"), dict) else {}

    dead_letter_age = pg.get("outbox_failed_oldest_age_seconds")

    present = bool(dec) or bool(fac)
    return {
        "present": present,
        "decisions": {
            "total": dec.get("total"),
            "grounded_in_pct": dec.get("grounded_in_pct"),
            "alternatives_pct": dec.get("alternatives_pct"),
            "confidence_pct": dec.get("confidence_pct"),
            "elicited_pct": dec.get("elicited_pct"),
        },
        "facts": {
            "total": fac.get("total"),
            "source_ref_pct": fac.get("source_ref_pct"),
            "elicited_pct": fac.get("elicited_pct"),
        },
        "emergent_fields": emergent[:8],
        "emergent_count": len(emergent),
        "alias_adjudications": alias.get("adjudications"),
        "alias_merged": verdict.get("alias"),
        "alias_distinct": verdict.get("distinct"),
        # Dead-letter age: a write the outbox worker gave up applying to Neo4j.
        # None (the healthy case) means nothing is stuck.
        "dead_letter_age_seconds": dead_letter_age,
        "dead_letter_age_human": humanize_age(dead_letter_age) if dead_letter_age is not None else None,
    }


def _schema_conformance(compliance: dict | None) -> dict:
    """Schema conformance — do graph writes stay inside the agreed vocabulary.

    Sourced from ``telemetry.compliance`` (gateway v0.6.3+). The integrity
    companion to first-write quality: node labels and relationship types are
    meant to be drawn from a fixed ontology, and anything outside it is a write
    the schema did not sanction. We surface the verdict plus the offending
    labels/relationships so the operator can see exactly what drifted, without
    needing graph access. ``predicate_types`` counts the distinct relationship
    kinds in use — context for how richly the graph is wired.
    """
    c = compliance if isinstance(compliance, dict) else {}

    def _named(key: str) -> list[dict]:
        out: list[dict] = []
        for item in c.get(key) or []:
            if isinstance(item, dict) and item.get("name") is not None:
                out.append({"name": item.get("name"), "count": item.get("count")})
        return out

    invalid_labels = _named("invalid_labels")
    invalid_rels = _named("invalid_relationships")
    label_ok = c.get("label_compliance")
    rel_ok = c.get("relationship_compliance")
    predicates = c.get("predicate_distribution")
    present = bool(label_ok or rel_ok or invalid_labels or invalid_rels or predicates)
    return {
        "present": present,
        "label_compliance": label_ok,
        "relationship_compliance": rel_ok,
        "compliant": label_ok == "compliant" and rel_ok == "compliant",
        "invalid_labels": invalid_labels[:8],
        "invalid_relationships": invalid_rels[:8],
        "invalid_label_total": sum(x.get("count") or 0 for x in invalid_labels),
        "invalid_relationship_total": sum(x.get("count") or 0 for x in invalid_rels),
        "predicate_types": len(predicates) if isinstance(predicates, dict) else None,
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
    # deferred is a benign skip (LLM pool/GPU busy, backup drain); per ADR-018
    # the actionable signal is `stalled` (handled above), not a single deferral.
    return "ok"


def _normalize_cycle(key: str, raw: dict | None) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    err = raw.get("last_error")
    # last_error is historical: the gateway keeps the most recent error even
    # after later cycles complete (e.g. OrphanedRun from a daemon restart whose
    # in-flight row was already recovered). Showing it against a healthy cycle
    # reads as a live fault, so surface it only while it is current — a
    # non-completed last outcome or an active failure streak.
    error_current = (
        raw.get("last_outcome") not in ("completed", "deferred")
        or int(raw.get("consecutive_failures") or 0) > 0
    )
    if isinstance(err, dict) and error_current:
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
    defer_reason = raw.get("last_deferred_reason")
    defer_reason_human = humanize_defer_reason(defer_reason)
    # A "deferred" cycle with nothing eligible isn't postponing work — there are
    # no clusters/facts to fold, so present it as idle rather than deferred.
    no_work = not raw.get("eligible_clusters") and not backlog
    if outcome == "deferred" and no_work:
        outcome_display = "idle"
    elif outcome == "deferred" and defer_reason_human:
        # Name the benign back-pressure so the drawer reads "deferred — inference
        # GPU busy" rather than an unexplained "deferred" (ADR-018 / nvtop gate).
        outcome_display = f"deferred — {defer_reason_human}"
    else:
        outcome_display = outcome

    cycle = {
        "key": key,
        "label": _CYCLE_LABELS.get(key, key.replace("_", " ").title()),
        "last_outcome": outcome,
        "last_outcome_display": outcome_display,
        "last_deferred_reason": defer_reason,
        "last_deferred_reason_human": defer_reason_human,
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


def _tile_value(*, stalled: bool, fresh: bool, reachable: bool, last_outcome: str | None,
                defer_reason: str | None = None) -> str:
    if not reachable:
        return "—"
    if fresh is False:
        return "Signal stale"
    if stalled:
        return "Stalled"
    if last_outcome == "deferred":
        reason = humanize_defer_reason(defer_reason)
        return f"Deferred — {reason}" if reason else "Deferred"
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
    entity_graph: dict = {}
    postgres_census: dict = {}
    spine: dict = {}
    compliance: dict = {}
    summaries_by_kind: list = []
    # nvtop inference-busy gate (tri-state busy|idle|unknown); top-level on both
    # /health and /memory/telemetry. "unknown" = nvtop absent / SLOT_AWARE=0 —
    # never coerce to "idle" (no-false-info guarantee).
    inference_busy = health.get("inference_busy") or health_cons.get("inference_busy")

    if isinstance(telemetry_payload, dict) and telemetry_payload.get("status") == "success":
        t = telemetry_payload.get("telemetry") or {}
        telemetry_at = t.get("timestamp")
        if not inference_busy:
            inference_busy = t.get("inference_busy")
        if isinstance(t.get("consolidation"), dict):
            rollup = t["consolidation"]
        if isinstance(t.get("nrem"), dict):
            nrem_density = t["nrem"]
        if isinstance(t.get("neo4j"), dict):
            neo4j_census = t["neo4j"]
        if isinstance(t.get("entity_graph"), dict):
            entity_graph = t["entity_graph"]
        if isinstance(t.get("postgres"), dict):
            postgres_census = t["postgres"]
        if isinstance(t.get("spine"), dict):
            spine = t["spine"]
        if isinstance(t.get("compliance"), dict):
            compliance = t["compliance"]
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
    defer_reason = rollup.get("last_deferred_reason")
    if defer_reason is None:
        # Fall back to whichever cycle actually deferred so the tile can explain
        # an aggregate "deferred" even when the rollup omits the reason.
        for c in cycles:
            if c.get("last_outcome") == "deferred" and c.get("last_deferred_reason"):
                defer_reason = c["last_deferred_reason"]
                break
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
        "inference_busy": inference_busy,
        "last_deferred_reason": defer_reason,
        "last_deferred_reason_human": humanize_defer_reason(defer_reason),
        "tile": {
            "state": tile_state,
            "value": _tile_value(
                stalled=stalled,
                fresh=fresh is not False,
                reachable=reachable,
                last_outcome=last_outcome,
                defer_reason=defer_reason,
            ),
            "stalled": stalled,
            "fresh": fresh,
            "last_outcome": last_outcome,
            "last_deferred_reason": defer_reason,
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
        "first_write_quality": _first_write_quality(spine, postgres_census),
        "schema_conformance": _schema_conformance(compliance),
        "coverage": _fact_coverage(neo4j_census, summaries_by_kind),
        "graph_health": _graph_health(entity_graph, neo4j_census),
        "nrem_density": {
            **nrem_density,
            "note": _NREM_DENSITY_NOTE,
        },
        "error": sanitize_error(health.get("error")) if not reachable else None,
    }


def consolidation_snapshot() -> dict:
    """Live consolidation panel — fetches gateway /health + /memory/telemetry."""
    return consolidation_from_payload(get_health(), get_telemetry())