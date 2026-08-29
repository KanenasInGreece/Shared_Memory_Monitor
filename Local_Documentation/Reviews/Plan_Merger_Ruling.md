# Merger ruling — dual-track plan review (v0.9.20)

**Merger:** Grok 4.6  
**Reviewers:** agy gemini-3.1-pro-high (intent + code tracks)

## Intent track (`Plan_Dual_Track_Intent.md`)

- **Critical** missing `max_batch_size`/`backend` invariants: **over-graded**. `max_batch_size` already passthrough (`test_p95_and_max_batch_passthrough`). Accepted as **Required** pins: new **I30** (`backend` own field, never model name) and **I31** (`max_batch_size` stays).
- Listed “Required” items that confirm the plan (tok_s_wall out of scope, mixed first-class, 1620 placement, 1362 last_ts) are **FYI / hold**, not changes.

## Code track (`Plan_Dual_Track_Code.md`)

- **Required** `latency.py:68` `or entry.get("backend")` name fallback: **accepted**. After 0.9.60 `backend` is a URL. Plan amended: name is `model` or `name` or `"?"` only.
- FYI items (fake 100% bar, unused `#latency-rem-note`, credsWarn hide predicate) confirm the plan.

## Verdict

Plan amended in `tasks/plan.md`. **CLEAR TO BUILD** Units A+B. Version files remain merger-owned.
