# WorldSpec Canonical Hash

_Created: 2026-05-05_

## Source

Derived only from:

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`
- `docs/tasks/model-training/separate-artifact-schemas-v1.md`
- `docs/current-work-status/model-training.md`

## Task

Task 84: WorldSpec Canonical Hash.

## Purpose

Define the `world_spec_v1` identity boundary and canonical hash rules before hidden-world, paired-world, or
calibration artifacts depend on world identity.

## Proposed Shape

`world_spec_v1` should include:

- schema and world name.
- split: `train`, `validation`, `hidden`, or `exploit`.
- universe and selection rule.
- clock/session and bar step.
- market rules.
- fee model.
- impact model.
- fill model.
- retail mix.
- liquidity seed reference.
- calibration target profile.
- scenario family.

## Current Mapping

Current Arena report metadata can support only a subset:

- symbols from `world_identity.symbols`.
- clock fields from `world_identity.clock_start_day`, `clock_speed`, and `run_clock`.
- liquidity seed configuration from the existing Arena liquidity seed settings.
- current world hash from the existing Arena `world_identity` canonical JSON hash.

Unsupported fields remain explicit `not_available` until their owners exist.

## Hash Rules

- Use canonical JSON with sorted keys and compact separators.
- Include only the world spec payload.
- Exclude any self hash field from the payload.
- Hash method: `sha256_json_canonical_v1`.

## Required Tests

- Same payload with different key order has the same hash.
- Any supported semantic input change changes the hash.
- Unsupported fields are explicit `not_available`, not omitted silently.
- The self hash is excluded from the hash payload.

## Current Status

Implemented in `app/services/evidence_core.py`.

Current code provides:

- `build_world_spec_v1(...)`
- `build_world_spec_from_arena_identity(...)`
- `world_spec_hash(...)`
- `canonical_json_hash(...)`

Focused tests live in `tests/runtime/test_evidence_core.py`.

Hidden-world registry, split generation, paired worlds, calibration runner behavior, GUI behavior, and PostgreSQL
behavior remain outside this task.
