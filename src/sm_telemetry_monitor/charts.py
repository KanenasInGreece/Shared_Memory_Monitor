from __future__ import annotations

from datetime import datetime, timezone

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

from .config import (
    GRAPHS_DIR,
    MAX_REM_PER_INTERVAL,
    POLL_INTERVAL_S,
    REM_BATCH,
    REM_POLL_S,
)


def _parse_times(rows: list[dict]) -> list[datetime]:
    return [datetime.fromisoformat(r["collected_at"]) for r in rows]


def _series(rows: list[dict], key: str) -> list[float | None]:
    return [r.get(key) for r in rows]


def _shade_rem_bursts(ax, t0: datetime, t1: datetime) -> None:
    start = t0.timestamp()
    end = t1.timestamp()
    cursor = start - (start % REM_POLL_S)
    while cursor < end:
        ax.axvspan(
            datetime.fromtimestamp(cursor, tz=timezone.utc),
            datetime.fromtimestamp(min(cursor + REM_POLL_S, end), tz=timezone.utc),
            alpha=0.06,
            color="steelblue",
            zorder=0,
        )
        cursor += REM_POLL_S


def _style_time_axis(ax, times: list[datetime]) -> None:
    span = (times[-1] - times[0]).total_seconds() if len(times) > 1 else 0
    fmt = "%H:%M:%S" if span < 3600 else "%m-%d %H:%M"
    ax.xaxis.set_major_formatter(mdates.DateFormatter(fmt))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right")


def _render_status_panel(rows: list[dict]) -> None:
    """Visual gauge panel — backlog bars + donut, not plain text."""
    latest, first = rows[-1], rows[0]
    backlog_labels = ["Facts REM\npending", "Unconsolidated\nfacts", "Decisions REM\npending"]
    backlog_vals = [
        latest.get("facts_rem_pending", 0) or 0,
        latest.get("facts_unconsolidated", 0) or 0,
        latest.get("decisions_rem_pending", 0) or 0,
    ]
    colors = ["#4da3ff", "#f5a623", "#3ddc97"]

    fig, axes = plt.subplots(1, 2, figsize=(11, 5), gridspec_kw={"width_ratios": [1.2, 1]})

    ax = axes[0]
    y_pos = range(len(backlog_labels))
    bars = ax.barh(y_pos, backlog_vals, color=colors, height=0.55)
    ax.set_yticks(y_pos, labels=backlog_labels)
    ax.set_xlabel("count")
    ax.set_title("Current backlog")
    ax.grid(True, axis="x", alpha=0.3)
    for bar, val in zip(bars, backlog_vals):
        ax.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height() / 2,
                str(val), va="center", fontsize=11, fontweight="bold")

    ax = axes[1]
    if sum(backlog_vals) > 0:
        ax.pie(backlog_vals, labels=backlog_labels, colors=colors, autopct="%1.0f%%",
               startangle=140, textprops={"fontsize": 9})
    ax.set_title("Backlog share")

    cleared = []
    for key, label in (
        ("facts_rem_pending", "facts REM"),
        ("facts_unconsolidated", "unconsolidated"),
        ("decisions_rem_pending", "decisions REM"),
    ):
        s, c = first.get(key, 0) or 0, latest.get(key, 0) or 0
        cleared.append(f"{label}: {s}→{c} ({max(0, s - c)} cleared)")

    fig.suptitle(
        f"Shared Memory @ {latest['collected_at'][11:19]} UTC  ·  "
        f"{len(rows)} samples  ·  poll {POLL_INTERVAL_S // 60} min  ·  REM {REM_BATCH}/{REM_POLL_S}s",
        fontsize=10, y=1.02,
    )
    fig.text(0.5, -0.02, "  |  ".join(cleared), ha="center", fontsize=9, color="#555")
    fig.tight_layout()
    fig.savefig(GRAPHS_DIR / "latest_snapshot.png", dpi=140, bbox_inches="tight")
    plt.close(fig)


