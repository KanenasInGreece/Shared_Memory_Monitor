"""Display formatting of GET /health JSON — sole source is bridge.get_health()."""

from __future__ import annotations

from datetime import datetime, timezone

from .bridge import get_health
from .sanitize import sanitize_error
from .summary import live_summary

# /health field mapping — "daemon" is the NREM consolidation process in the framework.
_INFRA_COMPONENTS = (
    ("gateway", "status", "Gateway", "service"),
    ("embedder", "embedder", "Embedder", "service"),
    ("reranker", "reranker", "Reranker", "service"),
    ("llm", "llm", "LLM", "service"),
    ("nrem_daemon", "daemon", "NREM", "daemon"),
    ("rem_daemon", "rem_daemon", "REM", "daemon"),
)

_OK_VALUES = frozenset({"ok", "running", "healthy"})
_WARN_VALUES = frozenset({"degraded", "warn", "warning"})
_STOPPED_VALUES = frozenset({"stopped", "down", "dead", "inactive", "failed"})


def _state(value, *, treat_missing_as: str = "unknown") -> str:
    if value is None or value == "":
        return treat_missing_as
    token = str(value).lower()
    if token in _OK_VALUES:
        return "ok"
    if token in _WARN_VALUES:
        return "warn"
    if token in _STOPPED_VALUES:
        return "bad"
    return "bad"


def _worst(*states: str) -> str:
    order = {"bad": 3, "warn": 2, "unknown": 1, "ok": 0}
    return max(states, key=lambda s: order.get(s, 0))


def _queue_state(count: int | None, *, warn_at: int = 1, hot_at: int = 10) -> tuple[str, str]:
    if count is None:
        return "unknown", "no backlog data"
    if count == 0:
        return "ok", "queue idle"
    if count >= hot_at:
        return "warn", f"{count} in backlog"
    if count >= warn_at:
        return "warn", f"{count} in backlog"
    return "ok", f"{count} in backlog"


def _telemetry_latest() -> dict:
    try:
        return live_summary().get("latest") or {}
    except Exception:
        return {}


def _process_display(key: str, raw_value) -> str:
    if raw_value is None or raw_value == "":
        return "unknown"
    token = str(raw_value).lower()
    if token in _OK_VALUES:
        return "up"
    if token in _STOPPED_VALUES:
        return "down"
    if token in _WARN_VALUES:
        return "degraded"
    return str(raw_value)


def _process_part(key: str, raw_value, kind: str) -> dict:
    if key in ("nrem_daemon", "rem_daemon"):
        caption = "daemon process"
    elif key == "gateway":
        caption = "API process"
    else:
        caption = "service process"

    return {
        "value": _process_display(key, raw_value),
        "state": _state(raw_value),
        "caption": caption,
    }


