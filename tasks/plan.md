# Implementation Plan: Align monitor with framework 0.9.4 logs + telemetry

## Overview

Bring Shared Memory Monitor up to date with the framework **v0.9.4** observability contract (facts **1294**, **1297**; decision **1295**): **telemetry is SIGNAL**, **logs are DETAIL**. The operator path is: a per-backend LLM rectangle warns → click it for last-event signal → follow a deep link into `/logs` and filter by that backend (and, on the credential log, by origin/gateway).

This is **not** a new top-level fault panel. Live `/health` already paints one rectangle per pool backend (`localhost:5000` local, `localhost:4000` local today). Remote/external backends use the same chip; they already get a `place-external` badge when `has_credential` is true. What is missing is joining additive `telemetry.llm_faults` / `telemetry.credentials` onto those chips, a click-to-inspect popover, a new **Credential audit** log source, and backend (plus origin) filter chips on the logs that carry those fields.

Working-tree leftover: uncommitted **v0.9.10** version bump for `slot_failures` already on `origin/main` (`95ee780`) under the **v0.9.9** tag. Merger folds that bump into this release. Do **not** commit `search_results.json` or `telemetry.json`.

Roles (fact **1184**, this cycle only — no project-adoption decision exists yet):

- **Planner / reviewer / merger:** Grok 4.6 (this session). Stays out of feature execution. Version files + CHANGELOG + tag + GitHub release are merger-only.
- **Builder:** Grok Build (`general-purpose` subagent). One worktree per parallel unit. Escalates instead of guessing.

## Architecture Decisions

- **A1. Division of surfaces (locked — decision 1295).** Dashboard chips carry counters + last-event context only. Log lines never appear on the dashboard. Investigation happens on `/logs`.
- **A2. Per-backend rectangle, not a top-level panel.** Reuse `#llm-pool-backends .pool-chip`. No new Status-deck card, no fourth drawer-trigger next to Data Quality / Latency / Schema.
- **A3. Click the chip to inspect that backend.** Same visual language as existing drawers (tokens, warn/ok/bad, `esc()`), but a compact popover anchored to the chip. Copy ends with a Logs deep link. Escape / outside click / second click closes it.
- **A4. Warn is a cue to open logs, not a deck-critical.** Credential-class faults (`llm.credential`) and gateway-path faults (`gateway`) mark that chip `warn` (or keep `down` if the pool already says down). Transient faults (`llm.transient`) also mark the chip `warn` with different popover copy. **Do not** flip `_overall_state` / the hero pill from these counters alone. `credentials.audit_log_dropped > 0` warns the **pool line**, not a chip. `credentials.token_verify_failed` is own-door auth — never paint an LLM chip.
- **A5. Remote backends appear the same way as local ones.** Same chip component. Sort **local first, then external, then unknown placement**. If `llm_faults` names a URL that is not in `llm_pool`, synthesise a chip for that URL (label via existing `_backend_label`) so the signal is not invisible. Join by URL, slash-normalised the same way `_config_backend_index` already does. Placement still comes only from `has_credential` — never infer from hostname.
- **A6. Logs: new source + existing filters, not a new page.** Add `credential_audit` to `list_sources()`. Reuse File picker, Follow/Pause, time range, severity chips. Add backend chips on **credential audit** and **agent audit**. Add origin chips (`gateway` / `upstream`) on credential audit only.
- **A7. Logrotate uses the existing picker.** Framework rotates `*-audit.jsonl` as `.1` (delaycompress, uncompressed) then `.2.gz`…`.14.gz`. Today `_archive_candidates` only globs `*.gz`, so yesterday’s `.1` is invisible. Extend the matcher to numbered rotates; do not invent a second archive UI.
- **A8. Additive and degrading.** Older gateways omit `llm_faults` / `credentials` / `credential-audit.jsonl` — hide the new bits, keep current behaviour. No `api_version` bump (still **4**).
- **A9. Secrets.** Never render raw tokens. `digest_prefix` may be shown as the gateway already stores it (8 hex of the presented token). `CREDENTIAL_AUDIT_LOG_PATH=""` means disabled — omit the source or show unavailable, do not invent a path.

