import os
from pathlib import Path
import subprocess
import sys


def test_market_adapter_promotes_entire_widget_tree_after_headless_import():
    project_root = Path(__file__).resolve().parents[3]
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment.pop("STOCKSIM_ENABLE_REAL_UI", None)
    program = """
from app.ui.adapters.market_adapter import MarketPanelAdapter
from PySide6.QtWidgets import QApplication, QWidget

application = QApplication([])
adapter = MarketPanelAdapter()
widget = adapter.widget()
detail_widget = adapter._detail.widget()
assert isinstance(widget, QWidget), type(widget).__name__
assert isinstance(detail_widget, QWidget), type(detail_widget).__name__
if adapter._detail._chart_widget is not None:
    assert isinstance(adapter._detail._chart_widget, QWidget), type(adapter._detail._chart_widget).__name__
widget.close()
application.processEvents()
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
