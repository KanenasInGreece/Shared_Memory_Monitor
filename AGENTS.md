# AGENTS.md

Rules for coding agents changing this repository. **Asked to install, upgrade or
uninstall the monitor? Follow [`OPERATE.md`](OPERATE.md) instead.**

A read-only dashboard over a Shared Memory gateway: it polls the gateway, stores
samples in SQLite and serves a UI on `127.0.0.1:8765`.

## Commands

```bash
uv sync
uv run --with pytest python -m pytest -q
./scripts/check-env.sh                      # doctor; never prints secrets
./scripts/run-loop.sh --serve --interval 600
./scripts/pre-publish-check.sh              # version pins + tests; must pass before a release
```

## Invariants

| Concern | Where |
|---------|-------|
| The only gateway HTTP client (`/health`, `/memory/telemetry`, `/pool/status`, read-only `/memory/graph`) | `src/sm_telemetry_monitor/bridge.py` |
| Env precedence: the monitor `.env` wins for token and URL | `env_loader.py` |
| Doctor and feature readiness | `doctor.py`, `scripts/check-env.sh` |
| Health verdict and the LLM pool | `system_health.py` |
| Poll cache | `collector.py`, `store.py` |
| HTTP server and UI | `server.py`, `static/` |
| Logs: the journal and audit JSONL only | `logs_reader.py` |

- Everything on screen comes from the gateway through `bridge.py` or from the framework's
  log files through `logs_reader.py`. When a number is missing, the fix belongs in the
  framework's telemetry, never in a monitor-side database or metrics API.
- No Postgres or Neo4j credentials, no framework imports, no LLM API keys.
- `/health` is the verdict and `/memory/telemetry` is the numbers. Never derive a
  health state from counts the gateway has already judged.
- The server binds loopback and has no auth of its own. Widening the bind publishes an
  unauthenticated ops tool.

## Boundaries

- Write only inside this checkout. Outside it, use only `systemctl --user`,
  `journalctl` and `curl` to `:8888`/`:8765`.
- Never commit `.env`, `data/`, `graphs/`, `.venv/` or a token, and never print a token.
- The workstation constitutions (`CLAUDE.md`, `GEMINI.md`, `OPENCODE.md`) are gitignored
  and hold the cycle, review and seat rules. Do not copy them here.

## Writing text agents read

This follows framework decision:2751, the consolidated rules for agent-read text.
- A comment is one or two sentences that keep the mechanism and the reason.
- Leave an already-clear one-line comment unchanged.
- Gloss every `fact:N` or `decision:N` you cite.
- Never shorten away a prohibition or the reason it exists.
- Delete review-round archaeology.
- Wrap at about 88 columns.
- A comment-only change must leave the AST unchanged once docstrings are blanked.
- Each file has one job: `OPERATE.md` runs the monitor, this file changes it, and
  `README.md` is the maintainer's voice (propose README edits, do not apply them).

## Releases

1. Bump the version everywhere `pre-publish-check.sh` checks: `pyproject.toml`,
   `src/sm_telemetry_monitor/__init__.py`, `CHANGELOG.md`, `README.md`, the `--ref` example in
   `OPERATE.md` and `docs/SISTER_PROJECT.md`.
2. `./scripts/pre-publish-check.sh` must pass.
3. If a page's layout changed, refresh `docs/images/*.png` (`scripts/capture-screenshots.sh`).
4. `uv build`, then `gh release create vX.Y.Z dist/*`.

Update `CHANGELOG.md` for every user-visible change.
