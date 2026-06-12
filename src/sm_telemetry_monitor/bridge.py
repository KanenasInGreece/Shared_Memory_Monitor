"""Sole gateway client — all telemetry on screen comes through here.

Reads GET /memory/telemetry, GET /health, POST /memory/graph only.
No parallel monitor metrics API; no framework imports; no Postgres/Neo4j.
"""

from __future__ import annotations

import httpx

from .env_loader import bootstrap_env, get
from .sanitize import sanitize_error

bootstrap_env()

API_VERSION = 1
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