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

## Outstanding work

- Audit whether `setup_frontend_entry.py` should continue to import `run_frontend()` from `app.main` until final wrapper removal.
- Identify remaining compatibility exports that are still relied on by tests or scripts.
- Decide final deletion conditions for `app/main.py`.
