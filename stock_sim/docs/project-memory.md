# Project Memory

## Stable conclusions

- `app/ui/main_window.py` is the intended single real frontend window structure.
- `app/main.py` is being reduced to a temporary compatibility/entry wrapper and should eventually be removable.
- Market detail currently combines multiple data paths rather than one unified source:
  - snapshot/order book path
  - bars/K-line path
  - trades path
  - holdings path
- Instrument creation is a real backend mutation that creates/registers engine state.
- `services/order_service.py` is the real order lifecycle orchestrator.
- Backend account freeze/refund/settlement semantics matter; frontend simplification must not ignore them.

## Current long-term refactor direction

1. unify MainWindow ownership in `app/ui/main_window.py`
2. shrink and retire `app/main.py`
3. document and stabilize Market detail field contracts
4. only then push larger GUI/K-line fixes with confidence
