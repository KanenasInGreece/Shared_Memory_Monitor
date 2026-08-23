# Code Quality Review: Single-Backend LLM Pool Synthesis

## Review against the Plan
- **Maintainability:** The plan focuses the logic exactly where the telemetry JSON is reshaped (`_llm_pool_summary`). It doesn't bleed UI concerns into the data layer and avoids hardcoded hacks on the dashboard.
- **Robustness:** Using `_inference_busy_state(raw)` ensures we use the exact same nvtop signal already accepted as ground truth, translating it to the `inflight` contract correctly.
- **Complexity:** The fix adds a targeted fallback that runs only when `llm_pool` is empty but `config.llm_backends` exists.

## Finding
No significant concerns. The plan keeps with the invariant: "The monitor never invents balance metrics; it only reshapes what `/health` already reports."
