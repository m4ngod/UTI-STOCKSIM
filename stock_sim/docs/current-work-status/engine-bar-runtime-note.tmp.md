## Bar-family run-scoped validation / recovery-severity note (2026-03-24)

### status
in-progress

### goal
Bring bar-family persisted facts into run-scoped replay/recovery reporting, while keeping severity policy realistic: `bars_1m` as the primary bar-health gate and `bars_1h / bars_1d` as warning-level derived layers.

### files involved
- `persistence/models_bars.py`
- `persistence/models_init.py`
- `services/bar_aggregator.py`
- `services/replay_service.py`
- `services/recovery_service.py`
- `tests/test_bar_run_report_contract.py`
- `tests/test_recovery_bar_severity_policy.py`

### change summary
- Added `run_id` to persisted bar models (`bars_1m`, `bars_1h`, `bars_1d`).
- Extended auto-migration/init logic so existing bar tables can receive `run_id`.
- Made bar aggregation persist `run_id` into generated bars.
- Extended replay/run-report validation to expose persisted bar-family facts for `1m / 1h / 1d`.
- Added recovery severity policy:
  - snapshots exist but `bars_1m` missing => degraded/severe
  - `bars_1m` exists but `bars_1h` or `bars_1d` missing => warning only
- Expanded recovery run discovery so snapshot/bar-only runs are no longer invisible.

### current conclusion
- Bar family is no longer outside the run-scoped backend health surface.
- `bars_1m` is now treated as the primary persisted bar truth because it is closest to snapshot-derived market facts.
- `bars_1h / bars_1d` are now visible and tracked, but intentionally remain warning-level derived layers instead of first-class recovery gates.

### impact / risk
- Positive: run reports now cover market-state derivatives more honestly.
- Positive: recovery can detect a broken snapshot->bar floor without overreacting to missing higher-level aggregates.
- Risk: bar event-side (`BAR_UPDATED`) contract is still less stable than row-side validation and should continue to be treated carefully.

### next actions
- Keep bar-family work centered on persisted-facts validation first.
- Later decide whether any `BAR_UPDATED` event-side checks are stable enough to promote beyond auxiliary coverage.
- Only after that, consider whether `simulation_runs` should become the next persistence anchor.
