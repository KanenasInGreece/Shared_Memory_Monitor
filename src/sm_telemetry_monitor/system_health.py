"""Display formatting of GET /health JSON — sole source is bridge.get_health()."""

from __future__ import annotations

from datetime import datetime, timezone

from .backup_reader import latest_backup_manifest
from .bridge import get_health, get_telemetry
from .consolidation import consolidation_from_payload
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


def _inference_busy_state(raw: dict) -> str:
    """nvtop GPU-busy gate, tri-state: 'busy' | 'idle' | 'unknown'.

    Top-level on /health (and /memory/telemetry). 'unknown' means nvtop is
    absent or SLOT_AWARE=0 — it is NEVER coerced to 'idle' (the gateway's
    no-false-info guarantee), so the tile shows "load unknown", not "idle".
    """
    token = str(raw.get("inference_busy") or "").lower()
    if token in ("busy", "idle", "unknown"):
        return token
    return "unknown"


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


def _workload_part(key: str, raw: dict, t: dict, *, nrem_stalled: bool = False,
                   llm_busy: bool = False, inference_busy: str = "unknown") -> dict:
    # nvtop confirming the GPU is inferring means the LLM is serving, even if the
    # :5000 reachability probe momentarily timed out under load — so the REM/NREM
    # gates must not call it "blocked (LLM down)" while it is plainly running.
    llm_ok = _state(raw.get("llm")) == "ok" or inference_busy == "busy"
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
        # Two independent facts: `llm` is :5000 reachability; `inference_busy` is
        # the nvtop GPU-busy gate REM/NREM defer on. Read load from nvtop first —
        # it sees a user chatting directly with :5000 (bypassing the gateway),
        # which no daemon ledger or cycle-in-flight signal can.
        if st != "ok":
            # Probe says unreachable, but nvtop says the GPU is actively inferring:
            # that is back-pressure (probe saturated under load), NOT an outage —
            # so warn, never the hard "bad" that would flip the deck to critical
            # while the LLM is plainly running.
            if inference_busy == "busy":
                return {"value": "busy", "state": "warn",
                        "caption": "GPU busy · reachability probe saturated"}
            return {"value": "unavailable", "state": "bad", "caption": "dream cycle blocked"}
        if inference_busy == "busy":
            return {"value": "busy", "state": "ok", "caption": "inference in flight · GPU busy"}
        if inference_busy == "idle":
            return {"value": "idle", "state": "ok", "caption": "reachable · GPU idle"}
        # inference_busy == "unknown": nvtop absent / SLOT_AWARE=0 — fall back to a
        # dream cycle in flight (the only busy signal we can still trust), and
        # never assert "idle" we cannot observe.
        if llm_busy:
            return {"value": "busy", "state": "ok", "caption": "dream-cycle inference in flight"}
        return {"value": "ready", "state": "ok", "caption": "reachable · load unknown"}

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
        # A non-zero NREM backlog is normal: clusters wait for the density gate
        # and fold on the next sweep. The actionable signal is consolidation
        # stall (ADR-018), not the raw count — so only warn when stalled.
        n = nrem_q or 0
        if n <= 0:
            return {"value": "queue idle", "state": "ok", "caption": "NREM backlog"}
        if nrem_stalled:
            return {"value": f"{n} stalled", "state": "warn", "caption": "NREM backlog"}
        return {"value": f"{n} queued", "state": "ok", "caption": "NREM backlog"}

    return {"value": "—", "state": "unknown", "caption": "workload"}


def _build_component(key: str, field: str, label: str, kind: str, raw: dict, t: dict,
                     *, nrem_stalled: bool = False, llm_busy: bool = False,
                     inference_busy: str = "unknown") -> dict:
    process = _process_part(key, raw.get(field), kind)
    workload = _workload_part(key, raw, t, nrem_stalled=nrem_stalled, llm_busy=llm_busy,
                              inference_busy=inference_busy)
    if key == "llm" and process["state"] == "bad" and inference_busy == "busy":
        # The reachability probe failed, but nvtop confirms the GPU is inferring.
        # Don't report the LLM "down" (→ deck critical) while it is demonstrably
        # running — degrade to a warn the deck can absorb without false alarm.
        process = {
            "value": "busy",
            "state": "warn",
            "caption": "GPU busy · probe saturated",
        }
    return {
        "key": key,
        "label": label,
        "kind": kind,
        "process": process,
        "workload": workload,
        "state": _worst(process["state"], workload["state"]),
    }


def _status_summary(
    components: list[dict],
    status: str,
    *,
    backup: dict | None = None,
    consolidation: dict | None = None,
) -> str:
    if backup and backup.get("in_progress"):
        return "backup underway"
    tile = (consolidation or {}).get("tile") or {}
    if tile.get("fresh") is False:
        return "consolidation signal stale"
    if tile.get("stalled"):
        return "consolidation stalled"
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


