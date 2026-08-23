# Implementation Plan: `llm_latency` and Single-Backend Rendering

## Objective
Adopt framework v0.9.14 telemetry additions: passthrough `llm_latency` from `GET /health` and ensure single-backend fleets display LLM pool chips in the dashboard.

## Scope
1. **`src/sm_telemetry_monitor/system_health.py`**
   - Extract `llm_latency` from the `raw` payload (if present).
   - Add it to the processed configuration returned to the frontend.
2. **`src/sm_telemetry_monitor/doctor.py`**
   - Add a check for `has_llm_latency` in `_check_coordinator()` and append `llm_latency` to the formatted report.
3. **`tests/test_system_health.py` & `tests/test_doctor.py`**
   - Update tests to account for the new `llm_latency` field.
4. **`static/dashboard.html`**
   - Access `H.config.llm_latency` (or wherever it's mapped) in the frontend.
   - For each backend in the LLM pool chips, display the average latency (`latency_sum_s / (requests_total - requests_failed_total)`) or `max latency` and request counts.
   - Ensure the logic for displaying the pool chips doesn't require `len(backends) > 1` (since the framework now emits it for single backends).
