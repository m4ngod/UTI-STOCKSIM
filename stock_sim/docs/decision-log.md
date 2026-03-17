# Decision Log

## 2026-03-17 - MainWindow unification before larger GUI fixes

Decision:
- Prioritize MainWindow structural unification and compatibility-layer shrinkage before broad GUI/K-line fixes.

Why:
- The project currently has both structural duplication (`app/main.py` vs `app/ui/main_window.py`) and semantic split (Market detail uses multiple data paths).
- Fixing GUI symptoms first would risk papering over architecture problems.

Implication:
- Continue moving structural ownership to `app/ui/main_window.py`.
- Keep `app/main.py` only as a temporary wrapper during migration.

## 2026-03-17 - Module status notes should not use line numbers

Decision:
- Module work-status notes will not record line numbers.
- They will record first/last code lines for each modified fragment, plus total changed line count.

Why:
- Line numbers drift and become brittle.
- Code anchors are more durable for future continuation.

Implication:
- All module notes under `docs/current-work-status/` should follow the anchor-based format.
