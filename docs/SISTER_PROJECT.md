# Sister project to Shared Memory

**Shared Memory Monitor** ([`Shared_Memory_Monitor`](https://github.com/KanenasInGreece/Shared_Memory_Monitor)) is an optional **operations plugin** for the [Shared Memory Framework](https://github.com/KanenasInGreece/Shared_Memory). It is maintained as a **separate repository** — not a subpackage inside the framework tree.

## Division of responsibility

| | Shared Memory Framework | Shared Memory Monitor |
|---|------------------------|----------------------|
| **Role** | Memory layer — gateway, daemons, Postgres, Neo4j | Read-only **view** — no separate data interfaces |
| **Install** | Gateway host (`hive-mind-gateway.service`) | Any machine that can reach `:8888` (+ logs on same host in practice) |
| **Agent surface** | `memory_bridge.py` skill / MCP | None — `bridge.py` + `logs_reader.py` only |
| **Credentials** | Full gateway tokens, DB passwords on gateway host | **Read-only** `monitor:read` token in monitor `.env` |
| **Authoritative data** | Telemetry API + log writers | Poll cache of telemetry; live re-read of telemetry + logs |
| **Coupling** | Framework does not depend on the monitor | Monitor depends only on telemetry routes + log files |

## Integration — two upstream sources only

The monitor never imports framework Python code. **No third data path** in monitor code.

**Gateway telemetry** (`bridge.py` → `COORDINATOR_URL` + `monitor:read`):

| Route | Purpose |
|-------|---------|
| `GET /health` | Infrastructure grid (embedder, LLM, daemons) |
| `GET /memory/telemetry` | Pipeline metrics, `telemetry.nrem`, `telemetry.breakdown` |
| `POST /memory/graph` | Neo4j schema panels (read-only Cypher, server-side guard) |

**Framework logs** (`logs_reader.py` → journal + JSONL on monitor host):

| Source | Purpose |
|--------|---------|
| `hive-mind-gateway.service` journal | Gateway daemon stdout |
| `rem-audit.jsonl` | REM outbox audit |
| `agent-audit.jsonl` | Per-request agent audit; diagram flow highlighting |

`data/telemetry.db` caches past `GET /memory/telemetry` responses for charts — it is not a monitor-owned metrics store. `:8765` `/api/*` routes are UI transport over `bridge.py` and `logs_reader.py`.

Framework **Phase 3 telemetry** (`nrem` + `breakdown` on `/memory/telemetry`) means the monitor needs **no direct Postgres** access.

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
- Not a metrics service with its own API or database schema
- Not required to use Shared Memory (agents can use `memory_bridge.py status` / CLI instead)
- Not a secrets store — `.env` stays local and gitignored

## Further reading

- Root [README.md](../README.md) — prerequisites, quick start, API
- [deploy/README.md](../deploy/README.md) — systemd user unit
- Framework [Documentation/server-setup.md](https://github.com/KanenasInGreece/Shared_Memory) — gateway provisioning