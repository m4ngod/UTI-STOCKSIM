# Model Route Gate v1

_Created: 2026-05-05_

## Source

Derived from:

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`
- `docs/tasks/model-training/evidence-runner-go-no-go-review.md`

## Purpose

Make section 16 model-route guidance machine-readable: do not upgrade to Transformer, complex MARL, historical replay,
or hybrid environment routes until the Evidence Runner phase reaches Go.

## Boundary

Implemented in:

- `app/services/model_route_gate.py`
- `tests/runtime/test_model_route_gate.py`

The gate is intentionally a standalone service. It does not yet block `ModelRegistryService` registration or Arena
execution directly; future wiring should call this service before enabling advanced model routes.

## Rule

When the Evidence Runner Go / No-Go review is `no_go`:

- allow current P0/P1 routes such as `ppo_lstm_v1` and rule baselines
- block advanced route tokens such as `transformer`, `gtrxl`, `marl`, `historical_replay`, `hybrid_env`, and `alpha_claim`

When the review is `go`, advanced routes may be allowed by this gate.

## Output

The service writes `model_route_gate_v1` JSON records under:

- `output/evidence_artifacts/model_route_gate_v1/`

The record includes:

- Go / No-Go decision
- allowed current routes
- advanced route tokens
- per-route allowed/blocked status
- blocked model ids
- failure reasons
- canonical `route_gate_hash`

## Explicitly Deferred

- Wiring the gate into `ModelRegistryService`.
- Registering Transformer, GTrXL, complex MARL, replay, or hybrid environment models.
- Making research claims from headless evidence only.
- PostgreSQL data deletion.

## Verification

- `python -m py_compile app/services/model_route_gate.py tests/runtime/test_model_route_gate.py`
- Direct behavior assertion passed with `MODEL_ROUTE_GATE_DIRECT_ASSERTIONS_OK`.

Targeted pytest could not run because the available runtime Python does not have `pytest` installed.
