# Changelog

All notable changes to Shared Memory Monitor are documented here.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.7.8] - 2026-07-23

**Docs / project-page impact.** Current main-page screenshot under the README title.

### Changed

- **README hero** — recaptured `docs/images/dashboard.png` (Gateway health OK,
  status deck, infrastructure, LLM pool, backlog) and placed it **directly under
  the title**, before the intro text. Screenshots section notes the same frame.
- Other README gallery images (diagram, logs, consolidation, schema) refreshed
  from the live monitor in the same capture pass.

## [0.7.7] - 2026-07-23

**Compatible with Shared Memory Framework gateway ≥ v0.8.9 for new fields · wire
contract API v3 unchanged.** Label clarity for the status deck.

### Changed

- **Deck title** — `Status · components` → **Gateway health** (pill label **Gateway**).
  Overall pill is gateway-class health only; per-component state is color-coded in
  the Infrastructure grid below. Tooltips updated so Pipeline vs Gateway are not
  confused with component colors.

## [0.7.6] - 2026-07-23

**Compatible with Shared Memory Framework gateway ≥ v0.8.9 for new fields · wire
contract API v3 unchanged.** Overall status tracks gateway-class health.

### Changed

- **Overall status contract (decision 903 / fact 902)** — `/api/health` `status`
  tracks gateway-class health only: process down, blocked paths, failed/degraded
  backends, consolidation telemetry stall/stale. **REM/NREM backlog** (including
  client `rem_drain` flat) is a process variable — tile text may say `N queued`
  with “no net drain yet”, but it no longer yellows the tile or elevates deck
  `status` to `warn`. Hero banner remains the home for “what’s upcoming”
  (REM/NREM-saturated). Missing optional fields (`unknown`) no longer elevate.

## [0.7.5] - 2026-07-23

**Compatible with Shared Memory Framework gateway ≥ v0.8.9 for new fields · wire
contract API v3 unchanged.** Diagram pool + install/doctor docs for current
telemetry UX.

### Added

- **Diagram LLM pool** — `/diagram` Reasoning LLM card lists multi-backend pool
  members from `/api/diagram` → `health.llm_pool` + `config.backends`, with
  **local** / **external** placement badges and optional model (gateway ≥0.8.9).
  Layer badge shows local/external mix; gateway→LLM flow still targets the pool
  card (single proxy hop).

### Changed

- **Install / doctor / agent docs** — `check-env` / doctor report modern telemetry
  panels (`entity_graph`, `latency`, `spine`, `compliance`) and non-secret LLM
  placement (`has_credential` → local/external counts). `install.sh` and
  `install-systemd-user.sh` describe what a green doctor means on the dashboard;
  README, `AGENTS.md`, sister contract, and `.env.example` aligned to full UI on
  framework **≥0.8.9** (wire still **API 3** / ≥0.7.0).
- **README screenshots** — dashboard + diagram recaptured for placement badges.

## [0.7.4] - 2026-07-23

**Compatible with Shared Memory Framework gateway ≥ v0.8.9 for new fields · wire
contract API v3 unchanged.** Local vs external LLM placement on the ops UI.

### Added

- **Local vs external LLM placement** (framework ≥0.8.9) — pass-through of
  non-secret `config.llm_backends[].has_credential` + optional `model` on
  `/api/health` (config backends + pool chips joined by URL). Infrastructure
  summary shows e.g. `2 LLM backends · 1 local · 1 external`; pool chips badge
  **local** / **external** and surface the model override when set. Pre-0.8.9
  gateways omit placement (no URL heuristics). Secrets never appear.

## [0.7.3] - 2026-07-22

**Compatible with Shared Memory Framework gateway ≥ v0.8.6 for new fields · wire
contract API v3 unchanged.** Post-review polish on the 0.7.2 drawer (Cloe consult
aligned).

### Changed

- **Graph health KPI de-dupe** — when `genuinely_referenced_entities` is present,
  show that census only (with % of all); omit the redundant **Mentioned** cell
  (same integer). Pre-0.8.6 gateways still show residual **Mentioned**.
- **REM fairness instrument tone** — `passed_over` / `starved_pending` use
  dashed/slate **instrument** styling (path-live / dormancy), not amber warn
  shared with dead-lettered/failing safety-net KPIs.
- **Consolidation KPI helper** — shared `consolidationKpiHtml` for drawer tones
  (`warn` / `bad` / `ok` / `instrument`); trends CSS remains in `theme.css`
  under a dated section comment (no second stylesheet).

## [0.7.2] - 2026-07-22

**Compatible with Shared Memory Framework gateway ≥ v0.8.6 for new fields · wire
contract API v3 unchanged.** Fields degrade cleanly on older gateways.

### Added

- **Genuinely referenced entities** (framework 0.8.6 / fact 895, decision 890
  refined via retro 893) — Consolidation drawer Graph health reads
  `telemetry.entity_graph.genuinely_referenced_entities` (MENTIONS-only census).
  **Alias coverage** uses that denominator when present
  (`alias_covered / genuinely_referenced`) instead of the mixed `entities_total`
  population (~54% Decision provenance free-text). `entities_total` stays on
  screen as "Entities (all)".
- **REM fairness gauges** (framework 0.8.6 / fact 895, decision 894) — same
  drawer band now shows `neo4j.rem_passed_over_total` and `rem_starved_pending`
  (batch-vs-solo yield fairness / starved sub-queue). Zeros under a thin backlog
  are honest dormancy (path not exercised), not a broken metric.

