# Plan — monitor v0.9.27: bucketed agent series + auto-discovered agent roster

Grounded on `fact:1804` (v0.9.26 trace) and `fact:1805` (scale envelope + operator-stated
outcome). No framework change: history timestamps come from the monitor's own store, agent
ids from the gateway audit JSONL already on disk. Keeps `fact:317` / `decision:260`.

## Problem being closed

1. `agent_activity()` is O(total corpus) **per request even on a cache hit** — 2 ms at 29.7k
   rows, ~124 ms projected at 1.48M. Months of logs is the growth axis that breaks it.
2. 63% of every scan is outside the slider range; 7/15 archives fall entirely outside it and
   are parsed anyway.
3. Agent chips are hardcoded: `codex` has a permanent chip and has never appeared;
   `backup` is real traffic with no chip. A first-time user sees agents they do not run.
4. The v0.9.26 "quiet" caption claims *no agent traffic* for intervals whose audit log has
   been rotated away. The store (18 d) already outlives the audit log (14 d).

## Unit A — server: one bucketed pass instead of N window queries

`src/sm_telemetry_monitor/logs_reader.py`

- **A1** Extend the `_AUDIT_CACHE` value to `(stamp, rows, span)` where `span` is the
  `(min_ts, max_ts)` of that file. Cheap: computed during the parse already happening.
- **A2** `_file_overlaps(span, since, until)` — skip a whole file whose span misses the
  window, without touching its rows. Closes finding 2.
- **A3** `audit_coverage() -> {"since", "until"}` — corpus min/max across all files, so the
  client can tell *no log coverage* from *quiet*. Closes finding 4.
- **A4** `agent_activity_series(timestamps)` — ONE pass, bucketing each row into the
  interval that ends at `timestamps[i]`, i.e. interval *i* covers `(t[i-1], t[i]]`.
  Uses `bisect_left(stamps, ts)`, which returns `k` for a row landing exactly on `t[k]` —
  matching the inclusive-`until` semantics of the existing `_in_window`. Rows before
  `t[0]` (index 0) and after `t[n-1]` (index n) are dropped.

  **Keyed by the interval's `until` timestamp, NOT by array index.** Measured risk that
  forces this: `parse_range` calls `datetime.now(UTC)` per request and the poll loop
  inserts rows between calls, so `/api/history` and the series endpoint genuinely can
  return different timestamp sets. Index alignment would then silently misattribute every
  interval. Keying by timestamp is drift-proof and sparse.

  Returns:
  ```
  {range,
   intervals: {"<until_ts>": {agents: {id: {read, write}},
                             daemon_logic: {node: {chat, embeddings, proxy}}}},
   roster: [{id, read, write}, ...],   # window totals, busiest first
   coverage: {since, until},           # audit corpus min/max
   fetched_at}
  ```
  Only non-empty intervals are emitted. Each interval's value has exactly the shape
  `summarizeAgentActivity` / `summarizeDaemonLogic` already consume, so the client lookup
  is `series.intervals[historyData.timestamps[tlIndex]] || EMPTY` and every downstream
  render path is unchanged.
- **A5** Keep `agent_activity()` (single-window form) and its route unchanged — it is a
  published endpoint with tests; the diagram simply stops calling it.

## Unit B — server: the route

`src/sm_telemetry_monitor/server.py`

- **B1** `GET /api/diagram/agent-activity-series?range=7d`. Derives timestamps from
  `load_history(since=parse_range(range), bucket_minutes=None)` — the *same* call the
  diagram's `/api/history?bucket=raw` makes — so alignment is structural, not coincidental.
  `range` is validated through the existing `parse_range`; anything unparseable falls back
  to the default rather than erroring.

## Unit C — client: chips discovered, not hardcoded

`static/diagram.html`

- **C1** Delete the 7 static `.arch-chip` elements; `#agent-chips` starts empty.
- **C2** `KNOWN_AGENTS`: canonical id → `{label, aliases[]}` for presentation only
  (`opencode` → "OpenCode (MCP)"). An id not in the table still gets a chip, labelled with
  its own id — discovery never silently drops an agent.
- **C3** `renderAgentRoster(roster)` builds chips with `createElement` + `textContent`
  only — **never** `innerHTML`, and `data-node` / `data-chip` carry a slugified
  `[a-z0-9_-]` value, never the raw id. Agent ids are untrusted (written by other
  processes); the v0.9.26 security review confirmed `chip.title` is the only sink today
  and this keeps it that way.
- **C4** Roster is derived from the WHOLE loaded window; only agents active in the
  SELECTED interval light up. Deriving per interval would make chips appear and vanish
  mid-drag.
- **C5** Drop the `other` / "Any HTTP client" chip — with discovery every observed agent
  has its own chip, so it can no longer be a catch-all.
- **C6** Empty roster → one muted line ("No agent traffic in the last 7 days"), not an
  empty rack.

## Unit D — client: scrubbing becomes an array index

