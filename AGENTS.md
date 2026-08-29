# AGENTS.md

**The canonical agent file for this repository.** Codex CLI reads it automatically;
Claude Code, Grok, Antigravity CLI and others are pointed here by `AGENT.md`.

Two missions — pick the one that matches what the user asked for:

- **Operate the monitor** — install, configure, start/stop/status, upgrade on a machine
  that can reach the Shared Memory gateway. Follow **Part 1**. Prefer the helper scripts
  over hand-rolled shell.
- **Develop in this repository** — change monitor code or docs. Follow **Part 2**.

`README.md` remains the human deep reference. Keep README Quick Start, this file, and
`CHANGELOG.md` in sync when setup steps change.

---

# Part 1 — Operate the monitor

This project is a **read-only visual aid** over **existing** Shared Memory gateway
telemetry (`GET /health`, `GET /memory/telemetry`) and framework logs. It does **not**
install Postgres, Neo4j, daemons, or the gateway. The framework must already be (or be
about to be) running on a reachable host — usually the same machine.

## Ground rules

1. **Secrets never enter the conversation or git.** Do not echo `AGENT_TOKEN` values.
   Prefer: user pastes the token into `.env` themselves, or you write it with `chmod 600`
   without printing it. Confirm `git check-ignore .env` before finishing.
2. **Never mint tokens inside this repo.** The `monitor:read` identity is created on the
   **framework / gateway host** (`generate_tokens.py` / `bootstrap_tokens.sh`). This
   dashboard only **consumes** that token.
3. **Verify before acting.** Run `./scripts/agent-status.sh` (or `check-env.sh`) first.
   Only run the phases that failed.
4. **Helper scripts are idempotent** — `install.sh`, `install-systemd-user.sh`,
   `agent-upgrade.sh`, `check-env.sh` are safe to re-run.
5. **No new data paths.** Do not add Postgres/Neo4j credentials or invent metrics APIs.
   Display only what the gateway already exposes.
6. **Ask before destructive actions** — e.g. `fuser -k 8765`, deleting `data/`, rotating
   tokens on the gateway, force-push.

## Smart tools (use these)

| Script | Purpose |
|--------|---------|
| `./scripts/agent-status.sh` | One-shot health **and GitHub update check** (`git ls-remote` origin): git, package, gateway, doctor, unit, dashboard; `updates.updates_available` + `next` upgrade command |
| `./scripts/agent-status.sh --json` | Same as machine-readable JSON (no secrets) |
| `./scripts/agent-status.sh --offline` | Skip origin/GitHub probe (local-only) |
| `./scripts/agent-upgrade.sh` | Status pre-check → `git pull` + `uv sync` + restart unit (if installed) + status |
| `./scripts/install.sh` | First-time: `uv sync`, create `.env` from example, run doctor |
| `./scripts/install-systemd-user.sh` | Persist as `shared-memory-monitor.service` (user unit) |
| `./scripts/uninstall-systemd-user.sh` | Cleanly remove the systemd unit and disable linger |
| `./scripts/check-env.sh` | Full doctor report (human or `--json`) |
| `./scripts/run-loop.sh --serve --interval 600` | Foreground poll + dashboard (dev) |

Exit codes for `agent-status.sh`: **0** ready (and up to date with origin when
checked), **1** partial **or** ready but **updates available** on GitHub, **2** not
ready (missing token, gateway down, etc.). Agents should treat exit **1** with
`updates.updates_available: true` as “run `./scripts/agent-upgrade.sh`”.

---

## First-time setup

### Phase 0 — Interview the user

Collect before writing files. Defaults in brackets are safe to offer.

| # | Ask | Fills |
|---|-----|--------|
| 1 | Is the **Shared Memory gateway** already running somewhere? URL? [`http://localhost:8888`] | `COORDINATOR_URL` |
| 2 | Where should this monitor checkout live? [clone into cwd or path they name] | working directory |
| 3 | Do they already have a **`monitor:read`** token, or must it be minted on the gateway host? | `AGENT_TOKEN` |
| 4 | Same host as gateway (logs + backups available) or remote HTTP-only? | optional `SHARED_MEMORY_ROOT` / log paths |
| 5 | Persist as **systemd user service** (recommended) or foreground only? | install-systemd vs run-loop |
| 6 | *(optional)* Non-default backup dir for sidebar “Last backup”? | `BACKUP_DIR` |

