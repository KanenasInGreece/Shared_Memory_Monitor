# Changelog

All notable changes to Shared Memory Monitor are documented here.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
  rotated `.gz` next to live audit files plus `shared_memory_YYYY-MM-DD.log.gz`
  save-log archives (`save_logs` source)
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

[Unreleased]: https://github.com/KanenasInGreece/Shared_Memory_Monitor/compare/v0.3.1...main
[0.3.1]: https://github.com/KanenasInGreece/Shared_Memory_Monitor/releases/tag/v0.3.1
[0.3.0]: https://github.com/KanenasInGreece/Shared_Memory_Monitor/releases/tag/v0.3.0
[0.2.0]: https://github.com/KanenasInGreece/Shared_Memory_Monitor/releases/tag/v0.2.0
[0.1.0]: https://github.com/KanenasInGreece/Shared_Memory_Monitor/releases/tag/v0.1.0