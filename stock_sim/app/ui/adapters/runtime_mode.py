from __future__ import annotations

import os

__all__ = ["ui_runtime_enabled"]


def ui_runtime_enabled() -> bool:
    """Return True only when adapter code should touch real Qt widgets.

    Rule of thumb:
    - Default to False (safe/headless) even if PySide6 is importable.
    - Enable only when the process explicitly opts in.

    This avoids the recurring class of crashes where tests/scripts have PySide6
    installed but do not have a full QApplication / GUI lifecycle.
    """
    flag = os.environ.get("STOCKSIM_ENABLE_REAL_UI", "").strip().lower()
    return flag in {"1", "true", "yes", "on"}
