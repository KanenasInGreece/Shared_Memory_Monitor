# Handoff — surface the Gateway agent-audit log in the monitor

**Goal:** add the gateway's per-request audit log as a third log source
(`gateway_audit`) in the monitor, alongside `gateway` (journal) and `rem_audit`.

**Data path:** the monitor is co-located with the gateway and already **tails log
files directly** (that's how `rem_audit` works). So this is a file-tail addition,
**not** a new gateway API endpoint. The gateway audit log is JSON-lines, the same
shape family as `rem-audit.jsonl`.

---

## What already exists (gateway side — `shared-memory-GitHub`, done)

The gateway already writes the log; the only action needed in that repo is to
**enable** it.

- **Writer:** `coordinator.py` → `_audit()` (in the auth-middleware section).
  Fires once per authenticated request, off the DB hot path.
- **Line format** (compact JSON, one object per line):
  ```json
  {"ts":"2026-06-12T18:04:11.checkZ","agent":"claude","role":"full","method":"POST","path":"/memory/search","status":200,"latency_ms":12.3,"request_id":"a1b2c3d4e5f6"}
  ```
  Fields: `ts, agent, role, method, path, status, latency_ms, request_id`.
- **Env var:** `GATEWAY_AUDIT_LOG_PATH` — unset = disabled (current state).
  Suggested value (already in the gateway `.env.example`):
  `~/.shared-memory/logs/gateway-audit.jsonl`.
- **To turn on:** add that line to `shared-memory-GitHub/.env`, then
  `systemctl --user restart hive-mind-gateway.service`.

---

## Monitor-side change points (this repo)

### 1. `src/sm_telemetry_monitor/env_loader.py` — the non-obvious gotcha
`_FRAMEWORK_KEYS` (frozenset, ~line 19) is a **whitelist** of keys the monitor is
allowed to read from the gateway `.env`. **Add `"GATEWAY_AUDIT_LOG_PATH"` to it.**
Without this the monitor silently won't pick up the path even when it's set on the
gateway. This is the single easiest step to miss.

### 2. `src/sm_telemetry_monitor/logs_reader.py` — register the source
- Add a `gateway_audit_path()` resolver beside the existing `audit_path()`:
  read `GATEWAY_AUDIT_LOG_PATH`, default to `log_dir() / "gateway-audit.jsonl"`.
- In `list_sources()` (currently returns `gateway` + `rem_audit`), append:
  ```python
  LogSource(
      id="gateway_audit",
      label="Gateway audit",
      kind="jsonl",
      path=str(gateway_audit_path()),
      description="Per-request gateway audit — agent, route, status, latency",
  )
  ```
- **Nothing else here changes.** `tail_source()` already handles `kind="jsonl"`
  generically; `server.py`'s `/api/logs/sources` (server.py:134) and
  `/api/logs/tail` allowlist (server.py:144) both derive from `list_sources()`,
  so the route and the UI tab appear automatically.

### 3. UI — edit **both** `static/logs.html` and `graphs/logs.html`
They are byte-identical copies; the server serves `static/`, `graphs/` is the
mirror. Keep them in sync.

- The source tab is dynamic (`bindSourceTabs` ← `/api/logs/sources`), so **no tab
  wiring is needed** — "Gateway audit" shows up on its own.
- Structured rendering is the real work. `renderRawLine()` (~line 279) has:
  ```js
  if (source === "rem_audit") { const audit = formatAuditLine(raw); ... }
  ```
  Extend that condition to include `gateway_audit`, **or** add a sibling
  formatter. `formatAuditLine()` (line **221**) is written for the `rem_audit`
  field set; the gateway log has different fields
  (`agent / role / method / path / status / latency_ms / request_id`), so lay
  those out (suggest: `agent` + `method path` + `status` + `latency_ms`).
- Optional polish: `classify(text)` (line **103**) drives severity coloring —
  map `status >= 400` to the warn/error class so failing requests stand out.

### 4. Tests — `tests/test_logs_reader.py`
Mirror `test_rem_audit_keeps_raw_json` (line 23): assert `gateway_audit` appears
in `list_sources()`, and that `tail_source("gateway_audit", …)` reads a temp
jsonl file. Same patterns as the existing source tests.

### 5. Docs (this repo)
`CHANGELOG.md` and `.grok/skills/shared-memory-monitor/SKILL.md` both enumerate
the log sources — add `gateway_audit`.

---

## End-to-end test recipe

1. **Enable** (gateway repo): add
   `GATEWAY_AUDIT_LOG_PATH=~/.shared-memory/logs/gateway-audit.jsonl` to `.env`;
   `systemctl --user restart hive-mind-gateway.service`.
2. **Generate traffic:** a couple of authenticated `memory_bridge.py search/save`
   calls; `tail -f ~/.shared-memory/logs/gateway-audit.jsonl` should fill.
3. **Monitor API:** `curl localhost:8765/api/logs/sources` lists `gateway_audit`;
   `curl 'localhost:8765/api/logs/tail?source=gateway_audit&lines=50'` returns
   the lines.
4. **UI:** open `localhost:8765/logs`, click **Gateway audit**.
5. **Tests:** `pytest tests/test_logs_reader.py` (monitor uses its own `uv` venv).

---

## Scope note

This surfaces the audit as a **raw tailable log feed**, consistent with
`rem_audit`. A per-agent **analytics** panel (request counts / latency by agent
over time) is a separate, larger dashboard addition — not required for the core
feature, but the obvious follow-up if aggregation is wanted instead of a feed.

## Background

The gateway audit log is the **observability tier** of agent auditing. Its rows
are the verified agent identity (bearer-token name today); they become
**non-repudiable** once the planned PoP (asymmetric-key + proof-of-possession)
auth overhaul lands, with no format change. See the `[Unreleased]` section of the
`shared-memory-GitHub` CHANGELOG for the hardening + auth/audit-seam work this
log is part of.
