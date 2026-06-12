import os
from pathlib import Path

from .env_loader import bootstrap_env, get

bootstrap_env()

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
DATA_FILE = DATA_DIR / "telemetry.jsonl"
DB_FILE = DATA_DIR / "telemetry.db"
GRAPHS_DIR = ROOT / "graphs"
STATIC_DIR = ROOT / "static"

POLL_INTERVAL_S = 600
REM_POLL_S = 120
REM_BATCH = 5
MAX_REM_PER_INTERVAL = (POLL_INTERVAL_S // REM_POLL_S) * REM_BATCH

# NREM triggers one consolidation cycle per qualifying (entity, domain) cluster.
NREM_FACT_CLUSTER_MIN = 5
NREM_DECISION_CLUSTER_MIN = 2

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8765

NEO4J_BROWSER_URL = get("NEO4J_BROWSER_URL", "http://127.0.0.1:7474") or "http://127.0.0.1:7474"

# Known stale outbox failures (prerelease test rows) — excluded from health alerts.
# Comma-separated neo4j_outbox.id values; default: id 4 (phase2_test).
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