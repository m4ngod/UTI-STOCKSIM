"""Packaging entry for the throwaway Qt Widgets candidate."""

from entry_common import run_packaged
from widgets_app import run_widgets


if __name__ == "__main__":
    raise SystemExit(run_packaged("widgets", run_widgets))
