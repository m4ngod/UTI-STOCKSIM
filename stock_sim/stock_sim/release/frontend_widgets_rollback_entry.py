"""Minimal same-commit Qt Widgets rollback package for the T02 size gate."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Sequence


READ_ONLY_ROLLBACK_PANELS = (
    "diagnostics",
    "account",
    "market",
    "agents",
    "arena",
    "leaderboard",
    "clock",
)


class ReadOnlyLayoutStore:
    def __init__(self, path: Path):
        self._path = path
        self._layout: dict[str, object] = {"panels": {}}
        if path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    self._layout = payload
            except (OSError, ValueError):
                pass

    def get(self) -> dict[str, object]:
        return json.loads(json.dumps(self._layout))

    def save(self, layout: dict[str, object]) -> None:
        self._layout = json.loads(json.dumps(layout))
        self._path.write_text(
            json.dumps(self._layout, ensure_ascii=False),
            encoding="utf-8",
        )


def _layout_path(report_dir: Path | None) -> Path:
    if report_dir is not None:
        return report_dir / "widgets-rollback-layout.json"
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home()
    return root / "UTI-STOCKSIM" / "widgets-rollback-layout.json"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-report-dir", type=Path)
    arguments = parser.parse_args(argv)

    from PySide6.QtWidgets import QApplication, QLabel

    from app.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    panel_widgets: dict[str, QLabel] = {}

    def panel_list() -> list[dict[str, str]]:
        return [
            {"name": name, "title": name.title()}
            for name in READ_ONLY_ROLLBACK_PANELS
        ]

    def panel_get(name: str) -> QLabel:
        if name not in READ_ONLY_ROLLBACK_PANELS:
            raise KeyError(name)
        if name not in panel_widgets:
            panel_widgets[name] = QLabel(
                f"{name.title()}\nRead-only rollback view"
            )
        return panel_widgets[name]

    layout_path = _layout_path(arguments.smoke_report_dir)
    layout_path.parent.mkdir(parents=True, exist_ok=True)
    layout_store = ReadOnlyLayoutStore(layout_path)
    window = MainWindow(
        frontend_v2_enabled=False,
        rollback_read_only=True,
        layout_path=str(layout_path),
        panel_list=panel_list,
        panel_get=panel_get,
        layout_store=layout_store,
    )
    window.setObjectName("widgetsRollbackPackageWindow")
    for panel_name in READ_ONLY_ROLLBACK_PANELS:
        window.open_panel(panel_name)
    window.resize(1024, 640)
    window.show()
    if arguments.smoke_report_dir is None:
        return int(app.exec())

    arguments.smoke_report_dir.mkdir(parents=True, exist_ok=True)
    app.processEvents()
    screenshot_path = arguments.smoke_report_dir / "widgets-rollback.png"
    if not window.grab().save(str(screenshot_path), "PNG"):
        return 1
    report = {
        "kind": "widgets-rollback",
        "host_class": type(window).__name__,
        "visible": window.isVisible(),
        "opened_panels": window.list_open(),
        "mode": "read-only",
        "screenshot": screenshot_path.name,
        "clean_exit": True,
    }
    (arguments.smoke_report_dir / "smoke-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    window.close()
    app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