If the gateway is not installed yet, stop and point them at the framework repo
([Shared_Memory](https://github.com/KanenasInGreece/Shared_Memory) `AGENTS.md` Part 1)
or offer to operate the framework first. The monitor cannot substitute for the gateway.

### Phase 1 — Clone and install deps

```bash
git clone https://github.com/KanenasInGreece/Shared_Memory_Monitor.git
cd Shared_Memory_Monitor
./scripts/install.sh
```

Creates `.env` from `.env.example` if missing; runs doctor (may fail until token is set).

### Phase 2 — Wire the monitor token

On the **gateway host** (framework install), mint or re-use the monitor identity:

```bash
# Framework host — example; paths vary by install
python shared-memory/scripts/generate_tokens.py   # or bootstrap_tokens.sh
# Ensure gateway .env has:
#   AGENT_TOKENS=...,monitor:tok_...
#   AGENT_ROLES=monitor:read
# Then: systemctl --user restart hive-mind-gateway.service # (or your specific gateway service name)
```

In **this** repo's gitignored `.env` (never commit):

```bash
AGENT_TOKEN=tok_...                  # monitor token only — not a skill agent token
COORDINATOR_URL=http://localhost:8888
# SHARED_MEMORY_ROOT=/path/to/framework   # optional: discover audit log paths
```

```bash
chmod 600 .env
git check-ignore .env                # MUST print .env
```

Do **not** paste the raw token into chat. If you write the file, confirm success by
`./scripts/check-env.sh` showing `AGENT_TOKEN source: monitor` (or `set`) without
printing the value.

### Phase 3 — Verify wiring

```bash
curl -sf "$COORDINATOR_URL/health" | head -c 200
./scripts/agent-status.sh            # or: ./scripts/check-env.sh
```

Expect: coordinator ok, telemetry ok, `read_role` ok (writes denied), token not borrowed
from a skill identity when possible. `api server=N client=N compat=ok` when gateway
reports `api_version` (this package speaks **API 4**).

On a modern gateway (verified against **framework ≥0.8.9**), doctor should also name
telemetry panels and LLM placement, e.g.:

```text
coordinator: ok · gateway 0.9.15 · api server=4 client=4 compat=ok · 3 LLM backends · llm_pool · pool_status · llm_routing · llm_token_usage · oldest_inflight · suspect_wedged · placement 2 local/1 external
telemetry: ok · nrem+breakdown+consolidation+entity_graph+latency+spine+compliance+graph_integrity+llm_faults+credentials
```

| Doctor signal | What the user sees on the dashboard |
|---------------|-------------------------------------|
| `oldest_inflight` | Hung-call age surfaced in pool summary and LLM caption (**≥ 0.9.15**) |
| `suspect_wedged` | Wedge suspect labels render as warn on the LLM pool chips (**≥ 0.9.15**) |
| `placement local` / `external` | Infrastructure config line + **LLM pool** chips badge local/external (`has_credential`) |
| `llm_pool` | Multi-backend pool panel (in-flight / routed % / free) |
| `nrem` + `breakdown` | Backlog / NREM + Schema drawer Postgres panels |
| `consolidation` | Consolidation tile + drawer |
| `entity_graph` | Graph health band in Consolidation drawer |
| `latency` | Throughput & latency drawer; **≥ 0.9.60** `wall_ms` / `n_service` / `timing_source` (`server`\|`wall`\|`mixed`) so external models are listed with N/A service columns |
| `spine` / `compliance` | First-write quality / schema conformance bands |
| `graph_integrity` | Graph integrity band in Schema drawer (write-path defect detection) |
| `llm_faults` | Per-backend fault counts on pool chips (framework **≥ 0.9.4**) |
| `credentials` | Own-door `token_verify_failed` / `audit_log_dropped` on the Infrastructure gateway hint (front door); **≥ 0.9.9** `credentialed_route_denied` on the LLM pool line; **≥ 0.9.8** pairs each with `*_last_ts` age |
| `llm_routing` / `llm_token_usage` | Pool-line role totals + refuse warns; chip-popover token totals (framework **≥ 0.9.13**) |
| `pool_status` | `N dream-ready` from `GET /pool/status` `free_slots`; `serves_all` / `counts_free_slot` on chips (framework **≥ 0.9.13**) |

Missing panel names mean an older gateway — the UI degrades (omits bands), not a hard fail.
`placement n/a (gateway <0.8.9)` means config backends exist but without `has_credential`.

### Phase 4 — Start

**Foreground (dev):**

```bash
./scripts/run-loop.sh --serve --interval 600
```

**Persistent user service (recommended on Linux):**

```bash
./scripts/install-systemd-user.sh
# optional: loginctl enable-linger "$USER"   # survive logout
systemctl --user status shared-memory-monitor.service
```

Open **http://127.0.0.1:8765/** (`/diagram`, `/logs`).

### Phase 5 — Smoke

```bash
./scripts/agent-status.sh
curl -sf http://127.0.0.1:8765/api/meta | head -c 200
curl -sf http://127.0.0.1:8765/api/health | python3 -c "
import sys, json
d = json.load(sys.stdin)
cfg = d.get('config') or {}
print('summary:', cfg.get('summary'))
print('backends:', [(b.get('label'), b.get('placement'), b.get('model'))
                    for b in (cfg.get('backends') or [])])
pool = d.get('llm_pool') or {}
print('pool placement:', [(b.get('label'), b.get('placement'))
                          for b in (pool.get('backends') or [])])
"
```

Report: unit active (if installed), dashboard HTTP 200, doctor features green enough
for the user's setup (logs optional if remote). On gateway ≥0.8.9, `config.summary`
should include `local` and/or `external`; pool chips carry the same `placement`.
Open **http://127.0.0.1:8765/** and confirm Infrastructure + **LLM pool** match that.

---

## Day-2 runbooks

### Status (always start here)

```bash
./scripts/agent-status.sh              # includes GitHub update check via origin
./scripts/agent-status.sh --json       # updates.behind_branch / behind_release / upgrade_cmd
./scripts/agent-status.sh --offline    # no network
```

Update detection uses `git ls-remote` against `origin` (does not rewrite local refs):
compares `HEAD` to `origin/<branch>` and the package version to the newest `vX.Y.Z` tag.

### Restart after `.env` or code change

Long-running processes do **not** hot-reload:

```bash
systemctl --user restart shared-memory-monitor.service
journalctl --user -u shared-memory-monitor.service -n 30 --no-pager
```

If only running foreground, stop and re-run `./scripts/run-loop.sh --serve --interval 600`.

### Upgrade to latest release

```bash
./scripts/agent-upgrade.sh           # pull main, uv sync, restart unit if present, status
# or pin: ./scripts/agent-upgrade.sh --ref v0.9.28   # example tag
```

After upgrade, confirm `compat=ok` if the gateway bumped `api_version` — the monitor
must advertise the **deployed** gateway contract (`bridge.API_VERSION`; currently **4**
for framework ≥0.8.33). For full Status-sidebar telemetry (LLM **local/external** badges,
genuine entity census, REM fairness instruments) prefer **framework ≥0.8.9**; older
gateways stay compatible on the wire and simply omit newer fields.

### Stop

```bash
systemctl --user stop shared-memory-monitor.service
```

### Uninstall (Teardown)

```bash
./scripts/uninstall-systemd-user.sh
# Note: disabling linger on some distributions (e.g., Debian) may require sudo.
# The script attempts `sudo -n loginctl disable-linger $USER`. If it fails, run manually:
# sudo loginctl disable-linger $USER
cd .. && rm -rf Shared_Memory_Monitor
```

### Token / auth problems

| Symptom | Action |
|---------|--------|
| `AGENT_TOKEN source: skill:…` | Put dedicated monitor token in **monitor** `.env` (wins over skill env) |
| telemetry 401 | Token missing/wrong; re-mint on gateway |
| write probe not denied | Token may be over-privileged — use `monitor:read` only |
| gateway unreachable | Start framework gateway; check `COORDINATOR_URL` |
| dashboard down, unit active | `journalctl --user -u shared-memory-monitor.service -n 50` |
| no LLM pool / no placement badges | Single-backend or gateway before 0.6.1 omits pool; placement needs **≥0.8.9** `has_credential` on `config.llm_backends` |
| doctor missing `entity_graph` / `latency` | Upgrade gateway; panels are optional and degrade cleanly |

---

# Part 2 — Develop in this repository

## Commands

```bash
uv sync
uv run --with pytest python -m pytest -q
./scripts/check-env.sh
./scripts/run-loop.sh --serve --interval 600
./scripts/pre-publish-check.sh
./scripts/publish.sh                 # push origin main after audit
```

### Releases

Before cutting any new tag or release on GitHub, agents must verify all 4 checkpoints:

1. **Version Consistency Across All Docs & Codebase**:
   - `pyproject.toml` (`version = "X.Y.Z"`)
   - `src/sm_telemetry_monitor/__init__.py` (`__version__ = "X.Y.Z"`)
   - `CHANGELOG.md` (top section `## [X.Y.Z] - YYYY-MM-DD`)
   - `README.md` (`This release`, `Compatibility (vX.Y.Z)`, `Client X-SM-Api-Version`, `Releases (current: vX.Y.Z)`)
   - `AGENTS.md` & `GEMINI.md` (`./scripts/agent-upgrade.sh --ref vX.Y.Z`)
   - `docs/SISTER_PROJECT.md` (`Monitor vX.Y.Z sets bridge.API_VERSION`)
2. **Automated Audit**:
   - Run `./scripts/pre-publish-check.sh` (fails automatically if any doc or test file is on an older version).
3. **UI Screenshots**:
   - If UI layout or drawers were modified, refresh screenshots in `docs/images/` (`dashboard.png`, `consolidation.png`, `latency.png`, `schema-breakdown.png`, `diagram.png`, `logs.png`).
4. **Build & Release Upload**:
   - Run `uv build` to produce wheel and sdist package distributions.
   - Run `gh release create vX.Y.Z` and attach built dist files (`gh release upload vX.Y.Z dist/*`).

## Architecture (invariants)

| Concern | Where |
|---------|--------|
| Sole gateway HTTP client | `src/sm_telemetry_monitor/bridge.py` |
| Env precedence (monitor `.env` wins token/URL) | `env_loader.py` |
| Doctor / check (panels + LLM placement) | `doctor.py`, `scripts/check-env.sh` |
| Infrastructure + LLM pool/placement | `system_health.py` ← `/health` only |
| Poll cache | `collector.py`, `store.py` |
| UI transport `:8765` | `server.py`, `static/` |
| Logs | `logs_reader.py` (journal + audit JSONL only) |

- **No** direct Postgres/Neo4j credentials in this repo.
- **No** imports of framework Python packages.
- **No** LLM API keys in monitor `.env` — cloud credentials stay on the gateway
  (`LLM_BACKENDS_JSON` / `token_env`); the monitor only shows non-secret
  `has_credential` + `model` from `/health.config`.
- Everything on screen derives from `/health`, `/memory/telemetry`, read-only graph, or
  framework log files the gateway writes.
- If a metric is missing, fix the **framework** telemetry surface — not a monitor-side DB.

### Distribution Quirks (Linux)

Our automation scripts deliberately handle the following OS-specific pitfalls you may encounter during operations:

| Distribution | Known Quirk | How We Handle It |
|--------------|-------------|------------------|
| **Debian 13** (`d9400`) | `loginctl enable-linger` / `disable-linger` throws "Access denied" for unprivileged users. | `install-systemd-user.sh` and `uninstall-systemd-user.sh` automatically attempt a `sudo -n loginctl` fallback. |
| **Ubuntu 26.04** (`glxvm`) | Non-interactive SSH sessions strip `~/.local/bin` from `$PATH`, hiding `uv` if installed via curl. | `agent-upgrade.sh` and `install.sh` explicitly export `~/.local/bin` and `~/.cargo/bin` to the PATH before running commands. |
| **Fedora 44** (Host) | Generally permissive with user units, but follows the exact same script logic for cross-compatibility. | Standard execution paths apply. |

---

## Boundaries

- Code/docs writes: this checkout only.
- Ops outside: `systemctl --user`, `journalctl`, `curl` to `:8888`/`:8765`, read framework
  docs when `SHARED_MEMORY_ROOT` is set.
- Never commit: `.env`, `data/*`, `graphs/*`, `.venv/`, tokens.

## After significant work

Prefer shared memory (Hive-Mind) for cross-agent facts when available; always update
`CHANGELOG.md` for user-visible behavior.

---

## Reference

- Human docs: [README.md](README.md), [docs/SISTER_PROJECT.md](docs/SISTER_PROJECT.md)
- Framework (gateway install / tokens): https://github.com/KanenasInGreece/Shared_Memory
- Maintainer skill (workstation-local, optional): `.grok/skills/shared-memory-monitor/`
