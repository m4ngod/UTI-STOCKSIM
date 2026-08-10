import os
from pathlib import Path
import subprocess
import sys


def test_remaining_retained_widgets_adapters_promote_after_headless_import():
    project_root = Path(__file__).resolve().parents[3]
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment.pop("STOCKSIM_ENABLE_REAL_UI", None)
    program = """
from app.ui.adapters.agents_adapter import AgentsPanelAdapter
from app.ui.adapters.orders_adapter import OrdersPanelAdapter
from PySide6.QtWidgets import QApplication, QWidget

application = QApplication([])
agents = AgentsPanelAdapter()
orders = OrdersPanelAdapter()
agents_widget = agents.widget()
orders_widget = orders.widget()
assert isinstance(agents_widget, QWidget), (type(agents_widget).__module__, type(agents_widget).__name__)
assert isinstance(orders_widget, QWidget), (type(orders_widget).__module__, type(orders_widget).__name__)
agents.stop()
agents_widget.close()
orders_widget.close()
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
