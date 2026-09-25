"""Schema drawer — everything from telemetry.compliance + telemetry.neo4j; the
Postgres half from telemetry.breakdown. One GET /memory/telemetry call, no POST."""

from __future__ import annotations

import threading
import time

from .bridge import get_telemetry
from .sanitize import sanitize_error

_CACHE: dict | None = None
_CACHE_AT: float = 0
_CACHE_TTL = 60
_CACHE_LOCK = threading.Lock()


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def fetch_neo4j_breakdown(t: dict | None) -> dict:
    """Map one telemetry payload into the schema drawer graph shape (fact:2771, the
    1.0.7 graph-shape note); the caller's single GET feeds this and the Postgres half.

    ``pipelines_as_of`` is set only when the gateway sent ``top_paths`` at all. Its
    ABSENCE is how dashboard.html tells a pre-1.0.7 gateway from "computing" (null)
    and "no paths" (set), so never default it.
    """
    out: dict = {
        "nodes": [], "relationships": [], "pipelines": [],
        "pipelines_error": None, "facts": None, "decisions": None, "error": None,
    }
    if not isinstance(t, dict):
        return out

    compliance = t.get("compliance")
    compliance = compliance if isinstance(compliance, dict) else {}

    label_dist = compliance.get("label_distribution")
    if isinstance(label_dist, dict):
        out["nodes"] = sorted(
            ({"label": k, "count": v} for k, v in label_dist.items() if _is_count(v)),
            key=lambda r: r["count"], reverse=True,
        )

    pred_dist = compliance.get("predicate_distribution")
    if isinstance(pred_dist, dict):
        out["relationships"] = [
            {"type": k, "count": v} for k, v in pred_dist.items() if _is_count(v)
        ]

    if "top_paths" in compliance:
        raw_paths = compliance.get("top_paths")
        out["pipelines"] = [
            {"from": p.get("from"), "rel": p.get("rel"), "to": p.get("to"),
             "count": p.get("count")}
            for p in raw_paths if isinstance(p, dict)
        ] if isinstance(raw_paths, list) else []
        out["pipelines_as_of"] = compliance.get("top_paths_as_of")

    if "top_paths_error" in compliance:
        out["pipelines_error"] = sanitize_error(str(compliance["top_paths_error"]))

    nj = t.get("neo4j")
    if isinstance(nj, dict) and nj:
        # Verbatim passthrough: no monitor-side arithmetic. Never reconcile with
        # label_distribution; the two Fact counts differ by definition.
        out["facts"] = {
            "total": nj.get("facts_total"),
            "rem_pending": nj.get("facts_rem_pending"),
            "unconsolidated": nj.get("facts_unconsolidated"),
        }
        out["decisions"] = {
            "total": nj.get("decisions_total"),
            "rem_pending": nj.get("decisions_rem_pending"),
        }

    return out


def postgres_breakdown_from_telemetry(telemetry: dict) -> dict:
    """Map telemetry.breakdown + postgres.outbox into the schema drawer shape."""
    out: dict = {
        "record_types": [], "agents": [], "sources": [], "domains": [],
        "summaries": [], "outbox": [],
        "technical_docs": None, "technical_docs_superseded": None,
        "error": None,
    }
    bd = telemetry.get("breakdown")
    if isinstance(bd, dict) and bd.get("error"):
        out["error"] = sanitize_error(str(bd["error"]))
        return out
    if not isinstance(bd, dict):
        out["error"] = "telemetry.breakdown not available"
        return out

    out["record_types"] = bd.get("record_types") or []
    out["agents"] = bd.get("agents") or []
    out["sources"] = bd.get("sources") or []
    out["domains"] = bd.get("domains") or []
    out["summaries"] = bd.get("summaries") or []

    pg = telemetry.get("postgres") if isinstance(telemetry.get("postgres"), dict) else {}
    out["technical_docs"] = pg.get("technical_docs")
    out["technical_docs_superseded"] = pg.get("technical_docs_superseded")
    ob = pg.get("outbox") or {}
    if isinstance(ob, dict):
        out["outbox"] = [{"key": k, "count": v} for k, v in ob.items()]
    return out


def _error_breakdowns(err: object) -> tuple[dict, dict]:
    msg = sanitize_error(str(err))
    neo4j = {
        "nodes": [], "relationships": [], "pipelines": [],
        "pipelines_error": None, "facts": None, "decisions": None,
        "error": msg,
    }
    postgres = {
        "record_types": [], "agents": [], "sources": [], "domains": [],
        "summaries": [], "outbox": [],
        "technical_docs": None, "technical_docs_superseded": None,
        "error": msg,
    }
    return neo4j, postgres


def _breakdown_ok(payload: dict) -> bool:
    nj = payload.get("neo4j") or {}
    pg = payload.get("postgres") or {}
    if nj.get("error") or pg.get("error"):
        return False
    return bool(nj.get("nodes") or nj.get("relationships") or pg.get("record_types"))


def fetch_breakdown(*, force: bool = False) -> dict:
    global _CACHE, _CACHE_AT
    now = time.time()
    with _CACHE_LOCK:
        if not force and _CACHE and (now - _CACHE_AT) < _CACHE_TTL:
            return _CACHE

    # One GET /memory/telemetry shared by both halves — the graph half used to
    # cost five more POST /memory/graph calls on top of this.
    payload = get_telemetry()
    t = payload.get("telemetry") if isinstance(payload, dict) else None
    if not isinstance(payload, dict) or payload.get("status") != "success" or not isinstance(t, dict):
        if isinstance(payload, dict):
            err = payload.get("message") or payload.get("error") or "telemetry poll failed"
        else:
            err = "telemetry poll failed"
        neo4j, postgres = _error_breakdowns(err)
    else:
        neo4j = fetch_neo4j_breakdown(t)
        postgres = postgres_breakdown_from_telemetry(t)

    out_payload = {
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "neo4j": neo4j,
        "postgres": postgres,
    }
    with _CACHE_LOCK:
        if _breakdown_ok(out_payload):
            _CACHE = out_payload
            _CACHE_AT = now
    return out_payload