### Changed

- **Pipeline vs Components pills** (chromebook-claude fact 872) — hero pill is
  labelled **Pipeline** (backlog narrative + coarse health); Status pill is
  **Components** (daemon/service stall heuristics). Tooltips state they are
  different signals so OK+WARN in one viewport no longer reads as a bug.
- **Trend hierarchy** — Status deck remains the primary operator surface; only
  **Backlog over time** stays always-visible. Throughput, cumulative, and tier-3
  growth sit under a collapsed **More trends** disclosure (Chart.js resizes on
  open). Compact chart heights reclaim first-paint real estate for live status.
  Throughput y-axis polish deferred.

## [0.7.1] - 2026-07-20

**Compatible with Shared Memory Framework gateway ≥ v0.7.0 · wire contract API v3.**
No wire-contract change — both fields were already arriving on `GET /memory/telemetry`
(live-diffed against a running 0.8.1 gateway) but the monitor never read them.

### Added

- **Live NREM density-gate thresholds** — the Consolidation drawer's density-gate
  note named cycle counts but not the gate itself; it now reads
  `telemetry.nrem.fact_threshold` / `decision_threshold` off the wire
  (`NREM density gate: 5 fact / 2 decision cycles (gate: ≥5 facts or ≥2
  decisions per domain, live)`) instead of only the monitor's local constants,
  so the copy can't silently drift if the framework retunes the gate.
- **In-flight cycle running time** — `telemetry.consolidation.<type>.last_started`
  was fetched and discarded; the by-cycle table now shows `yes (running 3m)`
  for a cycle actually mid-run instead of a flat `yes`/`—`.

## [0.7.0] - 2026-07-20

**Compatible with Shared Memory Framework gateway ≥ v0.7.0 · wire contract API v3.**
Verified against a live gateway upgraded to 0.8.1 during this release — wire
contract unchanged (`api_version` stays **3** on both sides).

Surfaces two more fields already on `GET /memory/telemetry` that framework
decisions landed the same day (819, 838, 840, 842) — still a pure visual aid,
no new data path.

### Added

- **REM reliability · stranded records** (decision 819) — the overloaded
  `rem_attempts` counter was split into `rem_pickups` (rotation, never charged)
  and `rem_attempts` (failure charging only), exposing a previously-invisible
  case: records picked up repeatedly, never succeeded, never blamed. New band
  in the Consolidation drawer shows `telemetry.neo4j.rem_dead_lettered` /
  `rem_failing` / `rem_max_attempts`, labelled explicitly as the safety net
  working as designed — a nonzero count is not a regression.
- **Deferred/Idle (24h) per cycle** (decision 842) — the shared idle clock was
  split by consumer (hygiene sweep vs. consolidation cycle) with reasoned-default
  timer values the framework calls explicitly **unproven**; a retrospective is
  "deliberately owed" once per-type run/deferral/idle telemetry accumulates over
  a full load cycle. New column in the by-cycle table surfaces
  `deferred_24h` / `idle_24h`, labelled **provisional** so a single day's numbers
  don't read as a verdict.

## [0.5.6] - 2026-07-20

**Compatible with Shared Memory Framework gateway ≥ v0.7.0 · wire contract API v3.**

Surfaces per-cycle-type consolidation telemetry already on
`GET /health.consolidation` and `telemetry.consolidation` so operators can tell
*which* dream-cycle type is stalled and whether it is actually folding — still
a pure visual aid (no new data path).

### Compatibility

| Monitor | Framework gateway | Client `X-SM-Api-Version` |
|---------|-------------------|--------------------------|
| **0.7.0** | **≥ 0.7.0** (verified against 0.8.1) | **3** |
| 0.5.6 | ≥ 0.7.0 | 3 |
| 0.5.5 | ≥ 0.7.0 | 3 |
| 0.5.4 | ≥ 0.7.0 | 3 |
| 0.5.1–0.5.3 | 0.6.5 (retro-as-record) | 2 |

### Added

- **Per-cycle-type consolidation telemetry** (framework gateway ≥0.7.x, decision
  834 / facts 828–835) — surfaces fields already on `GET /health.consolidation`
  and `telemetry.consolidation` without a new data path:
  - **Sidebar tile** — stalled headline names which type(s) are stuck
    (`Stalled [fact consolidation]`); caption tags last success with its cycle
    type (`success 4h ago (fact consolidation)`).
  - **Liveness KPIs** — stalled types, last success *(with type)*, last active
    cycle type. Fixes the OR'd-headline trap where one healthy cycle made the
    whole surface look dead for days while another type was still folding.
  - **By-cycle table** — `runs_24h`, avg cycle seconds, folds succeeded/attempted
    over 24h (insight empty runs vs fact-consolidation cost differ by ~1000×).
  - Poll cache stores stalled types + per-type 24h activity for the hero
    headline; Status summary says `consolidation stalled [fact consolidation]`.

## [0.5.5] - 2026-07-19

**Compatible with Shared Memory Framework gateway ≥ v0.7.0 · wire contract API v3.**

Surfaces multi-backend LLM pool telemetry already on `GET /health` so operators
can see which card is inferring, how load is routed, and hung-call age — still
a pure visual aid (no new data path).

### Compatibility

| Monitor | Framework gateway | Client `X-SM-Api-Version` |
|---------|-------------------|--------------------------|
| **0.5.5** | **≥ 0.7.0** | **3** |
| 0.5.4 | ≥ 0.7.0 | 3 |
| 0.5.1–0.5.3 | 0.6.5 (retro-as-record) | 2 |

