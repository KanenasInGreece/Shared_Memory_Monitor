# Code Quality Review 0.9.20

**Context**: Reviewing commit `b02ea17` on branch `feature/v0.9.20-latency-placement` against `tasks/plan.md`. The task involves integrating Gateway 0.9.60 latency `rem_ms.by_model` schema changes (wall, mixed, server rows) and splitting front-door credential metrics off the LLM pool line.

**Findings**:

- **FYI**: `correctness vs plan I22–I31, A2–A8` is fully met. Python passes through the new metrics (wall, timing_source, backend, n_service) without inventing default percentiles. The hide predicate (A3) correctly stops considering `token_verify_failed` and `audit_log_dropped`.
- **FYI**: `simplicity` and `architecture (observer-only)` are maintained. The gateway proxy performs straightforward dictionary extraction (`_anchor()`, `_p95()`) and the dashboard JS relies on boolean derivations like `isWall` without adding network calls. 
- **FYI**: `the JS ?? 100 path must not apply to wall rows` rule was successfully implemented. `isWall` short-circuits the stacked bar rendering entirely (`barHtml = ""`), effectively bypassing the service fraction defaulting logic. 
- **FYI**: `esc()/textContent at XSS-ish interpolations` rule is met. Strings (`m.model`, `m.backend`, joined tags) are wrapped with `esc()`, and `rem.note` leverages `textContent` avoiding injection entirely. `hint.innerHTML` correctly escapes the dynamic portion.
- **Nit**: `.lat-seg-wall` was added to `static/theme.css`, presumably to render a 100% width muted segment for wall times (as mentioned parenthetically in the plan). However, the implementation in `static/dashboard.html` simply clears `barHtml` for wall rows, leaving the CSS rule as dead code. This is acceptable since the text rendering correctly fulfills the primary display requirement.
- **Nit**: The `m.backend` subtitle interpolates as `<div class="lat-backend"><span class="lat-backend">...</span></div>` which applies the same class twice due to how `sub` was wrapped, though this doesn't break styling.

**Verdict**: APPROVE
