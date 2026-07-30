import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ACCESSIBLE_JOURNEY_PROBE = r"""
import json

from PySide6.QtCore import QObject
from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import QApplication

from app.features import (
    ApprovedScenarioRecipeId,
    DeterministicFakeEvidenceAndFindingsAdapter,
    DeterministicFakeRunMonitoringAdapter,
    EvidenceAndFindingsContext,
    EvidenceAndFindingsSelection,
    FormalDiagnosticCampaignId,
    MarketScenarioId,
    ReproductionManifestId,
    RunMonitoringContext,
    RunMonitoringSelection,
    StrategyRunId,
    StrategyUnderTestId,
)
from app.ui.journey_workspace import JourneyWorkspaceHost

app = QApplication([])
run_context = RunMonitoringContext.for_run(
    RunMonitoringSelection(
        campaign_id=FormalDiagnosticCampaignId("FDC-001"),
        run_id=StrategyRunId("RUN-001"),
    )
)
evidence_context = EvidenceAndFindingsContext.for_selection(
    EvidenceAndFindingsSelection(
        campaign_id=FormalDiagnosticCampaignId("FDC-001"),
        run_id=StrategyRunId("RUN-001"),
        strategy_id=StrategyUnderTestId("STRATEGY-MOMENTUM-001"),
        market_scenario_id=MarketScenarioId("SCENARIO-BASELINE"),
        approved_recipe_id=ApprovedScenarioRecipeId("RECIPE-001"),
        reproduction_manifest_id=ReproductionManifestId("RM-001"),
    )
)
run_feature = DeterministicFakeRunMonitoringAdapter()
evidence_feature = DeterministicFakeEvidenceAndFindingsAdapter()
run_feature.advance_to_running(run_context)
evidence_feature.advance_to_completed(evidence_context)
host = JourneyWorkspaceHost(
    run_feature,
    context=run_context,
    evidence_feature=evidence_feature,
    evidence_context=evidence_context,
)
host.resize(1280, 720)
host.move(-10000, -10000)
host.show()
for _ in range(4):
    app.processEvents()
root = host.rootObject()
tokens = root.findChild(QObject, "designTokens")
run_scroll = root.findChild(QObject, "runMonitoringFlickable")
run_status = root.findChild(QObject, "runMonitoringAccessibleStatus")
root.setProperty("activeRoute", "evidence_and_findings")
for _ in range(4):
    app.processEvents()
candidate = root.property("evidenceInitialFocusItem")
candidate_interface = QAccessible.queryAccessibleInterface(candidate)
status_interface = QAccessible.queryAccessibleInterface(run_status)
image = host.grab().toImage()
nontransparent = sum(
    image.pixelColor(x, y).alpha() > 0
    for y in range(0, image.height(), max(1, image.height() // 50))
    for x in range(0, image.width(), max(1, image.width() // 50))
)
print(
    json.dumps(
        {
            "api": host.quickWindow().rendererInterface().graphicsApi().name,
            "image_is_null": image.isNull(),
            "nontransparent": nontransparent,
            "text_scale": tokens.property("textScale"),
            "body_size": tokens.property("bodySize"),
            "reduced_motion": tokens.property("reducedMotion"),
            "high_contrast": tokens.property("highContrast"),
            "run_scrollable": (
                run_scroll.property("contentHeight")
                > run_scroll.property("height")
            ),
            "candidate_focus": candidate.property("activeFocus"),
            "candidate_name": candidate_interface.text(
                QAccessible.Text.Name
            ),
            "status_role": status_interface.role().name,
        }
    )
)
host.close_adapter()
host.close()
run_feature.close()
evidence_feature.close()
app.processEvents()
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
def test_accessible_journey_renders_at_200_percent_in_supported_lanes(
    lane,
    expected_api,
):
    environment = os.environ.copy()
    environment["PYTHONWARNINGS"] = "ignore"
    environment["QT_SCALE_FACTOR"] = "2"
    environment["STOCKSIM_TEXT_SCALE_PERCENT"] = "200"
    environment["STOCKSIM_REDUCED_MOTION"] = "1"
    environment["STOCKSIM_HIGH_CONTRAST"] = "1"
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
        [sys.executable, "-c", ACCESSIBLE_JOURNEY_PROBE],
        cwd=PROJECT_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
        check=True,
    )
    observation = json.loads(completed.stdout.strip().splitlines()[-1])

    assert observation["api"] == expected_api
    assert observation["image_is_null"] is False
    assert observation["nontransparent"] > 0
    assert observation["text_scale"] == 2.0
    assert observation["body_size"] == 26
    assert observation["reduced_motion"] is True
    assert observation["high_contrast"] is True
    assert observation["run_scrollable"] is True
    assert observation["candidate_focus"] is True
    assert observation["candidate_name"] == "Select candidate MODEL-B17"
    assert observation["status_role"] == "StatusBar"
