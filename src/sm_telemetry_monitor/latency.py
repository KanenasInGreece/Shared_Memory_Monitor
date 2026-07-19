"""Display formatting for the telemetry.latency block — processing time.

Two distinct signals, both read-only from ``GET /memory/telemetry``:

* **REM enrichment** (``latency.rem_ms.by_model``) — the many small per-record
  LLM calls that build a record's graph relationships. Each backend model
  reports its time split into ``service_ms`` (the model's own compute — a floor
  set by model + hardware) and ``contention_ms`` (extra delay from waiting for a
  free slot under load). That split is the actionable part: a model-bound bar
  says "make the model/prompt faster"; a contention-bound bar says "add capacity
  or reduce concurrency".
* **Consolidation cycles** (``latency.nrem_cycle_seconds``) — the periodic,
  heavier synthesis folds. Reported as p50/p95 over a rolling window, gated to
  real synthesis cycles (``folds_succeeded > 0``), so deferred/no-op sweeps no
  longer skew it. With a small sample the p95 is an *observed extreme*, not a
  statistical tail, so we always show ``n`` and never imply a target.

Latency is orthogonal to the consolidation-quality chain (first-write quality →
coverage → graph health): it measures *how fast/costly* processing is, not *how
much useful structure* it produces. It therefore lives in its own drawer.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .bridge import get_telemetry
from .sanitize import sanitize_error

# Below this many samples the numbers are shown but flagged as too few to trend.
_MIN_SAMPLES = 10
# REM contention share (queue wait ÷ total) at/above which the otherwise-hidden
# main-deck chip surfaces — load is stealing a meaningful slice of REM time.
_CONTENTION_CHIP_THRESHOLD = 30


def _anchor(value: float | int | dict | None) -> float | int | None:
    """Representative scalar from a latency field that may already be a scalar
    or a percentile dict — we anchor on p50 (median), the typical case."""
    if isinstance(value, dict):
        return value.get("p50")
    if isinstance(value, (int, float)):
        return value
    return None


def _pct(num: float | int | None, den: float | int | None) -> int | None:
    if num is None or not den:
        return None
    return round(100 * num / den)


def _p95(value: float | int | dict | None) -> float | int | None:
    """Optional p95 from a percentile dict; None when absent or scalar-only."""
    if isinstance(value, dict):
        return value.get("p95")
    return None


def _rem_by_model(rem_ms: dict | None) -> tuple[list[dict], int | None]:
    """Per-model REM service/contention split + the worst contention share."""
    rem = rem_ms if isinstance(rem_ms, dict) else {}
    models: list[dict] = []
    max_contention_pct: int | None = None
    for entry in rem.get("by_model") or []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("model") or entry.get("backend") or entry.get("name") or "?"
        service = _anchor(entry.get("service_ms"))
        contention = _anchor(entry.get("contention_ms"))
        service_p95 = _p95(entry.get("service_ms"))
        contention_p95 = _p95(entry.get("contention_ms"))
        total = None
        if service is not None or contention is not None:
            total = (service or 0) + (contention or 0)
        contention_pct = _pct(contention, total)
        if contention_pct is not None:
            max_contention_pct = (
                contention_pct if max_contention_pct is None
                else max(max_contention_pct, contention_pct)
            )
        models.append({
            "model": name,
            "service_ms": service,
            "contention_ms": contention,
            "service_ms_p95": service_p95,
            "contention_ms_p95": contention_p95,
            "total_ms": total,
            # Bar-segment widths (0–100) so the client draws the split without
            # re-deriving proportions; None total → no bar, just the empty note.
            # Fractions use the p50 (typical) anchors — p95 is shown as text only.
            "service_frac": _pct(service, total),
            "contention_frac": contention_pct,
            "contention_pct": contention_pct,
            "n": entry.get("n"),
            "max_batch_size": entry.get("max_batch_size"),
            "low_n": isinstance(entry.get("n"), int) and entry.get("n") < _MIN_SAMPLES,
        })
    return models, max_contention_pct


def _nrem_cycle(nrem: dict | None) -> dict:
    nrem = nrem if isinstance(nrem, dict) else {}
    n = nrem.get("n")
    p50 = nrem.get("p50")
    p95 = nrem.get("p95")
    present = p50 is not None or p95 is not None
    spread = None
    if isinstance(p50, (int, float)) and p50 and isinstance(p95, (int, float)):
        spread = round(p95 / p50, 1)
    return {
        "present": present,
        "n": n,
        "window_days": nrem.get("window_days"),
        "p50_seconds": p50,
        "p95_seconds": p95,
        # p95÷p50 — a rough variance/prompt-bloat cue, diagnostic only.
        "spread": spread,
        "low_n": isinstance(n, int) and n < _MIN_SAMPLES,
        "note": nrem.get("note"),
    }


def latency_from_payload(
    telemetry_payload: dict | None,
    *,
    fetched_at: str | None = None,
) -> dict:
    """Build the latency drawer snapshot from a GET /memory/telemetry response."""
    fetched_at = fetched_at or datetime.now(timezone.utc).isoformat()

    reachable = True
    error = None
    latency: dict = {}
    telemetry_at = None
    if isinstance(telemetry_payload, dict) and telemetry_payload.get("status") == "success":
        t = telemetry_payload.get("telemetry") or {}
        telemetry_at = t.get("timestamp")
        if isinstance(t.get("latency"), dict):
            latency = t["latency"]
    elif isinstance(telemetry_payload, dict) and telemetry_payload.get("status") in ("error", "unreachable"):
        reachable = False
        error = sanitize_error(telemetry_payload.get("message") or telemetry_payload.get("error"))

    rem_models, max_contention_pct = _rem_by_model(latency.get("rem_ms"))
    nrem = _nrem_cycle(latency.get("nrem_cycle_seconds"))
    rem_note = latency.get("rem_ms", {}).get("note") if isinstance(latency.get("rem_ms"), dict) else None

    # The block exists at all only on gateways that expose telemetry.latency;
    # older gateways omit it and the drawer shows an unsupported note.
    present = bool(latency)

    # Deck chip only when load is stealing a meaningful slice of REM time.
    chip = None
    if max_contention_pct is not None and max_contention_pct >= _CONTENTION_CHIP_THRESHOLD:
        chip = {"contention_pct": max_contention_pct}

    return {
        "reachable": reachable,
        "present": present,
        "fetched_at": fetched_at,
        "telemetry_at": telemetry_at,
        "rem": {
            "present": bool(rem_models),
            "models": rem_models,
            "max_contention_pct": max_contention_pct,
            "note": rem_note,
        },
        "nrem": nrem,
        "chip": chip,
        "contention_chip_threshold": _CONTENTION_CHIP_THRESHOLD,
        "error": error,
    }


def latency_snapshot() -> dict:
    """Live latency panel — fetches GET /memory/telemetry (read-only)."""
    return latency_from_payload(get_telemetry())
