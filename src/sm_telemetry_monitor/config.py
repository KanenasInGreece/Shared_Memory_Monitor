"""Paths and thresholds. The bind stays loopback because the server has no auth."""

import os
from pathlib import Path

from .env_loader import bootstrap_env, get, layout_paths

bootstrap_env()

_layout = layout_paths()
ROOT = _layout.monitor_root
DATA_DIR = _layout.data_dir
DATA_FILE = DATA_DIR / "telemetry.jsonl"
DB_FILE = DATA_DIR / "telemetry.db"
GRAPHS_DIR = _layout.graphs_dir
STATIC_DIR = _layout.static_dir

POLL_INTERVAL_S = 600
REM_POLL_S = 120
REM_BATCH = 5
MAX_REM_PER_INTERVAL = (POLL_INTERVAL_S // REM_POLL_S) * REM_BATCH

# A non-empty REM queue is only a stall if the GPU is free yet the backlog has
# not drained for ~2.5 REM sweeps (mirrors NREM's stall threshold). Below this
# span we cannot tell a stall from the normal poll-gap lag, so we never warn.
REM_STALL_WINDOW_S = int(REM_POLL_S * 2.5)  # 300s

# NREM triggers one consolidation cycle per qualifying (entity, domain) cluster.
NREM_FACT_CLUSTER_MIN = 5
NREM_DECISION_CLUSTER_MIN = 2

# Loopback by default. Everything the monitor reads is local — the gateway on
# 127.0.0.1:8888, log files on disk, its own SQLite — so nothing about its job
# requires reaching it from another host, and the dashboard carries no auth.
# Exposing it is therefore a deliberate act: set SERVER_HOST to widen it.
SERVER_HOST = get("SERVER_HOST", "127.0.0.1") or "127.0.0.1"
try:
    SERVER_PORT = int(get("SERVER_PORT", "8765") or "8765")
except ValueError:
    SERVER_PORT = 8765

NEO4J_BROWSER_URL = get("NEO4J_BROWSER_URL", "http://127.0.0.1:7474") or "http://127.0.0.1:7474"

# neo4j_outbox ids recorded on /api/meta. The list is not evidence those rows
# are inside the aggregate failure count, so it is not subtracted from it.
# Comma-separated ids; default: id 4 (phase2_test).
_ignored = os.environ.get("SM_IGNORED_OUTBOX_IDS", "4")
IGNORED_OUTBOX_IDS = tuple(
    int(x.strip()) for x in _ignored.split(",") if x.strip().isdigit()
)

# Telemetry JSON keys charted from cached GET /memory/telemetry polls.
SERIES_KEYS = (
    "dream_backlog",
    "rem_backlog",
    "nrem_backlog",
    "facts_rem_pending",
    "facts_unconsolidated",
    "decisions_rem_pending",
    "facts_consolidated",
    "summaries_total",
    "outbox_applied",
    "outbox_rem_reviewed",
    "outbox_failed",
    "technical_docs",
)