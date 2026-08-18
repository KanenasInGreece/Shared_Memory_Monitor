# Implementation Plan: Consume `/pool/status` (framework 0.9.13 leftover)

## Overview

Monitor **v0.9.13** (`fact:1365`, `decision:1369`) consumed `/health.llm_routing`,
`llm_token_usage`, descriptors, and `credentialed_route_denied`. It **deferred**
`GET /pool/status` (`fact:1359` meaning change ②). This cycle implements that
surface and the CQ-01 price-guard nit. Bump **0.9.13 → 0.9.14**. `api_version`
stays **4**.

Live `GET /pool/status` (authenticated, this host):

```json
{"free_slots": 3, "backends": {
  "http://localhost:5000": {
    "inflight": 0, "oldest_inflight_age_s": null, "cooldown": 0.0,
    "reserved": false, "available": true,
    "serves_all": true, "counts_free_slot": true
  }
}}
```

Anonymous / missing / error → `{}` (S-10). Never invent `free_slots: 0`.

`decision:1369` rejected this client **for v0.9.13**. This is a new cycle.

Roles (`decision:1300`): planner/reviewer/merger Grok 4.6; builder this session
(operator asked implement → review → merge → release in one pass).

Do **not** commit `Local_Documentation/`, `search_results.json`, `telemetry.json`, `diff.txt`.

## Architecture Decisions

- **A1. Sole HTTP client.** Add `bridge.get_pool_status()`. No other module fetches it.
- **A2. Distinct from inflight `free`.** Snapshot `dream_free_slots` is the
  gateway integer. Existing `llm_pool.free` stays the inflight-idle count.
  Do not overwrite one with the other (`fact:1359`).
- **A3. Join booleans.** Copy `serves_all` / `counts_free_slot` onto matching
  pool backends when present. Do not invent.
- **A4. Pool line.** When `dream_free_slots` is a finite number, append
  `N dream-ready`. Count is shown even at 0 (unlike credential warns) because
  a permanent 0 is the loud gateway warning case. Hide predicate includes the
  key so a pool-less but status-bearing gateway still shows the line.
- **A5. Popover.** Show `serves_all` / `counts_free_slot` only when boolean.
- **A6. CQ-01.** `hasPrice` accepts only a finite JS number, or a non-empty
  numeric string. `false`, `[]`, `null`, `""` are not prices.
- **A7. I2.** `free_slots` / the new booleans do not flip `_overall_state`.
- **A8. Doctor.** Coordinator reports `has_pool_status` when the payload has
  a numeric `free_slots` or a non-empty `backends` object; `format_report`
  names `pool_status` next to `llm_pool`.
- **A9. Secrets.** No tokens. `available` from this route is not a secret.

## Invariants

| Id | Rule | Test |
|----|------|------|
| I18 | `dream_free_slots` equals gateway `free_slots` when it is an int; bool is rejected; absent/`{}` omits the key (never invent 0). | `test_system_health.py` |
| I19 | `serves_all` / `counts_free_slot` copied onto matching backends only; unmatched URLs not invented. | same |
| I20 | `llm_pool.free` (idle) unchanged when `free_slots` is present. | same |
| I2 | Unchanged with `free_slots=0` or `3`. | same |
| I21 | `get_pool_status` 401/empty/`{}` → omit snapshot fields. | same + doctor |

## File ownership

| Unit | Files | Must not touch |
|------|-------|----------------|
| A | `bridge.py`, `system_health.py`, `doctor.py`, their tests | version files, CHANGELOG |
| B | `static/dashboard.html` | Python except if A missed a key |
| M | version, CHANGELOG, README, AGENTS, SISTER_PROJECT | feature after review |

## Tasks

### Task 1: Client + join (I18–I21, I2)

`get_pool_status()` in `bridge.py`. Snapshot join. Doctor flag. Tests first.

### Task 2: Pool line + popover + CQ-01

`dream-ready` on the line; booleans in popover; tighten `hasPrice`.

### Task 3: Review + v0.9.14 release (merger)

Five-axis + AGY Security. Bump, docs, restart, smoke, `pre-publish-check`,
`uv build`, push, `gh release create v0.9.14`.

## Out of scope

- Replacing inflight `free` with `free_slots`
- Reshaping credentials
- Painting own-door on chips
- `api_version` bump
