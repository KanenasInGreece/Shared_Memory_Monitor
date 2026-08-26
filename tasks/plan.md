# Implementation Plan: Gateway 0.9.60 latency + credential placement

## Overview

Monitor **v0.9.19 → v0.9.20**. `api_version` stays **4**. Consume framework
**0.9.60** `latency.rem_ms.by_model` wall/mixed/server keys (`fact:1626`) and
move front-door `token_verify_failed` off the LLM pool line (`fact:1620`).

Live gateway this host: **0.9.60**, `compat=ok`. Verified
`GET /memory/telemetry` matches 1626: three `by_model` rows including
`deepseek-v4-flash` `n=15` `n_service=0` `timing_source=wall`
`service_ms {null,null}` `wall_ms {4905.1, 6283.3}`. Current `/api/latency`
drops `wall_ms` / `n_service` / `timing_source` / `backend`; JS then paints a
100% “model” bar for DeepSeek.

Grounding: `fact:1620`, `fact:1621`, `fact:1622`, `fact:1625` (N3),
`fact:1626` (deployed contract), `fact:1314` (flat additive), `fact:1297`,
`decision:1362` (neighborhood refine, not reversal), `decision:1624`.

Roles (`decision:1300` / `fact:1526`): merger Grok 4.6; builder agy
`gemini-3.7-flash-high`; Architecture + Code Quality agy
`gemini-3.1-pro-high`; Security agy `claude-opus-4-6-thinking`.

## Architecture Decisions

- **A1. Observer only.** Passthrough gateway keys. Never invent 0 for null
  percentiles. Never recompute `timing_source`. Never call extra routes.
- **A2. Front-door vs LLM door (`fact:1620`).** `token_verify_failed` and
  `audit_log_dropped` render on the Infrastructure hint (`#system-hint`, next
  to `gatewayConfigHint`). `credentialed_route_denied` stays on the LLM pool
  line. Count 0 stays quiet. Last-ts age pairing from `decision:1362` is
  kept. Chips stay clean (I3).
- **A3. Hide predicate.** `tokenFailed` / `auditDropped` must not keep the
  LLM pool panel visible by themselves. Pool hide uses pool/age/aff/wedge/
  routeDenied/routing/dream-ready only.
- **A4. Three-way REM rows (`fact:1625` N3, `fact:1626`).** Dispatcher on
  `timing_source`: `server` | `wall` | `mixed`. Absent (pre-0.9.60): current
  stacked bar. Unknown string: treat like absent, do not coerce.
- **A5. n vs n_service.** Print `n_service` beside service/wait; `n` beside
  wall. Never a single `n=` that implies both.
- **A6. Not applicable, not missing.** Null service/contention → em dash
  labelled N/A. **Do not** default `service_frac` to 100. No stacked bar on
  `wall` rows.
- **A7. tok_s_wall out of scope.** Per-call `rem_timing` only; rollup does
  not aggregate (`fact:1626` (6)).
- **A8. rem.note.** Snapshot already carries it. Populate `#latency-rem-note`
  (element exists, currently never filled).
- **A9. Secrets / XSS.** `esc()` every interpolated string (`model`,
  `backend`, note, labels). Counts are numbers. Credential-audit `<a>` uses
  a constant href. `backend` URL is not a secret (already on pool chips).
- **A10. I2 unchanged.** Credentials never flip overall deck status.

## Rendering (the monitor’s decision)

| `timing_source` | Bar | Service / wait | Wall | Badge |
|-----------------|-----|----------------|------|-------|
| `server` | existing stacked bar | p50 numbers; `n_service=` | text `wall p50/p95` + `n=` | none (keep % wait if contention) |
| `wall` | **no stacked bar** | `—` N/A (not blank) | primary `wall p50/p95` + `n=` | `wall` |
| `mixed` | stacked bar from service/contention | p50 numbers; `n_service=` | text `wall p50/p95` + `n=` | `mixed · n_service/n` |
| absent | current behavior | current | omit wall | current |

`backend` is an optional subtitle (null → omit). Display name is
`entry.model` or `entry.name` or `"?"` — **never** `entry.backend` (that
key is now a URL; today's `_rem_by_model` fallback `or entry.get("backend")`
must be removed — plan-vs-code Required).

Wall bar (if a single-segment visual is needed): one `.lat-seg-wall` using
existing muted/card tokens — not a fake service/contention split.

Live fixture shape (values will move; **shape** is the test):

```
deepseek-v4-flash  n=15 n_service=0  timing_source=wall
  service_ms {p50:null,p95:null}  contention_ms {p50:null,p95:null}
  wall_ms {p50:4905.1,p95:6283.3}  max_batch_size=2
  backend=https://api.deepseek.com
```

Mixed fixture (not on this corpus; tests must pin): `n=500` `n_service=1`
`timing_source=mixed` with service percentiles present and wall present.

## Invariants

