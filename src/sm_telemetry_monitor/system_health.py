"""Display formatting of GET /health JSON — sole source is bridge.get_health()."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .analytics import rem_drain_signal
from .backup_reader import latest_backup_manifest
from .bridge import get_health, get_pool_status, get_telemetry
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


def _backend_placement(has_credential) -> str | None:
    """local vs external from non-secret has_credential (framework ≥0.8.9).

    ``True`` means the gateway resolved a per-backend token_env (paid/cloud API
    path). ``False`` means no credential — typical local llama.cpp. ``None`` when
    the field is absent (pre-0.8.9 gateways); never invent placement from URL.
    """
    if has_credential is True:
        return "external"
    if has_credential is False:
        return "local"
    return None


# Additive config.llm_backends descriptors (framework ≥0.9.13). Copy only when
# the gateway sent the key — including explicit null — never invent.
_BACKEND_DESCRIPTOR_KEYS = (
    "roles",
    "n_ctx",
    "private_ok",
    "max_inflight",
    "price_per_mtok_in",
    "price_per_mtok_out",
)


def _copy_backend_descriptors(src: dict, dest: dict) -> None:
    for key in _BACKEND_DESCRIPTOR_KEYS:
        if key in src:
            dest[key] = src[key]


def _config_backend_index(raw: dict) -> dict[str, dict]:
    """url → {has_credential, model, placement, descriptors…} from config.llm_backends."""
    cfg = raw.get("config")
    if not isinstance(cfg, dict):
        return {}
    backends_raw = cfg.get("llm_backends")
    if not isinstance(backends_raw, list):
        return {}
    out: dict[str, dict] = {}
    for b in backends_raw:
        if not isinstance(b, dict):
            continue
        url = b.get("url")
        if not url:
            continue
        url_s = str(url).rstrip("/")
        has_cred = b.get("has_credential")
        if not isinstance(has_cred, bool):
            has_cred = None
        model = b.get("model")
        model_s = str(model) if model not in (None, "") else None
        meta = {
            "has_credential": has_cred,
            "model": model_s,
            "placement": _backend_placement(has_cred),
        }
        _copy_backend_descriptors(b, meta)
        out[url_s] = meta
        # also index with trailing slash variants if gateway ever differs
        out[str(url)] = out[url_s]
    return out


def _apply_meta_descriptors(backend: dict, meta: dict) -> None:
    """Copy descriptor keys from config index onto a pool/config backend row."""
    _copy_backend_descriptors(meta, backend)


def _join_token_usage_onto_backends(backends: list[dict], health_raw: dict) -> None:
    """Attach tokens:{prompt_total,completion_total,last_ts} when URL has usage."""
    usage = health_raw.get("llm_token_usage")
    if not isinstance(usage, dict):
        return
    by_norm: dict[str, dict] = {}
    for url, entry in usage.items():
        if not isinstance(entry, dict):
            continue
        url_s = str(url)
        by_norm[url_s.rstrip("/")] = entry
        by_norm[url_s] = entry
    for b in backends:
        url = b.get("url")
        if url is None:
            continue
        entry = by_norm.get(str(url).rstrip("/")) or by_norm.get(str(url))
        if entry is None:
            continue
        b["tokens"] = {
            "prompt_total": entry.get("tokens_prompt_total"),
            "completion_total": entry.get("tokens_completion_total"),
            "last_ts": entry.get("tokens_last_ts"),
        }


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

    When present (framework ≥0.8.9), ``has_credential`` / ``model`` from
    ``config.llm_backends`` are joined by URL onto each pool chip so operators
    can tell local hardware from external/paid APIs without reading secrets.
    """
    pool = raw.get("llm_pool")
    if not isinstance(pool, dict) or not pool:
        return None
    reach = raw.get("llm_backends") if isinstance(raw.get("llm_backends"), dict) else {}
    meta_by_url = _config_backend_index(raw)
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
        meta = meta_by_url.get(str(url).rstrip("/")) or meta_by_url.get(str(url)) or {}
        row = {
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
            "has_credential": meta.get("has_credential"),
            "model": meta.get("model"),
            "placement": meta.get("placement"),
        }
        _apply_meta_descriptors(row, meta)
        backends.append(row)
    if not backends:
        return None
    _join_token_usage_onto_backends(backends, raw)
    return {
        "backends": backends,
        "total": len(backends),
        "up": sum(1 for b in backends if b["status"] == "ok"),
        "busy": sum(1 for b in backends if b["inflight"] > 0),
        "free": sum(1 for b in backends if b["available"]),
        "local": sum(1 for b in backends if b.get("placement") == "local"),
        "external": sum(1 for b in backends if b.get("placement") == "external"),
    }


