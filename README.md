# Shared Memory Monitor

> **Sister project** to the [Shared Memory Framework](https://github.com/KanenasInGreece/Shared_Memory) — a standalone, read-only operations UI for the REM/NREM dream cycle.

| | Framework | Monitor (this repo) |
|---|-----------|---------------------|
| **Role** | Memory layer — gateway, daemons, Postgres, Neo4j | Observer — charts, health, logs, local history |
| **Agent surface** | `memory_bridge.py` skill / MCP | None — standalone `httpx` in `bridge.py` |
| **Credentials** | Full gateway + DB secrets on gateway host | `monitor:read` token in monitor `.env` only |
| **Telemetry source** | Computes and serves `GET /memory/telemetry` | Polls that route; stores snapshots locally |
| **Logs** | Writes journal + audit JSONL on gateway host | Tails those files + `journalctl --user` |

Serves **http://127.0.0.1:8765/** — three pages: **Monitor** (dashboard), **Diagram** (framework topology), **Logs**.

### Read-only data planes

The monitor never writes to the framework and never connects to Postgres or Neo4j directly.

| Plane | Mechanism | Powers |
|-------|-----------|--------|
| **Gateway HTTP** | Bearer `monitor:read` token → `COORDINATOR_URL` | `GET /memory/telemetry`, `GET /health`, `POST /memory/graph` |
| **Local logs** | `journalctl --user` + JSONL on disk | `/logs` tabs; diagram agent/daemon flows via `agent-audit.jsonl` |

| Data | Source |
|------|--------|
| **Charts, sidebar backlog, raw samples table** | Stored poll snapshots in `data/telemetry.db` |
| **Infrastructure grid, schema breakdown** | Live gateway HTTP on demand |
| **Diagram node badges** | Live `GET /health` + latest stored telemetry |
| **Diagram flow lines** | Poll-interval telemetry deltas + parsed audit JSONL |
| **Log panes** | Local journal / files only — no gateway log API |

See [docs/SISTER_PROJECT.md](docs/SISTER_PROJECT.md) for the sister-repo contract.

---

## Screenshots

Captured from a running monitor (`./scripts/capture-screenshots.sh`).

### Monitor (`/`)

Hero headline and backlog charts from **stored** telemetry polls; sidebar **Status** and **Infrastructure** from live `GET /health`. Range selector (`1h`–`all`) filters SQLite history.

![Monitor — backlog charts, pipeline queues, infrastructure health](docs/images/dashboard.png)

### Diagram (`/diagram`)

Live **framework** layout (not the monitor process diagram below). Gateway-owned I/O: agents → coordinator; REM/NREM daemons ↔ gateway only; memory and inference hops via gateway buses. Flow lines from poll deltas + audit logs. Poll-history scrubber with caption under the slider.

![Diagram — agent layer, gateway cluster, memory lanes, inference backends](docs/images/diagram.png)

### Logs (`/logs?source=agent_audit`)

**Agent audit** tab: per-request `agent`, route, `status`, latency from `agent-audit.jsonl`. Also **Gateway daemons** (journal) and **REM audit** (outbox JSONL). Agent filter chips, **File** archive picker, optional time window.

![Logs — Agent audit with filter chips and formatted request lines](docs/images/logs.png)

---

## Quick start

```bash
git clone https://github.com/KanenasInGreece/Shared_Memory_Monitor.git
cd Shared_Memory_Monitor
./scripts/install.sh
```

Edit `.env` (wins over framework/skill copies for `AGENT_TOKEN` and `COORDINATOR_URL`):

```bash
AGENT_TOKEN=tok_monitor_...          # dedicated monitor:read token
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
| `/` | Pipeline dashboard |
| `/diagram` | Framework topology |
| `/logs` | Journal + audit tail (3s refresh) |

---

## Prerequisites

### Gateway HTTP (required)

| Item | Notes |
|------|-------|
| Framework gateway running | `hive-mind-gateway.service` (user unit) |
| `COORDINATOR_URL` reachable | Default `http://localhost:8888` |
| **`monitor:read` token** | In gateway `AGENT_TOKENS` + `AGENT_ROLES=monitor:read`; copy token to monitor `.env` |
| `telemetry.nrem` + `telemetry.breakdown` | Phase 3 coordinator fields — upgrade gateway if `check` reports missing |
| Python 3.11+ and [uv](https://docs.astral.sh/uv/) | `uv sync` / CLI |

Mint token on gateway host:

```bash
python shared-memory/scripts/generate_tokens.py
# gateway .env: AGENT_TOKENS=...,monitor:tok_...  and  AGENT_ROLES=monitor:read
systemctl --user restart hive-mind-gateway.service
```

### Local logs (required for `/logs` and diagram flows; same host as gateway in practice)

| Item | Default path / command |
|------|----------------------|
| Gateway journal | `journalctl --user -u hive-mind-gateway.service` |
| REM audit | `~/.shared-memory/logs/rem-audit.jsonl` (`AUDIT_LOG_PATH`) |
| Agent audit | `~/.shared-memory/logs/agent-audit.jsonl` (`GATEWAY_AUDIT_LOG_PATH` on framework) |

### Not required

Postgres/Neo4j credentials, `memory_bridge.py`, or a framework checkout on the monitor machine (only URL + token required for HTTP plane).

### Optional

`SHARED_MEMORY_ROOT` / `SM_GATEWAY_ENV` (non-default log paths), `loginctl enable-linger`, `SM_IGNORED_OUTBOX_IDS`, remote monitor (HTTP works over network; logs need local journal/files).

---

## Monitor architecture

How **this repo** observes the framework:

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

  subgraph mon [Monitor :8765]
    LOOP[Poll loop ~600s]
    DB[(SQLite + JSONL)]
    SRV[HTTP server + static UI]
    LOOP -->|monitor:read| TEL
    LOOP --> HLTH
    LOOP --> DB
    DB --> SRV
    SRV -->|30s refresh| HLTH
    SRV -->|60s cache| TEL
    SRV --> GRP
    SRV --> JRN & REMF & AGF
  end

  SRV --> UI[Monitor · Diagram · Logs]
```

| Process | Command | Role |
|---------|---------|------|
| Poll loop | `run-loop.sh` | Telemetry + health → SQLite/JSONL; PNG exports to `graphs/` |
| Web server | `serve.sh` or `--serve` | UI + APIs; live health/breakdown; log tail; charts from SQLite |

Charts do **not** hit the gateway on every page load — run the poll loop (or ship existing `data/`). Health, breakdown, and diagram flows add live gateway and/or log reads.

### What each page reads

| Page | Gateway HTTP | SQLite history | Local logs |
|------|-------------|----------------|------------|
| **Monitor** charts / hero | — | ✓ | — |
| **Monitor** infrastructure | ✓ `/health` | latest snapshot for counts | — |
| **Monitor** schema drawer | ✓ telemetry + graph | — | — |
| **Diagram** nodes | ✓ `/health` | ✓ snapshot / replay window | — |
| **Diagram** flows | — | ✓ interval deltas | ✓ agent + daemon audit |
| **Logs** | — | — | ✓ journal + JSONL |

---

## Framework topology (`/diagram`)

Visual map of the **Shared Memory framework** — live SVG, not a static README image.

```
  Agent layer          Claude · Grok · Codex · Antigravity · LM Studio · HTTP
         │  bottom read/write ports
         ▼
  Gateway cluster      REM daemon ═══ Hive-Mind Gateway + Coordinator ═══ NREM daemon
         │               (daemons ↔ gateway only; gateway owns store + inference I/O)
         ├─ Memory bus ──┬─ PostgreSQL + pgvector ═ Outbox·REM·NREM ═ Neo4j
         └─ Inference bus ─ Reasoning LLM · Embedder · Reranker (proxied, not gateway processes)
         │
  Poll-history scrubber + caption (live vs replay time window)
```

| Layer | Contents | Data |
|-------|----------|------|
| **Agents** | Six client chips | Agent audit → chip highlight; save/retrieve flow lines |
| **Gateway** | REM · coordinator · NREM; `127.0.0.1:8888` inset | `/health` process state, dream backlog, outbox |
| **Memory** | Postgres ↔ lanes (Outbox, REM, NREM) ↔ Neo4j | Telemetry counts; gateway-mediated I/O only |
| **Inference** | LLM, BGE-M3 embedder, BGE-Reranker | `/health` workload; blue logic lines per backend |

**Legend:** node states OK · Active · Waiting · Backlog · Down — flows Write (red) · Read (green) · Logic (blue).

**Flow rules:** Daemon↔gateway read/write need interval telemetry or daemon audit — standing backlog alone does not keep lines lit. Agent saves use the **outbox lane** (Postgres → Neo4j), not a direct gateway→Neo4j write.

**Replay:** Slider steps stored polls (~10 min). Right = live (last interval). Left = cumulative replay from history start. Caption under slider shows mode and timestamps. Health polling pauses while scrubbing.

---

## Logs (`/logs`)

| Tab | Source | Format |
|-----|--------|--------|
| **Gateway daemons** | `journalctl --user -u hive-mind-gateway.service` | Plaintext journal |
| **REM audit** | `AUDIT_LOG_PATH` | JSONL outbox reviews |
| **Agent audit** | `GATEWAY_AUDIT_LOG_PATH` | JSONL per-request audit |

Controls: **Follow** / **Pause**, since/until filters, **File** picker (live + `.gz` archives), agent filter chips (agent audit). Deep link: `/logs?source=agent_audit`.

Diagram `GET /api/diagram/agent-activity` parses the same agent-audit files for flow highlighting — not a gateway route.

---

## Monitor dashboard (`/`)

### Top bar

| Control | Meaning |
|---------|---------|
| **Range** | Chart window: `1h` · `6h` · `24h` · `7d` · `all` |
| **live** | Monitor API reachable |
| **Last updated / samples** | Latest telemetry timestamp and count in range |

### Main + sidebar

| Block | Source |
|-------|--------|
| **Hero** headline | Pipeline story from stored telemetry |
| **Sidebar Status** pill | Live `/api/health` rollup |
| **Dream backlog** | `rem_backlog + nrem_backlog` from latest poll |
| **Bottleneck** | REM vs NREM saturation + ETA hint |
| **Pipeline queues** | Outbox, REM/NREM pending, **NREM cycles** vs **NREM facts (raw)** |
| **Infrastructure** | Gateway, embedder, reranker, LLM, REM, NREM from `/health` |
| **Schema breakdown** drawer | `GET /api/breakdown` — Neo4j graph + `telemetry.breakdown` |

Main charts: backlog over time, throughput, cumulative cleared, tier-3 growth & errors, raw samples table.

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

## HTTP API (`:8765`)

| Endpoint | Source |
|----------|--------|
| `GET /api/meta` | Local config + sample count |
| `GET /api/summary` | Latest SQLite snapshot + story |
| `GET /api/history?range=&bucket=` | SQLite time series (`1h`/`6h`/`24h`/`7d`/`all`) |
| `GET /api/health` | Live gateway `GET /health` |
| `GET /api/breakdown` | Live telemetry + graph (60s cache) |
| `GET /api/diagram` | Summary + health bundle |
| `GET /api/diagram/agent-activity?since=&until=` | Agent-audit JSONL parse |
| `GET /api/logs/sources` | Journal + JSONL source metadata |
| `GET /api/logs/archives?source=` | Live + `.gz` archives |
| `GET /api/logs/tail?source=&lines=&archive=&since=&until=` | Tail journal or JSONL |

---

## Data on disk

| Path | Purpose |
|------|---------|
| `data/telemetry.db` | Primary time-series |
| `data/telemetry.jsonl` | Append export; synced into SQLite |
| `graphs/*.png` | Chart snapshots each poll |
| `graphs/dashboard.html` | Offline dashboard copy |

Duplicate polls within 60s with identical metrics are skipped.

---

## Metrics

| Field | Meaning |
|-------|---------|
| `rem_backlog` | `facts_rem_pending + decisions_rem_pending` |
| `nrem_backlog` | Pending NREM **consolidation cycles** (not raw fact count) |
| `dream_backlog` | `rem_backlog + nrem_backlog` |
| `facts_unconsolidated` | Diagnostic raw count — **not** queue depth |
| `outbox_failed` | Failures minus `SM_IGNORED_OUTBOX_IDS` |

### NREM cycle counting

NREM runs consolidation **cycles** when density thresholds are met (facts ≥5 per `(entity, domain)`; decisions ≥2 per `domain`). The coordinator exposes counts as `telemetry.nrem`; the monitor stores them — it does not recompute. Fallback: `nrem_backlog ≈ facts_unconsolidated // 5` when `telemetry.nrem` is absent.

| UI label | Field |
|----------|-------|
| Sidebar / chart **NREM** | `nrem_backlog` (cycles) |
| **NREM facts** | `facts_unconsolidated` (raw) |

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
├── static/                 # dashboard.html, diagram.html, logs.html, theme.css
├── src/sm_telemetry_monitor/
│   ├── bridge.py           # httpx → gateway (telemetry, health, graph)
│   ├── collector.py        # poll loop flatten + append
│   ├── store.py            # SQLite + JSONL
│   ├── analytics.py        # backlog story, API payloads
│   ├── system_health.py    # /health rollup for UI
│   ├── breakdown.py        # schema drawer
│   ├── logs_reader.py      # journalctl + audit tail + agent_activity
│   ├── server.py           # :8765 HTTP API
│   ├── doctor.py           # check-env / feature matrix
│   └── cli.py              # loop | serve | check
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

## Related

- [Shared Memory Framework](https://github.com/KanenasInGreece/Shared_Memory) — gateway, daemons, telemetry API
- **shared-memory skill** — agent CLI; monitor uses the same read routes via `httpx` plus local logs

## License

MIT — see [LICENSE](LICENSE). Integration is read-only gateway HTTP plus local log/journal access.