| Id | Rule | Test |
|----|------|------|
| I22 | Wall-only row is present; `service_ms`/`contention_ms` stay `None` (never 0) | `test_latency.py` |
| I23 | `timing_source` passthrough `server`/`wall`/`mixed`; unknown/absent not coerced | same |
| I24 | `wall_ms` p50/p95 passthrough; never invented | same |
| I25 | Legacy `n` unchanged; `n_service` copied when present | same |
| I26 | Contention chip not promoted from wall-only rows | same |
| I27 | `token_verify_failed` not in pool-line bits; still in `snapshot.credentials` | UI + existing I3 |
| I28 | `credentialed_route_denied` stays on pool line | UI |
| I29 | Wall rows do not get `service_frac=100` (frac stays `None`) | `test_latency.py` |
| I30 | `backend` passthrough as its own field; `null` allowed; never used as `model` | same |
| I31 | `max_batch_size` still passthrough (already tested; do not drop) | existing + wall fixture |
| I2 | Unchanged: credentials do not flip overall status | existing |

Python `_rem_by_model` currently omits the new keys, so I22–I26/I29 fail
until Unit A. Existing service/contention tests must still pass (Qwen/gemma
shape).

## File ownership

| Unit | Files | Must not touch |
|------|--------|----------------|
| **A** | `src/sm_telemetry_monitor/latency.py`, `tests/test_latency.py` | version files, CHANGELOG, UI |
| **B** | `static/dashboard.html`, `static/theme.css` (wall badge/seg only if needed) | Python except if A missed a key; `graphs/`; untracked `patch_*.py` |
| **M** | version 0.9.19→0.9.20, CHANGELOG, README, AGENTS.md credentials row, SISTER_PROJECT | feature code after review |

`#latency-rem-note` fill is Unit B (snapshot already has `rem.note`).

## Tasks

### Task 1: Latency passthrough (I22–I26, I29–I31)

TDD in `tests/test_latency.py` first (must fail on current `_rem_by_model`):

1. Wall-only DeepSeek-shaped row: present, `service_ms is None`, `wall_ms`
   p50/p95 set, `n_service=0`, `timing_source=="wall"`, `backend` URL,
   `service_frac is None`, `contention_frac is None`, no chip.
2. Mixed row: `timing_source=="mixed"`, service p50 from dict, wall p50
   from dict, `n` and `n_service` distinct.
3. Server row: legacy service/contention/frac still computed; plus wall
   passthrough and `timing_source=="server"`.
4. `{p50: None, p95: None}` service dict → `None` anchors (not 0).
5. Pre-0.9.60 row (no new keys) still matches today’s assertions.
6. `backend: null` passthrough; a row with `model` omitted and `backend` a URL still has `model == "?"` (or the `name` key), never the URL.

Then implement `_rem_by_model` additive fields only.

**Verification:** `uv run pytest tests/test_latency.py -q` then full suite.

### Task 2: Front-door placement + REM renderer (I27–I29, A2–A8)

`static/dashboard.html`:

- Split `credsWarn` / hide predicate per A2/A3.
- `token verify failed N · age` and `audit log dropped · age` on
  `#system-hint` (warn class when either > 0), labelled as gateway door;
  credential-audit link there when those fire.
- Pool line keeps `route denied` + routing/pool bits; credential-audit
  link on pool only for `routeDenied` (and existing routing refuses if
  already linked — do not duplicate the link on both if only tokenFailed).
- `renderLatency`: three-way row; populate `#latency-rem-note` from
  `rem.note` via `esc`/`textContent`.
- `aria-label` on bars must not claim “model compute” for wall rows.

**Verification:** `uv run pytest -q`. Live: `/api/latency` DeepSeek has
`timing_source=wall` and null fracs; dashboard LLM pool line has no
“token verify failed” when count is 0; drawer shows DeepSeek wall p50
~4.9 s with `—` in service/wait.

## Checkpoint: after Tasks 1–2

- [ ] Full pytest green
- [ ] No version bump in the builder commits
- [ ] Architecture + Code Quality (Pro 3.1) and Security (Opus 4.6) CLEAR
- [ ] Merger only then bumps 0.9.20, CHANGELOG, docs, merge --admin, release,
      `systemctl --user restart shared-memory-monitor.service`

## Out of scope

- `tok_s_wall` / `completion_tokens` on the drawer
- New Status card
- Framework repo
- `graphs/` (gitignored export)
- Untracked `patch_*.py`
- Doctor panel-name change unless `latency` already covers it (it does)

## Risks

| Risk | Mitigation |
|------|------------|
| JS `?? 100` fake bar | I29: Python leaves frac `None`; JS only draws stacked bar for server/mixed with numeric fracs |
| `audit_log_dropped` neighborhood | Assumed with token counter (same own-door family). Operator may override. |
| agy headless no shell | Merger pre-computes pytest + live JSON for reviewers; judge reviews by file mtime |
| Opus quota | Security falls to Pro 3.1 (still ≠ Flash builder) |