- **D1** `agentSeries` global, fetched by `loadAgentSeries()` alongside `loadHistory()`.
- **D2** `loadAgentActivityForView()` becomes a pure synchronous lookup into `agentSeries`.
- **D3** Remove the v0.9.26 debounce + AbortController machinery (`agentActivityTimer`,
  `agentActivityAbort`, `agentActivityPending`, `AGENT_ACTIVITY_DEBOUNCE_MS`,
  `fetchAgentActivity`, `cancelPendingAgentActivity`). The whole class of lost-update /
  stale-timer bugs the QA review found goes away with the mechanism rather than being
  guarded against.
- **D4** Caption gains a third state, ordered most-specific first:
  *out of audit coverage* → "audit log for this interval has been rotated away";
  *covered but empty* → "no agent traffic in this interval";
  otherwise → "activity within this poll interval only".

## Unit F — DECIDED (operator, 2026-08-29): diagram = now + ONE log rotation

Chosen over clamping-to-full-coverage. Measured: rotation is **daily** (15 files retained,
~15 days coverage), and at a 24 h window the series costs **21 ms / 2.9 KB** against
67 ms / 68.8 KB at 7 d — while **discovering the identical roster of 5 agents**. A 24 h
window touches only the live audit file and never a gzip archive, so the diagram's cost is
bounded regardless of how long the monitor has run. That answers the months-of-operation
question structurally instead of by caching.

Information architecture this settles: **logs own history, the dashboard owns the snapshot,
the diagram owns now.** The diagram scrubbing a week duplicated the Logs page and is what
dragged the whole audit corpus onto the interactive path to begin with.

- **F1** `HISTORY_RANGE` on the diagram becomes `1d`; the series is fetched at the same
  range. The server keeps its `range` parameter, so widening later is a one-constant
  client change with no server rework.
- **F2** State the window as a flat fact on the page — "last 24 hours · one log rotation" —
  rather than explaining a computed clamp.
- **F3** Past state must read at a glance: the timestamp and caption time range go **amber**
  the moment the view leaves live, plus an amber rule on the canvas itself so the picture is
  marked historical, not just the control under it. Live stays neutral — the past is the
  exceptional state and carries the marking.
- **F4** "Return to now": clicking the amber timestamp snaps back to live. Dragging a
  slider fully right is a poor way back.
- **F5** `coverage` is still rendered, for the case where rotation removes the window's tail
  while the page is open.

## Unit F-alt (NOT taken) — clamp the slider to what the audit log can answer

Measured on this host: audit rotation is **daily**, retained 15 files (live + `.1` +
`.2.gz`..`.14.gz`) = **~15 days coverage** (2026-08-14 → 08-29). The 7-day slider sits
inside that today, but the monitor's own store is already 18 days and grows forever with
no pruning, and retention is the framework's logrotate, not the monitor's — so the
mismatch is structural, not hypothetical.

- **F1** Rather than explain a dead zone, remove it: clamp the slider's minimum index to
  the first history sample at/after `coverage.since`. The scrubber then spans exactly the
  intersection of stored history and audit coverage — self-tuning, so an operator keeping
  3 days of logs gets a 3-day scrubber and one keeping 30 is bounded by `HISTORY_RANGE`.
- **F2** Keep D4's caption fallback anyway, for the interval that rotates away while the
  page is open.
- **F3** Surface the coverage span in the replay caption's context line so the operator
  can see why the slider starts where it does.

## Unit E — tests (`tests/test_logs_reader.py`, `tests/test_server.py` if needed)

All hermetic: `tempfile` + mocked `agent_audit_path` / `_log_root`, no workstation paths.

- E1 bucketing: a row lands in the interval ending at the first timestamp `>=` its ts;
  boundary row lands in the earlier interval; rows before `t[0]` / after `t[-1]` dropped.
- E2 roster: alias folding (`claude-code` → `claude`), unknown agent still listed, daemons
  excluded.
- E3 coverage: reports corpus min/max; empty corpus reports nulls.
- E4 archive skipping: a file whose span misses the window is not parsed (spy on
  `_read_audit_lines`).
- E5 malformed rows (list agent, dict path, epoch-int ts, non-dict row) tolerated in the
  series path exactly as in the window path.
- E6 series with < 2 timestamps returns an empty, well-formed payload.
- E7 cache still bounded; series and window forms agree on the same interval.

## Verification

- Full suite green, and green under `env -i` with no HOME / no workstation log paths.
- Live: series request count on a 100-step drag must be **0**; page load must issue exactly
  one series request.
- Browser: roster shows exactly the agents in the corpus (expect `claude`, `grok`,
  `lm_studio`, `gemini`, `backup`, `opencode` — and **no** `codex`).
- Re-run the 180-step storm benchmark; `/api/diagram` must stay flat.
- `scripts/pre-publish-check.sh` green.

## Out of scope (recorded, not done)

Monitor store retention/pruning (~225 MB/year, `fact:1805`); the `0.0.0.0` bind + no-auth +
`ACAO: *` posture flagged by the v0.9.26 security review; a server-side concurrency cap.
