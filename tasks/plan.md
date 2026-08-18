# Implementation Plan: Consume framework 0.9.9–0.9.13 LLM + credential surfaces

## Overview

Monitor **v0.9.12** (`fact:1361`) already consumes framework **0.9.8**
`credentials.*_last_ts` on the pool line. The gateway on this workstation is
now **0.9.13** (`api_version` still **4**). Two adoption-suggestion facts
were filed for this repo after that release:

- **`fact:1337`** (gateway **0.9.9**, `fact:1335` on the framework side).
  S-10 auth slimming is already satisfied (monitor sends the bearer; first
  post-deploy poll was the authenticated shape). Two remaining suggestions:
  render `credentialed_route_denied` + `*_last_ts`; surface
  `config.allow_unauthenticated_provider_keys` when present **and true**.
- **`fact:1359`** (gateway **0.9.13**, 2026-08-18). LLM contract notes:
  401/403 on a *credentialed* liveness probe is now `ok`; `/health` gained
  `llm_routing` and `llm_token_usage`; `config.llm_backends` gained additive
  descriptors (`roles`, `n_ctx`, `private_ok`, `max_inflight`,
  `price_per_mtok_*`). `/pool/status` `free_slots` / `serves_all` /
  `counts_free_slot` are a **different** endpoint.

Live on this host (measured 2026-08-18, monitor `/api/health` vs raw
`bridge.get_health()`):

| Surface | Raw `/health` or telemetry | Monitor `/api/health` today |
|---------|----------------------------|-----------------------------|
| `credentials.credentialed_route_denied` (+ last_ts) | 0 / null (passthrough) | present, **not rendered** |
| `allow_unauthenticated_provider_keys` | **absent** (auth on) | absent |
| `llm_routing` (6 counters + 6 last_ts) | present; extract=4 | **dropped** |
| `llm_token_usage` per backend | 5000 has 5711/2003 tokens | **dropped** |
| backend `roles` / `n_ctx` / prices / `max_inflight` | keys present, values null | **dropped** |
| backend `private_ok` | `true` on all three | **dropped** |
| DeepSeek chip `status` | `ok` (401-as-ok shipped) | `ok` — no special-case to retire |
| `/pool/status` free_slots | not fetched | n/a |

`system_health` only copies known config/pool fields and never puts
`llm_routing` / `llm_token_usage` on the snapshot. The credentials dict is
already passed through wholesale (I10).

Roles (`decision:1300` grounded on `fact:1184`):

- **Planner / reviewer / merger:** Grok 4.6. Stays out of feature execution.
  Version files, CHANGELOG, tag, GitHub release are merger-only.
- **Builder:** Grok Build (`general-purpose` subagent). One worktree. Escalates
  instead of guessing.

Do **not** commit `search_results.json` or `telemetry.json`.

## Architecture Decisions

- **A1. Division of surfaces (locked — `decision:1295`).** Dashboard carries
  counters + last-event context only. Log lines stay on `/logs`.
- **A2. No new HTTP client this cycle.** Stay on `bridge.get_health()` +
  `get_telemetry()`. Do **not** add `GET /pool/status`. Gateway
  `free_slots` / `serves_all` / `counts_free_slot` stay out of scope; the
  pool line `free` remains the existing inflight-based count. Escalate if a
  later fact puts those fields on `/health`.
- **A3. Flat passthrough, no reshape.** `llm_routing` and `llm_token_usage`
  go onto `/api/health` as the gateway sent them (values not rewritten;
  `null` last_ts stays `null`; missing keys stay missing). Credentials
  remain the telemetry dict (already includes `credentialed_route_denied`).
- **A4. Own-door stays off chips (locked — plan A3 / I3 / I11).**
  `token_verify_failed` and `credentialed_route_denied` never appear on a
  pool backend chip or in a chip popover. `audit_log_dropped` stays on the
  pool line. `daemon_tokens_issued` stays hidden.
- **A5. Pool-line warns (count 0 quiet).** When `credentialed_route_denied > 0`,
  append `route denied N` plus relative age from
  `credentialed_route_denied_last_ts` (same `fmtLastEventAge` as 0.9.12).
  When `routing_no_eligible_backend`, `routing_backend_at_capacity`, or
  `routing_fit_rejected` is `> 0`, append a short label + age from the
  matching `*_last_ts`. Warn class if any of those or the existing
  credential warns fire. Hide predicate includes these warns (A6 of 0.9.12).
- **A6. Quiet routing totals.** If any `routed_role_extract|verify|judge > 0`
  and no routing-refuse warn, show a compact `extract N` (etc.) on the pool
  line **without** warn class. Count 0 stays off the line.
