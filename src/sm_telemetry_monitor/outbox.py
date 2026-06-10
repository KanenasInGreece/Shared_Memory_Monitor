"""Outbox failure filtering — ignore known stale prerelease rows."""

from __future__ import annotations

from .config import IGNORED_OUTBOX_IDS


def _baseline_actionable(raw: int) -> dict:
    ignored = min(raw, len(IGNORED_OUTBOX_IDS))
    actionable = max(0, raw - ignored)
    return {"raw": raw, "actionable": actionable, "ignored": ignored}


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