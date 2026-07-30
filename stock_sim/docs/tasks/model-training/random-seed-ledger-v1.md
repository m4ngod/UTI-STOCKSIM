# RandomSeedLedger v1

_Created: 2026-05-05_

## Source

Derived only from:

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`
- `docs/tasks/model-training/worldspec-canonical-hash.md`
- `docs/current-work-status/model-training.md`

## Task

Task 85: RandomSeedLedger v1.

## Purpose

Define a real seed ledger contract before Evidence Runner artifacts claim reproducibility.

## Seed Derivation

The documented method is `sha256_label_derivation_v1`:

```python
def derive_seed(master_seed: int, *labels: str) -> int:
    payload = str(master_seed) + "|" + "|".join(labels)
    return int(sha256(payload.encode()).hexdigest()[:16], 16) % (2**31 - 1)
```

## Required Labels

The ledger should eventually cover:

- `retail_population`
- `liquidity_noise`
- `model_initialization`
- `episode_sampling`
- `hidden_world_selection`
- `world_generation`
- `calibration`
- `baselines`
- `paired_perturbations`
- `exploit_worlds`
- `pbt_mutation`

## Blocking Rules

Evidence artifacts that depend on stochastic replay must not pass when `random_seed_ledger_hash` is missing.
This applies to calibration, baseline, hidden evaluation, exploit test, paired sensitivity, and parent gate artifacts.

## Current Status

Implemented in `app/services/evidence_core.py`.

Current code provides:

- `derive_seed(...)`
- `build_random_seed_ledger(...)`
- `random_seed_ledger_hash(...)`
- `REQUIRED_SEED_LABELS`

Focused tests live in `tests/runtime/test_evidence_core.py`.

Existing Arena `random_seed_identity.status=not_available`, `random_seed=None`, and `missing_sources=random_seed`
remain unchanged until owning stochastic services consume the ledger.
