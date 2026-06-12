# Changelog

All notable changes to Shared Memory Monitor are documented here.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.3.4] - 2026-06-12

### Changed

- **Diagram topology** — REM and NREM connect to the gateway only (read · write ·
  logic side ports with bridge gaps); gateway owns all Postgres, Neo4j, and
  inference I/O
- **Gateway infra buses** — separate bottom **Memory** (`mem-read` / `mem-write`)
  and **Inference** (`inf-llm` / `inf-embedder` / `inf-reranker`) connectors;
  memory routes drop vertically to avoid crossing daemon cards
- **Inference backends** — one blue logic line per service (no read/write split
  at the gateway edge)
- **Agent layer** — bottom read/write ports only; removed redundant layer notes
  and skill footers
- **Flow activation** — daemon↔gateway read/write lines light from replay-interval
  evidence or daemon audit, not standing backlog alone; agent audit drives gateway
  memory save/retrieve/outbox paths

### Added

- **`daemon_logic`** in agent-activity API — REM/NREM `/v1/chat/completions` and
  `/v1/embeddings` counts for blue proxy lines

### Fixed

- False always-on REM/NREM read/write connectors when `rem_backlog` /
  `facts_unconsolidated` was nonzero but the last poll window was quiet
- Gateway memory write lines hidden behind daemon cards (left-edge routing →
  bottom `infra-down` paths)
- Inference lines crossing NREM (`infra-right` elbow → `infra-down`)

## [0.3.3] - 2026-06-12

### Added

- **Diagram agent highlighting** — agent layer chips highlight agents active in the
  selected replay interval using agent audit data (green read, red write; daemons
  omitted)
- **`GET /api/diagram/agent-activity`** — per-agent read/write counts for a
  `since`/`until` window (live jsonl + logrotated `.gz` archives)

## [0.3.2] - 2026-06-12

### Changed

- **README** — document agent audit logging (`agent_audit` source, agent filter
  chips, archive picker, `GATEWAY_AUDIT_LOG_PATH` prerequisite on framework host)

## [0.3.1] - 2026-06-12

### Removed

- **`save_logs` tab** — the monitor only reads rotated audit archives on the REM
  and Agent audit sources; per-save `shared_memory_*.log.gz` files remain
  framework-side and are not surfaced as a separate log source

## [0.3.0] - 2026-06-12

### Added

- **Agent audit** log source (`agent_audit`, renamed from `gateway_audit`) — tails
  `GATEWAY_AUDIT_LOG_PATH` (framework env); defaults to `agent-audit.jsonl` with
  legacy `gateway-audit.jsonl` fallback
- **Historical log archives** — `/api/logs/archives` and UI **File** picker for
  logrotated `.gz` next to live REM and agent audit jsonl files
- Portable logrotate example: `deploy/logrotate/shared-memory-audit.example`

### Security

- Archive reads are basename-only and must match discovered files under
  `MEMORY_LOG_PATH` (no path traversal)

## [0.2.0] - 2026-06-12

### Added

- **Gateway audit** log source (`gateway_audit`) — tails `GATEWAY_AUDIT_LOG_PATH`
  (default `~/.shared-memory/logs/gateway-audit.jsonl`) for per-request agent,
  route, status, and latency lines from the hive-mind gateway auth seam
- Logs UI: structured rendering for gateway audit rows; HTTP `status >= 400`
  severity coloring; **agent filter chips** (toggle any agent present in the feed)

## [0.1.0] - 2026-06-10

### Added

- Standalone sister-repo plugin — direct `httpx` to hive-mind gateway (`:8888`)
- Pipeline dashboard, architecture diagram, and live logs UI on `:8765`
- `telemetry.nrem` cycle counts and `telemetry.breakdown` schema panels (no direct Postgres)
- Read-only monitor token support (`monitor:read` role probe in `check`)
- Gateway logs via `journalctl --user -u hive-mind-gateway.service`
- SQLite + JSONL telemetry history, PNG chart exports
- `deploy/systemd/user/` template and `install-systemd-user.sh` for persistent user service
- `pre-publish-check.sh` secret audit for GitHub pushes

### Security

- `.env` and `.grok/` gitignored; doctor never prints credential values
- Error sanitization for tokens and connection strings

[Unreleased]: https://github.com/KanenasInGreece/Shared_Memory_Monitor/compare/v0.3.4...main
[0.3.4]: https://github.com/KanenasInGreece/Shared_Memory_Monitor/releases/tag/v0.3.4
[0.3.3]: https://github.com/KanenasInGreece/Shared_Memory_Monitor/releases/tag/v0.3.3
[0.3.2]: https://github.com/KanenasInGreece/Shared_Memory_Monitor/releases/tag/v0.3.2
[0.3.1]: https://github.com/KanenasInGreece/Shared_Memory_Monitor/releases/tag/v0.3.1
[0.3.0]: https://github.com/KanenasInGreece/Shared_Memory_Monitor/releases/tag/v0.3.0
[0.2.0]: https://github.com/KanenasInGreece/Shared_Memory_Monitor/releases/tag/v0.2.0
[0.1.0]: https://github.com/KanenasInGreece/Shared_Memory_Monitor/releases/tag/v0.1.0