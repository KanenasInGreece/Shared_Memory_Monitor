from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .analytics import pipeline_snapshot, story_summary
from .config import GRAPHS_DIR


def render_pipeline(rows: list[dict]) -> None:
    """Horizontal funnel — where work sits in the sleep-cycle pipeline."""
    if not rows:
        return
    GRAPHS_DIR.mkdir(parents=True, exist_ok=True)
    latest = rows[-1]
    stages = pipeline_snapshot(latest)
    story = story_summary(rows)

    # Skip zero-width noise for the funnel bars, but keep failed/pending visible.
    plot_stages = [s for s in stages if s["value"] > 0 or s["key"] in ("outbox_failed", "outbox_pending")]
    if not plot_stages:
        plot_stages = stages[-4:]

    labels = [s["label"].replace(" ", "\n") for s in plot_stages]
    values = [s["value"] for s in plot_stages]
    colors = []
    for s in plot_stages:
        if s["key"] == "outbox_failed":
            colors.append("#ff6b6b")
        elif "queue" in s["key"] or s["key"] == "facts_unconsolidated":
            colors.append("#f5a623")
        elif s["key"] in ("summaries_total", "facts_consolidated"):
            colors.append("#3ddc97")
        else:
            colors.append("#4da3ff")

    fig, ax = plt.subplots(figsize=(12, 6))
    y = range(len(plot_stages))
    bars = ax.barh(y, values, color=colors, height=0.6)
    ax.set_yticks(y, labels=labels, fontsize=9)
    ax.set_xlabel("count")
    ax.set_title("Sleep-cycle pipeline — where work lives right now", fontsize=12, pad=12)
    ax.grid(True, axis="x", alpha=0.25)
    for bar, val in zip(bars, values):
        ax.text(bar.get_width() + max(values) * 0.01, bar.get_y() + bar.get_height() / 2,
                str(val), va="center", fontweight="bold")

    fig.text(0.5, 0.02, story["headline"], ha="center", fontsize=11, fontweight="bold",
             color={"critical": "#c0392b", "warn": "#d68910", "ok": "#1e8449"}.get(story["health"], "#333"))
    fig.text(0.5, -0.02, story["detail"], ha="center", fontsize=8.5, color="#555", wrap=True)
    fig.tight_layout()
    fig.savefig(GRAPHS_DIR / "pipeline.png", dpi=140, bbox_inches="tight")
    plt.close(fig)