def _backup_in_progress(raw: dict) -> bool | None:
    value = raw.get("backup_in_progress")
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    token = str(value).lower()
    if token in {"true", "1", "yes", "running", "in_progress", "active"}:
        return True
    if token in {"false", "0", "no", "idle", "none"}:
        return False
    return None


def _backup_timestamp_from_health(raw: dict) -> str | None:
    for key in ("last_backup_at", "last_backup", "backup_last_at"):
        value = raw.get(key)
        if value is None or value == "":
            continue
        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
            except (OSError, OverflowError, ValueError):
                continue
        text = str(value).strip()
        try:
            if text.endswith("Z"):
                dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            else:
                dt = datetime.fromisoformat(text)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    return None


def _resolve_last_backup(raw: dict, *, reachable: bool) -> dict:
    manifest = latest_backup_manifest()
    health_at = _backup_timestamp_from_health(raw) if reachable else None
    if health_at:
        return {"last_at": health_at, "last_name": None, "last_source": "health"}
    if manifest:
        return {
            "last_at": manifest["at"],
            "last_name": manifest.get("name"),
            "last_source": "manifest",
        }
    return {"last_at": None, "last_name": None, "last_source": None}


def _backup_part(raw: dict, *, reachable: bool, last: dict | None = None) -> dict:
    last = last or _resolve_last_backup(raw, reachable=reachable)
    last_at = last.get("last_at")
    last_name = last.get("last_name")
    last_source = last.get("last_source")

    def _with_last(base: dict) -> dict:
        base.update({
            "last_at": last_at,
            "last_name": last_name,
            "last_source": last_source,
        })
        return base

    if not reachable:
        return _with_last({
            "in_progress": None,
            "state": "unknown",
            "value": "unknown",
            "caption": "gateway unreachable",
        })

    active = _backup_in_progress(raw)
    if active is True:
        return _with_last({
            "in_progress": True,
            "state": "active",
            "value": "underway",
            "caption": "framework backup running",
        })
    if active is False:
        caption = "no backup running"
        if last_at:
            caption = f"last backup {last_at}"
        return _with_last({
            "in_progress": False,
            "state": "idle",
            "value": "idle",
            "caption": caption,
        })
    return _with_last({
        "in_progress": None,
        "state": "unknown",
        "value": "unknown",
        "caption": "backup status unclear",
    })


def _consolidation_status(consolidation: dict | None) -> str | None:
    if not consolidation or not consolidation.get("reachable"):
        return None
    tile = consolidation.get("tile") or {}
    if tile.get("fresh") is False:
        return "warn"
    if tile.get("stalled"):
        return "critical"
    if tile.get("state") == "warn":
        return "warn"
    return None


def _overall_state(
    components: list[dict],
    *,
    reachable: bool,
    consolidation: dict | None = None,
) -> str:
    if not reachable:
        return "critical"
    states = [c["state"] for c in components]
    if "bad" in states:
        return "critical"
    cons = _consolidation_status(consolidation)
    if cons == "critical":
        return "critical"
    if "warn" in states or "unknown" in states or cons == "warn":
        return "warn"
    return "ok"


def system_health_snapshot() -> dict:
    """Live infrastructure (/health) plus workload context from latest telemetry."""
    fetched_at = datetime.now(timezone.utc).isoformat()
    raw = get_health()
    telemetry_payload = get_telemetry()
    telemetry = _telemetry_latest()
    telemetry_at = telemetry.get("collected_at")
    consolidation = consolidation_from_payload(raw, telemetry_payload, fetched_at=fetched_at)

    last_backup = _resolve_last_backup(raw, reachable=raw.get("status") != "unreachable")

    if raw.get("status") == "unreachable":
        return {
            "status": "critical",
            "reachable": False,
            "fetched_at": fetched_at,
            "telemetry_at": telemetry_at,
            "version": None,
            "components": [],
            "backup": _backup_part(raw, reachable=False, last=last_backup),
            "consolidation": consolidation,
            "error": sanitize_error(raw.get("error")) or "gateway unreachable",
        }

    nrem_stalled = bool((consolidation.get("tile") or {}).get("stalled"))
    llm_busy = any(c.get("in_flight") for c in (consolidation.get("cycles") or []))
    inference_busy = _inference_busy_state(raw)
    components = [
        _build_component(key, field, label, kind, raw, telemetry,
                         nrem_stalled=nrem_stalled, llm_busy=llm_busy,
                         inference_busy=inference_busy)
        for key, field, label, kind in _INFRA_COMPONENTS
    ]
    backup = _backup_part(raw, reachable=True, last=last_backup)
    status = _overall_state(components, reachable=True, consolidation=consolidation)

    return {
        "status": status,
        "summary": _status_summary(components, status, backup=backup, consolidation=consolidation),
        "reachable": True,
        "fetched_at": fetched_at,
        "telemetry_at": telemetry_at,
        "inference_busy": inference_busy,
        "version": raw.get("version"),
        "api_version": raw.get("api_version"),
        "components": components,
        "backup": backup,
        "consolidation": consolidation,
        "error": sanitize_error(raw.get("error")) or None,
    }