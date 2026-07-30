import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RENDER_PROBE = """
import json
import os
from PySide6.QtCore import QPointF, QUrl
from PySide6.QtQuick import QQuickView
from PySide6.QtWidgets import QApplication

app = QApplication([])
view = QQuickView()
view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
view.resize(160, 90)
view.setPosition(-10000, -10000)
view.setSource(QUrl.fromLocalFile(os.environ["EVIDENCE_CHART_QML"]))
item = view.rootObject()
if item is None:
    raise RuntimeError("EvidenceChart.qml did not load")
item.setProperty(
    "normalizedPoints",
    [
        QPointF(0.0, 0.15),
        QPointF(0.33, 0.85),
        QPointF(0.66, 0.35),
        QPointF(1.0, 0.60),
    ],
)
item.setProperty(
    "overlayModels",
    [
        {
            "identity": "OV-1",
            "axis": "horizontal",
            "position": 0.25,
            "selected": False,
        },
        {
            "identity": "OV-2",
            "axis": "horizontal",
            "position": 0.75,
            "selected": True,
        },
        {
            "identity": "OV-3",
            "axis": "vertical",
            "position": 0.60,
            "selected": False,
        },
    ],
)
item.setProperty("selectedPointX", 0.66)
item.setProperty("selectedPointY", 0.35)
view.show()
for _ in range(4):
    app.processEvents()
image = view.grabWindow()
nontransparent = sum(
    image.pixelColor(x, y).alpha() > 0
    for y in range(image.height())
    for x in range(image.width())
)
print(
    json.dumps(
        {
            "api": view.rendererInterface().graphicsApi().name,
            "image_is_null": image.isNull(),
            "nontransparent": nontransparent,
            "sample_points": item.property("samplePointCount"),
            "overlays": item.property("overlayCount"),
        }
    )
)
view.close()
app.processEvents()
del view
"""


@pytest.mark.parametrize(
    ("lane", "expected_api"),
    (
        ("software", "Software"),
        pytest.param(
            "hardware",
            "Direct3D11",
            marks=pytest.mark.skipif(
                sys.platform != "win32",
                reason="The production hardware lane targets Windows D3D11.",
            ),
        ),
    ),
)
def test_production_chart_renders_deterministically_in_supported_lanes(
    lane,
    expected_api,
):
    environment = os.environ.copy()
    environment["PYTHONWARNINGS"] = "ignore"
    environment["EVIDENCE_CHART_QML"] = str(
        PROJECT_ROOT / "app" / "ui" / "qml" / "EvidenceChart.qml"
    )
    if lane == "software":
        environment["QT_QPA_PLATFORM"] = "offscreen"
        environment["QT_QUICK_BACKEND"] = "software"
        environment["QSG_RENDER_LOOP"] = "basic"
        environment.pop("QSG_RHI_BACKEND", None)
    else:
        environment.pop("QT_QPA_PLATFORM", None)
        environment.pop("QT_QUICK_BACKEND", None)
        environment.pop("QSG_RENDER_LOOP", None)
        environment["QSG_RHI_BACKEND"] = "d3d11"

    completed = subprocess.run(
        [sys.executable, "-c", RENDER_PROBE],
        cwd=PROJECT_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=20,
        check=True,
    )
    observation = json.loads(completed.stdout.strip().splitlines()[-1])

    assert observation["api"] == expected_api
    assert observation["image_is_null"] is False
    assert observation["sample_points"] == 4
    assert observation["overlays"] == 3
    assert observation["nontransparent"] > 0