### Added

- **LLM pool panel (Infrastructure)** — when the gateway emits multi-backend
  `/health.llm_pool` + `llm_backends`, the Status sidebar shows per-backend
  chips (host:port, busy/free/down, in-flight, routed %, weight, fails,
  cooldown) plus a summary line (busy/free/up, GPU busy state). Still
  read-only from gateway health — no direct GPU or DB access.
- **Oldest in-flight age** — `llm_oldest_inflight_age_s` on `/api/health` and
  in the pool summary / LLM caption (wedge visibility on single- and
  multi-backend installs).
- **Live affinity** — `llm_affinity` hit/miss/hot-prefix counters (multi-backend
  runtime map) under the pool panel; static knobs remain on the config hover.
- **Wedge suspect** — `llm_suspect_wedged` labels surface as warn on the LLM
  tile caption and pool line when the gateway flags hung generation.
- **Latency drawer** — REM per-model **p95** service/wait times and
  `max_batch_size` when present on `telemetry.latency.rem_ms.by_model` (bars
  still use p50 anchors).

### Changed

- LLM tile captions name **which backend(s)** are inferring (labels from the
  pool map) and include oldest-in-flight age when the gateway reports it.

## [0.5.4] - 2026-07-16

**Compatible with Shared Memory Framework gateway v0.7.0 · wire contract API v3.**

This release aligns the monitor client with the live enrichment-rebuild gateway
(framework **0.7.0**, `api_version` **3**). The dashboard remains a pure visual
aid over existing `GET /health` and `GET /memory/telemetry` — no new data path.
Relation calibration routes (`/memory/relations/review`, `/label`) stay
write-role only and are not proxied here.

### Compatibility

| Monitor | Framework gateway | Client `X-SM-Api-Version` |
|---------|-------------------|--------------------------|
| **0.5.4** | **≥ 0.7.0** (verified on 0.7.0) | **3** |
| 0.5.1–0.5.3 | 0.6.5 (retro-as-record) | 2 |

`./scripts/check-env.sh` reports `api server=N client=N compat=ok` when versions
match. Older gateways still answer most reads; the header bump stops gateway
skew warnings after a 0.7.0 deploy.

### Changed

- **API contract header** — `bridge.API_VERSION` (and the doctor write-probe
  header) advertise **3**, matching framework **v0.7.0 / api_version 3**. Policy
  unchanged: track the *deployed* gateway contract, not an unreleased tree.

### Added

- **Gateway effective config** — `/health.config` (backends + weights, pool
  tuning, affinity knobs, `embed_max_chars`) is parsed into `/api/health` and
  shown under Infrastructure (e.g. `Gateway 0.7.0 · API 3 · 1 LLM backend ·
  embed 24k`; hover for per-backend / tuning detail). Works on single-backend
  installs where live `llm_pool` status maps are omitted.
- **Largest alias group** KPI on Graph health — surfaces
  `entity_graph.largest_alias_component` when the alias layer is active.

## [0.5.3] - 2026-07-16

### Added

- **`agent-status.sh` GitHub update check** — probes `origin` with `git ls-remote`
  (no local ref rewrite): reports `behind_branch`, `behind_release` / latest
  `vX.Y.Z` tag, `updates_available`, and an `upgrade_cmd`. Human output shows a
  **github:** line; `--offline` skips the network. Exit **1** when ready but
  updates are available (`overall: ready_updates`) so agents can auto-upgrade.
- **`agent-upgrade.sh`** runs a status pre-check (including GitHub) before pull.

### Changed

- **AGENTS.md** / **README** document the update-check loop.

## [0.5.2] - 2026-07-16

Agent-operable quick start: a coding agent can install, verify, run, and upgrade the
monitor without a human walking every shell step.

### Added

- **`AGENTS.md`** (+ thin **`AGENT.md` pointer**) — Part 1 operate (interview → install →
  `monitor:read` token → verify → start/systemd → day-2 runbooks) and Part 2 develop
  (commands, architecture invariants). Same pattern as the framework agent playbook.
- **`scripts/agent-status.sh`** — one-shot status (human or `--json`): git, package,
  gateway HTTP, doctor/api compat, user unit, dashboard. Exit 0/1/2 = ready/partial/not
  ready; prints a **next** action for agents. No secrets.
- **`scripts/agent-upgrade.sh`** — `git pull` (or `--ref TAG`), `uv sync`, reinstall/
  restart user unit if present, then `agent-status.sh`.

### Changed

- **README Quick start** — points agents at `AGENTS.md` and documents `agent-status` /
  `agent-upgrade`.

## [0.5.1] - 2026-07-16

Alignment with **live** framework gateway **v0.6.5 / api_version 2** (retro-as-record)
and a README packaging pass: USP lede + quick start first. Still a pure visual aid
over **existing** gateway telemetry and logs — no new data path.

### Fixed

- **API contract header** — `bridge.API_VERSION` (and the doctor write-probe header)
  now advertise **2**, matching live framework gateway **v0.6.5 / api_version 2**
  (retro-as-record). Ends the recurring gateway journal skew warning for the
  monitor agent. Policy: track the *deployed* gateway, not an unreleased tree
  (e.g. rem-rebuild API v3).
- **Doctor `dashboard_history`** — `FEATURE_MATRIX` depended on `telemetry_cache`
  but readiness never handled that key (always `unknown`). Now maps to poll-cache
  sample count like other local features.
