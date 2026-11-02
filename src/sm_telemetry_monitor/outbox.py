"""Outbox failure counts. The configured id list is not per-row evidence."""

from __future__ import annotations

from .config import IGNORED_OUTBOX_IDS


def _baseline_actionable(raw: int) -> dict:
    """Keep the gateway aggregate when no poll names the ignored ids."""
    return {"raw": raw, "actionable": raw, "ignored": 0}


def fetch_outbox_failure_counts() -> dict | None:
    """Estimate actionable vs ignored failed rows without direct Postgres."""
    if not IGNORED_OUTBOX_IDS:
        return None
    return None


def apply_outbox_ignore(row: dict, *, pg_counts: dict | None = None) -> dict:
    """Replace aggregate outbox_failed with actionable count; keep raw/ignored."""
    row = dict(row)
    if pg_counts is None and row.get("outbox_failed_raw") is not None:
        return row
    raw = row.get("outbox_failed_raw")
    if raw is None:
        raw = row.get("outbox_failed") or 0
    if pg_counts is not None:
        counts = {
            "raw": pg_counts.get("raw", raw),
            "actionable": pg_counts["actionable"],
            "ignored": pg_counts["ignored"],
        }
    else:
        counts = _baseline_actionable(raw)

    row["outbox_failed_raw"] = counts["raw"]
    row["outbox_failed_ignored"] = counts["ignored"]
    row["outbox_failed"] = counts["actionable"]
    return row