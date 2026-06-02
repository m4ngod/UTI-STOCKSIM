# Evidence Runner Phase Charter

_Created: 2026-05-05_

## Source

Derived only from:

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/current-work-status/model-training.md`

## Task

Task 82: Evidence Runner Phase Charter.

## Purpose

The model-training work is now in Evidence Runner Phase. Further horizontal expansion of
`experiment_record_completeness.field_status` is frozen by default unless it fixes a documented
bug or directly supports a separate Evidence Runner artifact.

## Priority Order

The next work should proceed in this order:

1. Separate artifact schemas.
2. WorldSpec canonical hash.
3. RandomSeedLedger.
4. Market metrics extractor.
5. Calibration scorecard.
6. Calibration artifact writer.
7. Baseline, hidden-world, paired sensitivity, exploit, gate, aggregate, GUI, and long-run evidence work.

## Guardrails

- Do not label embedded report metadata as independent evidence.
- Keep calibration, hidden evaluation, exploit tests, paired sensitivity, and parent-gate evidence as
  `not_available` until independent artifacts or runners exist.
- Do not change training, execution, reward, account, PBT, checkpoint, GUI, or PostgreSQL behavior as part
  of this charter.

## Acceptance

- The project has a documented phase boundary.
- Task 83 through Task 101 are treated as Evidence Runner work rather than metadata-only work.
- Missing evidence remains explicit instead of being inferred from report completeness.

## Current Status

Done as a docs-first charter. No runner or artifact behavior is claimed by this task.
