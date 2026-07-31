import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ACCESSIBLE_JOURNEY_PROBE = r"""
import hashlib
import json
import os
from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import QApplication

from app.features import (
    ApprovedScenarioRecipeId,
    DeterministicFakeDiagnosticTasksAdapter,
    DeterministicFakeEvidenceAndFindingsAdapter,
    DeterministicFakeRunMonitoringAdapter,
    DiagnosticTasksContext,
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


evidence_directory_value = os.environ.get(
    "STOCKSIM_ACCESSIBLE_JOURNEY_EVIDENCE_DIR"
)
evidence_directory = (
    None
    if evidence_directory_value is None
    else Path(evidence_directory_value)
)
if evidence_directory is not None:
    evidence_directory.mkdir(parents=True, exist_ok=True)


def save_evidence(image, filename):
    if evidence_directory is None:
        return
    if not image.save(str(evidence_directory / filename)):
        raise RuntimeError(f"could not save renderer evidence {filename}")


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
diagnostic_tasks = DeterministicFakeDiagnosticTasksAdapter()
run_feature.advance_to_running(run_context)
evidence_feature.advance_to_completed(evidence_context)
host = JourneyWorkspaceHost(
    run_feature,
    context=run_context,
    diagnostic_tasks_feature=diagnostic_tasks,
    diagnostic_tasks_context=DiagnosticTasksContext.workspace(),
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
diagnostic_scroll = root.findChild(QObject, "diagnosticTasksFlickable")
diagnostic_status = root.findChild(QObject, "diagnosticTasksAccessibleStatus")
diagnostic_create = root.findChild(QObject, "createDiagnosticTaskButton")
diagnostic_focus = diagnostic_create.property("activeFocus")
diagnostic_control_height = diagnostic_create.property("height")
diagnostic_image = host.grabFramebuffer()
save_evidence(diagnostic_image, "diagnostic_tasks.png")
diagnostic_digest = hashlib.sha256(
    bytes(diagnostic_image.bits())
).hexdigest()
root.setProperty("activeRoute", "run_monitoring")
for _ in range(4):
    app.processEvents()
run_scroll = root.findChild(QObject, "runMonitoringFlickable")
run_status = root.findChild(QObject, "runMonitoringAccessibleStatus")
run_image = host.grabFramebuffer()
save_evidence(run_image, "run_monitoring.png")
run_digest = hashlib.sha256(bytes(run_image.bits())).hexdigest()
root.setProperty("activeRoute", "evidence_and_findings")
for _ in range(4):
    app.processEvents()
candidate = root.property("evidenceInitialFocusItem")
candidate_interface = QAccessible.queryAccessibleInterface(candidate)
status_interface = QAccessible.queryAccessibleInterface(run_status)
image = host.grabFramebuffer()
save_evidence(image, "evidence_and_findings.png")
evidence_digest = hashlib.sha256(bytes(image.bits())).hexdigest()
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
            "diagnostic_scrollable": (
                diagnostic_scroll.property("contentHeight")
                > diagnostic_scroll.property("height")
            ),
            "diagnostic_focus": diagnostic_focus,
            "diagnostic_control_height": diagnostic_control_height,
            "diagnostic_status_role": (
                QAccessible.queryAccessibleInterface(
                    diagnostic_status
                ).role().name
            ),
            "run_scrollable": (
                run_scroll.property("contentHeight")
                > run_scroll.property("height")
            ),
            "route_screenshots_distinct": len(
                {diagnostic_digest, run_digest, evidence_digest}
            ) == 3,
            "route_screenshot_sha256": {
                "diagnostic_tasks.png": diagnostic_digest,
                "run_monitoring.png": run_digest,
                "evidence_and_findings.png": evidence_digest,
            },
            "image_width": image.width(),
            "image_height": image.height(),
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
diagnostic_tasks.close()
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

    evidence_root_value = os.environ.get(
        "STOCKSIM_ACCESSIBLE_JOURNEY_EVIDENCE_ROOT"
    )
    if evidence_root_value is not None:
        evidence_directory = Path(evidence_root_value) / lane
        environment["STOCKSIM_ACCESSIBLE_JOURNEY_EVIDENCE_DIR"] = str(
            evidence_directory
        )

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
    if evidence_root_value is not None:
        evidence_directory.mkdir(parents=True, exist_ok=True)
        (evidence_directory / "renderer-report.json").write_text(
            json.dumps(
                {
                    "source_commit": os.environ.get(
                        "STOCKSIM_SOURCE_COMMIT",
                        "working-tree",
                    ),
                    "lane": lane,
                    **observation,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    assert observation["api"] == expected_api
    assert observation["image_is_null"] is False
    assert observation["nontransparent"] > 0
    assert observation["text_scale"] == 2.0
    assert observation["body_size"] == 26
    assert observation["reduced_motion"] is True
    assert observation["high_contrast"] is True
    assert observation["diagnostic_scrollable"] is True
    assert observation["diagnostic_focus"] is True
    assert observation["diagnostic_control_height"] >= 76
    assert observation["diagnostic_status_role"] == "StatusBar"
    assert observation["run_scrollable"] is True
    assert observation["route_screenshots_distinct"] is True
    assert len(set(observation["route_screenshot_sha256"].values())) == 3
    assert observation["image_width"] > 0
    assert observation["image_height"] > 0
    assert observation["candidate_focus"] is True
    assert observation["candidate_name"] == "Select candidate MODEL-B17"
    assert observation["status_role"] == "StatusBar"