def _placement_sort_key(backend: dict) -> tuple[int, str]:
    """local → external → unknown; stable by label within a band."""
    p = backend.get("placement")
    if p == "local":
        band = 0
    elif p == "external":
        band = 1
    else:
        band = 2
    return (band, str(backend.get("label") or backend.get("url") or ""))


def _fault_slot(obj) -> dict | None:
    """Pass through a {count, last, ...} blob; None when absent/invalid."""
    return obj if isinstance(obj, dict) else None


def _backend_faults_from_entry(entry: dict | None) -> dict:
    """Flatten telemetry.llm_faults[url] → chip faults {gateway, credential, transient}."""
    if not isinstance(entry, dict):
        return {"gateway": None, "credential": None, "transient": None}
    llm = entry.get("llm") if isinstance(entry.get("llm"), dict) else {}
    return {
        "gateway": _fault_slot(entry.get("gateway")),
        "credential": _fault_slot(llm.get("credential")),
        "transient": _fault_slot(llm.get("transient")),
    }


def _recompute_pool_totals(backends: list[dict]) -> dict:
    return {
        "backends": backends,
        "total": len(backends),
        "up": sum(1 for b in backends if b.get("status") == "ok"),
        "busy": sum(1 for b in backends if (b.get("inflight") or 0) > 0),
        "free": sum(1 for b in backends if b.get("available")),
        "local": sum(1 for b in backends if b.get("placement") == "local"),
        "external": sum(1 for b in backends if b.get("placement") == "external"),
    }


def _join_llm_faults(
    llm_pool: dict | None,
    telemetry_payload: dict | None,
    health_raw: dict,
) -> tuple[dict | None, dict | None]:
    """Join telemetry.llm_faults onto pool backends; extract credentials.

    Returns (llm_pool, credentials). ``faults`` is attached only when the
    telemetry object has an ``llm_faults`` key (empty ``{}`` still attaches
    null slots). Fault URLs missing from the pool synthesise a backend row.
    credentials is the dict when the key exists, else None — never invent zeros.
    Fault counts do not affect overall deck state (caller must not feed them in).
    """
    t = (telemetry_payload or {}).get("telemetry")
    t = t if isinstance(t, dict) else {}
    has_faults_key = "llm_faults" in t
    if "credentials" in t and isinstance(t.get("credentials"), dict):
        credentials: dict | None = t["credentials"]
    else:
        credentials = None

    llm_faults = t.get("llm_faults") if has_faults_key else None
    if has_faults_key and not isinstance(llm_faults, dict):
        llm_faults = {}

    faults_by_norm: dict[str, tuple[str, dict | None]] = {}
    if has_faults_key:
        for url, entry in (llm_faults or {}).items():
            url_s = str(url)
            faults_by_norm[url_s.rstrip("/")] = (
                url_s,
                entry if isinstance(entry, dict) else None,
            )

    backends: list[dict] = list((llm_pool or {}).get("backends") or [])
    seen_norm: set[str] = set()
    meta_by_url = _config_backend_index(health_raw)

    for b in backends:
        url = b.get("url")
        nurl = str(url).rstrip("/") if url is not None else ""
        seen_norm.add(nurl)
        if has_faults_key:
            pair = faults_by_norm.get(nurl)
            entry = pair[1] if pair else None
            b["faults"] = _backend_faults_from_entry(entry)

    if has_faults_key:
        for nurl, (orig_url, entry) in faults_by_norm.items():
            if nurl in seen_norm:
                continue
            meta = meta_by_url.get(nurl) or meta_by_url.get(orig_url) or {}
            row = {
                "url": orig_url,
                "label": _backend_label(orig_url),
                "status": "unknown",
                "inflight": 0,
                "cooldown": 0.0,
                "reserved": False,
                "available": False,
                "weight": None,
                "routed": None,
                "routed_pct": None,
                "fails": None,
                "has_credential": meta.get("has_credential"),
                "model": meta.get("model"),
                "placement": meta.get("placement"),
                "faults": _backend_faults_from_entry(entry),
            }
            _apply_meta_descriptors(row, meta)
            backends.append(row)

    if not backends:
        return llm_pool, credentials

    _join_token_usage_onto_backends(backends, health_raw)
    backends.sort(key=_placement_sort_key)
    return _recompute_pool_totals(backends), credentials


def _dream_free_slots(status_raw) -> int | None:
    """Gateway /pool/status free_slots — int only; bool rejected; missing → None."""
    if not isinstance(status_raw, dict):
        return None
    free = status_raw.get("free_slots")
    if isinstance(free, bool) or not isinstance(free, int):
        return None
    return free