- **A7. Token usage lives in the chip popover, not the chip face.** Join
  `llm_token_usage[url]` onto the matching backend as
  `tokens: {prompt_total, completion_total, last_ts}` when that URL has an
  entry; omit the key when absent. Do **not** compute a poll-to-poll delta
  (in-process counters reset on gateway restart — `fact:1359`). Optional
  cost line only when that backend has a numeric `price_per_mtok_in` /
  `price_per_mtok_out` **and** token totals: `(prompt/1e6)*in +
  (completion/1e6)*out`. Never invent prices.
- **A8. Descriptor join.** Pass `roles`, `n_ctx`, `private_ok`,
  `max_inflight`, `price_per_mtok_in`, `price_per_mtok_out` from
  `config.llm_backends` onto `config.backends[]` and the matching pool
  chip. Render in the popover when the value is not `null` / missing. Chip
  face stays compact (placement + model + existing inflight/routed meta).
- **A9. Unauth-keys beacon.** If `config.allow_unauthenticated_provider_keys`
  is present and `true` on raw `/health.config` (or a top-level boolean of
  the same name), put `allow_unauthenticated_provider_keys: true` on
  `snapshot.config` and append a warn fragment on the Infrastructure hint
  (`gatewayConfigHint`). Absent or `false` stays silent — do not invent the
  key.
- **A10. 401-as-ok is a no-op.** Monitor already trusts `/health.llm_backends`
  status. Live DeepSeek is `ok`. Do not add a 401 special-case; do not
  treat `llm_faults.credential` as chip-down. No lore to delete in code.
- **A11. No deck-critical.** New counters / beacons do not flip
  `_overall_state` / the hero pill (I2).
- **A12. Doctor.** Coordinator block reports `has_llm_routing` /
  `has_llm_token_usage` from key presence on `/health`. Human line names
  them next to `llm_pool` when present. `has_credentials` already covers
  the new credential counter.
- **A13. Secrets.** Never render tokens or provider keys. last_ts is ISO
  only. Prices are public config numbers, not secrets.
- **A14. `api_version` stays 4.**

## Numbered invariants (mutation-tested)

| Id | Rule | Test lives in |
|----|------|----------------|
| I10 | Unchanged: credentials dict including new siblings is not rewritten. | existing + I14 |
| I14 | `/api/health.credentials` preserves `credentialed_route_denied` and `credentialed_route_denied_last_ts` when present; absent keys stay absent; `null` stays `null`. | `tests/test_system_health.py` |
| I11 | Own-door keys (`token_verify_failed`, `credentialed_route_denied`, all `*_last_ts`) never appear on `llm_pool.backends[]`. | `tests/test_system_health.py` |
| I12 | `/api/health.llm_routing` is the `/health.llm_routing` dict when present (pin every counter + every last_ts value); absent key → snapshot key absent or null, never invented zeros. | `tests/test_system_health.py` |
| I13 | `/api/health.llm_token_usage` preserves per-URL totals + `tokens_last_ts`; backends without an entry are not invented. Joined `tokens` on a pool backend matches that URL's blob. | `tests/test_system_health.py` |
| I16 | Descriptor fields on `config.backends[]` and pool backends are copied when present; missing/null stay missing/null; never inferred from URL. | `tests/test_system_health.py` |
| I17 | `config.allow_unauthenticated_provider_keys` appears on the snapshot only when the gateway sent it. | `tests/test_system_health.py` |
| I2 | Unchanged: credential / routing / token counters do not change `_overall_state`. | existing I2 + new fixtures |
| I3 | Unchanged: own-door credentials stay top-level, not a chip. | existing |

UI A5–A9 are browser-verified after merger restart (no JS test harness).
Mutation on I12/I13: a test that only checks key presence still passes if
values are rewritten — pin the **values**.

## File ownership

| Unit | Owner files | Must not touch |
|------|-------------|----------------|
| **A — passthrough + join** | `tests/test_system_health.py`, `src/sm_telemetry_monitor/system_health.py`; `tests/test_doctor.py`, `src/sm_telemetry_monitor/doctor.py` | version files, CHANGELOG, static UI, docs |
| **B — pool line / popover / hint** (after A) | `static/dashboard.html`; `static/theme.css` only if a new warn class is required | Python, `logs.html`, version files |
| **M — merge / release** | `pyproject.toml`, `src/sm_telemetry_monitor/__init__.py`, `CHANGELOG.md`, `README.md`, `AGENTS.md`, `GEMINI.md` if it pins a version, `docs/SISTER_PROJECT.md`, `.env.example`, `.grok/skills/shared-memory-monitor/SKILL.md` if the compatibility line is listed | feature code |

## Task List

### Task 1: Pin passthrough + join (I12–I17, I2, I11)

