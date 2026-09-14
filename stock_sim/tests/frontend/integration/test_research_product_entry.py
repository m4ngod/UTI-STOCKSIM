"""The public console entry reaches the real composed four-page product UI."""

import pytest

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import setup_frontend_entry
from app.ui.main_window import MainWindow
from stock_sim.release import frontend_v2_package_entry
from tests.frontend.integration.test_research_resource_pages import until


@pytest.mark.parametrize("entry_kind", ["console", "package"])
def test_research_option_opens_four_pages_and_returns_health_focus(tmp_path, monkeypatch, entry_kind):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2_ADAPTER", "fake")
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "0")
    original = b'{"journey_workspace_bookmark_json":"future-or-malformed","sentinel":"old-original"}'
    legacy_paths = [tmp_path / name for name in ("frontend_settings.json", "frontend-v2-settings.json", "layout_main.json")]
    for path in legacy_paths:
        path.write_bytes(original)
    app = QApplication.instance() or QApplication([])
    if not QFontDatabase.families():
        assert QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc") >= 0
        app.setFont(QFont("Microsoft YaHei UI", 10))
    failures = []
    observed = []
    windows = []

    def inspect():
        try:
            window = next(item for item in app.topLevelWidgets()
                          if isinstance(item, MainWindow) and item.isVisible())
            windows.append(window)
            host = window.centralWidget()
            root = host.rootObject()
            assert root.objectName() == "researchWorkspace"
            catalog = root.findChild(QQuickItem, "researchAssetList")
            until(app, lambda: catalog.property("count") > 0)
            for name, route in (
                ("strategyLibraryRouteNavigation", "strategy_library"),
                ("scenarioLabRouteNavigation", "scenario_lab"),
                ("diagnosticTasksRouteNavigation", "diagnostic_tasks"),
                ("evidenceAndFindingsRouteNavigation", "evidence_and_findings"),
            ):
                button = root.findChild(QQuickItem, name)
                button.forceActiveFocus()
                QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
                assert host.active_route.value == route
                observed.append(route)
            health = root.findChild(QQuickItem, "researchHealthButton")
            health.forceActiveFocus()
            QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
            assert root.findChild(QObject, "researchHealthPopup").property("opened")
            QTest.keyClick(host.quickWindow(), Qt.Key.Key_Escape)
            assert health.hasActiveFocus()
            assert host.active_route.value == "evidence_and_findings"
            assert window.list_open() == []
        except BaseException as error:
            failures.append(error)
        finally:
            app.quit()

    inspect_timer = QTimer()
    inspect_timer.setSingleShot(True)
    inspect_timer.timeout.connect(inspect)
    inspect_timer.start(0)
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(app.quit)
    timeout.start(15000)
    try:
        if entry_kind == "console":
            result = setup_frontend_entry.main(["--research-shell", "--skip-db-check"])
        else:
            result = frontend_v2_package_entry.main(["--research-shell", "--renderer-lane", "software"])
        assert result == 0
        if failures:
            raise failures[0]
        assert observed == ["strategy_library", "scenario_lab", "diagnostic_tasks", "evidence_and_findings"]
    finally:
        inspect_timer.stop()
        timeout.stop()
        for window in windows:
            window.close()
            window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
    for path in legacy_paths:
        assert path.read_bytes() == original


def test_research_console_rejects_headless_without_creating_settings(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as rejected:
        setup_frontend_entry.main(["--research-shell", "--headless"])
    assert rejected.value.code == 2
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("report_option", [
    "--smoke-report-dir", "--package-assembly-smoke-report-dir",
    "--installed-dpi-preflight-report", "--performance-report",
    "--migration-report", "--recovery-report", "--observation-readiness-report",
])
def test_research_entry_does_not_run_or_label_legacy_certification(tmp_path, monkeypatch, report_option):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as rejected:
        frontend_v2_package_entry.main(["--research-shell", report_option, str(tmp_path / "report")])
    assert rejected.value.code == 2
    assert list(tmp_path.iterdir()) == []