def _join_pool_status(llm_pool: dict | None, status_raw) -> dict | None:
    """Copy serves_all / counts_free_slot onto matching pool backends (I19)."""
    if not isinstance(llm_pool, dict):
        return llm_pool
    if not isinstance(status_raw, dict):
        return llm_pool
    backends_raw = status_raw.get("backends")
    if not isinstance(backends_raw, dict) or not backends_raw:
        return llm_pool
    by_norm: dict[str, dict] = {}
    for url, entry in backends_raw.items():
        if not isinstance(entry, dict):
            continue
        url_s = str(url)
        by_norm[url_s.rstrip("/")] = entry
        by_norm[url_s] = entry
    backends = list(llm_pool.get("backends") or [])
    if not backends:
        return llm_pool
    joined: list[dict] = []
    for b in backends:
        row = dict(b)
        url = row.get("url")
        entry = None
        if url is not None:
            entry = by_norm.get(str(url).rstrip("/")) or by_norm.get(str(url))
        if isinstance(entry, dict):
            if "serves_all" in entry:
                row["serves_all"] = entry["serves_all"]
            if "counts_free_slot" in entry:
                row["counts_free_slot"] = entry["counts_free_slot"]
        joined.append(row)
    return _recompute_pool_totals(joined)


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

    Framework ≥0.8.9 adds per-backend ``has_credential`` (bool) and optional
    ``model`` override — used only for local vs external visibility.
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
            has_cred = b.get("has_credential")
            if not isinstance(has_cred, bool):
                has_cred = None
            model = b.get("model")
            model_s = str(model) if model not in (None, "") else None
            row = {
                "url": str(url),
                "label": str(url).split("//", 1)[-1],
                "weight": b.get("weight"),
                "has_credential": has_cred,
                "model": model_s,
                "placement": _backend_placement(has_cred),
            }
            _copy_backend_descriptors(b, row)
            backends.append(row)

    pool_tuning = cfg.get("llm_pool_tuning") if isinstance(cfg.get("llm_pool_tuning"), dict) else {}
    affinity = cfg.get("llm_affinity") if isinstance(cfg.get("llm_affinity"), dict) else {}
    embed_max = cfg.get("embed_max_chars")

    n = len(backends)
    if n == 0 and not pool_tuning and not affinity and embed_max is None:
        return None

    n_local = sum(1 for b in backends if b.get("placement") == "local")
    n_external = sum(1 for b in backends if b.get("placement") == "external")

    bits: list[str] = []
    if n:
        bits.append(f"{n} LLM backend" + ("s" if n != 1 else ""))
        # Placement mix only when the gateway reports has_credential (0.8.9+).
        if n_local or n_external:
            if n_local and n_external:
                bits.append(f"{n_local} local · {n_external} external")
            elif n_external:
                bits.append(f"{n_external} external" if n_external != n else "external")
            elif n_local:
                bits.append(f"{n_local} local" if n_local != n else "local")
    if embed_max is not None:
        try:
            em = int(embed_max)
            if em >= 1000 and em % 1000 == 0:
                bits.append(f"embed {em // 1000}k")
            else:
                bits.append(f"embed {em}")
        except (TypeError, ValueError):
            bits.append(f"embed {embed_max}")

    out = {
        "present": True,
        "backend_count": n,
        "backends": backends,
        "local_count": n_local,
        "external_count": n_external,
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
    # I17: only when gateway sent it (config preferred, else top-level health bool).
    if "allow_unauthenticated_provider_keys" in cfg:
        out["allow_unauthenticated_provider_keys"] = cfg["allow_unauthenticated_provider_keys"]
    elif "allow_unauthenticated_provider_keys" in raw:
        out["allow_unauthenticated_provider_keys"] = raw["allow_unauthenticated_provider_keys"]
    return out


def _rem_trend() -> str:
    """REM backlog drain signal over the recent stored tail (analytics heuristic)."""
    try:
        since = datetime.now(UTC) - timedelta(seconds=REM_STALL_WINDOW_S * 6)
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
            # Flat backlog with a free slot is process-variable (upcoming work /
            # slow drain), not an alarm — no rem_stalled on gateway yet. Hero
            # owns "what's upcoming"; do not yellow the tile or the deck
            # (decision 903 / fact 902).
            if rem_trend == "flat":
                return {"value": f"{rem_q} queued", "state": "ok",
                        "caption": "REM backlog · pool free · no net drain yet"}
            if rem_trend == "draining":
                return {"value": f"{rem_q} draining", "state": "ok", "caption": "REM backlog"}
            return {"value": f"{rem_q} queued", "state": "ok", "caption": "REM backlog"}
        # Single-backend stacks keep the global nvtop gate: while any inference
        # holds the GPU, REM defers by design (nvtop is a strict superset — the GPU
        # may be a direct :5000 chat, not REM; doesn't matter, REM is gated off).
        if inference_busy == "busy":
            return {"value": f"{rem_q} deferring", "state": "ok",
                    "caption": "REM backlog · GPU busy"}
        # GPU idle/unknown: backlog is still upcoming work until the gateway
        # exposes rem_stalled — never promote client rem_drain flat to warn.
        if rem_trend == "flat":
            return {"value": f"{rem_q} queued", "state": "ok",
                    "caption": "REM backlog · GPU free · no net drain yet"}
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
        types = tile.get("stalled_types_short") or []
        if types:
            return f"consolidation stalled [{', '.join(types)}]"
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
                return datetime.fromtimestamp(value, tz=UTC).isoformat()
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
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat()
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


def _component_fault_level(component: dict) -> str | None:
    """Deck-elevating fault from one infra component, or None.

    Decision 903: overall status tracks gateway-class health. Dream-cycle
    backlog (REM/NREM workload) is a process variable — hero + tile text show
    upcoming work; it must not paint the deck warn. Elevate only process-down,
    blocked paths (workload bad), and infra warn on gateway/embedder/reranker/llm
    (failed/degraded backends, outbox, probe saturation, wedge).
    """
    key = component.get("key")
    proc = (component.get("process") or {}).get("state")
    load = (component.get("workload") or {}).get("state")
    if proc == "bad" or load == "bad":
        return "critical"
    # REM/NREM: process down already handled; backlog/stall heuristics stay local.
    if key in ("rem_daemon", "nrem_daemon"):
        return None
    if proc == "warn" or load == "warn":
        return "warn"
    return None


def _overall_state(
    components: list[dict],
    *,
    reachable: bool,
    consolidation: dict | None = None,
    graph_invalid_nodes: int | None = None,
    graph_integrity: dict | None = None,
) -> str:
    if not reachable:
        return "critical"
    worst = "ok"
    rank = {"ok": 0, "warn": 1, "critical": 2}
    for c in components:
        level = _component_fault_level(c)
        if level and rank[level] > rank[worst]:
            worst = level
    cons = _consolidation_status(consolidation)
    if cons == "critical":
        return "critical"
    if cons == "warn" and rank["warn"] > rank[worst]:
        worst = "warn"
    if graph_invalid_nodes and graph_invalid_nodes > 0 and rank["warn"] > rank[worst]:
        worst = "warn"
    if isinstance(graph_integrity, dict):
        if (graph_integrity.get("error") or graph_integrity.get("clean") is False or (
            isinstance(graph_integrity.get("invalid_nodes"), int)
            and not isinstance(graph_integrity.get("invalid_nodes"), bool)
            and graph_integrity["invalid_nodes"] > 0
        )) and rank["warn"] > rank[worst]:
            worst = "warn"
    # "unknown" alone does not elevate — missing optional fields are not faults.
    return worst


def system_health_snapshot() -> dict:
    """Live infrastructure (/health) plus workload context from latest telemetry."""
    fetched_at = datetime.now(UTC).isoformat()
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
    # Join additive telemetry.llm_faults / credentials after pool summary.
    # Fault counts never feed _overall_state / _status_summary (I2).
    llm_pool, credentials = _join_llm_faults(llm_pool, telemetry_payload, raw)
    pool_status_raw = get_pool_status()
    llm_pool = _join_pool_status(llm_pool, pool_status_raw)
    dream_free_slots = _dream_free_slots(pool_status_raw)
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
    graph_invalid_nodes = raw.get("graph_invalid_nodes")
    if graph_invalid_nodes is None and isinstance(raw.get("consolidation"), dict):
        graph_invalid_nodes = raw.get("consolidation", {}).get("graph_invalid_nodes")
    graph_integrity = (telemetry_payload or {}).get("telemetry", {}).get("graph_integrity")
    
    status = _overall_state(
        components,
        reachable=True,
        consolidation=consolidation,
        graph_invalid_nodes=graph_invalid_nodes,
        graph_integrity=graph_integrity,
    )

    out = {
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
        "graph_invalid_nodes": raw.get("graph_invalid_nodes"),
        "graph_integrity": (telemetry_payload or {}).get("telemetry", {}).get("graph_integrity"),
        "credentials": credentials,
    }
    if dream_free_slots is not None:
        out["dream_free_slots"] = dream_free_slots
    # I12/I13: flat passthrough — absent keys stay absent; never invent zeros.
    if "llm_routing" in raw and isinstance(raw.get("llm_routing"), dict):
        out["llm_routing"] = raw["llm_routing"]
    if "llm_token_usage" in raw and isinstance(raw.get("llm_token_usage"), dict):
        out["llm_token_usage"] = raw["llm_token_usage"]
    return out
