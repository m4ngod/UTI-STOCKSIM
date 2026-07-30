# GUI Evidence Board v1

_Created: 2026-05-05_

## Source

Derived only from:

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`

## Task

Task 99: GUI Evidence Board.

## Purpose

Downgrade Arena leaderboard rank as the primary decision signal and expose candidate evidence status in the Arena
panel. The board should show whether evidence passes, fails, is missing, or remains `not_available`.

## Board Boundary

Implemented in:

- `app/services/evidence_board_service.py`
- `app/panels/arena/panel.py`
- `app/ui/adapters/arena_adapter.py`

The board consumes `series_evidence_aggregate_v1` output and does not run evidence runners or rerank models.

## Displayed Fields

The v1 board displays:

- candidate id
- baseline
- calibration
- hidden
- exploit
- fee/impact sensitivity
- parent eligible
- research claim eligible

Rows also preserve overall status, failed evidence, missing evidence, not-available evidence, and not-available debt
metadata for downstream GUI work.

## Not Available Debt

When evidence is `not_available`, the board exposes:

- owner
- required input
- blocking reason
- planned task id
- replacement artifact kind

## Explicitly Deferred

- Full visual redesign of the Arena panel.
- Color-coded desktop styling.
- Clicking evidence rows to open artifact files.
- Running long Arena series.
- PostgreSQL artifact persistence or data deletion.

## Verification

- `python -m py_compile app/services/evidence_board_service.py app/panels/arena/panel.py app/ui/adapters/arena_adapter.py tests/runtime/test_evidence_board_service.py tests/frontend/unit/test_arena_panel.py`
- Direct behavior assertion passed with `GUI_EVIDENCE_BOARD_DIRECT_ASSERTIONS_OK`.

Targeted pytest could not run because the project `.venv` points to a missing `Python311` executable and the available
system/runtime Python installations do not have `pytest` installed.