## Numbered invariants (mutation-tested)

| Id | Rule | Test lives in |
|----|------|----------------|
| I1 | `/api/health.llm_pool.backends[]` may carry a `faults` object `{gateway, credential, transient}` joined from `telemetry.llm_faults[url]`; missing telemetry → no `faults` key, chips unchanged. | `tests/test_system_health.py` |
| I2 | Chip warn from faults does **not** change `_overall_state` when all processes are otherwise ok. | `tests/test_system_health.py` |
| I3 | `audit_log_dropped > 0` appears on the health payload as `credentials.audit_log_dropped` and does not attach to a backend chip. `token_verify_failed` never appears on a backend chip. | `tests/test_system_health.py` |
| I4 | A `llm_faults` URL absent from `llm_pool` still produces a backend row (synthesised chip). | `tests/test_system_health.py` |
| I5 | Backends sort local → external → unknown. | `tests/test_system_health.py` |
| I6 | `list_sources()` includes `credential_audit` whose live path is `CREDENTIAL_AUDIT_LOG_PATH` or `log_dir()/credential-audit.jsonl`. Empty env disables the live file. | `tests/test_logs_reader.py` |
| I7 | `list_archives("credential_audit")` and `list_archives("agent_audit")` include `*.1` and `*.N.gz` next to the live stem; path traversal still rejected. | `tests/test_logs_reader.py` |
| I8 | Doctor telemetry line names `llm_faults` and `credentials` when those keys exist on the payload (empty `{}` still counts as present). | `tests/test_doctor.py` |
| I9 | Agent-audit and credential-audit lines keep raw JSON on the wire (`parse_log_entry`); UI-only formatting. | `tests/test_logs_reader.py` (existing contract) |

## File ownership (parallelism)

| Unit | Owner files | Must not touch |
|------|-------------|----------------|
| **A — health join** | `src/sm_telemetry_monitor/system_health.py`, `tests/test_system_health.py`, `src/sm_telemetry_monitor/doctor.py`, `tests/test_doctor.py` | version files, CHANGELOG, static UI |
| **B — pool popover** (after A) | `static/dashboard.html`, `static/theme.css` (popover/warn-on-chip only) | `logs.html`, Python except via `/api/health` |
| **C — log source + archives** | `src/sm_telemetry_monitor/env_loader.py`, `src/sm_telemetry_monitor/logs_reader.py`, `tests/test_logs_reader.py`, `deploy/logrotate/shared-memory-audit.example` | version files, dashboard |
| **D — log filters** (after C) | `static/logs.html` | `theme.css` unless a class already exists — **do not edit theme.css** if B owns it; reuse `chip`, `chip-filter-active`, `logs-agent-bar` |
| **M — merge / release** | `pyproject.toml`, `src/sm_telemetry_monitor/__init__.py`, `CHANGELOG.md`, `README.md`, `AGENTS.md`, `GEMINI.md`, `docs/SISTER_PROJECT.md`, `.grok/skills/shared-memory-monitor/SKILL.md` if the log table is listed | feature code |

Shared file: `static/theme.css` is named. **B owns it.** D reuses existing chip classes.

`server.py` already derives `/api/logs/sources` and `/api/logs/archives` from `list_sources()` — no change unless a test proves otherwise.

## Task List

### Phase 0 — Hygiene (merger, before builders)

- [ ] Task 0: Leave leftover v0.9.10 version-file edits uncommitted on this checkout. Builders branch from `HEAD` (v0.9.9 code). Do not commit `search_results.json` / `telemetry.json`.

### Phase 1 — Signal on existing rectangles

### Task 1: Join `llm_faults` + `credentials` onto `/api/health`

**Description:** `system_health_snapshot()` already calls `get_telemetry()`. Read `telemetry.llm_faults` and `telemetry.credentials` (payload is `{status, telemetry:{...}}`). Attach a compact `faults` object to each pool backend. Pass `credentials` through at snapshot top-level. Sort backends local → external → unknown. Synthesise a chip when a fault URL is missing from the pool. Doctor names `llm_faults` + `credentials` when the keys exist.

