# Builder Report: Gateway 0.9.60 Latency + Credential Placement (v0.9.20)

**Builder Role:** Gemini 3.7 Flash  
**Worktree:** `/home/xenofon/grok-labs/projects/shared-memory-monitor-wt-0960`  
**Branch:** `feature/v0.9.20-latency-placement`  
**Status:** Units A and B Complete · 189 tests passing  

---

## Files Changed

1. `src/sm_telemetry_monitor/latency.py` (Unit A)
   - Updated `_rem_by_model` to extract and pass through `wall_ms` (via `_anchor`), `wall_ms_p95` (via `_p95`), `n_service`, `timing_source`, and `backend`.
   - Fixed name fallback to `entry.get("model") or entry.get("name") or "?"` so that backend URL is never used as the model name.
   - Preserved service/contention/fraction/n/max_batch_size metrics. Null percentiles are never coerced to 0, and frac remains `None` when service/contention are null.

2. `tests/test_latency.py` (Unit A)
   - Added TDD unit tests covering invariants I22–I26, I29–I31:
     - `test_wall_only_deepseek_shape`: wall-only DeepSeek row with null service/contention, `wall_ms` p50/p95 set, `n_service=0`, `timing_source="wall"`, backend URL, `service_frac=None`, `contention_frac=None`, `chip=None`.
     - `test_mixed_timing_source`: `n=500`, `n_service=1`, `timing_source="mixed"`, service and wall percentiles present, fracs calculated from service+contention.
     - `test_server_row_with_wall_and_timing_source`: server row retaining service/contention split while passing through `wall_ms`, `timing_source="server"`, `n_service`, and `backend`.
     - `test_pre_0960_row_defaults`: verifies backwards compatibility for pre-0.9.60 rows where new keys are absent/None without errors.
     - `test_name_fallback_never_uses_backend_url`: verifies model name falls back to `"?"` or `name` key, never backend URL.

3. `static/dashboard.html` (Unit B)
   - **Front-door vs LLM door separation:**
     - Removed `token_verify_failed` and `audit_log_dropped` from LLM pool line bits, pool hide predicate, and pool `credsWarn`.
     - Placed front-door events on `#system-hint` (appending `"gateway door: token verify failed N · age"` and/or `"audit log dropped · age"`), adding `.warn` class and linking to `/logs?source=credential_audit`.
     - Retained `credentialed_route_denied` on the LLM pool line with credential-audit link.
   - **Three-way `renderLatency`:**
     - `server` / absent: stacked bar for service/contention; `n_service` beside service; wall p50/p95 as text; `n` beside wall.
     - `wall`: no stacked bar; `— (N/A)` for service/wait; primary wall p50/p95 and `n=`; `.lat-badge` `"wall"`; aria-label does not say "model compute".
     - `mixed`: stacked bar from numeric service/contention fracs only; badge `mixed · n_service/n`; wall text + `n=`; `n_service` beside service.
     - Populated `#latency-rem-note` from `rem.note`.
     - Escaped all dynamic strings with `esc()`.

4. `static/theme.css` (Unit B)
   - Added `.lat-key-wall::before`, `.lat-seg-wall`, and `.lat-backend` using existing design tokens (`var(--muted)`, `var(--card-inset)`, `var(--border)`, `var(--mono)`).

---

## Verification & Execution

- **Test Suite Execution:**
  - `uv run python3 -m unittest tests/test_latency.py`: 15 tests passed.
  - `uv run python3 -m unittest discover tests`: 189 tests passed (0 failures, 0 errors).
- **Static & Syntax Validation:**
  - `python3 -m py_compile src/sm_telemetry_monitor/latency.py tests/test_latency.py`: Passed.
  - Extracted JavaScript from `static/dashboard.html` validated with `node --check`: Passed.
- **Environment Notes:**
  - `uv run pytest` was attempted initially but the `pytest` executable is not installed in the venv; all tests were executed and verified via `uv run python3 -m unittest`.

---

## Invariants Checklist

| Invariant | Status |
|-----------|--------|
| **I22** Wall-only row present; service/contention stay `None` | Verified (`test_wall_only_deepseek_shape`) |
| **I23** `timing_source` passthrough `server`/`wall`/`mixed` | Verified (`test_latency.py`) |
| **I24** `wall_ms` p50/p95 passthrough; never invented | Verified (`test_latency.py`) |
| **I25** Legacy `n` unchanged; `n_service` copied | Verified (`test_latency.py`) |
| **I26** Contention chip not promoted from wall-only rows | Verified (`test_wall_only_deepseek_shape`) |
| **I27** `token_verify_failed` on `#system-hint`, not pool line | Verified in `static/dashboard.html` |
| **I28** `credentialed_route_denied` stays on pool line | Verified in `static/dashboard.html` |
| **I29** Wall rows do not get `service_frac=100` (`None`) | Verified (`test_wall_only_deepseek_shape`) |
| **I30** `backend` own field, never model name | Verified (`test_name_fallback_never_uses_backend_url`) |
| **I31** `max_batch_size` passthrough maintained | Verified (`test_wall_only_deepseek_shape`) |
| **Forbidden files untouched / No version bump** | Verified (`git status` clean outside allowed files) |
