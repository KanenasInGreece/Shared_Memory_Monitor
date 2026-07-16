"""Schema drawer — gateway telemetry.breakdown + POST /memory/graph via bridge.py."""

from __future__ import annotations

import threading
import time

from .bridge import get_telemetry, query_graph
from .sanitize import sanitize_error

_CACHE: dict | None = None
_CACHE_AT: float = 0
_CACHE_TTL = 60
_CACHE_LOCK = threading.Lock()


def _records(result, errors: list[str]) -> list[dict]:
    if isinstance(result, dict):
        if result.get("status") == "error":
            msg = result.get("message", "query failed")
            if msg not in errors:
                errors.append(msg)
            return []
        if "records" in result:
            return result["records"] or []
        if "data" in result and isinstance(result["data"], list):
            return result["data"]
        return []
    if isinstance(result, list):
        return result
    return []


def fetch_neo4j_breakdown() -> dict:
    out: dict = {"nodes": [], "relationships": [], "pipelines": [], "error": None}
    errors: list[str] = []

    nodes = _records(query_graph(
        "MATCH (n) UNWIND labels(n) AS label "
        "RETURN label, count(*) AS count ORDER BY count DESC"
    ), errors)
    if nodes:
        out["nodes"] = [{"label": r.get("label"), "count": r.get("count", 0)} for r in nodes]

    rels = _records(query_graph(
        "MATCH ()-[r]->() RETURN type(r) AS type, count(r) AS count ORDER BY count DESC"
    ), errors)
    if rels:
        out["relationships"] = [{"type": r.get("type"), "count": r.get("count", 0)} for r in rels]

    paths = _records(query_graph(
        "MATCH (a)-[r]->(b) "
        "RETURN coalesce(labels(a)[0],'?') AS from_label, type(r) AS rel, "
        "coalesce(labels(b)[0],'?') AS to_label, count(*) AS count "
        "ORDER BY count DESC LIMIT 15"
    ), errors)
    if paths:
        out["pipelines"] = [
            {"from": r.get("from_label"), "rel": r.get("rel"),
             "to": r.get("to_label"), "count": r.get("count", 0)}
            for r in paths
        ]

    facts = _records(query_graph(
        "MATCH (f:Fact) WHERE f.pg_id IS NOT NULL RETURN "
        "count(f) AS total, "
        "count(CASE WHEN coalesce(f.rem_processed,false) THEN 1 END) AS rem_done, "
        "count(CASE WHEN coalesce(f.consolidated,false) THEN 1 END) AS consolidated"
    ), errors)
    if facts:
        out["facts"] = facts[0]

    decisions = _records(query_graph(
        "MATCH (d:Decision) RETURN "
        "count(d) AS total, "
        "count(CASE WHEN coalesce(d.rem_processed,false) THEN 1 END) AS rem_done"
    ), errors)
    if decisions:
        out["decisions"] = decisions[0]

    if errors:
        out["error"] = sanitize_error(errors[0])
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


def fetch_postgres_breakdown() -> dict:
    """Postgres panels from GET /memory/telemetry — no direct DB connection."""
    payload = get_telemetry()
    if payload.get("status") != "success":
        err = payload.get("message") or payload.get("error") or "telemetry poll failed"
        return {
            "record_types": [], "agents": [], "sources": [], "domains": [],
            "summaries": [], "outbox": [],
            "technical_docs": None, "technical_docs_superseded": None,
            "error": sanitize_error(str(err)),
        }
    return postgres_breakdown_from_telemetry(payload["telemetry"])

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

    payload = {
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "neo4j": fetch_neo4j_breakdown(),
        "postgres": fetch_postgres_breakdown(),
    }
    with _CACHE_LOCK:
        if _breakdown_ok(payload):
            _CACHE = payload
            _CACHE_AT = now
    return payload