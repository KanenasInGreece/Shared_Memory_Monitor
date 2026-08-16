# Implementation Plan: Consume framework 0.9.8 credential last-event timestamps

## Overview

Framework **v0.9.8** (`fact:1314`, main `dc9b122`, PR #248) amended `fact:1307`.
`GET /memory/telemetry` `credentials` is still the three integer counters from
`fact:1297`, plus three **flat additive** sibling timestamps:

- `token_verify_failed_last_ts`
- `daemon_tokens_issued_last_ts`
- `audit_log_dropped_last_ts`

A `null` last_ts means “not in this process”, distinct from “just now”. The
shape is **not** `{count, last:{ts}}` — 1297 stays additive, `api_version`
stays **4**. The skill `status` human renderer now prints non-zero
`credentials` / `llm_faults` (the other 16 Aug finding). That client is
already shipped; this cycle is the **monitor**.

Live on this workstation (gateway 0.9.8, already joined onto `/api/health`):

```text
token_verify_failed=0 / last_ts=null
daemon_tokens_issued=2 / last_ts=2026-08-16T21:12:04Z
audit_log_dropped=0 / last_ts=null
llm_faults={}
```

`system_health._join_llm_faults` already passes the credentials dict through.
The product gap is presentation: `token_verify_failed` is never rendered, and
`audit_log_dropped` has no age. `fact:1307` + `fact:1314`: pair the count with
last-event age so a stale one-off reads as historical.

Roles (`decision:1300` grounded on `fact:1184`):

- **Planner / reviewer / merger:** Grok 4.6. Stays out of feature execution.
  Version files, CHANGELOG, tag, GitHub release are merger-only.
- **Builder:** Grok Build (`general-purpose` subagent). One worktree. Escalates
  instead of guessing.

Do **not** commit `search_results.json` or `telemetry.json`.

## Architecture Decisions

- **A1. Division of surfaces (locked — `decision:1295`).** Dashboard carries
  counters + last-event context only. Log lines stay on `/logs`.
- **A2. Flat siblings, not a restructure (`fact:1314`).** Do not nest
  credentials into `{count, last}`. Pass the dict through. Missing last_ts
  keys on older gateways stay missing — never invent timestamps.
- **A3. Own-door auth stays off LLM chips (locked — plan A4 / I3).**
  `token_verify_failed` is own-door. It never appears on a pool backend chip
  or in a chip popover. `audit_log_dropped` stays on the **pool line**.
- **A4. Age lives on the pool line.** When `token_verify_failed > 0`, append
  `token verify failed N` plus a relative age when `token_verify_failed_last_ts`
  is a parseable ISO string. When `audit_log_dropped > 0`, keep
  `audit log dropped` and append the same age form from
  `audit_log_dropped_last_ts` if present. Count 0 stays quiet (match skill
  `status`). Do **not** surface `daemon_tokens_issued` (normal start mint).
- **A5. Relative age, not a second clock.** Reuse the existing
  `fmtInflightAge` idea: “12m ago”, “2h ago”. Clock-skew / unparseable → omit
  the age, keep the count. Null last_ts + count > 0 (old gateway or
  never-stamped) → count only.
- **A6. Visibility.** If the only signal is a credentials warn (no pool / age /
  affinity / wedge), the pool panel must still show so the line is not hidden.
  Today `auditDropped` is computed then ignored in the hide predicate — fix
  that in the same `renderLlmPool` edit.
- **A7. No deck-critical.** These counters still must not flip `_overall_state`
  / the hero pill (I2).
- **A8. Deep link.** A credentials warn on the pool line may add a small link
  `/logs?source=credential_audit` (no backend filter — own-door). Do not invent
  a new Status-deck card.
- **A9. Secrets.** Never render tokens. last_ts is an ISO timestamp only.

## Numbered invariants (mutation-tested)

| Id | Rule | Test lives in |
|----|------|----------------|
| I10 | `/api/health.credentials` preserves `*_last_ts` sibling keys when present; absent keys stay absent; values are not rewritten; `null` stays `null`. | `tests/test_system_health.py` |
| I11 | `token_verify_failed` and any `*_last_ts` never appear on `llm_pool.backends[]` (extends I3). | `tests/test_system_health.py` |
| I2 | Unchanged: credential counters / last_ts do not change `_overall_state`. | existing I2 + last_ts fixture |
| I3 | Unchanged: `audit_log_dropped` stays top-level credentials, not a chip. | existing |

UI A4–A6 are browser-verified (no JS test harness). Mutation on I10: a test
that only checks `token_verify_failed` still passes if last_ts is dropped —
pin the **value** of each last_ts key.

## File ownership

| Unit | Owner files | Must not touch |
|------|-------------|----------------|
| **A — passthrough tests** | `tests/test_system_health.py`; `src/sm_telemetry_monitor/system_health.py` **only if** a test proves the dict is stripped (today it is not) | version files, CHANGELOG, static UI, docs |
| **B — pool-line age** (after A) | `static/dashboard.html`; `static/theme.css` only if the line needs a link class that does not already exist | Python, `logs.html`, version files |
| **M — merge / release** | `pyproject.toml`, `src/sm_telemetry_monitor/__init__.py`, `CHANGELOG.md`, `README.md`, `AGENTS.md`, `GEMINI.md` if it pins a version, `docs/SISTER_PROJECT.md`, `.env.example`, `.grok/skills/shared-memory-monitor/SKILL.md` if the compatibility line is listed | feature code |

## Task List

### Task 1: Pin last_ts passthrough (I10, I11)

**Description:** Extend `LlmFaultsCredentialsJoinTests` so a credentials blob
with the three 0.9.8 last_ts siblings survives `_join_llm_faults` / the
snapshot unchanged. Older fixture without those keys still has no invented
timestamps.

**Acceptance criteria:**
- [ ] I10 and I11 fail before any Python change (or stay green if passthrough
      already holds — then no `system_health.py` edit).
- [ ] I2 still green with last_ts populated and `token_verify_failed > 0`.

**Verification:** `uv run pytest -q tests/test_system_health.py`

**Dependencies:** None
**Estimated scope:** S

### Task 2: Pool-line last-failure age

**Description:** In `renderLlmPool`, implement A4–A8. Count 0 stays quiet.
Warn class if `audit_log_dropped > 0` **or** `token_verify_failed > 0`.

**Acceptance criteria:**
- [ ] Injected `token_verify_failed=2` + last_ts ~12 minutes ago shows
      `token verify failed 2` and a relative age; no LLM chip warn from this.
- [ ] Injected count>0 without last_ts shows the count only.
- [ ] `audit_log_dropped > 0` still warns the line and can show age.
- [ ] Hide predicate includes credentials warns (A6).
- [ ] Hero / deck status unchanged (I2).
- [ ] Desktop and ~400px sidebar: line wraps, does not overflow.

**Verification:** Browser on `http://127.0.0.1:8765/` after merger restarts the
user unit. Live today is count=0 — use a console fixture on `H.credentials`
or a temporary health override documented in the handoff. Check `/logs` still
loads. Do not leave a temporary override in the commit.

**Dependencies:** Task 1
**Estimated scope:** S

### Checkpoint
- [ ] `uv run pytest -q`
- [ ] No version/CHANGELOG edits from the builder

### Task 3: Review + merge + v0.9.12 (merger only)

**Description:** Five-axis review against this plan. Then merger: bump
**0.9.11 → 0.9.12**, CHANGELOG, docs that name framework **0.9.8** last_ts
and fix the stale installer bits (SISTER_PROJECT telemetry table,
AGENTS Phase-3 example, `.env.example` still says `api_version 3`).
Screenshots only if the pool line layout actually changed. Restart user
unit, smoke, `pre-publish-check.sh`, `uv build`, push `origin main`,
`gh release create v0.9.12`.

**Acceptance criteria:**
- [ ] Critical/Required review findings resolved or operator-overruled.
- [ ] Version consistent in pyproject, `__init__`, CHANGELOG, README, AGENTS,
      SISTER_PROJECT (and GEMINI if it pins).
- [ ] Tag `v0.9.12` + GitHub release with wheel/sdist.

**Dependencies:** Tasks 1–2 + review
**Estimated scope:** M

## Out of scope

- Framework / skill edits (already shipped in 0.9.8).
- Reshaping credentials to `{count, last}`.
- Painting `token_verify_failed` on LLM chips.
- Surfacing `daemon_tokens_issued` on the dashboard.
- A5 `/health` slimming.
- Inventing monitor-side timestamps or reading the credential log to recover age.
- Committing `search_results.json` / `telemetry.json`.

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Live count is 0 — cannot see the warn path | Med | Console fixture / documented inject; tests pin the payload |
| Relative-age wording vs skill `_age_phrase` | Low | Same idea, not a shared module — do not import framework code |
| Screenshot / layout drift | Low | Recapture `docs/images/dashboard.png` only if the line is visibly new |
