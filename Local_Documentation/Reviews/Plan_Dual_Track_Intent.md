## Context
Reviewing the Gateway 0.9.60 latency + credential placement implementation plan (`tasks/plan.md`) against `fact:1620`, `fact:1625`, `fact:1626`, `fact:1314`, and `decision:1362`. The focus is on contract intent, proper branch handling, and UI placement.

## Findings

*   **Critical:**
    *   **Missing Invariant for `max_batch_size` and `backend`:** While `fact:1626` specifies `max_batch_size` and `backend` as keys and they appear in the plan's sample fixture, there are no explicit invariants in the table guaranteeing their passthrough. Task 1 mentions `backend` implicitly but misses `max_batch_size` entirely. An invariant must be added to ensure these keys are carried through the pipeline without mutation.
*   **Required:**
    *   **`tok_s_wall` Omission:** The plan successfully avoids inventing `tok_s_wall` (A7 correctly places it out of scope, adhering to `fact:1626 (6)`).
    *   **`mixed` Branch:** `mixed` is correctly handled as a first-class branch in both the architectural decisions (A4) and the rendering table.
    *   **Placement (`fact:1620`):** Correct. `token_verify_failed` is moved off the LLM pool line and correctly placed on the `#system-hint` infrastructure panel (A2, Task 2), satisfying the contract.
    *   **Neighborhood Refine (`decision:1362`):** Correct. The plan preserves `last_ts` pairing and leaves chips clean.

## Verdict: REQUEST CHANGES
