# Sister project to Shared Memory

**Shared Memory Monitor** ([`Shared_Memory_Monitor`](https://github.com/KanenasInGreece/Shared_Memory_Monitor)) is an optional **operations plugin** for the [Shared Memory Framework](https://github.com/KanenasInGreece/Shared_Memory). It is maintained as a **separate repository** — not a subpackage inside the framework tree.

## Division of responsibility

| | Shared Memory Framework | Shared Memory Monitor |
|---|------------------------|----------------------|
| **Role** | Memory layer — gateway, REM/NREM daemons, Postgres, Neo4j, consolidation | Operations UI — backlog, health, logs, history |
| **Install** | Gateway host (`hive-mind-gateway.service`) | Any machine that can reach `:8888` |
| **Agent surface** | `memory_bridge.py` skill / MCP (save, search, graph) | None — thin HTTP client only |
| **Credentials** | Full gateway tokens, DB passwords on gateway host | **Read-only** `monitor:read` token in monitor `.env` |
| **Data ownership** | Authoritative stores + `GET /memory/telemetry` | Local SQLite/JSONL history for charts |
| **Coupling** | Framework does not depend on the monitor | Monitor depends only on public HTTP routes |

## Integration surfaces (read-only)

The monitor never imports framework Python code. Two planes:

**Gateway HTTP** (`COORDINATOR_URL` + `monitor:read` token):

| Route | Purpose |
|-------|---------|
| `GET /health` | Infrastructure grid (embedder, LLM, daemons) |
| `GET /memory/telemetry` | Pipeline metrics, `telemetry.nrem`, `telemetry.breakdown` |
| `POST /memory/graph` | Neo4j schema panels (read-only Cypher, server-side guard) |

**Local logs** (filesystem + `journalctl --user` on the monitor host):

| Source | Purpose |
|--------|---------|
| `hive-mind-gateway.service` journal | Gateway daemon stdout |
| `rem-audit.jsonl` | REM outbox audit |
| `agent-audit.jsonl` | Per-request agent audit; diagram flow highlighting |

Framework **Phase 3 telemetry** (`nrem` + `breakdown` on `/memory/telemetry`) means the monitor needs **no direct Postgres** access for metrics or breakdown.

## Deployment pattern

Typical homelab layout:

```
~/shared-memory-GitHub/     ← framework repo (gateway runs here)
~/Shared_Memory_Monitor/    ← this repo (sister checkout)
```

1. Provision gateway + `AGENT_ROLES=monitor:read` on the framework host.
2. Clone this repo, `cp .env.example .env`, set `AGENT_TOKEN` + `COORDINATOR_URL`.
3. `./scripts/install.sh` then optional `./scripts/install-systemd-user.sh` for persistence.

## What this repo is not

- Not a fork or vendor copy of `memory_bridge.py`
- Not required to use Shared Memory (agents can use `memory_bridge.py status` / CLI instead)
- Not a secrets store — `.env` stays local and gitignored

## Further reading

- Root [README.md](../README.md) — prerequisites, quick start, API
- [deploy/README.md](../deploy/README.md) — systemd user unit
- Framework [Documentation/server-setup.md](https://github.com/KanenasInGreece/Shared_Memory) — gateway provisioning