# Market Metrics Extractor v0

_Created: 2026-05-05_

## Source

Derived only from:

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`
- `docs/architecture/runtime/retail-persona-calibration-blueprint.md`
- `docs/tasks/model-training/random-seed-ledger-v1.md`
- `docs/current-work-status/model-training.md`

## Task

Task 86: Market Metrics Extractor v0.

## Purpose

Define the normalized inputs and metric coverage boundary that Calibration Scorecard v0 and
`calibration_artifact_v1` must consume.

## Inputs

The extractor may consume project-owned runtime facts:

- orders.
- trades.
- snapshots.
- bars.
- accounts.
- account equity snapshots.
- optional holding samples.

## Metric Groups

Supported groups are:

- price stylized facts: returns, volatility, skew/kurtosis proxies, autocorrelation proxies.
- microstructure: spread, depth, order imbalance where source data exists.
- liquidity: volume, turnover, active agent count, market/limit order ratio, empty-book ratio.
- behavior: holding period, buy/sell ratio, concentration, retail family contribution where available.
- rule consistency: T+1, short-sell, fee ledger, frozen cash/position release checks where available.

## Coverage Status

Each metric must carry one of:

- `present`
- `missing`
- `not_available`
- `not_applicable`

Required metrics that are `missing` or `not_available` must block calibration pass/fail until their source exists.

## Current Status

Implemented in `app/services/evidence_core.py`.

Current code provides `MarketMetricsExtractor.extract(...)` with metrics and coverage statuses for project-owned
runtime facts.

Focused tests live in `tests/runtime/test_evidence_core.py`.

Calibration runner execution, target profile storage, hidden runner, paired runner, exploit runner, GUI behavior, and
PostgreSQL behavior remain outside this task.
