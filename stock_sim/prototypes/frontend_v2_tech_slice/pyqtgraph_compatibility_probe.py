"""Reproduce the current PySide6/pyqtgraph ViewBox incompatibility.

THROWAWAY PROTOTYPE EVIDENCE. This script does not alter project state.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pyqtgraph as pg
from PySide6 import __version__ as pyside_version
from PySide6.QtCore import qVersion
from PySide6.QtWidgets import QApplication

from contract import build_timeline


def main() -> int:
    app = QApplication([])
    plot = pg.PlotWidget()
    curve = plot.plot()
    x, candidate, *_rest = build_timeline().display_points()
    curve.setData(x, candidate)
    plot.show()
    app.processEvents()
    plot.getViewBox().autoRange()
    app.processEvents()
    parent = curve.parentItem()
    view_range = plot.getPlotItem().viewRange()
    expected_x = [float(x.min()), float(x.max())]
    expected_y = [float(candidate.min()), float(candidate.max())]
    compatible = (
        parent is not None
        and view_range[0][1] >= expected_x[1] * 0.9
        and view_range[1][0] <= expected_y[0]
        and view_range[1][1] >= expected_y[1]
    )
    payload = {
        "PySide6": pyside_version,
        "Qt": qVersion(),
        "pyqtgraph": pg.__version__,
        "curve_parent_type": type(parent).__name__ if parent is not None else None,
        "expected_x_range": expected_x,
        "expected_y_range": expected_y,
        "observed_view_range": view_range,
        "compatible": compatible,
        "fallback": "shared 4,000-point QPainter timeline",
    }
    print(json.dumps(payload, indent=2))
    return 0 if compatible else 2


if __name__ == "__main__":
    raise SystemExit(main())
