"""Sole gateway client — all telemetry on screen comes through here.

Reads GET /memory/telemetry, GET /health, GET /pool/status, POST /memory/graph only.
No parallel monitor metrics API; no framework imports; no Postgres/Neo4j.
"""

from __future__ import annotations

import httpx

from .env_loader import bootstrap_env, get
from .sanitize import sanitize_error

bootstrap_env()

# Wire contract with the live gateway (GET /health api_version). Bump only when
# the *deployed* gateway contract changes — not an unreleased framework branch.
# Live gateway as of v0.8.33+ is API v4 (projects registry + sentinel + telemetry
# enhancements). Mismatch only logs a gateway warning; reads still work.
API_VERSION = 4
CLIENT_VERSION_HEADER = "X-SM-Api-Version"

_HTTP: httpx.Client | None = None


def _http() -> httpx.Client:
    global _HTTP
    if _HTTP is None:
        _HTTP = httpx.Client(timeout=15.0)
    return _HTTP


def _coordinator_base() -> str:
    return get("COORDINATOR_URL", "http://localhost:8888") or "http://localhost:8888"


def _request_headers() -> dict[str, str]:
    headers = {CLIENT_VERSION_HEADER: str(API_VERSION)}
    token = (get("AGENT_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _coordinator_unavailable(exc: Exception) -> dict:
    return {
        "status": "error",
        "message": sanitize_error(str(exc)) or "coordinator unreachable",
    }


def _auth_error() -> dict:
    return {
        "status": "error",
        "message": "Coordinator rejected token. Set AGENT_TOKEN in the monitor .env.",
    }


def get_telemetry() -> dict:
    """Fetch GET /memory/telemetry (includes nrem + breakdown)."""
    try:
        r = _http().get(
            f"{_coordinator_base()}/memory/telemetry",
            headers=_request_headers(),
        )
        if r.status_code == 401:
            return _auth_error()
        if r.status_code >= 400:
            return {
                "status": "error",
                "message": sanitize_error(f"coordinator returned HTTP {r.status_code}"),
            }
        return r.json()
    except Exception as exc:
        return _coordinator_unavailable(exc)


def query_graph(cypher: str, params: dict | None = None) -> list | dict:
    """POST /memory/graph with read-only Cypher."""
    try:
        r = _http().post(
            f"{_coordinator_base()}/memory/graph",
            json={"cypher": cypher, "params": params or {}},
            headers=_request_headers(),
            timeout=30.0,
        )
        if r.status_code == 401:
            return _auth_error()
        if r.status_code >= 400:
            return {
                "status": "error",
                "message": sanitize_error(f"coordinator returned HTTP {r.status_code}"),
            }
        result = r.json()
    except Exception as exc:
        return _coordinator_unavailable(exc)

    if isinstance(result, dict):
        return result.get("records", result)
    return result


def get_health() -> dict:
    """GET /health — unauthenticated infrastructure snapshot."""
    try:
        r = _http().get(
            f"{_coordinator_base()}/health",
            headers=_request_headers(),
        )
        if r.status_code == 401:
            return {"status": "unreachable", "error": "Coordinator rejected token"}
        if r.status_code >= 400:
            return {
                "status": "unreachable",
                "error": sanitize_error(f"coordinator returned HTTP {r.status_code}"),
            }
        return r.json()
    except Exception as exc:
        return {"status": "unreachable", "error": sanitize_error(str(exc)) or "coordinator unreachable"}


def get_pool_status() -> dict:
    """GET /pool/status — dream-job free_slots + per-backend serves_all.

    Authenticated on modern gateways (S-10: anonymous body is ``{}``).
    Missing, 401, error, or empty dict → ``{}`` so callers omit the surface
    instead of inventing ``free_slots: 0``.
    """
    try:
        r = _http().get(
            f"{_coordinator_base()}/pool/status",
            headers=_request_headers(),
        )
        if r.status_code >= 400:
            return {}
        payload = r.json()
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}

def patch_raw(raw: dict, t: dict) -> dict:
    if "config" in t:
        raw["config"] = t["config"]
    if "llm" in t and isinstance(t["llm"], dict):
        if "pool" in t["llm"]:
            raw["llm_pool"] = t["llm"]["pool"]
        if "affinity" in t["llm"]:
            raw["llm_affinity"] = t["llm"]["affinity"]
        if "routing" in t["llm"]:
            raw["llm_routing"] = t["llm"]["routing"]
        if "token_usage" in t["llm"]:
            raw["llm_token_usage"] = t["llm"]["token_usage"]
        if "latency" in t["llm"]:
            raw["llm_latency"] = t["llm"]["latency"]
        if "oldest_inflight_age_s" in t["llm"]:
            raw["llm_oldest_inflight_age_s"] = t["llm"]["oldest_inflight_age_s"]
        if "suspect_wedged" in t["llm"]:
            raw["llm_suspect_wedged"] = t["llm"]["suspect_wedged"]
    if "capacity" in t:
        raw["capacity"] = t["capacity"]
    if "gpu_probe" in t:
        raw["gpu_probe"] = t["gpu_probe"]
    if "postgres" in t and isinstance(t["postgres"], dict) and "pgvector" in t["postgres"]:
        raw["pgvector"] = t["postgres"]["pgvector"]
    # Daemon PID enums are a rename WITHIN /health (framework 0.9.74): the new
    # names are rem_daemon_process / nrem_daemon_process; the legacy keys
    # rem_daemon / daemon are dual-emitted this release only and leave at the
    # drop. Backfill the legacy spelling so every downstream reader keeps one
    # name; the new key wins when both are present.
    if "rem_daemon_process" in raw:
        raw["rem_daemon"] = raw["rem_daemon_process"]
    if "nrem_daemon_process" in raw:
        raw["daemon"] = raw["nrem_daemon_process"]
    return raw
