# TODO: Consume framework 0.9.8 credential last-event timestamps

## Phase 1 — Signal
- [x] Task 1: Pin `*_last_ts` passthrough (I10, I11)
- [x] Task 2: Pool-line last-failure age (A4–A8)

## Checkpoint
- [x] Tests pass; builder did not edit version files / CHANGELOG

## Phase 2 — Release (Grok 4.6)
- [x] Five-axis review against `tasks/plan.md`
- [x] Task 3: Merge to main, version 0.9.12, push, tag, `gh release create`

## Standing Definition of Done (every task)
- [x] Acceptance criteria met
- [x] Tests fail without the change and pass with it (or documented already-green passthrough)
- [x] No unrelated files touched
- [x] Builders did not edit version files / CHANGELOG