**Description:** Extend `LlmFaultsCredentialsJoinTests` / `GatewayConfigTests`
so 0.9.9 credential siblings, 0.9.13 `llm_routing`, `llm_token_usage`,
backend descriptors, and the unauth-keys boolean survive
`system_health_snapshot` unchanged. Older fixtures without those keys still
have no invented fields. Then implement the minimum `system_health.py`
(and doctor flags) to make the tests pass.

**Acceptance criteria:**
- [ ] I14 pins `credentialed_route_denied` + last_ts value (including `null`).
- [ ] I12 pins all six routing counters and six last_ts values from a
      fixture copied from live 0.9.13 shape.
- [ ] I13 pins per-URL token totals; a backend with no usage entry has no
      invented `tokens` object.
- [ ] I16 pins `private_ok=True` and `roles is None` without dropping the
      keys when the gateway sent them; a pre-0.9.13 fixture has none of
      the new descriptor keys.
- [ ] I17: key absent → not on `config`; key `true` → on `config`.
- [ ] I2 still green with routing refuses > 0, tokens populated, and
      `credentialed_route_denied > 0`.
- [ ] I11 includes `credentialed_route_denied` / its last_ts.
- [ ] Doctor coordinator JSON has `has_llm_routing` / `has_llm_token_usage`;
      `format_report` names them when true.

**Verification:** `uv run pytest -q tests/test_system_health.py tests/test_doctor.py`

**Dependencies:** None
**Estimated scope:** M

### Task 2: Pool line, popover, infrastructure hint

**Description:** In `renderLlmPool` / `fillLlmPoolPopover` / `gatewayConfigHint`,
implement A5–A9. Count 0 stays quiet. Reuse `fmtLastEventAge`.

**Acceptance criteria:**
- [ ] Injected `credentialed_route_denied=2` + last_ts ~12 minutes ago shows
      `route denied 2` and a relative age; no LLM chip warn from this.
- [ ] Injected `routing_no_eligible_backend=1` (+ last_ts) warns the pool
      line; `routed_role_extract=4` with refuses=0 shows `extract 4` without
      warn.
- [ ] Popover shows token totals + last age when `tokens` present; shows
      `private_ok` / `roles` / `n_ctx` / `max_inflight` only when set;
      cost line only when prices are numeric.
- [ ] `config.allow_unauthenticated_provider_keys === true` adds a warn
      fragment on the Infrastructure hint; absent/false does not.
- [ ] Hide predicate includes credential + routing warns.
- [ ] Hero / deck status unchanged (I2).
- [ ] Desktop and ~400px sidebar: line wraps, popover does not overflow.

**Verification:** Browser on `http://127.0.0.1:8765/` after merger restarts
the user unit. Live today is refuses=0 and route-denied=0 — use a console
fixture on `H.credentials` / `H.llm_routing` or a temporary health override
documented in the handoff. Check `/logs` still loads. Do not leave a
temporary override in the commit. Tokens on localhost:5000 are live and
can be checked without a fixture.

**Dependencies:** Task 1
**Estimated scope:** S

### Checkpoint
- [ ] `uv run pytest -q`
- [ ] No version/CHANGELOG edits from the builder

### Task 3: Review + merge + v0.9.13 (merger only)

**Description:** Five-axis review against this plan. Then merger: bump
**0.9.12 → 0.9.13**, CHANGELOG, docs that name framework **0.9.9**
`credentialed_route_denied` and **0.9.13** `llm_routing` /
`llm_token_usage` / backend descriptors. Screenshots only if the pool
line or popover layout actually changed. Restart user unit, smoke,
`pre-publish-check.sh`, `uv build`, push `origin main`,
`gh release create v0.9.13`.

**Acceptance criteria:**
- [ ] Critical/Required review findings resolved or operator-overruled.
- [ ] Version consistent in pyproject, `__init__`, CHANGELOG, README, AGENTS,
      SISTER_PROJECT (and GEMINI if it pins).
- [ ] Tag `v0.9.13` + GitHub release with wheel/sdist.

**Dependencies:** Tasks 1–2 + review
**Estimated scope:** M

## Out of scope

- `GET /pool/status` and `free_slots` / `serves_all` / `counts_free_slot`.
- Framework / skill edits.
- Reshaping credentials to `{count, last}`.
- Painting own-door counters on LLM chips.
- Surfacing `daemon_tokens_issued`.
- Inventing monitor-side timestamps, prices, or token deltas.
- Special-casing DeepSeek / 401 probe (already `ok` on the wire).
- Committing `search_results.json` / `telemetry.json`.

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Live refuse/denied counts are 0 | Med | Console fixture / documented inject; tests pin the payload |
| Token totals reset on gateway restart | Med | Never subtract consecutive polls; show totals + last_ts only |
| Descriptor/price fields are null on this host | Low | Hide empty; tests pin both present-null and absent |
| Screenshot / layout drift | Low | Recapture `docs/images/dashboard.png` only if the line/popover is visibly new |