- **Doctor report** — connectivity line includes gateway version + server/client
  `api_version` and `compat`.
- **Deferred cycle display** — `eligible_clusters is None` no longer collapses to
  **idle** (unknown ≠ zero). Idle only when the gate census is *explicitly* 0.
- **Agent-audit I/O classification** — `/memory/search` is **read**; supersede /
  review_hold / relations/label are **write**; lineage `GET /memory/status/{id}`
  and relations/review are **read**.

### Changed

- **First-write completeness labels** (API v2 honesty) — spine non-decision total
  is labeled **Non-decision records** (facts + retrospectives + other types), not
  “Facts written”. Note explains the gateway bucket. **Elicited %** is shown for
  decisions and non-decision records when the spine provides it.
- **README** — opens with a USP-style pitch (visual aid over *existing* Shared
  Memory telemetry) and **Quick start** before architecture depth.

### Added

- **Superseded docs count** — `postgres.technical_docs_superseded` (and total) on
  the Schema drawer meta table and in the poll-cache flatten; no new data path.

## [0.5.0] - 2026-07-15

First consumption of the framework gateway's **v0.6.2 / v0.6.3** telemetry — the
new `spine`, `compliance`, and `latency` blocks. Everything below reads only
what `GET /health` and `GET /memory/telemetry` already expose (read-only
`monitor:read` token); no new data path.

### Added

- **First-write quality band** (consolidation drawer, above Coverage). Sourced
  from `telemetry.spine` + `postgres.outbox_failed_oldest_age_seconds`, it is the
  *upstream* quality gate for the two consolidation axes: a record folds and
  resolves well only if it arrived complete. Three groups read left-to-right —
  **Completeness** (the fill-rate of the fields the write path prompts for:
  decisions with sources cited / alternatives / confidence, facts with a
  citation; low rates flagged as an elicitation gap), **Schema growth** (metadata
  keys records carry that the schema hasn't adopted — promotion candidates, not
  errors), and **Integrity** (duplicate-entity merges, plus any writes abandoned
  before reaching the graph). Omitted with no error on pre-0.6.2 gateways.
- **Schema conformance** (integrity group of the same band). From
  `telemetry.compliance`: whether graph node labels and relationship types stay
  within the agreed ontology, naming the off-vocabulary offenders. Pre-0.6.3
  gateways omit it.
- **Throughput & latency drawer** (new drill-down). From `telemetry.latency`:
  - **Record enrichment** — per backend model, a stacked bar splitting time into
    the model's own compute (**model floor**, set by model + hardware) vs
    **queue wait** (delay under load). A mostly-floor bar is model-bound; a large
    wait segment is load-bound (add capacity / reduce concurrency). Degrades to an
    honest empty state when no enrichment ran in the window.
  - **Consolidation cycles** — median and p95 cycle time over a rolling window,
    always shown with the sample count and window, plus a plain-language note on
    the p95/p50 spread. The gateway gates this to real synthesis cycles
    (`folds_succeeded > 0`), so deferred/no-op sweeps no longer skew it.
  - A **queue-wait chip** promotes to the drawer trigger on the main deck *only*
    when a model's contention share crosses 30% — otherwise latency stays in the
    drill-down (no vanity always-on number).

### Changed

