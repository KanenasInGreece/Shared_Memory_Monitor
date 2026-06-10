"""NREM backlog = pending consolidation cycles from telemetry.nrem.

Framework computes (entity, domain) cycle counts server-side; the monitor
reads them via GET /memory/telemetry (decision 258/259).
"""

from __future__ import annotations

import threading
import time

from .bridge import get_telemetry
from .config import NREM_DECISION_CLUSTER_MIN, NREM_FACT_CLUSTER_MIN
from .sanitize import sanitize_error

DEFAULT_DOMAIN = "general"

_CACHE: dict | None = None
_CACHE_AT: float = 0
_CACHE_TTL = 60
_CACHE_LOCK = threading.Lock()


def partition_domain_clusters(
    pg_ids: list[int],
    *,
    domain_map: dict[int, str],
    threshold: int,
) -> int:
    """Count (entity, domain) buckets meeting the density threshold."""
    by_domain: dict[str, list[int]] = {}
    for pid in pg_ids:
        dom = domain_map.get(pid) or DEFAULT_DOMAIN
        by_domain.setdefault(dom, []).append(pid)
    return sum(1 for ids in by_domain.values() if len(ids) >= threshold)


def estimate_nrem_backlog(row: dict) -> int:
    """Fallback when telemetry.nrem is unavailable."""
    fu = row.get("facts_unconsolidated") or 0
    cycles = fu // NREM_FACT_CLUSTER_MIN if fu >= NREM_FACT_CLUSTER_MIN else 0
    return cycles


def nrem_counts_from_telemetry(telemetry: dict) -> dict | None:
    """Parse telemetry.nrem into enrich_row-compatible counts."""
    nrem = telemetry.get("nrem")
    if not isinstance(nrem, dict):
        return None
    if nrem.get("error"):
        return {"error": sanitize_error(str(nrem["error"]))}
    fact = int(nrem.get("fact_cycles") or 0)
    decision = int(nrem.get("decision_cycles") or 0)
    total = nrem.get("total_cycles")
    if total is None:
        total = fact + decision
    return {
        "nrem_backlog": int(total),
        "nrem_fact_cycles": fact,
        "nrem_decision_cycles": decision,
        "nrem_backlog_source": "telemetry",
    }


def compute_nrem_cycles(
    *,
    fact_clusters: list[dict] | None = None,
    decision_pg_ids: list[int] | None = None,
    domain_map: dict[int, str] | None = None,
) -> dict:
    """Pure helper retained for unit tests (mirrors framework partition logic)."""
    fact_clusters = fact_clusters or []
    decision_pg_ids = decision_pg_ids or []
    domain_map = domain_map or {}

    fact_cycles = 0
    for cluster in fact_clusters:
        pg_ids = [int(x) for x in (cluster.get("pg_ids") or []) if x is not None]
        fact_cycles += partition_domain_clusters(
            pg_ids,
            domain_map=domain_map,
            threshold=NREM_FACT_CLUSTER_MIN,
        )

    decision_cycles = partition_domain_clusters(
        decision_pg_ids,
        domain_map=domain_map,
        threshold=NREM_DECISION_CLUSTER_MIN,
    )

    return {
        "nrem_backlog": fact_cycles + decision_cycles,
        "nrem_fact_cycles": fact_cycles,
        "nrem_decision_cycles": decision_cycles,
        "nrem_backlog_source": "clusters",
    }


def fetch_nrem_backlog(*, force: bool = False) -> dict | None:
    """Live NREM cycle count from GET /memory/telemetry."""
    global _CACHE, _CACHE_AT
    now = time.time()
    with _CACHE_LOCK:
        if not force and _CACHE and (now - _CACHE_AT) < _CACHE_TTL:
            return _CACHE

    payload = get_telemetry()
    if payload.get("status") != "success":
        return None

    counts = nrem_counts_from_telemetry(payload["telemetry"])
    if counts is None:
        return None

    with _CACHE_LOCK:
        _CACHE = counts
        _CACHE_AT = now
    return counts