def _workload_part(key: str, raw: dict, t: dict) -> dict:
    llm_ok = _state(raw.get("llm")) == "ok"
    rem_q = t.get("rem_backlog")
    nrem_q = t.get("nrem_backlog")
    outbox_actionable = t.get("outbox_failed")
    outbox_pending = t.get("outbox_pending") or 0

    if key == "gateway":
        if outbox_actionable and outbox_actionable > 0:
            st, val = "bad", f"{outbox_actionable} outbox failed"
        elif outbox_pending > 0:
            st, val = "warn", f"{outbox_pending} outbox pending"
        else:
            st, val = "ok", "outbox synced"
        return {"value": val, "state": st, "caption": "pipeline"}

    if key == "embedder":
        # Save/search path — no per-request queue in telemetry; workload is informational.
        st = _state(raw.get("embedder"))
        if st == "ok":
            val = "standby"
        elif st == "warn":
            val = "degraded"
        else:
            val = "unavailable"
        return {"value": val, "state": st, "caption": "inference path"}

    if key == "reranker":
        st = _state(raw.get("reranker"))
        if st == "ok":
            val = "standby"
        elif st == "warn":
            val = "degraded"
        else:
            val = "unavailable"
        return {"value": val, "state": st, "caption": "inference path"}

    if key == "llm":
        st = _state(raw.get("llm"))
        if st != "ok":
            return {"value": "unavailable", "state": "bad", "caption": "dream cycle blocked"}
        backlog = (rem_q or 0) + (nrem_q or 0)
        if backlog > 0:
            return {"value": "busy", "state": "ok", "caption": f"dream cycle ({backlog} backlog)"}
        return {"value": "idle", "state": "ok", "caption": "dream cycle load"}

    if key == "rem_daemon":
        proc = _state(raw.get("rem_daemon"))
        if proc != "ok":
            return {"value": "—", "state": "bad", "caption": "REM backlog"}
        if not llm_ok:
            return {"value": "blocked (LLM down)", "state": "bad", "caption": "REM backlog"}
        st, val = _queue_state(rem_q, warn_at=1, hot_at=10)
        return {"value": val, "state": st, "caption": "REM backlog"}

    if key == "nrem_daemon":
        proc = _state(raw.get("daemon"))
        if proc != "ok":
            return {"value": "—", "state": "bad", "caption": "NREM backlog"}
        if not llm_ok:
            return {"value": "blocked (LLM down)", "state": "bad", "caption": "NREM backlog"}
        st, val = _queue_state(nrem_q, warn_at=1, hot_at=10)
        return {"value": val, "state": st, "caption": "NREM backlog"}

    return {"value": "—", "state": "unknown", "caption": "workload"}


def _build_component(key: str, field: str, label: str, kind: str, raw: dict, t: dict) -> dict:
    process = _process_part(key, raw.get(field), kind)
    workload = _workload_part(key, raw, t)
    return {
        "key": key,
        "label": label,
        "kind": kind,
        "process": process,
        "workload": workload,
        "state": _worst(process["state"], workload["state"]),
    }


def _status_summary(components: list[dict], status: str) -> str:
    if status == "ok":
        return "all processes up"
    bits: list[str] = []
    for c in components:
        proc = c.get("process") or {}
        load = c.get("workload") or {}
        label = c.get("label") or c.get("key") or "?"
        if proc.get("state") == "bad":
            bits.append(f"{label} down")
        elif load.get("state") == "bad":
            bits.append(f"{label} {load.get('value')}")
        elif load.get("state") == "warn" and load.get("value") not in ("queue idle", "idle", "standby", "outbox synced"):
            val = load.get("value") or ""
            m = val.split()[0] if val.endswith("backlog") else val
            bits.append(f"{label} {m}")
    return " · ".join(bits[:3]) if bits else status


def _overall_state(components: list[dict], *, reachable: bool) -> str:
    if not reachable:
        return "critical"
    states = [c["state"] for c in components]
    if "bad" in states:
        return "critical"
    if "warn" in states or "unknown" in states:
        return "warn"
    return "ok"


def system_health_snapshot() -> dict:
    """Live infrastructure (/health) plus workload context from latest telemetry."""
    fetched_at = datetime.now(timezone.utc).isoformat()
    raw = get_health()
    telemetry = _telemetry_latest()
    telemetry_at = telemetry.get("collected_at")

    if raw.get("status") == "unreachable":
        return {
            "status": "critical",
            "reachable": False,
            "fetched_at": fetched_at,
            "telemetry_at": telemetry_at,
            "version": None,
            "components": [],
            "error": sanitize_error(raw.get("error")) or "gateway unreachable",
        }

    components = [
        _build_component(key, field, label, kind, raw, telemetry)
        for key, field, label, kind in _INFRA_COMPONENTS
    ]
    status = _overall_state(components, reachable=True)

    return {
        "status": status,
        "summary": _status_summary(components, status),
        "reachable": True,
        "fetched_at": fetched_at,
        "telemetry_at": telemetry_at,
        "version": raw.get("version"),
        "api_version": raw.get("api_version"),
        "components": components,
        "error": sanitize_error(raw.get("error")) or None,
    }