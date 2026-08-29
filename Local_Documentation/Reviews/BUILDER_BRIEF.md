You are the BUILDER (Gemini 3.7 Flash) for Shared Memory Monitor.

Work ONLY in this worktree. Implement tasks/plan.md Units A then B. TDD for Unit A.

## Forbidden (do not touch)
- pyproject.toml, src/sm_telemetry_monitor/__init__.py, CHANGELOG.md, README.md, AGENTS.md, docs/SISTER_PROJECT.md, GEMINI.md
- graphs/, untracked patch_*.py, .env, data/
- Do not bump the version. Do not merge to main.

## Allowed
- src/sm_telemetry_monitor/latency.py
- tests/test_latency.py
- static/dashboard.html
- static/theme.css (only if you add .lat-badge wall/mixed or .lat-seg-wall using existing CSS tokens)

## Unit A — tests first in tests/test_latency.py

Add tests that FAIL on current _rem_by_model, then implement.

Helpers: reuse _payload().

Required cases:
1. Wall-only (DeepSeek shape). Input:
   model=deepseek-v4-flash, n=15, n_service=0, timing_source=wall,
   backend=https://api.deepseek.com, max_batch_size=2,
   service_ms={p50:None,p95:None}, contention_ms={p50:None,p95:None},
   wall_ms={p50:4905.1,p95:6283.3}
   Assert: model name is deepseek-v4-flash NOT the URL; service_ms is None;
   contention_ms is None; wall_ms==4905.1; wall_ms_p95==6283.3; n_service==0;
   timing_source=="wall"; backend URL; service_frac is None; contention_frac is None;
   max_batch_size==2; snap["chip"] is None; rem.present True.

2. Mixed: n=500, n_service=1, timing_source=mixed, service_ms={p50:100,p95:200},
   contention_ms={p50:10,p95:20}, wall_ms={p50:4000,p95:8000}, backend=null.
   Assert n=500, n_service=1, timing_source mixed, backend is None, service_ms=100,
   wall_ms=4000, fracs computed from service+contention (not wall).

3. Server row keeps existing split AND adds wall + timing_source + n_service + backend.

4. Pre-0.9.60 row without new keys: existing test_service_vs_contention_split still passes;
   new fields are None/absent without crashing.

5. Name fallback: entry with NO model, backend=https://api.deepseek.com → models[0]["model"] == "?"
   (never the URL). Optional name key used if present.

Then edit _rem_by_model:
- name = entry.get("model") or entry.get("name") or "?"
- pass through wall_ms via _anchor, wall_ms_p95 via _p95
- n_service, timing_source, backend as-is (do not coerce)
- keep service/contention/frac/n/max_batch_size as today
- never invent 0 for null percentiles
- never drop a row because service is null

If you can run tests: `uv run pytest tests/test_latency.py -q`
If you cannot run a shell, still write the tests and implementation.

## Unit B — static/dashboard.html

1. Front-door vs LLM door
   - tokenFailed and auditDropped are NOT pool-line bits.
   - They do NOT participate in the LLM pool hide predicate.
   - They DO render on #system-hint (append to gatewayConfigHint text), warn class when either > 0, labelled as gateway door (e.g. "gateway door: token verify failed N · age").
   - When those fire, include the same credential-audit <a href="/logs?source=credential_audit"> using esc() for all dynamic text (constant href).
   - Keep credentialed_route_denied on the pool line ("route denied N · age").
   - Pool credsWarn / poolLineWarn must not include tokenFailed or auditDropped.
   - If you add HTML to #system-hint, use esc(); counts are numbers.

2. renderLatency three-way on m.timing_source
   - server (or absent with numeric service_frac): current stacked bar; extras include n_service beside service/wait if n_service != null; wall p50/p95 as text if wall_ms != null; n beside wall.
   - wall: NO stacked bar (do not use service_frac ?? 100). Show — for service/wait as N/A. Primary: wall p50/p95 and n=. Badge "wall".
   - mixed: stacked bar from service/contention fracs only if they are numbers; badge `mixed · n_service/n`; wall text + n=; n_service beside service.
   - Populate #latency-rem-note from rem.note with textContent (or esc into text). Element already exists.
   - aria-label must not say "model compute" on wall rows.
   - esc() model, backend, notes.

3. CSS: optional .lat-badge for wall/mixed; if a single wall bar, .lat-seg-wall using existing muted tokens. Do not invent a new palette.

## Done when
- Only allowed files changed
- Tests in test_latency.py cover I22–I31
- No version bump

Write a short BUILDER_REPORT.md in Local_Documentation/Reviews/ listing files changed and what you could not run.
