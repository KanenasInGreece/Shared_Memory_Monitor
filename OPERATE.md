# OPERATE.md

Install, upgrade and uninstall the monitor for an operator. Changing the code is
[`AGENTS.md`](AGENTS.md); the product story is [`README.md`](README.md).

The monitor is a read-only view over a Shared Memory gateway that must already be
running. It installs no database, daemon or gateway.

## Rules

1. **Never see the token.** Do not read, print, request or paste `AGENT_TOKEN`. The
   operator issues it and pastes it into `.env` in their own terminal. Nothing un-writes a
   transcript.
2. **Never disable linger.** It is per-user, and the gateway's user unit on the same account
   depends on it.
3. **Ask first** before you delete the checkout or `data/`, stop a process holding `:8765`,
   restart the gateway, or rotate any token.
4. **Start with `./scripts/agent-status.sh` and do what its `next:` line says.** Run only
   the steps that failed. Every script is idempotent and exports `~/.local/bin`, so it works
   over a non-login SSH shell where a bare `uv` does not.

`agent-status.sh` exit codes: `0` ready · `1` partial, or ready with an update on GitHub ·
`2` not ready (token missing or rejected, gateway down). `--json` gives the same data
without secrets; `--offline` skips the GitHub check.

## Install

1. **Ask:** the gateway URL [`http://localhost:8888`], where the checkout goes, whether it
   is the gateway's host (logs and backups are then shown), and whether to run it as a
   systemd user service [yes]. If there is no gateway, stop: install the
   [framework](https://github.com/KanenasInGreece/Shared_Memory) first.
2. **Clone and install:**
   ```bash
   git clone https://github.com/KanenasInGreece/Shared_Memory_Monitor.git
   cd Shared_Memory_Monitor && ./scripts/install.sh
   ```
   This creates `.env` from `.env.example`. Set `COORDINATOR_URL` there if it is not
   the default.
3. **Token.** Hand the operator the steps below. Framework 1.0.4+ refuses `--reveal`
   unless it is run in a terminal.
   ```bash
   # OPERATOR, on the gateway host, in the framework checkout:
   bash shared-memory/scripts/bootstrap_tokens.sh --add monitor --reveal monitor     # first time
   bash shared-memory/scripts/bootstrap_tokens.sh --remint monitor --reveal monitor  # already registered
   # paste the value as AGENT_TOKEN=... into this checkout's .env, then:
   chmod 600 .env
   systemctl --user restart hive-mind-gateway.service   # auth is read at startup
   ```
   Do not use `--install-path` for the monitor: it registers a skill install that
   `sync_skills.sh` would then fill with skill files.
4. **Verify:** `git check-ignore .env` must print `.env`. `./scripts/check-env.sh` must show
   `AGENT_TOKEN source: monitor` and `read_role: ok`.
5. **Run:** `./scripts/install-systemd-user.sh` installs `shared-memory-monitor.service`,
   enables linger and waits for the dashboard. It exits `3` when another process holds
   `:8765`; see rule 3. To run in the foreground instead: `./scripts/run-loop.sh --serve --interval 600`.
6. **Done** when `agent-status.sh` reports `overall: ready` and
   http://127.0.0.1:8765/ answers.

## Upgrade

```bash
./scripts/agent-upgrade.sh                  # fast-forward main, uv sync, restart the unit, status
./scripts/agent-upgrade.sh --ref v0.9.32    # pin a release
```

It refuses a dirty tree. After a restart the process has new code; `.env` changes also
need `systemctl --user restart shared-memory-monitor.service`.

## Uninstall

```bash
./scripts/uninstall-systemd-user.sh   # stops and removes the unit, verifies it is gone
```

The checkout, `.env` and `data/` (poll history) stay. Delete them only when the operator
says so (`rm -rf <checkout>`). The token stays registered on the gateway, so a later
reinstall uses `--remint`.

## When `next:` is not enough

| Symptom | Action |
|---------|--------|
| `Token rejected (HTTP 401)` | Install step 3 with `--remint` (operator) |
| `AGENT_TOKEN source: skill:…` | A skill token was picked up; the monitor `.env` token must win (step 3) |
| `write probe … over-privileged` | The token is not read-only; remint `monitor` (it is always minted `read`) |
| gateway unreachable | Start the gateway, or fix `COORDINATOR_URL` |
| unit active, `:8765` silent | `journalctl --user -u shared-memory-monitor.service -n 50` |
| panel missing in `check-env.sh` | The gateway is older; the UI leaves that band out and nothing fails |

Optional `.env` keys (log paths, backup directory, bind address, retention) are
documented inline in [`.env.example`](.env.example).
