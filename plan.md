# Implementation Plan: Framework v0.9.15 Telemetry

## Goal
Update the monitor to explicitly verify and report the presence of `llm_oldest_inflight_age_s` and `llm_suspect_wedged` (introduced in framework v0.9.15) during the `doctor.py` (`check-env.sh`) check. (Note: `system_health.py` already supports reading these fields).

## Steps

1. **`src/sm_telemetry_monitor/doctor.py`**
   - In `_check_coordinator()`:
     - Check if `"llm_oldest_inflight_age_s" in raw` and assign to `has_llm_oldest_inflight`.
     - Check if `"llm_suspect_wedged" in raw` and assign to `has_llm_suspect_wedged`.
     - Return these in the dictionary.
   - In `format_report()` (inside the `name == "coordinator"` block):
     - `if block.get("has_llm_oldest_inflight"): bits.append("oldest_inflight")`
     - `if block.get("has_llm_suspect_wedged"): bits.append("suspect_wedged")`

2. **`tests/test_doctor.py`**
   - Update any tests mocking `_check_coordinator()` or `format_report()` to account for these two new boolean keys.
   - Add a test or modify an existing one to assert `"oldest_inflight · suspect_wedged"` appears in the formatted report when the gateway provides them.

3. **`AGENTS.md`**
   - Update the example output in "Phase 3 — Verify wiring" to include `oldest_inflight` and `suspect_wedged`.
   - E.g., `coordinator: ok · gateway 0.9.15 · api server=4 client=4 compat=ok · ... · oldest_inflight · suspect_wedged`

4. **Run Checks**
   - `uv run --with pytest python -m pytest -q`
