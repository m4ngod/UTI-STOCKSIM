# Compatibility Retirement Status

## Module

Legacy wrapper and compatibility-surface retirement

## Current goal

- Reduce `app/main.py` to a temporary entry wrapper.
- Move ownership of structural concepts to real modules.
- Prepare for eventual deletion of compatibility-only files.

## Current state

in-progress

## Files involved

- `app/main.py`
- `app/ui/main_window.py`
- `setup_frontend_entry.py`
- tests importing or referencing compatibility symbols
- `docs/frontend-backend-dependency-map.md`

---

## Task 2026-03-17-compat-01
- **time**: 2026-03-17
- **status**: done
- **goal**: define retirement plan for compatibility files
- **files involved**:
  - `docs/frontend-backend-dependency-map.md`
- **total changed lines**: 39

### Code fragment anchors
#### fragment 1
- **first line**: `## 9. Compatibility retirement roadmap`
- **last line**: `> Compatibility files are scaffolding, not architecture.`

### Change summary
- Added a four-phase roadmap for shrinking and eventually removing compatibility files.

### Purpose
- Turn compatibility cleanup into a tracked plan.

### Impact / risk
- No runtime impact.

### Next actions
- Keep module status notes synchronized with roadmap progress.

---

## Task 2026-03-17-compat-02
- **time**: 2026-03-17
- **status**: in-progress
- **goal**: reduce `app/main.py` to entry-only responsibilities
- **files involved**:
  - `app/main.py`
  - `app/ui/main_window.py`
- **total changed lines**: 77

### Code fragment anchors
#### fragment 1
- **first line**: `"""Legacy frontend entry wrapper.`
- **last line**: `    return mw`

#### fragment 2
- **first line**: `# Temporary compatibility alias. New code should import DEFAULT_PRELOAD_PANELS`
- **last line**: `_DEFAULT_PRELOAD = DEFAULT_PRELOAD_PANELS`

### Change summary
- Kept `run_frontend()` in `app/main.py`.
- Moved preload constant ownership to `app.ui.main_window` and left a temporary alias in `app.main`.

### Purpose
- Make `app.main` increasingly deletable.

### Impact / risk
- Moderate migration risk because external callers still use the wrapper.

### Next actions
- Migrate remaining callers away from compatibility alias/exports where practical.

---

## Task 2026-03-18-compat-03
- **time**: 2026-03-18
- **status**: in-progress
- **goal**: remove another runtime compatibility assumption from the frontend entry path
- **files involved**:
  - `setup_frontend_entry.py`
- **total changed lines**: small targeted patch

### Change summary
- Replaced a legacy `mw.opened_panels` assumption with a compatibility-safe fallback that prefers `list_open()` when the real unified `MainWindow` is returned.

### Purpose
- Prevent startup/runtime breakage while `app.main` remains a temporary wrapper over the unified window implementation.

### Impact / risk
- Low risk.
- Helps entry scripts coexist with the new ownership model while avoiding re-expanding the compatibility surface.

### Next actions
- Continue auditing other runtime scripts for `opened_panels`-style assumptions.
- Keep shrinking compatibility usage instead of adding new aliases.

---

## Task 2026-03-23-compat-04
- **time**: 2026-03-23
- **status**: done
- **goal**: move headless ownership out of `app.main` so the legacy wrapper no longer owns non-GUI frontend behavior
- **files involved**:
  - `app/headless.py`
  - `app/main.py`
  - `setup_frontend_entry.py`
  - `tests/test_headless_no_gui_attrs.py`
  - `tests/test_e2e_headless_no_gui_attrs.py`
  - `tests/test_e2e_headless_widget_no_gui_attrs.py`
  - `tests/frontend/integration/test_frontend_entry.py`
- **total changed lines**: targeted headless-surface extraction + test migration

### Code fragment anchors
#### fragment 1
- **first line**: `"""Headless frontend compatibility surface.`
- **last line**: `__all__ = ["HeadlessMainWindow", "run_headless_frontend"]`

#### fragment 2
- **first line**: `from app.headless import HeadlessMainWindow, run_headless_frontend`
- **last line**: `        return run_headless_frontend()`

#### fragment 3
- **first line**: `    if headless:`
- **last line**: `        return run_headless_frontend()`

### Change summary
- Introduced a dedicated `app/headless.py` compatibility surface.
- Moved `HeadlessMainWindow` ownership out of `app.main`.
- Switched the entry-local headless startup path to `run_headless_frontend()`.
- Migrated explicit headless tests away from importing `app.main` as the headless owner.

### Purpose
- Shrink `app.main` toward a thinner legacy entry wrapper.
- Separate headless behavior from the GUI/legacy wrapper path.
- Reduce the number of reasons tests and entry code must keep importing `app.main`.

### Impact / risk
- Positive structural impact: `app.main` no longer owns headless runtime behavior.
- Low to medium migration risk: headless tests and entry wrappers needed coordinated updates.
- Runtime verification stayed green after migration.

### Next actions
- Continue removing external test/e2e references to `app.main.run_frontend(headless=True)`.
- Reassess whether `run_frontend()` should remain the only compatibility export still used by entry code.

---

## Task 2026-03-23-compat-05
- **time**: 2026-03-23
- **status**: done
- **goal**: retire the preload compatibility alias so `app.main` no longer carries preload ownership indirection
- **files involved**:
  - `app/main.py`
  - `tests/frontend/unit/test_panel_registry_main.py`
  - preload-related regression tests
- **total changed lines**: small alias removal + test-contract alignment

### Code fragment anchors
#### fragment 1
- **first line**: `from app.ui.main_window import DEFAULT_PRELOAD_PANELS, MainWindow`
- **last line**: `    for name in DEFAULT_PRELOAD_PANELS:`

