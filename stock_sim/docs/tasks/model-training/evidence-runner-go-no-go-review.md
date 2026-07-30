# Evidence Runner Go / No-Go Review

_Created: 2026-05-05_

## Source

Derived from:

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`

## Purpose

Apply the section 15 Go / No-Go standard after Task 82-101 work. This review decides whether the project should move to
more complex model work.

## Decision

No-Go for more complex model work.

The Evidence Runner stack has usable schema, runner, gate, aggregate, board, contract-test, and package boundaries, but
the live long Arena series remains blocked by the local Python dependency environment. Therefore the project should not
upgrade Transformer, MARL, or more complex model routes yet.

## Go Criteria Review

| Criterion | Status | Reason |
|---|---|---|
| Three world splits exist: train, validation, hidden | pass | Hidden World Registry supports visible/train, validation, hidden, and exploit splits. |
| `calibration_artifact_v1` is no longer `not_available` | partial | Separate calibration artifact writer exists, but live long-run proof is still blocked. |
| At least two of TWAP/VWAP/AC-lite can run | partial | Baseline policies and artifact requirements exist, but live long-run proof is still blocked. |
| `hidden_eval_artifact_v1` can evaluate frozen checkpoint | partial | Hidden-World Runner v0 enforces frozen/no-learning evaluation, but live long-run proof is still blocked. |
| `exploit_test_artifact_v1` identifies no-signal or boundary cheating | pass | Exploit Runner and contract tests reject constructed bad-policy signals. |
| `paired_sensitivity_artifact_v1` outputs degradation curve | pass | Paired sensitivity runner writes degradation curves for required fee, impact, and latency perturbations. |
| `strict_parent_gate_v2` rejects high-return models with missing evidence | pass | Strict parent gate v2 rejects failed or missing required evidence. |
| Series aggregate clearly displays pass/fail/missing/not_available | pass | Series Evidence Aggregate and Evidence Board expose those four states. |

## No-Go Signals

The current blocker is not a model result failure from a live run; it is an evidence-production failure:

- Live long Arena series could not run because the available runtime lacks `sqlalchemy`.
- Project `.venv` and sibling `Quent\.venv` point to a missing Python311 launcher.
- Targeted pytest cannot run because the available runtime does not include `pytest`.
- Task 101 has only a deterministic headless evidence package, not a live PostgreSQL/runtime long run.

Because section 15 requires evidence before model-complexity escalation, this is a No-Go until live dependency and long
run blockers are resolved.

## Allowed Next Work

- Repair the local Python/runtime dependency environment.
- Re-run Task 101 using the live database-backed Arena path.
- Keep current ppo_lstm_v1 and rule-baseline route as the research target.
- Do not upgrade to Transformer, complex MARL, or new alpha-claim model routes before a live evidence package passes.

## Explicitly Deferred

- Any more complex model architecture.
- Any research claim based on the headless package alone.
- PostgreSQL data deletion.
