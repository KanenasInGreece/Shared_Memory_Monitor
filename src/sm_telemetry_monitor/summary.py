from __future__ import annotations

from .analytics import enrich_row, story_summary
from .store import load_all, meta


def live_summary() -> dict:
    rows = load_all()
    m = meta()
    if not rows:
        return {
            "status": "empty",
            "samples": 0,
            "story": {"headline": "No telemetry yet", "detail": "Start the poll loop.", "health": "warn"},
            "latest": {},
            **m,
        }
    enriched = [enrich_row(r) for r in rows]
    latest = enriched[-1]
    story = story_summary(enriched)
    return {
        "status": "ok",
        "samples": len(rows),
        "last_at": latest.get("collected_at"),
        "latest": latest,
        "story": story,
        **m,
    }