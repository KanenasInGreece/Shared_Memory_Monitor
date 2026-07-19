"""Display formatting of GET /health JSON — sole source is bridge.get_health()."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .analytics import rem_drain_signal
from .backup_reader import latest_backup_manifest
from .bridge import get_health, get_telemetry
from .config import REM_STALL_WINDOW_S
from .consolidation import consolidation_from_payload
from .sanitize import sanitize_error
from .store import load_history
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


def _age_caption(age_s: float | None) -> str | None:
    """Human fragment for oldest in-flight age; None when not applicable."""
    if age_s is None or age_s < 0:
        return None
    if age_s < 1:
        return "oldest in-flight <1s"
    if age_s < 60:
        return f"oldest in-flight {int(age_s)}s"
    m, s = divmod(int(age_s), 60)
    if m < 60:
        return f"oldest in-flight {m}m {s}s" if s else f"oldest in-flight {m}m"
    h, m = divmod(m, 60)
    return f"oldest in-flight {h}h {m}m"


def _backend_label(url: str) -> str:
    """Short host:port (or path tail) for chips — no scheme."""
    return str(url).split("//", 1)[-1]


def _llm_pool_summary(raw: dict) -> dict | None:
    """Multi-backend LLM pool state from /health.llm_pool + /health.llm_backends.

    The gateway emits both only when more than one backend is configured
    (LLM_BACKENDS in the gateway env); single-backend deployments omit them and
    the tiles keep the nvtop-based semantics. Per-backend `inflight` is the
    truthful busy signal for each model — all LLM traffic flows through the
    gateway pool, and REM/NREM gate on a free slot, not on global GPU load.

    Pass-through of weight / routed / routed_pct / fails is intentional: the
    monitor never invents balance metrics; it only reshapes what /health already
    reports so the UI can show which card is working and how load split.
    """
    pool = raw.get("llm_pool")
    if not isinstance(pool, dict) or not pool:
        return None
    reach = raw.get("llm_backends") if isinstance(raw.get("llm_backends"), dict) else {}
    backends = []
    for url, p in pool.items():
        if not isinstance(p, dict):
            continue
        status = str(reach.get(url, "")).lower() or "unknown"
        inflight = int(p.get("inflight") or 0)
        cooldown = float(p.get("cooldown") or 0.0)
        reserved = bool(p.get("reserved"))
        weight = p.get("weight")
        try:
            weight_f = float(weight) if weight is not None else None
        except (TypeError, ValueError):
            weight_f = None
        routed = p.get("routed")
        try:
            routed_i = int(routed) if routed is not None else None
        except (TypeError, ValueError):
            routed_i = None
        routed_pct = p.get("routed_pct")
        try:
            routed_pct_f = float(routed_pct) if routed_pct is not None else None
        except (TypeError, ValueError):
            routed_pct_f = None
        fails = p.get("fails")
        try:
            fails_i = int(fails) if fails is not None else None
        except (TypeError, ValueError):
            fails_i = None
        backends.append({
            "url": url,
            # short label for UI chips: strip scheme, keep host:port tail
            "label": _backend_label(url),
            "status": status,
            "inflight": inflight,
            "cooldown": cooldown,
            "reserved": reserved,
            "available": status == "ok" and inflight == 0 and cooldown <= 0 and not reserved,
            "weight": weight_f,
            "routed": routed_i,
            "routed_pct": routed_pct_f,
            "fails": fails_i,
        })
    if not backends:
        return None
    return {
        "backends": backends,
        "total": len(backends),
        "up": sum(1 for b in backends if b["status"] == "ok"),
        "busy": sum(1 for b in backends if b["inflight"] > 0),
        "free": sum(1 for b in backends if b["available"]),
    }


def _oldest_inflight_age_s(raw: dict) -> float | None:
    """Seconds the oldest in-flight LLM call has been open — wedge visibility.

    Present on single- and multi-backend gateways when any call is in flight.
    Distinguishes a healthy long generation from a hung accept-thread (see
    framework wedge probes + optional llm_suspect_wedged).
    """
    v = raw.get("llm_oldest_inflight_age_s")
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _suspect_wedged(raw: dict) -> list[str] | None:
    """Backend labels the gateway flagged as suspect-wedged (optional list of URLs)."""
    w = raw.get("llm_suspect_wedged")
    if not isinstance(w, list) or not w:
        return None
    out = [_backend_label(u) for u in w if u]
    return out or None


def _llm_affinity_live(raw: dict) -> dict | None:
    """Runtime cache-affinity counters from /health.llm_affinity (multi-backend).

    Distinct from /health.config.llm_affinity (static knobs). Live block has
    hits/misses/hit_rate and optional hot_prefixes map.
    """
    aff = raw.get("llm_affinity")
    if not isinstance(aff, dict) or not aff:
        return None
    if not any(k in aff for k in ("hits", "misses", "hit_rate", "hot_prefixes")):
        return None
    hot_raw = aff.get("hot_prefixes")
    prefixes: list[dict] = []
    if isinstance(hot_raw, dict):
        for key, val in hot_raw.items():
            if not isinstance(val, dict):
                continue
            backend = val.get("backend") or ""
            prefixes.append({
                "prefix": str(key)[:12],
                "backend": _backend_label(backend) if backend else "",
                "url": str(backend) if backend else None,
                "hits": val.get("hits"),
            })
    return {
        "hits": aff.get("hits"),
        "misses": aff.get("misses"),
        "hit_rate": aff.get("hit_rate"),
        "hot_prefixes": prefixes,
    }


def _gateway_config(raw: dict) -> dict | None:
    """Non-secret effective config from /health.config (framework v0.6.1+).

    Always present on modern gateways — including single-backend installs where
    ``llm_pool`` / live ``llm_backends`` status maps are omitted. Surfaces the
    resolved backend list, pool-tuning knobs, affinity settings, and embed cap
    so the operator can inspect the live setup without reading gateway ``.env``.
    Secrets are never echoed by the gateway in this block.
    """
    cfg = raw.get("config")
    if not isinstance(cfg, dict) or not cfg:
        return None

    backends_raw = cfg.get("llm_backends")
    backends: list[dict] = []
    if isinstance(backends_raw, list):
        for b in backends_raw:
            if not isinstance(b, dict):
                continue
            url = b.get("url")
            if not url:
                continue
            backends.append({
                "url": str(url),
                "label": str(url).split("//", 1)[-1],
                "weight": b.get("weight"),
            })

    pool_tuning = cfg.get("llm_pool_tuning") if isinstance(cfg.get("llm_pool_tuning"), dict) else {}
    affinity = cfg.get("llm_affinity") if isinstance(cfg.get("llm_affinity"), dict) else {}
    embed_max = cfg.get("embed_max_chars")

    n = len(backends)
    if n == 0 and not pool_tuning and not affinity and embed_max is None:
        return None

    bits: list[str] = []
    if n:
        bits.append(f"{n} LLM backend" + ("s" if n != 1 else ""))
    if embed_max is not None:
        try:
            em = int(embed_max)
            if em >= 1000 and em % 1000 == 0:
                bits.append(f"embed {em // 1000}k")
            else:
                bits.append(f"embed {em}")
        except (TypeError, ValueError):
            bits.append(f"embed {embed_max}")

    return {
        "present": True,
        "backend_count": n,
        "backends": backends,
        "embed_max_chars": embed_max,
        "pool_tuning": {
            "fail_threshold": pool_tuning.get("fail_threshold"),
            "fail_window_s": pool_tuning.get("fail_window_s"),
            "cooldown_s": pool_tuning.get("cooldown_s"),
            "max_tries": pool_tuning.get("max_tries"),
        } if pool_tuning else None,
        "affinity": {
            "prefix_chars": affinity.get("prefix_chars"),
            "ttl_s": affinity.get("ttl_s"),
            "max_inflight": affinity.get("max_inflight"),
        } if affinity else None,
        "summary": " · ".join(bits) if bits else "configured",
    }


def _rem_trend() -> str:
    """REM backlog drain signal over the recent stored tail (analytics heuristic)."""
    try:
        since = datetime.now(timezone.utc) - timedelta(seconds=REM_STALL_WINDOW_S * 6)
        rows = load_history(since=since)
    except Exception:
        return "insufficient"
    samples = [
        {
            "collected_at": r.get("collected_at"),
            "rem_backlog": r.get("rem_backlog")
            if r.get("rem_backlog") is not None
            else (r.get("facts_rem_pending") or 0) + (r.get("decisions_rem_pending") or 0),
        }
        for r in rows
    ]
    return rem_drain_signal(samples, window_s=REM_STALL_WINDOW_S)


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
                   llm_busy: bool = False, inference_busy: str = "unknown",
                   rem_trend: str = "insufficient", llm_pool: dict | None = None) -> dict:
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
        # Two independent facts: `llm` is backend reachability; `inference_busy`
        # is the nvtop GPU-busy signal. On a multi-backend gateway the pool's
        # per-backend in-flight is the authoritative per-model busy signal (all
        # LLM traffic flows through the gateway), so read it first.
        if llm_pool:
            n = llm_pool["total"]
            if llm_pool["up"] == 0:
                # whole pool unreachable — same saturation nuance as single-backend
                if inference_busy == "busy":
                    return {"value": "busy", "state": "warn",
                            "caption": "GPU busy · reachability probes saturated"}
                return {"value": "unavailable", "state": "bad", "caption": "dream cycle blocked"}
            busy_n = llm_pool["busy"]
            down_n = n - llm_pool["up"]
            age = _oldest_inflight_age_s(raw)
            age_bit = _age_caption(age)
            wedged = _suspect_wedged(raw)
            if busy_n > 0:
                busy_labels = [
                    b["label"] for b in llm_pool["backends"]
                    if b.get("inflight", 0) > 0
                ]
                cap = f"{busy_n} of {n} backends inferring"
                if busy_labels:
                    cap += f" · {', '.join(busy_labels)}"
                if down_n:
                    cap += f" · {down_n} down"
                if age_bit:
                    cap += f" · {age_bit}"
                if wedged:
                    cap += f" · wedge suspect: {', '.join(wedged)}"
                    return {"value": f"busy {busy_n}/{n}", "state": "warn", "caption": cap}
                return {"value": f"busy {busy_n}/{n}", "state": "warn" if down_n else "ok",
                        "caption": cap}
            if down_n:
                return {"value": f"{llm_pool['up']}/{n} up", "state": "warn",
                        "caption": f"pool degraded · {down_n} backend{'s' if down_n > 1 else ''} down"}
            if inference_busy == "busy":
                # pool idle but the GPU is inferring: load outside the gateway
                # (e.g. a direct chat with a backend) — truthful, not an alarm.
                return {"value": "busy", "state": "ok",
                        "caption": "GPU busy · no pool call in flight"}
            if inference_busy == "idle":
                return {"value": "idle", "state": "ok", "caption": f"pool of {n} · GPU idle"}
            return {"value": "ready", "state": "ok", "caption": f"pool of {n} · load unknown"}
        # Single backend: read load from nvtop first — it sees a user chatting
        # directly with :5000 (bypassing the gateway), which no daemon ledger or
        # cycle-in-flight signal can.
        age_bit = _age_caption(_oldest_inflight_age_s(raw))
        wedged = _suspect_wedged(raw)
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
            cap = "inference in flight · GPU busy"
            if age_bit:
                cap += f" · {age_bit}"
            if wedged:
                return {"value": "busy", "state": "warn",
                        "caption": cap + f" · wedge suspect: {', '.join(wedged)}"}
            return {"value": "busy", "state": "ok", "caption": cap}
        if inference_busy == "idle":
            return {"value": "idle", "state": "ok", "caption": "reachable · GPU idle"}
        # inference_busy == "unknown": nvtop absent / SLOT_AWARE=0 — fall back to a
        # dream cycle in flight (the only busy signal we can still trust), and
        # never assert "idle" we cannot observe.
        if llm_busy:
            cap = "dream-cycle inference in flight"
            if age_bit:
                cap += f" · {age_bit}"
            return {"value": "busy", "state": "ok", "caption": cap}
        return {"value": "ready", "state": "ok", "caption": "reachable · load unknown"}

    if key == "rem_daemon":
        proc = _state(raw.get("rem_daemon"))
        if proc != "ok":
            return {"value": "—", "state": "bad", "caption": "REM backlog"}
        if not llm_ok:
            return {"value": "blocked (LLM down)", "state": "bad", "caption": "REM backlog"}
        if rem_q is None:
            return {"value": "no backlog data", "state": "unknown", "caption": "REM backlog"}
        if rem_q <= 0:
            return {"value": "queue idle", "state": "ok", "caption": "REM backlog"}
        # A non-empty REM queue is normal — it only warrants a warning when the
        # LLM is free yet nothing is draining (a genuine stall). What "free"
        # means depends on the gateway: multi-backend pools gate REM on a free
        # pool slot (v0.6.1+, defer reason "pool_busy"), so global GPU load is
        # NOT a defer signal there — REM itself keeps a card busy while it works.
        if llm_pool:
            if llm_pool["free"] == 0:
                return {"value": f"{rem_q} deferring", "state": "ok",
                        "caption": "REM backlog · LLM pool busy"}
            if rem_trend == "flat":
                return {"value": f"{rem_q} stalled", "state": "warn",
                        "caption": "REM backlog · pool slot free, not draining"}
            if rem_trend == "draining":
                return {"value": f"{rem_q} draining", "state": "ok", "caption": "REM backlog"}
            return {"value": f"{rem_q} queued", "state": "ok", "caption": "REM backlog"}
        # Single-backend stacks keep the global nvtop gate: while any inference
        # holds the GPU, REM defers by design (nvtop is a strict superset — the GPU
        # may be a direct :5000 chat, not REM; doesn't matter, REM is gated off).
        if inference_busy == "busy":
            return {"value": f"{rem_q} deferring", "state": "ok",
                    "caption": "REM backlog · GPU busy"}
        # GPU idle/unknown: REM should be working the backlog down.
        if rem_trend == "flat":
            return {"value": f"{rem_q} stalled", "state": "warn",
                    "caption": "REM backlog · GPU free, not draining"}
        if rem_trend == "draining":
            return {"value": f"{rem_q} draining", "state": "ok", "caption": "REM backlog"}
        # insufficient history — can't tell stall from normal poll-gap lag; don't warn.
        return {"value": f"{rem_q} queued", "state": "ok", "caption": "REM backlog"}

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
                     inference_busy: str = "unknown", rem_trend: str = "insufficient",
                     llm_pool: dict | None = None) -> dict:
    process = _process_part(key, raw.get(field), kind)
    workload = _workload_part(key, raw, t, nrem_stalled=nrem_stalled, llm_busy=llm_busy,
                              inference_busy=inference_busy, rem_trend=rem_trend,
                              llm_pool=llm_pool)
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
            "api_version": None,
            "config": None,
            "components": [],
            "backup": _backup_part(raw, reachable=False, last=last_backup),
            "consolidation": consolidation,
            "llm_pool": None,
            "llm_oldest_inflight_age_s": None,
            "llm_suspect_wedged": None,
            "llm_affinity_live": None,
            "error": sanitize_error(raw.get("error")) or "gateway unreachable",
        }

    nrem_stalled = bool((consolidation.get("tile") or {}).get("stalled"))
    llm_busy = any(c.get("in_flight") for c in (consolidation.get("cycles") or []))
    inference_busy = _inference_busy_state(raw)
    llm_pool = _llm_pool_summary(raw)
    gateway_config = _gateway_config(raw)
    rem_trend = _rem_trend()
    components = [
        _build_component(key, field, label, kind, raw, telemetry,
                         nrem_stalled=nrem_stalled, llm_busy=llm_busy,
                         inference_busy=inference_busy, rem_trend=rem_trend,
                         llm_pool=llm_pool)
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
        "llm_pool": llm_pool,
        "llm_oldest_inflight_age_s": _oldest_inflight_age_s(raw),
        "llm_suspect_wedged": _suspect_wedged(raw),
        "llm_affinity_live": _llm_affinity_live(raw),
        "version": raw.get("version"),
        "api_version": raw.get("api_version"),
        "config": gateway_config,
        "components": components,
        "backup": backup,
        "consolidation": consolidation,
        "error": sanitize_error(raw.get("error")) or None,
    }