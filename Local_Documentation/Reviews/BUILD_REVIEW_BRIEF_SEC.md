You are the Security reviewer (Claude Opus 4.6) for Shared Memory Monitor.

Do NOT implement. Do NOT edit src/, static/, tests/, version files. Do NOT merge.

Commit: b02ea17 on branch feature/v0.9.20-latency-placement
Worktree: /home/xenofon/grok-labs/projects/shared-memory-monitor-wt-0960
Files: src/sm_telemetry_monitor/latency.py, tests/test_latency.py, static/dashboard.html, static/theme.css

Focus:
- XSS: innerHTML vs textContent vs esc() on model, backend URL, rem.note, hint line, pool line
- No secrets in passthrough (backend URL is already public on pool chips)
- No new routes, no token widening, credentials still do not flip deck status (I2)
- Constant href /logs?source=credential_audit only
- style=width:${frac}% only when frac is a number

Write the review to:
Local_Documentation/Reviews/Security_Review_0.9.20.md

Format: Context, Findings (Critical/Required/Optional/Nit/FYI), Verdict APPROVE | REQUEST CHANGES.