**Acceptance criteria:**
- [ ] I1–I5 and I8 hold with failing tests written first.
- [ ] Live `curl /api/health` on this workstation still shows both local chips when `llm_faults` is `{}`.
- [ ] Empty/missing sections do not change chip `status`/`fails`/`placement`.

**Verification:**
- [ ] `uv run pytest -q tests/test_system_health.py tests/test_doctor.py`
- [ ] `curl -sf http://127.0.0.1:8765/api/health` after a local restart (or builder notes that the user unit must be restarted by the merger).

**Dependencies:** Task 0
**Files:** `system_health.py`, `tests/test_system_health.py`, `doctor.py`, `tests/test_doctor.py`
**Estimated scope:** M

### Task 2: Chip warn + click popover + Logs deep link

**Description:** In `renderLlmPool`, apply an extra `warn` class when `b.faults` has any count > 0 (keep `down` if already down). Make each chip a button (keyboard + `aria-expanded`). Click opens a compact popover: origin-split counts, last `{ts, class|status, error_type}`, one sentence that this is a cue to read logs, and links `/logs?source=credential_audit&backend=<url>` and `/logs?source=agent_audit&backend=<url>`. Reuse existing `--warn` / `--ok` / `--bad` tokens. Do not add a Status-deck card.

**Acceptance criteria:**
- [ ] External and local chips stay the same rectangle component; only data and interaction change.
- [ ] Popover is per-backend; closing does not navigate away.
- [ ] Deep-link query params match what Task 4 will read (`source`, `backend`).
- [ ] No log line text is rendered on the dashboard.

**Verification:**
- [ ] Browser: open `http://127.0.0.1:8765/`, confirm both current chips still render; click one, popover shows “no faults” empty state; Tab/Escape work.
- [ ] With a fixture or temporarily injected `faults` in the browser console, warn class + last-event copy appear.
- [ ] Desktop and ~400px sidebar width: popover does not overflow off-screen.

**Dependencies:** Task 1
**Files:** `static/dashboard.html`, `static/theme.css`
**Estimated scope:** M

### Checkpoint: Phase 1
- [ ] Tests pass. Dashboard still shows the approved pool chips. No top-level fault panel.

### Phase 2 — Logs detail

### Task 3: Credential-audit source + numbered logrotate archives

**Description:** Whitelist `CREDENTIAL_AUDIT_LOG_PATH` in `env_loader._FRAMEWORK_KEYS`. Add `credential_audit_path()` / `list_sources()` entry. Extend `_archive_candidates` to include live-stem `*.1` and `*.N.gz` (and keep current `*.gz` prefix match). Add `credential-audit.jsonl` to the shipped logrotate example. Format function is UI-side (Task 4); reader keeps raw lines.

**Acceptance criteria:**
- [ ] I6, I7, I9 hold with failing tests first.
- [ ] `GET /api/logs/sources` lists `credential_audit`.
- [ ] `GET /api/logs/archives?source=agent_audit` includes `gateway-audit.jsonl.1` on this host.
- [ ] Traversal (`../`, absolute paths) still raises.

**Verification:**
- [ ] `uv run pytest -q tests/test_logs_reader.py tests/test_security.py`
- [ ] `curl -sf http://127.0.0.1:8765/api/logs/sources` and archives for `credential_audit` / `agent_audit`.

**Dependencies:** Task 0 (parallel with Task 1)
**Files:** `env_loader.py`, `logs_reader.py`, `tests/test_logs_reader.py`, `deploy/logrotate/shared-memory-audit.example`
**Estimated scope:** M

### Task 4: Backend + origin filters; format credential lines

**Description:** Mirror the existing **Agent** chip bar. On `agent_audit` and `credential_audit`, collect `backend` from JSON and render filter chips (label = host:port via the same shortening as pool chips). On `credential_audit` only, also render origin chips (`gateway` / `upstream` from `origin`). Honour URL `?backend=` and `?origin=` on load (dashboard deep links). Format credential lines like agent-audit (ts, event, origin, backend, request_id, status/error_type — no payload dump). File picker already bound — just works once Task 3 lists `.1`.

