## Context
Review of the "Gateway 0.9.60 latency + credential placement" implementation plan against the current Python and JavaScript codebase (`latency.py`, `dashboard.html`, `test_latency.py`, `theme.css`). Track 2 only (plan vs current code).

## Findings

**Required:** Python model-name fallback will coerce URLs into model names.
- **Evidence:** `src/sm_telemetry_monitor/latency.py:68` defines `name = entry.get("model") or entry.get("backend") or entry.get("name") or "?"`.
- **Impact:** The plan introduces `backend` as a URL (e.g., `https://api.deepseek.com`). If a telemetry row omits `model`, the Python layer will mistakenly use the URL as the primary model name. The plan states "Do not use it as the model name when model is present" but fails to address the current Python fallback behavior if `model` is absent.
- **Fix:** Update the plan to explicitly remove `entry.get("backend")` from the fallback chain in Python.

**FYI:** Python does not drop wall-only rows; it drops the new keys, and JS fakes the bar.
- **Evidence:** The plan's observation is correct. `latency.py:92-93` computes `service_frac` and `contention_frac` as `None` when service/contention are missing. In `static/dashboard.html:1166`, `const sf = m.service_frac ?? (m.contention_frac != null ? 100 - m.contention_frac : 100);` defaults to `100` if `service_frac` is null.
- **Note:** The plan states "Current `/api/latency` drops `wall_ms` ... JS then paints a 100% “model” bar for DeepSeek." This premise is fully accurate.

**FYI:** `#latency-rem-note` element exists in the DOM and is currently unused.
- **Evidence:** `static/dashboard.html:281` contains `<p class="consolidation-note" id="latency-rem-note"></p>`. In `renderLatency` (`static/dashboard.html:1142-1190`), this element is never targeted or manipulated.
- **Note:** The plan's claim (A8) that the "element exists, currently never filled" is correct.

**FYI:** `credsWarn` currently keeps the LLM pool panel open by itself.
- **Evidence:** `static/dashboard.html:1596` evaluates `const credsWarn = tokenFailed > 0 || ...`. On line 1600, the hide predicate `if (!hasPool && ... && !credsWarn ...)` explicitly prevents `panel.hidden = true;` if `credsWarn` is true. Thus, `tokenFailed > 0` alone currently keeps the panel visible.
- **Note:** The plan's directive (A3) that "tokenFailed / auditDropped must not keep the LLM pool panel visible by themselves" correctly identifies the need to change this logic.

## Verdict: REQUEST CHANGES
The plan perfectly maps the frontend behaviors and correctly diagnoses why the UI currently paints a fake 100% bar. It also correctly identifies the unused `#latency-rem-note` DOM element and the visibility rules governed by `credsWarn`. However, the plan misses the existing Python fallback (`latency.py:68`) that will erroneously promote the new `backend` URL to the model name if `model` is absent. Please amend the plan to address this before proceeding to implementation.
