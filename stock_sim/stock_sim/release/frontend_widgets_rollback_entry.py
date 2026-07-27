"""Same-commit read-only Qt Widgets rollback package."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import re
from typing import Sequence


READ_ONLY_ROLLBACK_PANELS = (
    "diagnostics",
    "account",
    "market",
    "agents",
    "arena",
    "leaderboard",
    "clock",
    "orders",
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
        return deepcopy(self._layout)

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
    parser.add_argument(
        "--source-commit",
        default="unbound-interactive",
    )
    arguments = parser.parse_args(argv)

    from PySide6.QtWidgets import (
        QAbstractButton,
        QApplication,
    )

    from app.app_context import reset_app_context
    from app.event_bridge import EventBridge
    from app.panels import (
        get_panel,
        list_panels,
        register_builtin_panels,
        register_ui_adapters,
        reset_registry,
    )
    from app.ui.main_window import MainWindow

    os.environ.pop("STOCKSIM_FRONTEND_V2", None)
    app = QApplication.instance() or QApplication([])
    layout_path = _layout_path(arguments.smoke_report_dir)
    layout_path.parent.mkdir(parents=True, exist_ok=True)
    bridge = EventBridge(subscribe_backend=False)
    bridge.mark_disconnected()
    context = reset_app_context(
        settings_path=str(layout_path.with_name("frontend-settings.json")),
        run_monitoring_mode="live",
        event_bridge=bridge,
        legacy_read_only=True,
    )
    reset_registry()
    register_builtin_panels()
    register_ui_adapters(read_only=True)
    layout_store = ReadOnlyLayoutStore(layout_path)
    window = MainWindow(
        frontend_v2_enabled=False,
        rollback_read_only=True,
        layout_path=str(layout_path),
        panel_list=list_panels,
        panel_get=get_panel,
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
    panel_implementations = {
        name: type(get_panel(name)).__name__
        for name in READ_ONLY_ROLLBACK_PANELS
    }
    placeholder_panels = sorted(
        name
        for name, implementation in panel_implementations.items()
        if implementation == "_PlaceholderPanel"
    )
    forbidden_manual_action = re.compile(
        r"^(?:buy|sell|submit order|cancel order|replace order|bulk order)$",
        re.IGNORECASE,
    )
    manual_trading_action_count = sum(
        1
        for button in window.findChildren(QAbstractButton)
        if forbidden_manual_action.fullmatch(button.text().strip())
    )
    report = {
        "kind": "widgets-rollback",
        "source_commit": arguments.source_commit,
        "host_class": type(window).__name__,
        "visible": window.isVisible(),
        "opened_panels": window.list_open(),
        "mode": "read-only",
        "panel_implementations": panel_implementations,
        "placeholder_panels": placeholder_panels,
        "real_panel_count": (
            len(panel_implementations) - len(placeholder_panels)
        ),
        "manual_trading_action_count": manual_trading_action_count,
        "screenshot": screenshot_path.name,
        "clean_exit": True,
    }
    (arguments.smoke_report_dir / "smoke-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    window.close()
    context.run_monitoring_feature.close()
    context.evidence_and_findings_feature.close()
    bridge.stop()
    app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
