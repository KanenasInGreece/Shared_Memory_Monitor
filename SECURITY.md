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

## Network exposure

The default bind address is loopback. If you expose `:8765` beyond localhost, treat it like any internal ops tool — no built-in authentication on the monitor HTTP server.

## Reporting

Open a GitHub security advisory on the monitor repository for vulnerabilities in **this codebase**. Gateway/auth issues in the framework belong in the [Shared Memory Framework](https://github.com/KanenasInGreece/Shared_Memory) repository.