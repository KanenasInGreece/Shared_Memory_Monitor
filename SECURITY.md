# Security policy

## Scope

Shared Memory Monitor is a **local-first** dashboard. It stores telemetry history on disk and serves HTTP on `127.0.0.1:8765` by default.

## Secrets

| Rule | Detail |
|------|--------|
| **Never commit** | `.env`, real `AGENT_TOKEN` values, Postgres/Neo4j passwords |
| **Ship** | `.env.example` with placeholders only |
| **Runtime** | `doctor` / `check` print key *names* and paths, never values |
| **Errors** | `sanitize.py` redacts `tok_*` and `postgresql://` in API/log output |

Before pushing to GitHub, run:

```bash
./scripts/pre-publish-check.sh
```

## Monitor token

Use a **dedicated read-only** gateway identity (`monitor:read`). A leaked monitor token must not be able to call `POST /memory/save`. `sm_telemetry_monitor check` probes this (expects 200 on telemetry, 403 on save).

Do not reuse agent skill tokens (Grok, Claude, etc.) in the monitor `.env`.

## Attack surface — default deny

The monitor is allowed exactly what it needs to watch a local gateway, and nothing else.
Anything not on these lists is absent by construction, not by configuration. If you add a
capability, add it here and say which feature required it.

**Outbound — what the monitor asks of the gateway.** All read. The token is a dedicated
`monitor:read` identity; there are no database drivers in the package and no credentials
for one.

| Call | Why it is needed |
|------|------------------|
| `GET /health` | node states, versions, dependency enums |
| `GET /memory/telemetry` | every number the dashboard renders |
| `GET /pool/status` | LLM pool free slots / per-backend serves_all |
| `POST /memory/graph` | read-only Cypher for the schema drawer (write clauses are refused gateway-side) |

`sm_telemetry_monitor check` additionally sends one deliberately **unsaveable** body to
`POST /memory/save` to prove the write door is shut. It expects `403`. The body is invalid
on purpose, so that the check cannot perform the write it exists to rule out.

**Inbound — what the monitor exposes.** `GET` only; every other method answers `501`
because no other handler exists. Every route below is fetched by one of the three pages;
a route no page calls is removed rather than left listening.

`/` (aliases `/dashboard`, `/dashboard.html`) · `/logs` (`/logs.html`) ·
`/diagram` (`/diagram.html`) · `/static/*` (traversal-guarded) ·
`/api/summary` `/api/health` `/api/consolidation` `/api/latency` `/api/diagram`
`/api/breakdown` `/api/history` `/api/meta` `/api/logs/sources` `/api/logs/archives`
`/api/logs/tail`

**Filesystem.** Reads the gateway journal via `journalctl --user`, the framework's audit
JSONL under the log root, and its own SQLite under `data/`. It writes only `data/`.

**No CORS header is sent.** The dashboard is same-origin; a wildcard would have let any
page the operator happened to visit read this host's telemetry.

**The `Host` header is checked against a loopback allow-list** (`127.0.0.1`, `localhost`,
`[::1]`, plus `SERVER_HOST` when set). Binding loopback stops other hosts reaching the
port; it does not stop DNS rebinding, where a page on any domain re-resolves its own name
to `127.0.0.1` and becomes same-origin. Anything else gets `421`.

**`/api/logs/tail?lines=` is clamped** to `MAX_TAIL_LINES` (5000). A tail is a diagnostic
read, and the value is passed to `journalctl -n`.

`logs_reader.agent_activity()` remains as a library function with **no HTTP route** — it is
covered by tests for the audit-cache and malformed-row paths. Nothing reaches it over the
network; if a route is ever added for it, add it to the list above.

## Dependencies

Runtime dependencies are `httpx` and `matplotlib`. There are no database drivers, and
nothing in the package holds a credential for one.

Audit both the resolved set **and the floors**, because a downstream install is entitled to
any version at or above a declared minimum — a clean lockfile says nothing about what a new
user gets:

```bash
./scripts/audit-deps.sh
```

It checks three things: the resolved set for known advisories, the lowest versions the
declared minimums permit, and whether every declared dependency is actually imported. A
dependency nothing imports is surface with no function; remove it rather than carry its
advisories.

## Network exposure

The default bind address is **loopback** (`127.0.0.1`), and everything the monitor reads is
local, so nothing about its job needs a wider bind. Set `SERVER_HOST` to expose it
deliberately — and treat that as publishing an unauthenticated ops tool, because the
monitor HTTP server has no authentication of its own.

## Reporting

Open a GitHub security advisory on [Shared_Memory_Monitor](https://github.com/KanenasInGreece/Shared_Memory_Monitor/security/advisories/new) for vulnerabilities in **this codebase**. Gateway/auth issues in the framework belong in the [Shared Memory Framework](https://github.com/KanenasInGreece/Shared_Memory) repository.