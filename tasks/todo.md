# TODO: Consume framework 0.9.9–0.9.13 LLM + credential surfaces

## Phase 1 — Signal
- [x] Task 1: Pin passthrough + join (I12–I17, I2, I11) + doctor flags
- [x] Task 2: Pool line, popover, infrastructure hint (A5–A9)

## Checkpoint
- [x] Tests pass; builder did not edit version files / CHANGELOG

## Phase 2 — Release (Grok 4.6)
- [x] Five-axis review against `tasks/plan.md` (Required: null-price cost guard — fixed `b618fcb`)
- [x] Task 3: Merge to main, version 0.9.13, push, tag, `gh release create`

## Standing Definition of Done (every task)
- [ ] Acceptance criteria met
- [ ] Tests fail without the change and pass with it (or documented already-green passthrough)
- [ ] No unrelated files touched
- [ ] Builders did not edit version files / CHANGELOG