#### fragment 2
- **first line**: `def test_mainwindow_registered_panels_open():`
- **last line**: `    assert 'account' in getattr(mw, '_panel_widgets', {})`

### Change summary
- Removed the `_DEFAULT_PRELOAD` compatibility alias from `app.main`.
- Kept preload usage pointed directly at `app.ui.main_window.DEFAULT_PRELOAD_PANELS`.
- Updated a stale unit test that still assumed older `list_registered()` / `open_panel()` return shapes.

### Purpose
- Eliminate one more non-entry compatibility surface from `app.main`.
- Keep tests aligned with current MainWindow/public-behavior reality instead of forcing legacy assumptions back into runtime code.

### Impact / risk
- Positive structural impact: preload ownership is now fully outside `app.main`.
- Low risk: only stale test assumptions required adjustment.

### Next actions
- Keep `app.main` free of new non-entry compatibility aliases.
- Continue scanning remaining direct imports of `app.main`.

---

## Task 2026-03-23-compat-06
- **time**: 2026-03-23
- **status**: done
- **goal**: migrate remaining test/e2e headless callers away from `app.main` and strengthen the dedicated headless surface
- **files involved**:
  - `app/headless.py`
  - `tests/frontend/e2e/test_create_instrument_and_batch_agents.py`
  - `tests/test_e2e_rollback_alert_notification_widget.py`
- **total changed lines**: targeted caller migration + headless adapter registration fix

### Code fragment anchors
#### fragment 1
- **first line**: `from app.panels import register_builtin_panels, register_ui_adapters, get_panel, list_panels`
- **last line**: `        register_ui_adapters()`

#### fragment 2
- **first line**: `from app.headless import run_headless_frontend  # noqa: E402`
- **last line**: `    mw = run_headless_frontend()`

#### fragment 3
- **first line**: `from app.headless import run_headless_frontend`
- **last line**: `    assert isinstance(mw.list_available(), list)`

### Change summary
- Migrated the remaining explicit headless e2e tests away from `app.main` imports.
- Strengthened `run_headless_frontend()` so headless mode still attempts `register_ui_adapters()` before falling back to placeholders.
- Preserved the semantic distinction that headless means “no GUI event loop”, not “logicless placeholder-only mode”.

### Purpose
- Make `app.headless` the real owner of headless test/compatibility behavior.
- Keep headless e2e flows capable of exercising logic-backed panels.
- Reduce the external dependency surface of `app.main` to near entry-only usage.

### Impact / risk
- Positive structural impact: direct external `app.main` imports are now largely limited to entry compatibility usage.
- Positive runtime impact: headless e2e flows remain meaningful after migration.
- Low migration risk after targeted regression verification.

### Next actions
- Audit whether `setup_frontend_entry.py` still needs `_compat_run_frontend(headless=False)` as a GUI fallback.
- Decide when `MainWindow` re-export from `app.main` can be retired.
- Define final deletion conditions for `app/main.py` once the remaining entry compatibility surface is replaced.

---

## Task 2026-03-23-compat-07
- **time**: 2026-03-23
- **status**: done
- **goal**: localize product-entry GUI startup in `setup_frontend_entry.py` so release packaging does not depend on `app.main`
- **files involved**:
  - `setup_frontend_entry.py`
  - `app/main.py`
  - `tests/frontend/integration/test_frontend_entry.py`
- **total changed lines**: targeted product-entry convergence

### Code fragment anchors
#### fragment 1
- **first line**: `from app.headless import run_headless_frontend`
- **last line**: `from app.ui.main_window import DEFAULT_PRELOAD_PANELS, MainWindow`

#### fragment 2
- **first line**: `def _start_frontend(*, headless: bool):`
- **last line**: `    return mw`

#### fragment 3
- **first line**: `__all__ = ["run_frontend"]`
- **last line**: `def run_frontend(*, headless: bool = False) -> MainWindow | HeadlessMainWindow:`

### Change summary
- Removed the GUI fallback import from `setup_frontend_entry.py` to `app.main.run_frontend`.
- Made the console/product entry own GUI startup locally using the real `MainWindow` and `DEFAULT_PRELOAD_PANELS`.
- Kept headless startup on the dedicated `app.headless` surface.
- Retired the `MainWindow` public re-export from `app.main.__all__`.
- Confirmed by dependency scan that no external project code now directly imports `app.main`.

### Purpose
- Make `setup_frontend_entry.py` a true product-entry surface suitable for future application packaging/distribution.
- Prevent the release/startup path from depending on the historical compatibility wrapper.
- Push `app.main` closer to a fully deletable legacy wrapper with no external project callers.

### Impact / risk
- Positive structural impact: product entry is now local and explicit.
- Positive release-engineering impact: packaging targets can point at `setup_frontend_entry.py` without inheriting historical wrapper coupling.
- Low migration risk after targeted regression verification.

### Next actions
- Define explicit final deletion conditions for `app/main.py`.
- Decide whether `run_frontend()` should now be marked deprecated in comments/docs.
- Consider a small release-entry note documenting `setup_frontend_entry.py` as the intended packaged-app entry point.

---

## Outstanding work

- Define final deletion conditions for `app/main.py`.
- Decide whether `run_frontend()` should now be marked deprecated in comments/docs.
- Consider adding a release-entry / packaging note that explicitly points future app distribution at `setup_frontend_entry.py`.
- Headless compatibility tests and headless e2e flows now use `app.headless` rather than `app.main`.
- The `_DEFAULT_PRELOAD` compatibility alias has been retired.
- Current deletion result (2026-03-24): `app.main` has now been deleted after dependency verification confirmed no internal project code still imports it; canonical entry ownership remains with `setup_frontend_entry.py` and `app.headless`.