def render_graphs(rows: list[dict]) -> None:
    if not rows:
        return
    GRAPHS_DIR.mkdir(parents=True, exist_ok=True)
    times = _parse_times(rows)
    t0, t1 = times[0], times[-1]

    fig, ax = plt.subplots(figsize=(11, 5))
    _shade_rem_bursts(ax, t0, t1)
    ax.plot(times, _series(rows, "facts_rem_pending"), marker="o", label="facts REM pending")
    ax.plot(times, _series(rows, "facts_unconsolidated"), marker="s", label="facts unconsolidated")
    ax.plot(times, _series(rows, "decisions_rem_pending"), marker="^", label="decisions REM pending")
    ax.set_title("Dream-cycle backlog (shaded bands = 120 s REM poll windows)")
    ax.set_ylabel("count")
    ax.legend(loc="upper right")
    ax.grid(True, alpha=0.3)
    _style_time_axis(ax, times)
    fig.tight_layout()
    fig.savefig(GRAPHS_DIR / "backlog.png", dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(times, _series(rows, "outbox_applied"), marker="o", label="applied")
    ax.plot(times, _series(rows, "outbox_rem_reviewed"), marker="s", label="rem_reviewed")
    ax.plot(times, _series(rows, "outbox_failed"), marker="x", color="crimson", label="failed")
    ax.set_title("Neo4j outbox progress")
    ax.set_ylabel("count")
    ax.legend()
    ax.grid(True, alpha=0.3)
    _style_time_axis(ax, times)
    fig.tight_layout()
    fig.savefig(GRAPHS_DIR / "outbox.png", dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(times, _series(rows, "technical_docs"), marker="o", label="technical_docs")
    ax.plot(times, _series(rows, "facts_total"), marker="s", label="facts total")
    ax.plot(times, _series(rows, "decisions_total"), marker="^", label="decisions total")
    ax.plot(times, _series(rows, "summaries_total"), marker="d", label="community summaries")
    ax.set_title("Corpus growth")
    ax.set_ylabel("count")
    ax.legend()
    ax.grid(True, alpha=0.3)
    _style_time_axis(ax, times)
    fig.tight_layout()
    fig.savefig(GRAPHS_DIR / "growth.png", dpi=140)
    plt.close(fig)

    if len(rows) >= 2:
        deltas = []
        for i in range(1, len(rows)):
            prev, cur = rows[i - 1], rows[i]
            deltas.append({
                "time": datetime.fromisoformat(cur["collected_at"]),
                "rem_pending_delta": (prev.get("facts_rem_pending") or 0)
                - (cur.get("facts_rem_pending") or 0),
                "decisions_rem_delta": (prev.get("decisions_rem_pending") or 0)
                - (cur.get("decisions_rem_pending") or 0),
                "applied_delta": (cur.get("outbox_applied") or 0)
                - (prev.get("outbox_applied") or 0),
                "summaries_delta": (cur.get("summaries_total") or 0)
                - (prev.get("summaries_total") or 0),
            })

        d_times = [d["time"] for d in deltas]
        fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True)

        ax = axes[0]
        _shade_rem_bursts(ax, d_times[0], d_times[-1])
        ax.bar(d_times, [d["rem_pending_delta"] for d in deltas], width=0.003,
               label="facts REM pending cleared", alpha=0.85)
        ax.bar(d_times, [d["decisions_rem_delta"] for d in deltas], width=0.003,
               label="decisions REM pending cleared", alpha=0.55)
        ax.axhline(
            MAX_REM_PER_INTERVAL, color="gray", linestyle="--", linewidth=1,
            label=f"max REM throughput / {POLL_INTERVAL_S // 60} min (~{MAX_REM_PER_INTERVAL})",
        )
        ax.set_ylabel("items cleared")
        ax.set_title(
            f"Backlog cleared per {POLL_INTERVAL_S // 60}-min sample "
            f"(REM: batch {REM_BATCH} every {REM_POLL_S}s)"
        )
        ax.legend(loc="upper right", fontsize=8)
        ax.grid(True, alpha=0.3)

        ax = axes[1]
        ax.bar(d_times, [d["applied_delta"] for d in deltas], width=0.003,
               label="outbox applied", alpha=0.85)
        ax.bar(d_times, [d["summaries_delta"] for d in deltas], width=0.003,
               label="new summaries", alpha=0.55)
        ax.set_ylabel("items added")
        ax.set_title("Pipeline additions per interval")
        ax.legend(loc="upper right", fontsize=8)
        ax.grid(True, alpha=0.3)
        _style_time_axis(ax, d_times)
        fig.tight_layout()
        fig.savefig(GRAPHS_DIR / "progress_deltas.png", dpi=140)
        plt.close(fig)

    _render_status_panel(rows)