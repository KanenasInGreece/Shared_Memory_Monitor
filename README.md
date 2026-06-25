# Shared Memory Monitor

> Read-only operations UI for the [Shared Memory Framework](https://github.com/KanenasInGreece/Shared_Memory) REM/NREM dream cycle — **http://127.0.0.1:8765/**

## Contents

- [What this is](#what-this-is)
- [Screenshots](#screenshots)
- [Quick start](#quick-start)
- [Prerequisites](#prerequisites)
- [Architecture](#architecture)
- [Pages in detail](#pages-in-detail)
- [Configuration](#configuration)
- [Run modes](#run-modes)
- [HTTP API](#http-api)
- [Data on disk](#data-on-disk)
- [Metrics](#metrics)
- [systemd service](#systemd-service)
- [Project layout](#project-layout)
- [Troubleshooting](#troubleshooting)
- [Docs & release](#docs--release)
- [Related](#related)
- [License](#license)

---

## What this is

**Shared Memory Monitor** is a sister project to the framework — a read-only **view** over **gateway telemetry** and **framework logs**. It does not own memory stores, daemons, or a separate metrics API.

| | Framework | Monitor (this repo) |
|---|-----------|---------------------|
| **Role** | Memory layer — gateway, daemons, Postgres, Neo4j | Presents telemetry + logs |
| **Agent surface** | `memory_bridge.py` skill / MCP | Two clients only: `bridge.py`, `logs_reader.py` |
| **Credentials** | Full gateway + DB secrets on gateway host | `monitor:read` token in monitor `.env` only |
| **Upstream data** | Serves telemetry; writes journal + audit JSONL | Reads those directly — never Postgres/Neo4j |

Three browser views (**Monitor**, **Diagram**, **Logs**) over the **same two upstream sources**:

| Upstream | Code | Framework exposes |
|----------|------|-------------------|
| **Gateway telemetry** | `bridge.py` | `GET /memory/telemetry`, `GET /health`, `POST /memory/graph` |
| **Framework logs** | `logs_reader.py` | `journalctl --user` + `rem-audit.jsonl` + `agent-audit.jsonl` |

| On screen | Traces to |
|-----------|-----------|
| Backlog, outbox, NREM, charts, hero | `GET /memory/telemetry` (cached in `data/telemetry.db` between polls) |
| Infrastructure, diagram node health | `GET /health` |
| Schema Neo4j panels | `POST /memory/graph` |
| Schema Postgres panels | `telemetry.breakdown` in the telemetry payload |
| Log panes | Journal + audit files the framework writes |
| Diagram agent/daemon flows | Same `agent-audit.jsonl` as the **Agent audit** log tab |

`data/telemetry.db` caches past telemetry responses — not a third source. `:8765` `/api/*` routes are **UI transport** to the browser.

See [docs/SISTER_PROJECT.md](docs/SISTER_PROJECT.md) for the sister-repo contract.

---

## Screenshots

Captured from a running monitor (`./scripts/capture-screenshots.sh`).

### Monitor (`/`)

Backlog charts, pipeline queues, and infrastructure health from gateway telemetry (cached polls + live `GET /health`). Range selector (`1h`–`all`) filters the local poll cache.

![Monitor — backlog charts, pipeline queues, infrastructure health](docs/images/dashboard.png)

### Schema breakdown (side drawer)

Opens from **Schema breakdown** in the sidebar — a slide-over panel on the right, not a separate page. Neo4j graph from `POST /memory/graph`; Postgres inventory from `telemetry.breakdown`.

![Schema breakdown — Neo4j labels, graph paths, telemetry record types and domains](docs/images/schema-breakdown.png)

### Diagram (`/diagram`)

Live framework topology: agents → gateway; REM/NREM ↔ gateway; memory and inference via gateway buses. Node counts from telemetry; health from `GET /health`; flow lines from telemetry deltas + agent-audit JSONL.

![Diagram — agent layer, gateway cluster, memory lanes, inference backends](docs/images/diagram.png)

### Logs (`/logs?source=agent_audit`)

**Agent audit** tab: per-request `agent`, route, `status`, latency from `agent-audit.jsonl`. Also **Gateway daemons** (journal) and **REM audit** (outbox JSONL).

![Logs — Agent audit with filter chips and formatted request lines](docs/images/logs.png)

---

## Quick start

```bash
git clone https://github.com/KanenasInGreece/Shared_Memory_Monitor.git
cd Shared_Memory_Monitor
./scripts/install.sh
```

### Gateway token (issued by the framework)

`AGENT_TOKEN` is **not** an agent skill token. The [Shared Memory Framework](https://github.com/KanenasInGreece/Shared_Memory) ships a dedicated **`monitor`** identity for this dashboard: register it in gateway `AGENT_TOKENS`, assign **`monitor:read`** in `AGENT_ROLES`, and copy the minted token here. That role is read-only — `GET /health`, `GET /memory/telemetry`, and guarded `POST /memory/graph` only; `POST /memory/save` and search return **403**.

**How to mint it** (on the gateway host): run the framework's [`generate_tokens.py`](https://github.com/KanenasInGreece/Shared_Memory/blob/main/shared-memory/scripts/generate_tokens.py) (or `bootstrap_tokens.sh` on a fresh install). It prints `AGENT_TOKENS=...,monitor:tok_...` and `AGENT_ROLES=monitor:read`. Add those lines to the **gateway** `.env`, restart `hive-mind-gateway.service`, then paste the `monitor` token below.

Details: [Framework SECURITY.md — read-only roles (`AGENT_ROLES`)](https://github.com/KanenasInGreece/Shared_Memory/blob/main/SECURITY.md#agent-authentication--implemented-v035).

Edit **this repo's** `.env` (monitor `.env` wins over framework/skill copies for `AGENT_TOKEN` and `COORDINATOR_URL`):

```bash
AGENT_TOKEN=tok_...                  # monitor token from framework generate_tokens.py
COORDINATOR_URL=http://localhost:8888
# SHARED_MEMORY_ROOT=/path/to/framework   # optional — audit log path discovery
```

```bash
curl -s http://localhost:8888/health | head -c 200
./scripts/check-env.sh               # expect: monitor token, telemetry ok, read_role ok
./scripts/run-loop.sh --serve --interval 600
```

Open **http://127.0.0.1:8765/**

| Path | Page |
|------|------|
| `/` | Pipeline dashboard (+ schema drawer) |
| `/diagram` | Framework topology |
| `/logs` | Journal + audit tail (3s refresh) |

---

## Prerequisites

### Gateway HTTP (required)

| Item | Notes |
|------|-------|
| Framework gateway running | `hive-mind-gateway.service` (user unit) |
| `COORDINATOR_URL` reachable | Default `http://localhost:8888` |
| **`monitor:read` token** | Framework-issued read-only identity — see [Quick start](#gateway-token-issued-by-the-framework) |
| `telemetry.nrem` + `telemetry.breakdown` | Phase 3 coordinator fields — upgrade gateway if `check` reports missing |
| `telemetry.consolidation` + `/health.consolidation` | ADR-018 consolidation signal (v0.4.7+) — upgrade gateway if `check` reports `has_consolidation: false` |
| Python 3.11+ and [uv](https://docs.astral.sh/uv/) | `uv sync` / CLI |

### Local logs (required for `/logs` and diagram flows; same host as gateway in practice)

| Item | Default path / command |
|------|----------------------|
| Gateway journal | `journalctl --user -u hive-mind-gateway.service` |
| REM audit | `~/.shared-memory/logs/rem-audit.jsonl` (`AUDIT_LOG_PATH`) |
| Agent audit | `~/.shared-memory/logs/agent-audit.jsonl` (`GATEWAY_AUDIT_LOG_PATH` on framework) |

### Local backups (optional — Status sidebar “Last” date)

| Item | Default / notes |
|------|-----------------|
| Backup manifests | `~/.shared-memory/backups/sm-backup-*.manifest.json` (`BACKUP_DIR` on framework host) |
| Monitor override | Set `BACKUP_DIR` in monitor `.env` when manifests live outside the default path |

The **Backup** card lights when `backup_in_progress` is true on `GET /health`. The **Last** line is the `created` timestamp from the newest manifest — not yet on `/health`. If the directory is missing or empty, the UI shows **Last never**.

### Not required

Postgres/Neo4j credentials, `memory_bridge.py`, or a framework checkout on the monitor machine (only URL + token required for HTTP plane).

### Optional

`SHARED_MEMORY_ROOT` / `SM_GATEWAY_ENV` (non-default log paths), `BACKUP_DIR` (non-default backup manifest path), `loginctl enable-linger`, `SM_IGNORED_OUTBOX_IDS`, remote monitor (HTTP works over network; logs and backup manifests need local paths).

---

## Architecture

Two read clients, one web server, one poll cache. **No other I/O paths.**

```mermaid
flowchart TB
  subgraph fw [Framework — gateway host]
    GW[Gateway :8888]
    TEL["GET /memory/telemetry"]
    HLTH["GET /health"]
    GRP["POST /memory/graph"]
    JRN[journalctl user unit]
    REMF[rem-audit.jsonl]
    AGF[agent-audit.jsonl]
    GW --- TEL & HLTH & GRP
  end

  subgraph mon [Monitor :8765 — presentation only]
    BR[bridge.py]
    LR[logs_reader.py]
    LOOP[Poll loop ~600s]
    DB[(telemetry poll cache)]
    SRV[server.py + static UI]
    BR --> TEL & HLTH & GRP
    LR --> JRN & REMF & AGF
    LOOP --> BR
    LOOP --> DB
    DB --> SRV
    BR --> SRV
    LR --> SRV
  end

  SRV --> UI[Monitor · Diagram · Logs]
```

| Module | Upstream | Role |
|--------|----------|------|
| `bridge.py` | Gateway `:8888` | Sole telemetry client — `get_telemetry()`, `get_health()`, `query_graph()` |
| `logs_reader.py` | Journal + JSONL | Sole log client — `tail_source()`, `agent_activity()` |
| `collector.py` + `store.py` | Via `bridge.py` | Append telemetry JSON to poll cache |
| `server.py` + `static/` | Via bridge + logs_reader | Serve cached/live telemetry and log bytes to the browser |
| `analytics.py`, `system_health.py` | Telemetry JSON only | Display formatting — no extra fetches |

Charts read the **poll cache** (past `GET /memory/telemetry` responses). Live panels call `bridge.py` or `logs_reader.py` directly.

| Page | Gateway telemetry | Framework logs |
|------|-------------------|----------------|
| **Monitor** charts, hero, backlog | ✓ cached `GET /memory/telemetry` | — |
| **Monitor** infrastructure | ✓ `GET /health` | — |
| **Monitor** schema drawer | ✓ telemetry + `POST /memory/graph` | — |
| **Diagram** node metrics | ✓ telemetry + `GET /health` | — |
| **Diagram** flow lines | ✓ telemetry interval deltas | ✓ agent-audit JSONL |
| **Logs** | — | ✓ journal + REM + agent JSONL |

---

## Pages in detail

### Monitor dashboard (`/`)

| Control / block | Upstream |
|-----------------|----------|
| **Range** (`1h`–`all`) | Filters cached telemetry polls |
| **Hero** headline | Derived labels from cached telemetry JSON |
| **Sidebar Status** pill | `GET /health` |
| **Backup** card | `GET /health` (`backup_in_progress`) + latest `sm-backup-*.manifest.json` in `BACKUP_DIR` |
| **Consolidation** card | `GET /health` → `consolidation` (cached liveness); click opens drill-down from `telemetry.consolidation` |
| **Dream backlog** | `rem_backlog + nrem_backlog` telemetry fields |
| **Pipeline queues** | Telemetry postgres/neo4j/outbox fields |
| **Infrastructure** grid | `GET /health` component blocks |
| **Schema breakdown** drawer | `telemetry.breakdown` + `POST /memory/graph` |

Main charts: backlog over time, throughput, cumulative cleared, tier-3 growth & errors, raw samples table.

### Framework topology (`/diagram`)

```
  Agent layer          Claude · Grok · Codex · Antigravity · LM Studio · HTTP
         │  bottom read/write ports
         ▼
  Gateway cluster      REM daemon ═══ Hive-Mind Gateway + Coordinator ═══ NREM daemon
         ├─ Memory bus ──┬─ PostgreSQL + pgvector ═ Outbox·REM·NREM ═ Neo4j
         └─ Inference bus ─ Reasoning LLM · Embedder · Reranker (proxied)
```

| Layer | Shown from |
|-------|------------|
| **Agents** | `agent-audit.jsonl` |
| **Gateway** | `GET /health` + telemetry backlog fields |
| **Memory** | Telemetry postgres/neo4j counts |
| **Inference** | `GET /health` embedder/reranker/llm blocks |

**Legend:** OK · Active · Waiting · Backlog · Down — flows Write (red) · Read (green) · Logic (blue).

**Replay:** Slider steps stored polls (~10 min). Caption under slider shows live vs replay window. Health polling pauses while scrubbing.

### Logs (`/logs`)

| Tab | Source | Format |
|-----|--------|--------|
| **Gateway daemons** | `journalctl --user -u hive-mind-gateway.service` | Plaintext journal |
| **REM audit** | `AUDIT_LOG_PATH` | JSONL outbox reviews |
| **Agent audit** | `GATEWAY_AUDIT_LOG_PATH` | JSONL per-request audit |

Controls: **Follow** / **Pause**, since/until filters, **File** picker (live + `.gz` archives), agent filter chips (agent audit), **Consolidation** filter chip (gateway journal). Deep links: `/logs?source=agent_audit`, `/logs?source=gateway&consolidation=1`.

Gateway journal lines for consolidation observability are severity-colored: `Consolidation run […] CRASHED` (error), `deferring` / `health refresh failed` (warn), completed runs (info).

---

## Configuration

| Variable | Required | Purpose |
|----------|----------|---------|
| `AGENT_TOKEN` | ✓ | `monitor:read` bearer token |
| `COORDINATOR_URL` | ✓ | Gateway base URL (default `:8888`) |
| `SHARED_MEMORY_ROOT` | | Discover audit paths from framework `.env` |
| `SM_GATEWAY_ENV` | | Explicit gateway `.env` for log paths |
| `SM_JOURNAL_UNIT` | | Journal unit (default `hive-mind-gateway.service`) |
| `AUDIT_LOG_PATH` | | REM audit JSONL |
| `GATEWAY_AUDIT_LOG_PATH` | | Agent audit JSONL |
| `BACKUP_DIR` | | Directory of `sm-backup-*.manifest.json` for sidebar **Last** backup date (default `~/.shared-memory/backups`; auto-discovered from framework `.env` via `SHARED_MEMORY_ROOT`) |
| `NEO4J_BROWSER_URL` | | Neo4j Browser tab link |
| `SM_IGNORED_OUTBOX_IDS` | | Stale outbox IDs excluded from alerts (default `4`) |

```bash
./scripts/check-env.sh          # human report
./scripts/check-env.sh --json   # machine-readable
uv run python -m sm_telemetry_monitor check
```

Copy `.env.example` → `.env`. Never commit `.env` or tokens.

---

## Run modes

```bash
./scripts/run-loop.sh --serve --interval 600   # recommended
./scripts/run-loop.sh --interval 600           # poll only → data/ + graphs/
./scripts/serve.sh                             # UI only (uses existing data/)
uv run python -m sm_telemetry_monitor --once   # single poll
```

```
uv run python -m sm_telemetry_monitor [loop|serve|check] [--interval N] [--serve] [--once] [--open] [--json]
```

Entry point alias: `sm-telemetry`

---

## HTTP API

**UI transport only** — every data endpoint proxies `bridge.py` or `logs_reader.py`.

| Endpoint | Upstream |
|----------|----------|
| `GET /api/meta` | Poll config (not framework data) |
| `GET /api/summary` | Latest cached telemetry poll + display story |
| `GET /api/history?range=&bucket=` | Cached telemetry polls |
| `GET /api/health` | `bridge.get_health()` + `telemetry.consolidation` → enriched infrastructure + consolidation tile |
| `GET /api/consolidation` | Live consolidation drill-down (`consolidation.py`) |
| `GET /api/breakdown` | `bridge.get_telemetry()` + `bridge.query_graph()` |
| `GET /api/diagram` | Cached telemetry + `bridge.get_health()` |
| `GET /api/diagram/agent-activity?since=&until=` | `logs_reader.agent_activity()` → `agent-audit.jsonl` |
| `GET /api/logs/tail` etc. | `logs_reader.tail_source()` → journal or JSONL |

---

## Data on disk

| Path | What it is |
|------|------------|
| `data/telemetry.db` | **Poll cache** — copies of `GET /memory/telemetry` (+ health per poll) |
| `data/telemetry.jsonl` | Same cache, JSONL export |
| `graphs/*.png` | Renders from cached telemetry |

Duplicate polls within 60s with identical telemetry are skipped.

---

## Metrics

All fields are **telemetry JSON keys** from `GET /memory/telemetry` (display-derived where noted).

| Field | Meaning |
|-------|---------|
| `rem_backlog` | `facts_rem_pending + decisions_rem_pending` |
| `nrem_backlog` | Pending NREM **consolidation cycles** (not raw fact count) |
| `dream_backlog` | `rem_backlog + nrem_backlog` |
| `facts_unconsolidated` | Diagnostic raw count — **not** queue depth |
| `outbox_failed` | Failures minus `SM_IGNORED_OUTBOX_IDS` |

NREM counts come from `telemetry.nrem` on the gateway — the monitor only displays and caches them. Fallback estimate (`facts_unconsolidated // 5`) when `telemetry.nrem` is absent.

| UI label | Field |
|----------|-------|
| Sidebar / chart **NREM** | `nrem_backlog` (cycles) |
| **NREM facts** | `facts_unconsolidated` (raw) |

### Consolidation signal (ADR-018, gateway v0.4.12+)

Requires framework gateway with `telemetry.consolidation` and cached `/health.consolidation`.

| Source | Field | Meaning |
|--------|-------|---------|
| `/health` (cached ~60s) | `consolidation.stalled` | **Red alert** — eligible backlog, no fold within stall threshold, nothing in-flight |
| `/health` | `consolidation.fresh` | `false` → show **signal stale**; do not trust `stalled` |
| `/health` | `consolidation.last_outcome` | `completed` \| `crashed` \| `deferred` \| null |
| `telemetry.consolidation` | `insight` / `fact_consolidation` | Per-cycle outcome, in-flight, failures, `last_error`, coverage |
| `telemetry.consolidation.*.backlog` | strict-gate `eligible_clusters` | **Not** the same as `telemetry.nrem` density cycles |

`decision_cycles > 0` with `eligible_clusters = 0` is normal (cluster fails strict insight gate) — not a stall.

Correlate stalls in the **Gateway daemons** log tab (Consolidation filter): `CRASHED` (code bug), repeated `deferring` (GPU/backup), or `health refresh failed` (stale signal).

---

## systemd service

```bash
./scripts/install-systemd-user.sh    # template: deploy/systemd/user/shared-memory-monitor.service
```

Requires user linger for persistence after logout. Put `AGENT_TOKEN` + `COORDINATOR_URL` in monitor `.env`. See [deploy/README.md](deploy/README.md).

---

## Project layout

```
shared-memory-monitor/
├── static/                 # browser UI (fetches :8765 /api/* only)
├── src/sm_telemetry_monitor/
│   ├── bridge.py           # gateway client → telemetry / health / graph
│   ├── logs_reader.py      # log client → journal + audit JSONL
│   ├── collector.py        # poll loop: bridge → cache
│   ├── store.py            # telemetry poll cache (SQLite/JSONL)
│   ├── analytics.py        # display formatting of telemetry fields
│   ├── system_health.py    # display formatting of GET /health
│   ├── consolidation.py    # ADR-018 liveness + coverage formatting
│   ├── breakdown.py        # bridge telemetry + graph for schema drawer
│   ├── server.py           # UI transport (:8765)
│   ├── doctor.py           # wiring check
│   └── cli.py
├── scripts/                # install, run-loop, capture-screenshots, publish
├── docs/images/            # README screenshots
└── data/                   # runtime (gitignored)
```

Regenerate screenshots: `./scripts/capture-screenshots.sh` (Playwright; monitor must be running).

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Wiring unclear | `./scripts/check-env.sh` |
| Empty charts | Start poll loop or copy `data/` with history |
| `skill:*` token source | Use dedicated monitor token in monitor `.env` |
| NREM `estimate` source | Upgrade gateway for `telemetry.nrem` |
| Consolidation card shows `—` | Upgrade gateway for ADR-018 `telemetry.consolidation`; run `./scripts/check-env.sh` |
| `fresh=false` on consolidation | Coordinator cache refresh failing — check journal for `consolidation health refresh failed` |
| Empty agent audit | Enable `GATEWAY_AUDIT_LOG_PATH` on gateway; restart gateway |
| Empty gateway log tab | `journalctl --user -u hive-mind-gateway.service -n 5` |
| Port 8765 busy | `fuser -k 8765/tcp` |

---

## Docs & release

| Doc | Topic |
|-----|-------|
| [SISTER_PROJECT.md](docs/SISTER_PROJECT.md) | Framework boundary |
| [CHANGELOG.md](CHANGELOG.md) | Releases |
| [SECURITY.md](SECURITY.md) | Secrets policy |

```bash
./scripts/pre-publish-check.sh && ./scripts/publish.sh
```

---

## Related

- [Shared Memory Framework](https://github.com/KanenasInGreece/Shared_Memory) — gateway, daemons, telemetry API
- **shared-memory skill** — agent CLI; monitor uses the same read routes via `httpx` plus local logs

---

## License

MIT — see [LICENSE](LICENSE). All framework data is read via gateway telemetry (`bridge.py`) or logs (`logs_reader.py`) — no separate monitor interfaces.