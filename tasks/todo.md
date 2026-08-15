# TODO: Align monitor with framework 0.9.4 logs + telemetry

## Phase 0 — Hygiene
- [x] Task 0: Leave leftover v0.9.10 version bump uncommitted; builders branch from HEAD; do not add `search_results.json` / `telemetry.json`

## Phase 1 — Signal on existing rectangles
- [x] Task 1: Join `llm_faults` + `credentials` onto `/api/health` (I1–I5, I8)
- [x] Task 2: Chip warn + click popover + Logs deep link (depends on 1)

## Checkpoint: Phase 1
- [x] Tests pass; no top-level fault panel; both local chips still render

## Phase 2 — Logs detail
- [x] Task 3: `credential_audit` source + numbered logrotate archives (I6, I7, I9)
- [x] Task 4: Backend + origin filter chips; format credential lines (depends on 3)

## Checkpoint: Phase 2
- [x] Chip → popover → `/logs?source=…&backend=…` works; full pytest green

## Phase 3 — Release (Grok 4.6)
- [x] Five-axis review against `tasks/plan.md`
- [ ] Task 5: Merge to main, version 0.9.10, push, tag, `gh release create`

## Standing Definition of Done (every task)
- [ ] Acceptance criteria met
- [ ] Tests fail without the change and pass with it
- [ ] No unrelated files touched
- [ ] Builders did not edit version files / CHANGELOG