**Acceptance criteria:**
- [ ] `/logs?source=credential_audit&backend=http://localhost:5000` shows only that backend (or the empty-state sentence).
- [ ] `/logs?source=agent_audit&backend=http://localhost:4000` same for agent audit.
- [ ] Origin chip `gateway` hides upstream-only events.
- [ ] Archive picker lists previous rotates; switching file keeps filters.
- [ ] Style matches existing agent chips (`chip chip-agent` / `chip-filter-active`).

**Verification:**
- [ ] Browser `/logs`: new tab present; File includes live; backend chips appear on agent audit (live data has `:5000` and `:4000`); credential tab shows the three live events; apply time range + archive if `.1` exists.
- [ ] Follow/Pause/severity/consolidation on gateway tab still work (regression).

**Dependencies:** Task 3
**Files:** `static/logs.html`
**Estimated scope:** M

### Checkpoint: Phase 2
- [ ] Operator path works: chip → popover → Logs with backend pre-filtered.
- [ ] Full `uv run pytest -q`

### Phase 3 — Release (merger only)

### Task 5: Review, merge to main, v0.9.10 tag + GitHub release

**Description:** Five-axis review against this plan. Reject scope creep. Then merger: version **0.9.10** across the release checklist (including stale `GEMINI.md` `v0.9.7` pin), CHANGELOG that describes this cycle (not only slot_failures), screenshots if Logs/Status layout changed (`docs/images/dashboard.png`, `docs/images/logs.png`), `./scripts/pre-publish-check.sh`, restart user unit, smoke `/api/health` + `/logs`, commit on `main` (or squash-merge the builder branches), push `origin main`, `gh release create v0.9.10` with wheel/sdist.

**Acceptance criteria:**
- [ ] Review findings at Critical/Required resolved or operator-overruled in writing.
- [ ] Version consistent in pyproject, `__init__`, CHANGELOG, README, AGENTS, GEMINI, SISTER_PROJECT.
- [ ] `pre-publish-check.sh` exits 0.
- [ ] Tag `v0.9.10` on the merge commit; GitHub release attached.

**Verification:**
- [ ] `./scripts/pre-publish-check.sh`
- [ ] `uv run pytest -q`
- [ ] `systemctl --user restart shared-memory-monitor.service` then doctor + browser smoke.
- [ ] `git ls-remote --tags origin` shows `v0.9.10`.

**Dependencies:** Tasks 1–4 + review
**Files:** merger-only list above
**Estimated scope:** M

## Parallelization

```
Task 1 (A) ──────────► Task 2 (B)
Task 3 (C) ──────────► Task 4 (D)
                              └──► Review (4.6) ──► Task 5 (merger)
```

A ∥ C are disjoint files. B waits on A (`/api/health` shape). D waits on C (source id + archives). theme.css: B only.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Empty `llm_faults` today hides the popover path | Low | Always allow click; empty state says “no faults — open logs to inspect” |
| `.1` files are uncompressed JSONL, not gzip | Med | Archive reader already tails non-gz via `_tail_lines_text`; do not force gzip |
| `agent-audit.jsonl` vs live `gateway-audit.jsonl` | Low | Existing fallback stays; new source is a third file |
| Deep-link `backend` is a full URL | Low | Query-param encode; compare against JSON `backend` after slash-normalise |
| Click-chip vs existing hover `title=` | Low | Keep title tooltip; click is the inspect affordance |
| Screenshot drift | Low | Recapture dashboard + logs if layout changes |

## Open Questions (defaults if unanswered)

- **Popover vs reuse Schema drawer chrome:** default popover (A3). A full-width drawer would compete with the three existing drill-downs.
- **Deck elevation on credential faults:** default no (A4). Say so if you want the LLM health-item to go warn when any backend has `llm.credential.count > 0`.
- **Build-cycle adoption:** this cycle follows 1184 operationally. A saved project decision is **not** created unless you ask.

## Out of scope

- Inventing monitor-side metrics or reading Postgres/Neo4j.
- A5 `/health` reshape (framework later).
- Surfacing `dream-metrics.jsonl` or per-save `shared_memory_*.log.gz`.
- Changing consolidation / schema / latency drawers.
- Publishing anything except the v0.9.10 release you already approved.