- Clarity pass on drawer copy for a general audience — internal terms (the
  framework's "spine" etc.) are not surfaced in the UI.

## [0.4.13] - 2026-07-03

Alignment release for framework gateway **v0.6.1** (LLM backend pool +
entity-resolution alias writer). Everything below reads only what `/health`
and `GET /memory/telemetry` already expose — no new data path.

### Added

- **Per-backend LLM pool on the LLM tile.** Multi-backend gateways
  (`LLM_BACKENDS` in the gateway env) expose `llm_pool` / `llm_backends` on
  `/health`; the tile now reads them as the authoritative per-model busy
  signal: `busy 1/2` when one backend is inferring, `1/2 up` (warn) when a
  backend is down, `idle · pool of 2` when the whole pool is free. When the
  pool is idle but nvtop still reports the GPU busy, the tile reads
  "GPU busy · no pool call in flight" — truthful direct-load (outside the
  gateway) rather than a false pool claim. Single-backend gateways omit the
  pool fields and keep the existing nvtop-based tile unchanged. The snapshot
  exposes the parsed pool as `llm_pool` for the dashboard.
- **`pool_busy` defer reason.** v0.6.1+ daemons gate dream cycles on a free
  pool slot and record `last_deferred_reason: "pool_busy"`; the tile and
  drill-down now render "Deferred — LLM pool busy" (the pre-pool `gpu_busy`
  wording is kept for single-backend stacks).
- **Graph health aligned to the corrected v0.6.1 `entity_graph` semantics.**
  `orphan_entities` is now truly dangling (degree 0 — flagged warn when
  nonzero, expected 0); the new `unmentioned_entities` ("Structural only")
  is the honest coverage proxy; **Mentioned** (entities with live
  fact/decision mentions) replaces the old "Connected" derivation, which the
  corrected orphan count had reduced to a constant 100%. Alias-layer KPIs are
  now live: edges · groups (`alias_components`) and alias coverage. Pre-0.6.1
  gateways simply omit the new KPIs.

### Fixed

- **REM stall detection no longer hides behind global GPU load on pool
  gateways.** Since v0.6.1 REM defers only when the whole LLM pool is busy —
  nvtop-busy (often REM's own card, or a direct chat) is not a defer signal
  there. The REM tile now gates on pool free-slots: "deferring · LLM pool
  busy" only when no slot is free, and a flat backlog with a free slot warns
  as a genuine stall even while the GPU reads busy.
- **Stale cycle errors no longer displayed as live faults.** The gateway keeps
  the most recent cycle error indefinitely (e.g. `OrphanedRun` from a daemon
  restart whose in-flight row was already recovered); the drill-down now shows
  `last_error` only while it is current — a non-completed outcome or an active
  failure streak — instead of pinning a long-fixed error to a healthy cycle.

### Documentation

- README consolidation section rewritten around the two-axis view (Coverage =
  output, Graph health = input) with the new `telemetry.entity_graph` fields and
  the REM-pending caveat; drawer-fields and metrics tables extended accordingly.
  Screenshots refreshed from a live monitor (consolidation drawer now shows the
  Graph health · entity resolution row).

## [0.4.12] - 2026-06-28

### Added

- **Graph health — the input-side consolidation-quality axis** in the
  consolidation drill-down. ADR-017/018 frame consolidation quality on two axes:
  the *output* side (Coverage — facts folded into summaries, already shown) and
  the *input* side (entity resolution — how connected the graph is before a cycle
  runs). The drawer now surfaces the input side from `telemetry.entity_graph`:
  **Entities**, **Connected** (count · %), **Orphans** (count · %), **Singletons**
  (count · %), **Top hub degree**, and **Alias edges**. Orphan and singleton
  entities are weakly connected and never fold into a summary, so a high orphan
  share caps achievable coverage regardless of cycle liveness — making this the
  "garbage-in" leading indicator that complements the liveness/coverage signals.
  These are the GDS-family signals (orphan / low-degree counts and the
  node-degree hub head) the gateway already computes; the monitor surfaces them
  read-only with **no new data path** — consistent with the data-sourcing
  principle. WCC / Louvain modularity are not in the gateway payload, so the
  fragmentation proxy is derived from the orphan/singleton ratios that are.

  **Requires framework gateway v0.6.0+** (first version to expose
  `telemetry.entity_graph`). On older gateways the field is absent and the Graph
  health block is omitted with no error.

- **REM-pending anti-bloat caveat on Graph health.** `entity_graph` counts
  *every* entity node, including those extracted from records still awaiting REM
  — but REM is the stage that builds an entity's relationships, so a pre-REM
  entity is counted as an orphan/singleton purely because it hasn't been
  processed yet. Graph health now surfaces **Awaiting REM** (`rem_pending_facts`
  / `rem_pending_decisions`, flagged warn) and annotates the note so the
  orphan/singleton share reads as an *upper bound* on true fragmentation until
  REM catches up — never a settled quality verdict (avoids bloated numbers).

### Changed

- `consolidation_from_payload` now extracts `telemetry.entity_graph` and returns
  a `graph_health` block (`_graph_health`), threaded with the `telemetry.neo4j`
  REM-pending census; every field degrades to `None`/`[]` on missing input so one
  absent metric never blanks the rest.

## [0.4.11] - 2026-06-26

### Changed

- **The REM tile warns only on a genuine stall, never on a non-empty queue.**
  Previously the REM daemon tile warned whenever `rem_backlog >= 1` (a flat
  count gate), so a healthy queue draining while the LLM was busy showed a false
  WARNING — the same false alarm NREM shed in v0.4.9. The tile now reads:
  `queue idle` when caught up; **`N deferring`** (ok, no warn) while
  `inference_busy == busy` (REM is gated off by design — GPU-owner-agnostic, per
  the nvtop strict-superset guarantee); **`N draining`/`N queued`** (ok) when the
  GPU is idle/unknown and the backlog is falling or there is too little history
  to judge; and **`N stalled`** (warn) only when the GPU is free *and* the
  backlog has not drained for ~2.5 REM sweeps. This mirrors NREM's stall-only
  philosophy and consumes only already-exposed telemetry — no framework change.

### Added

- **`rem_drain_signal()` — a client-side REM drain heuristic** (`analytics.py`)
  over the stored sample tail, returning `draining | flat | insufficient`,
  anchored to the latest sample's own timestamp so the 600s persisted-poll lag
  never trips a false stall. `REM_STALL_WINDOW_S` (= `REM_POLL_S * 2.5` = 300s)
  mirrors NREM's 2.5×-sweep threshold. This is the honest interim until the
  gateway exposes an authoritative server-side `rem_stalled` field.

## [0.4.10] - 2026-06-26

### Added

- **`inference_busy` — a truthful "LLM Busy" signal from nvtop.** The gateway now
  exposes the nvtop GPU-busy gate (the exact check REM/NREM defer on) as a
  top-level tri-state `inference_busy` (`busy` | `idle` | `unknown`) on both
  `GET /health` and `GET /memory/telemetry`. The LLM tile reads load from this
  signal instead of inferring "busy" only from a consolidation cycle in flight,
  so it now reflects a user chatting directly with `:5000` — load no daemon
  ledger could ever see. `unknown` (nvtop absent / `SLOT_AWARE=0`) is never
  rendered as a false `idle`. The signal is also persisted to the sample history.

### Changed

- **The LLM tile no longer flips to critical while the LLM is running.** When the
  `:5000` reachability probe times out under a GPU-busy load but nvtop confirms
  the GPU is inferring, the LLM is shown as **busy (probe saturated)** — a warn,
  not the hard "down"/critical it used to report — and the REM/NREM gates stop
  claiming "blocked (LLM down)" while inference is plainly in flight.
- **GPU-busy log lines read as deferred warnings, not errors.** REM/NREM
  back-pressure during GPU-busy periods (`LLM failed — skipping`, `503 backend
  unreachable`, connection/read timeouts, `next sweep retries`) is now classified
  as warnings in both the log viewer and the severity counts — these are
  self-healing deferrals the daemon retries, not faults. Genuine crashes and
  unrelated failures still surface as errors.
- **Consolidation deferrals are explained.** The consolidation tile and drill-down
  now name the deferral reason from `last_deferred_reason`, rendering
  "Deferred — inference GPU busy" / "backup in progress" instead of a bare
  "deferred".

## [0.4.9] - 2026-06-25

### Changed

- **Consolidation drill-down — liveness & coverage depth.** "Last success" is now
  derived from the freshest per-cycle success when the top-level rollup is null
  (no more false "never" while consolidated facts/insights exist), and is hidden
  entirely when no timestamp exists anywhere. Coverage adds a **Decisions (REM)**
  line and a **Consolidations by type** breakdown (insight / thematic / community,
  active + superseded) — the output-side evidence that consolidation has run.
- **Pipeline queues — NREM clarity.** Renamed "NREM facts" → **Unconsolidated**;
  NREM cycles and Unconsolidated are density-gated (facts wait until a cluster
  meets the gate), so a non-zero count is normal. They now read **green = healthy**
  (red only when consolidation is stalled) instead of an ambiguous grey, with
  hover tooltips sourced from the telemetry hints.
- **NREM daemon & Status pill — consistent signal.** A non-zero NREM backlog no
  longer marks the Infrastructure NREM daemon `warn` (amber) or trips the Status
  pill to **WARN** with an "NREM N" summary. The daemon shows "N queued" (ok) and
  only warns when the consolidation signal is **stalled** — so the same pending
  cycle is never green in the pipeline yet amber in Infrastructure.
- **LLM "Busy" restated.** The LLM tile previously showed **Busy** whenever a
  REM/NREM backlog existed, even with the LLM idle (the gateway only reports it
  reachable). It now shows **Up** (reachable · no active cycle) and **Busy** only
  when a dream cycle is actually in flight — so "Busy" reflects real inference,
  not merely queued/gated work.

## [0.4.8] - 2026-06-25

### Changed

- **Sidebar drill-downs** — Consolidation and Schema breakdown share a
  **Drill-down** section with unified `drawer-trigger` styling (dashed border,
  **Open** pill, live status accent on Consolidation). Drill-down sits at the
  top of the sidebar; Backup and Infrastructure follow the metrics blocks.
- **Status deck layout** — status blocks form a full-width deck above the charts
  in three labelled rows: **Drill-down**, **Backlog & queues** (Dream backlog,
  REM / NREM split, Pipeline queues), and Backup / Infrastructure. The metrics
  row fills the width (no empty right strip); Backup and Infrastructure each have
  an aligned heading.
- **Consolidation drill-down** — added a **Coverage** summary computed from the
  neo4j fact census (REM-processed facts, consolidated count + %, awaiting-fold
  count + %) so the panel reports real progress, not just per-cycle liveness. The
  per-cycle table column **Coverage** is renamed **Eligible** (it reports
  `eligible_clusters`, the strict-gate clusters awaiting a fold — not a ratio);
  deferred cycles with no eligible work now read **idle** instead of **deferred**,
  and a benign deferral is no longer styled as a warning. Drawer subtitle no
  longer cites an internal ADR.
- **Pipeline sidebar grid** — odd cell count no longer leaves an empty column
  on the right (last row spans full width).

### Fixed

- **REM audit false errors** — the log severity classifier scanned the whole
  JSONL line (including the memory-content payload), so benign REM-audit entries
  whose content mentioned “error”/“failed”/“defer” were painted red/amber.
  Structured audit lines are now classified by their status field only; the
  free-text heuristics are restricted to the gateway journal.
- **Redundant bottleneck label** — the REM/NREM saturation verdict appeared in
  both the hero banner and a sidebar card; the card is now **REM / NREM split**
  (split bar, counts, ETA) and the banner is the single source of the verdict.
- **Logs deep link** — `/logs?consolidation=1` no longer throws before init
  (`consolidationFilter` temporal dead zone); forces gateway source when needed.
- **Consolidation drawer** — removed redundant “Correlate in logs” section;
  header **Logs** link opens gateway journal with the Consolidation filter
  (patterns documented on the filter chip tooltip).
- **Phantom right column / scrollbar** — closed schema/consolidation drawers used
  `display: flex`, which overrode the HTML `hidden` attribute; off-screen drawers
  still expanded page width. `[hidden]` and `overflow-x: clip` now suppress it.
- **Dashboard layout** — removed the fixed 340px right sidebar column (empty grid
  strip + nested scrollbar); status blocks are a full-width **status deck**
  above the charts.

### Docs

- Refreshed README screenshots for the status-deck layout and added a
  **Consolidation health** drawer capture (`scripts/capture_screenshots.py` now
  captures the consolidation drill-down). Documented the consolidation drawer
  liveness/coverage fields and their sources.

## [0.4.7] - 2026-06-25

### Added

- **Consolidation health (Status sidebar)** — clickable card keyed on gateway
  `GET /health` → `consolidation.stalled` / `fresh`; shows outcome and last
  success age. Opens a drill-down drawer with per-cycle liveness and coverage
  from `telemetry.consolidation` (ADR-018 / framework PR #79).
- **`GET /api/consolidation`** — live consolidation panel payload for the drawer.
- **Logs — Consolidation filter** — on the Gateway daemons tab, chip filters
  journal lines for consolidation runs, crashes, deferrals, and health-refresh
  failures; deep link `/logs?source=gateway&consolidation=1`.
- **`consolidation.py`** — formats liveness + coverage; `doctor` reports
  `has_consolidation` on telemetry check.

### Changed

- **`/api/health`** — includes `consolidation` block; stalled consolidation
  raises overall status to **critical**; stale signal (`fresh=false`) to **warn**.
- **Hero headline** — prioritizes consolidation stalled / signal stale over backlog.
- **Poll cache** — persists consolidation fields from health + telemetry.

## [0.4.6] - 2026-06-17

### Added

- **Backup reporting (Status sidebar)** — lights when gateway `GET /health` reports
  `backup_in_progress`; shows **Last** completed backup from the newest
  `sm-backup-*.manifest.json` in `BACKUP_DIR` (configurable; default
  `~/.shared-memory/backups`). Ready for a future `last_backup_at` health field.

### Changed

- **README / `.env.example`** — document `BACKUP_DIR` for non-default manifest paths

## [0.4.5] - 2026-06-12

### Changed

- **README quick start** — explains `AGENT_TOKEN` comes from the framework's
  `monitor:read` role; links to `generate_tokens.py` and framework SECURITY.md

## [0.4.4] - 2026-06-12

### Fixed

- **Schema breakdown screenshot** — crops to `#schema-content` only (panels, no monitor
  header or drawer chrome)

## [0.4.3] - 2026-06-12

### Changed

- **README** — table of contents; order is what-it-is → screenshots → quick start →
  reference sections; schema breakdown caption clarifies side drawer
- **Schema screenshot** — viewport capture (drawer overlay on dashboard), not full-page
  scroll; removed capture-mode CSS that flattened the drawer into document flow

## [0.4.2] - 2026-06-12

### Added

- **README schema breakdown screenshot** — `docs/images/schema-breakdown.png`;
  capture opens the schema drawer (`/?schema=1&capture=1`) after breakdown data loads

## [0.4.1] - 2026-06-12

### Changed

- **Architecture emphasis** — README, `SISTER_PROJECT.md`, module docstrings, and UI
  subtitle state clearly: all on-screen data is gateway telemetry or framework logs;
  `bridge.py` + `logs_reader.py` are the only upstream clients; poll cache and
  `/api/*` are UI transport, not separate monitor backends

## [0.4.0] - 2026-06-12

### Changed

- **README** — full editorial pass: two read-only data planes, monitor vs framework
  diagrams, per-page data sources, framework topology layout, logs guide; screenshots
  regenerated

## [0.3.9] - 2026-06-12

### Changed

- **README architecture** — documents two read-only planes (gateway HTTP with
  `monitor:read` token vs local journal/audit JSONL); corrects mermaid diagram,
  data-source table, and API descriptions (stored polls vs live gateway vs logs)

## [0.3.8] - 2026-06-12

### Fixed

- **README logs screenshot** — capture opens the **Agent audit** tab (`?source=agent_audit`)
  with formatted per-request lines and agent filter chips

## [0.3.7] - 2026-06-12

### Fixed

- **README diagram screenshot** — `capture-screenshots.sh` now uses Playwright
  full-page capture and waits for diagram telemetry/history before shooting
  (fixes cropped/outdated topology on GitHub)

## [0.3.6] - 2026-06-12

### Changed

- **README** — architecture diagram section matches gateway-owned topology, audit-driven
  flows, poll-history scrubber caption, and `GET /api/diagram/agent-activity`
- **Screenshots** — regenerated `docs/images/dashboard.png`, `diagram.png`, `logs.png`
  from the live monitor UI

## [0.3.5] - 2026-06-12

### Changed

- **Diagram replay bar** — removed cryptic flow/audit event strip beside the
  slider; added a two-line caption underneath that explains live vs replay and
  shows the poll interval or cumulative timeframe (`viewTimeWindow`)

## [0.3.4] - 2026-06-12

### Changed

- **Diagram topology** — REM and NREM connect to the gateway only (read · write ·
  logic side ports with bridge gaps); gateway owns all Postgres, Neo4j, and
  inference I/O
- **Gateway infra buses** — separate bottom **Memory** (`mem-read` / `mem-write`)
  and **Inference** (`inf-llm` / `inf-embedder` / `inf-reranker`) connectors;
  memory routes drop vertically to avoid crossing daemon cards
- **Inference backends** — one blue logic line per service (no read/write split
  at the gateway edge)
- **Agent layer** — bottom read/write ports only; removed redundant layer notes
  and skill footers
- **Flow activation** — daemon↔gateway read/write lines light from replay-interval
  evidence or daemon audit, not standing backlog alone; agent audit drives gateway
  memory save/retrieve/outbox paths

### Added

- **`daemon_logic`** in agent-activity API — REM/NREM `/v1/chat/completions` and
  `/v1/embeddings` counts for blue proxy lines

### Fixed

- False always-on REM/NREM read/write connectors when `rem_backlog` /
  `facts_unconsolidated` was nonzero but the last poll window was quiet
- Gateway memory write lines hidden behind daemon cards (left-edge routing →
  bottom `infra-down` paths)
- Inference lines crossing NREM (`infra-right` elbow → `infra-down`)

## [0.3.3] - 2026-06-12

### Added

- **Diagram agent highlighting** — agent layer chips highlight agents active in the
  selected replay interval using agent audit data (green read, red write; daemons
  omitted)
- **`GET /api/diagram/agent-activity`** — per-agent read/write counts for a
  `since`/`until` window (live jsonl + logrotated `.gz` archives)

## [0.3.2] - 2026-06-12

### Changed

- **README** — document agent audit logging (`agent_audit` source, agent filter
  chips, archive picker, `GATEWAY_AUDIT_LOG_PATH` prerequisite on framework host)

## [0.3.1] - 2026-06-12

### Removed

- **`save_logs` tab** — the monitor only reads rotated audit archives on the REM
  and Agent audit sources; per-save `shared_memory_*.log.gz` files remain
  framework-side and are not surfaced as a separate log source

## [0.3.0] - 2026-06-12

### Added

- **Agent audit** log source (`agent_audit`, renamed from `gateway_audit`) — tails
  `GATEWAY_AUDIT_LOG_PATH` (framework env); defaults to `agent-audit.jsonl` with
  legacy `gateway-audit.jsonl` fallback
- **Historical log archives** — `/api/logs/archives` and UI **File** picker for
  logrotated `.gz` next to live REM and agent audit jsonl files
- Portable logrotate example: `deploy/logrotate/shared-memory-audit.example`

### Security

- Archive reads are basename-only and must match discovered files under
  `MEMORY_LOG_PATH` (no path traversal)

## [0.2.0] - 2026-06-12

### Added

- **Gateway audit** log source (`gateway_audit`) — tails `GATEWAY_AUDIT_LOG_PATH`
  (default `~/.shared-memory/logs/gateway-audit.jsonl`) for per-request agent,
  route, status, and latency lines from the hive-mind gateway auth seam
- Logs UI: structured rendering for gateway audit rows; HTTP `status >= 400`
  severity coloring; **agent filter chips** (toggle any agent present in the feed)

## [0.1.0] - 2026-06-10

### Added

- Standalone sister-repo plugin — direct `httpx` to hive-mind gateway (`:8888`)
- Pipeline dashboard, architecture diagram, and live logs UI on `:8765`
- `telemetry.nrem` cycle counts and `telemetry.breakdown` schema panels (no direct Postgres)
- Read-only monitor token support (`monitor:read` role probe in `check`)
- Gateway logs via `journalctl --user -u hive-mind-gateway.service`
- SQLite + JSONL telemetry history, PNG chart exports
- `deploy/systemd/user/` template and `install-systemd-user.sh` for persistent user service
- `pre-publish-check.sh` secret audit for GitHub pushes

### Security

- `.env` and `.grok/` gitignored; doctor never prints credential values
- Error sanitization for tokens and connection strings

[Unreleased]: https://github.com/KanenasInGreece/Shared_Memory_Monitor/compare/v0.7.5...main
[0.7.5]: https://github.com/KanenasInGreece/Shared_Memory_Monitor/releases/tag/v0.7.5
[0.7.4]: https://github.com/KanenasInGreece/Shared_Memory_Monitor/releases/tag/v0.7.4
[0.5.3]: https://github.com/KanenasInGreece/Shared_Memory_Monitor/releases/tag/v0.5.3
[0.5.2]: https://github.com/KanenasInGreece/Shared_Memory_Monitor/releases/tag/v0.5.2
[0.5.1]: https://github.com/KanenasInGreece/Shared_Memory_Monitor/releases/tag/v0.5.1
[0.5.0]: https://github.com/KanenasInGreece/Shared_Memory_Monitor/releases/tag/v0.5.0
[0.4.13]: https://github.com/KanenasInGreece/Shared_Memory_Monitor/releases/tag/v0.4.13
[0.4.0]: https://github.com/KanenasInGreece/Shared_Memory_Monitor/releases/tag/v0.4.0
[0.3.9]: https://github.com/KanenasInGreece/Shared_Memory_Monitor/releases/tag/v0.3.9
[0.3.8]: https://github.com/KanenasInGreece/Shared_Memory_Monitor/releases/tag/v0.3.8
[0.3.7]: https://github.com/KanenasInGreece/Shared_Memory_Monitor/releases/tag/v0.3.7
[0.3.6]: https://github.com/KanenasInGreece/Shared_Memory_Monitor/releases/tag/v0.3.6
[0.3.5]: https://github.com/KanenasInGreece/Shared_Memory_Monitor/releases/tag/v0.3.5
[0.3.4]: https://github.com/KanenasInGreece/Shared_Memory_Monitor/releases/tag/v0.3.4
[0.3.3]: https://github.com/KanenasInGreece/Shared_Memory_Monitor/releases/tag/v0.3.3
[0.3.2]: https://github.com/KanenasInGreece/Shared_Memory_Monitor/releases/tag/v0.3.2
[0.3.1]: https://github.com/KanenasInGreece/Shared_Memory_Monitor/releases/tag/v0.3.1
[0.3.0]: https://github.com/KanenasInGreece/Shared_Memory_Monitor/releases/tag/v0.3.0
[0.2.0]: https://github.com/KanenasInGreece/Shared_Memory_Monitor/releases/tag/v0.2.0
[0.1.0]: https://github.com/KanenasInGreece/Shared_Memory_Monitor/releases/tag/v0.1.0