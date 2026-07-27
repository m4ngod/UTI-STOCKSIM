"""Installed-package black-box entry point for the Frontend V2 release gate."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import json
import os
from pathlib import Path
import re
from time import monotonic, sleep
from typing import Any, Callable, Sequence


UTC = timezone.utc
RUN_ID = "RUN-RC-001"
CAMPAIGN_ID = "FDC-RC-001"
STRATEGY_ID = "STRATEGY-RC-001"
SCENARIO_ID = "SCENARIO-RC-001"
RECIPE_ID = "RECIPE-RC-001"
MANIFEST_ID = "RM-RC-001"
PRODUCTION_PATH = (
    "AppContext",
    "EventBridge",
    "LiveRunMonitoringAdapter",
    "LiveEvidenceAndFindingsAdapter",
    "JourneyWorkspaceHost",
)
EXPECTED_JOURNEY = (
    (
        "launched_active_run",
        "run_monitoring",
        "active",
        "ready",
        "fresh",
        "fresh",
    ),
    (
        "active_evidence",
        "evidence_and_findings",
        "active",
        "ready",
        "fresh",
        "fresh",
    ),
    (
        "disconnected_run",
        "run_monitoring",
        "active",
        "ready",
        "disconnected",
        "disconnected",
    ),
    (
        "disconnected_evidence",
        "evidence_and_findings",
        "active",
        "ready",
        "disconnected",
        "disconnected",
    ),
    (
        "reconnected_run",
        "run_monitoring",
        "active",
        "ready",
        "fresh",
        "fresh",
    ),
    (
        "reconnected_evidence",
        "evidence_and_findings",
        "active",
        "ready",
        "fresh",
        "fresh",
    ),
    (
        "completed_run",
        "run_monitoring",
        "terminal",
        "ready",
        "fresh",
        "fresh",
    ),
    (
        "completed_evidence",
        "evidence_and_findings",
        "terminal",
        "ready",
        "fresh",
        "fresh",
    ),
)
_APPROVED_INTERACTIVE_NAMES = re.compile(
    r"^(?:"
    r"Open Run Monitoring|"
    r"Open Evidence and Findings|"
    r"Pause diagnostic task|"
    r"Resume diagnostic task|"
    r"Cancel diagnostic task|"
    r"Select candidate .+|"
    r"Select finding .+|"
    r"Select chart overlay .+|"
    r"Select Sensitivity Breakpoint .+|"
    r"Select diagnostic evidence point|"
    r"Filter evidence by risk|"
    r"Sort evidence by coverage|"
    r"Focus compound stress evidence|"
    r"Show (?:findings|assumptions|provenance|context) tab"
    r")$"
)


class RendererLane(str, Enum):
    HARDWARE = "hardware"
    SOFTWARE = "software"


@dataclass(frozen=True, slots=True)
class SmokeStateObservation:
    stage: str
    route: str
    run_state: str
    evidence_state: str
    run_freshness: str
    evidence_freshness: str
    run_phase: str
    evidence_phase: str
    run_revision: str
    evidence_revision: str
    source_generation: str
    headline: str
    detail: str
    screenshot: str | None


@dataclass(frozen=True, slots=True)
class PackageSmokeResult:
    schema_version: int
    source_commit: str
    renderer_lane: RendererLane
    graphics_api: str
    production_path: tuple[str, ...]
    run_identity: str
    routes_rendered: tuple[str, ...]
    connection_transitions: tuple[str, ...]
    observations: tuple[SmokeStateObservation, ...]
    manual_trading_action_count: int
    read_only_context_visible: bool
    errors: tuple[str, ...]
    clean_exit: bool


class _ReleaseCandidateRuntimeQueries:
    """Fixed runtime data read through the production live Feature Adapters."""

    def __init__(self) -> None:
        self._revision = 1
        self._status = "running"
        self._updated_at = datetime.now(UTC)

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def status(self) -> str:
        return self._status

    def advance(self, *, status: str = "running") -> int:
        self._revision += 1
        self._status = status
        self._updated_at = datetime.now(UTC)
        return self._revision

    def get_run_monitoring_snapshot(
        self,
        run_id: str,
    ) -> dict[str, Any] | None:
        if run_id != RUN_ID:
            return None
        terminal = self._status == "completed"
        return {
            "run_id": RUN_ID,
            "revision": self._revision,
            "scenario_name": SCENARIO_ID,
            "scenario_set_id": "SET-RC-001",
            "strategy_id": STRATEGY_ID,
            "reproduction_manifest_id": MANIFEST_ID,
            "task_id": "TASK-RC-001",
            "status": self._status,
            "started_at": self._updated_at - timedelta(minutes=3),
            "updated_at": self._updated_at,
            "last_sim_day": 5 if terminal else 2,
            "last_sim_dt": self._updated_at - timedelta(days=1),
            "completed_nodes": 5 if terminal else 2,
            "total_nodes": 5,
            "current_node_id": (
                "NODE-RC-COMPLETE" if terminal else "NODE-RC-RUNNING"
            ),
            "current_node_label": (
                "Evidence ready" if terminal else "Running scenario"
            ),
            "requested_execution": {"fee_multiplier": "1.0x"},
            "effective_execution": {"fee_multiplier": "1.6x"},
            "execution_override_reasons": {
                "fee_multiplier": "Approved Scenario Recipe override"
            },
            "alerts": [],
            "market_context": ["600519.SH · diagnostic market context"],
            "account_context": ["MODEL-RC-001 · research account"],
            "position_context": ["600519.SH · +100 · evidence snapshot"],
            "order_context": ["ORD-RC-001 · filled · read-only trace"],
            "fill_context": ["FILL-RC-001 · 100 @ 1500 · read-only trace"],
        }

    def get_evidence_and_findings_snapshot(
        self,
        run_id: str,
    ) -> dict[str, Any] | None:
        if run_id != RUN_ID:
            return None
        return {
            "run_id": RUN_ID,
            "revision": self._revision,
            "updated_at": self._updated_at.isoformat(),
            "status": self._status,
            "selection": {
                "campaign_id": CAMPAIGN_ID,
                "run_id": RUN_ID,
                "strategy_id": STRATEGY_ID,
                "market_scenario_id": SCENARIO_ID,
                "approved_recipe_id": RECIPE_ID,
                "reproduction_manifest_id": MANIFEST_ID,
            },
            "candidates": [self._candidate()],
            "read_only_context": {
                "market": ["600519.SH · closed diagnostic session"],
                "account": ["MODEL-RC-001 · simulated research account"],
                "positions": ["600519.SH · +100 · evidence snapshot"],
                "orders": [
                    {
                        "id": "ORD-RC-001",
                        "instrument": "600519.SH",
                        "status": "filled",
                        "diagnostic_note": "Read-only execution trace.",
                    }
                ],
                "fills": [
                    {
                        "id": "FILL-RC-001",
                        "order_id": "ORD-RC-001",
                        "instrument": "600519.SH",
                        "quantity": 100,
                        "price": "1500.00",
                    }
                ],
            },
        }

    @staticmethod
    def _candidate() -> dict[str, Any]:
        return {
            "candidate_id": "MODEL-RC-001",
            "label": "Release candidate",
            "evidence": [
                {
                    "id": "E-RC-BASE",
                    "coverage": "baseline",
                    "dimension": "return",
                    "label": "Baseline return",
                    "value": "7.4",
                    "unit": "%",
                    "availability": "complete",
                    "interpretation": "Persisted baseline evidence.",
                },
                {
                    "id": "E-RC-FEE",
                    "coverage": "isolated_sensitivity",
                    "dimension": "execution",
                    "label": "Fee sensitivity",
                    "value": "-1.8",
                    "comparison_evidence_id": "E-RC-BASE",
                    "comparison_value": "7.4",
                    "unit": "return delta points",
                    "availability": "complete",
                    "interpretation": "Fees reduce the baseline result.",
                },
                {
                    "id": "E-RC-COMPOUND",
                    "coverage": "compound_scenario",
                    "dimension": "stability",
                    "label": "Compound stability",
                    "value": "61",
                    "comparison_evidence_id": "E-RC-BASE",
                    "comparison_value": "83",
                    "unit": "% stable windows",
                    "availability": "complete",
                    "interpretation": "Compound stress reduces stability.",
                },
            ],
            "comparisons": [
                {
                    "id": "CMP-RC-FEE",
                    "label": "Baseline versus fee sensitivity",
                    "reference_evidence_id": "E-RC-BASE",
                    "observed_evidence_id": "E-RC-FEE",
                    "interpretation": "Fees reduce the result.",
                }
            ],
            "findings": [
                {
                    "id": "F-RC-FEE",
                    "title": "Fees break the baseline result",
                    "disposition": "concern",
                    "comparison_summary": "The fee case is weaker.",
                    "failure_reason": "Turnover amplifies effective fees.",
                    "evidence_ids": ["E-RC-BASE", "E-RC-FEE"],
                    "comparison_ids": ["CMP-RC-FEE"],
                    "sensitivity_breakpoints": [
                        {
                            "id": "BP-RC-FEE",
                            "assumption_name": "fee_multiplier",
                            "threshold": "1.6x",
                            "outcome": "Excess return becomes non-positive.",
                            "evidence_ids": ["E-RC-BASE", "E-RC-FEE"],
                        }
                    ],
                }
            ],
            "execution_assumptions": [
                {
                    "name": "fee_multiplier",
                    "requested_value": "1.0x",
                    "effective_value": "1.6x",
                    "override_reason": "Approved Scenario Recipe override",
                }
            ],
            "provenance": {
                "artifact_hashes": ["sha256:release-candidate"],
                "source_run_ids": [RUN_ID],
                "runner_version": "frontend-v2-release-candidate/1",
                "build_version": "uti-stocksim/wave1",
                "dependencies": [
                    {
                        "name": "reproduction-manifest",
                        "version": MANIFEST_ID,
                        "artifact_hash": "sha256:release-manifest",
                    }
                ],
            },
            "chart": {
                "identity": "MODEL-RC-001-diagnostic-series",
                "label": "Release candidate evidence path",
                "unit": "normalized evidence value",
                "values": [100.0, 101.2, 99.8, 102.0, 98.9, 101.4],
                "overlays": [
                    {
                        "identity": "OV-RC-LOW",
                        "label": "Lower evidence threshold",
                        "axis": "horizontal",
                        "coordinate": 99.0,
                        "interpretation": "Lower diagnostic threshold.",
                        "evidence_ids": ["E-RC-BASE"],
                    },
                    {
                        "identity": "OV-RC-BREAK",
                        "label": "Sensitivity breakpoint",
                        "axis": "vertical",
                        "coordinate": 3,
                        "interpretation": "Fee sensitivity begins here.",
                        "evidence_ids": ["E-RC-FEE"],
                    },
                ],
            },
        }


def configure_renderer_environment(renderer_lane: RendererLane) -> None:
    if renderer_lane is RendererLane.SOFTWARE:
        os.environ["QT_QUICK_BACKEND"] = "software"
        os.environ["QSG_RHI_BACKEND"] = "software"
        return
    os.environ.pop("QT_QUICK_BACKEND", None)
    os.environ["QSG_RHI_BACKEND"] = "d3d11"


def _configure_smoke_route_identity() -> dict[str, str | None]:
    route_identity = {
        "STOCKSIM_FRONTEND_V2": "1",
        "STOCKSIM_FRONTEND_V2_CAMPAIGN_ID": CAMPAIGN_ID,
        "STOCKSIM_FRONTEND_V2_RUN_ID": RUN_ID,
        "STOCKSIM_FRONTEND_V2_STRATEGY_ID": STRATEGY_ID,
        "STOCKSIM_FRONTEND_V2_MARKET_SCENARIO_ID": SCENARIO_ID,
        "STOCKSIM_FRONTEND_V2_APPROVED_RECIPE_ID": RECIPE_ID,
        "STOCKSIM_FRONTEND_V2_REPRODUCTION_MANIFEST_ID": MANIFEST_ID,
    }
    previous = {
        name: os.environ.get(name)
        for name in route_identity
    }
    os.environ.update(route_identity)
    return previous


def _restore_environment(previous: dict[str, str | None]) -> None:
    for name, value in previous.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def _create_production_window(
    *,
    event_bridge: Any,
    settings_path: Path,
    runtime_gateway: Any | None = None,
) -> tuple[Any, Any, Any]:
    from app.app_context import build_app_context
    from app.ui.main_window import MainWindow

    context = build_app_context(
        settings_path=str(settings_path),
        run_monitoring_mode="live",
        event_bridge=event_bridge,
        runtime_gateway=runtime_gateway,
    )
    window = MainWindow(
        run_monitoring_feature=context.run_monitoring_feature,
        run_monitoring_context=context.run_monitoring_context,
        evidence_and_findings_feature=(
            context.evidence_and_findings_feature
        ),
        evidence_and_findings_context=(
            context.evidence_and_findings_context
        ),
        frontend_v2_enabled=True,
    )
    if not window.journey_workspace_active:
        raise RuntimeError(
            "Production AppContext did not mount the Journey Workspace"
        )
    host = window._journey_workspace
    return context, window, host


def run_smoke_journey(
    *,
    report_dir: Path,
    renderer_lane: RendererLane,
    source_commit: str = "development-smoke",
    capture_images: bool = True,
) -> PackageSmokeResult:
    from PySide6.QtWidgets import QApplication

    from app.event_bridge import EventBridge

    report_dir.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    queries = _ReleaseCandidateRuntimeQueries()
    bridge = EventBridge(subscribe_backend=False)
    previous_environment = _configure_smoke_route_identity()
    try:
        context, window, host = _create_production_window(
            event_bridge=bridge,
            runtime_gateway=queries,
            settings_path=report_dir / "frontend-v2-settings.json",
        )
    except BaseException:
        _restore_environment(previous_environment)
        raise
    run_feature = context.run_monitoring_feature
    evidence_feature = context.evidence_and_findings_feature
    window.setObjectName("frontendV2PackageWindow")
    window.resize(1280, 720)
    bridge.start()
    window.show()
    app.processEvents()

    observations: list[SmokeStateObservation] = []
    root = host.rootObject()
    if root is None:
        raise RuntimeError("Journey Workspace root object is unavailable")

    def observe(
        stage: str,
        route: str,
        run_state: str,
        evidence_state: str,
        run_freshness: str,
        evidence_freshness: str,
    ) -> None:
        root.setProperty("activeRoute", route)
        run_adapter = host._run_monitoring
        evidence_adapter = host._evidence_and_findings
        if evidence_adapter is None:
            raise RuntimeError("Evidence & Findings Adapter is unavailable")
        try:
            _settle_until(
                app,
                lambda: (
                    root.property("activeRoute") == route
                    and root.property("screenState") == run_state
                    and root.property("evidenceScreenState")
                    == evidence_state
                    and run_adapter.property("freshness")
                    == run_freshness
                    and evidence_adapter.property("freshness")
                    == evidence_freshness
                ),
                (
                    f"{stage}: expected {route}/{run_state}/"
                    f"{evidence_state}/{run_freshness}/"
                    f"{evidence_freshness}"
                ),
            )
        except RuntimeError as error:
            raise RuntimeError(
                f"{error}; observed "
                f"{root.property('activeRoute')}/"
                f"{root.property('screenState')}/"
                f"{root.property('evidenceScreenState')}/"
                f"{run_adapter.property('freshness')}/"
                f"{evidence_adapter.property('freshness')}"
            ) from error
        host.update()
        quick_window = host.quickWindow()
        if quick_window is not None:
            quick_window.update()
        app.processEvents()
        sleep(0.05)
        app.processEvents()
        observations.append(
            _observe_state(
                root=root,
                host=host,
                report_dir=report_dir,
                stage=stage,
                route=route,
                capture_images=capture_images,
            )
        )

    try:
        observe(*EXPECTED_JOURNEY[0])
        observe(*EXPECTED_JOURNEY[1])

        bridge.mark_disconnected()
        observe(*EXPECTED_JOURNEY[2])
        observe(*EXPECTED_JOURNEY[3])

        queries.advance()
        bridge.mark_reconnected()
        bridge.on_snapshot(
            {
                "run_id": RUN_ID,
                "revision": queries.revision,
                "status": queries.status,
            },
            generation=bridge.connection_generation,
        )
        bridge.flush(force=True)
        observe(*EXPECTED_JOURNEY[4])
        observe(*EXPECTED_JOURNEY[5])

        queries.advance(status="completed")
        bridge.on_snapshot(
            {
                "run_id": RUN_ID,
                "revision": queries.revision,
                "status": queries.status,
            },
            generation=bridge.connection_generation,
        )
        bridge.flush(force=True)
        observe(*EXPECTED_JOURNEY[6])
        observe(*EXPECTED_JOURNEY[7])

        graphics_api = _graphics_api_name(host)
        manual_action_count = _unapproved_interactive_action_count(root)
        read_only_context_visible = _read_only_context_visible(host)
    finally:
        host.close_adapter()
        window.close()
        run_feature.close()
        evidence_feature.close()
        bridge.stop()
        _restore_environment(previous_environment)
        app.processEvents()

    result = PackageSmokeResult(
        schema_version=2,
        source_commit=source_commit,
        renderer_lane=renderer_lane,
        graphics_api=graphics_api,
        production_path=PRODUCTION_PATH,
        run_identity=RUN_ID,
        routes_rendered=("run_monitoring", "evidence_and_findings"),
        connection_transitions=(
            "connected",
            "disconnected",
            "reconnected",
            "completed",
        ),
        observations=tuple(observations),
        manual_trading_action_count=manual_action_count,
        read_only_context_visible=read_only_context_visible,
        errors=(),
        clean_exit=True,
    )
    _write_smoke_report(result, report_dir / "smoke-report.json")
    return result


def _settle_until(
    app: Any,
    predicate: Callable[[], bool],
    description: str,
    *,
    timeout_seconds: float = 3.0,
) -> None:
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        app.processEvents()
        if predicate():
            app.processEvents()
            return
        sleep(0.01)
    raise RuntimeError(f"Timed out waiting for {description}")


def _observe_state(
    *,
    root: Any,
    host: Any,
    report_dir: Path,
    stage: str,
    route: str,
    capture_images: bool,
) -> SmokeStateObservation:
    run_adapter = host._run_monitoring
    evidence_adapter = host._evidence_and_findings
    if evidence_adapter is None:
        raise RuntimeError("Evidence & Findings Adapter is unavailable")
    screenshot_name = None
    if capture_images:
        screenshot_name = f"{stage}.png"
        _capture_qml_frame(host, report_dir / screenshot_name)
    return SmokeStateObservation(
        stage=stage,
        route=route,
        run_state=str(root.property("screenState")),
        evidence_state=str(root.property("evidenceScreenState")),
        run_freshness=str(run_adapter.property("freshness")),
        evidence_freshness=str(evidence_adapter.property("freshness")),
        run_phase=str(run_adapter.property("phase")),
        evidence_phase=str(evidence_adapter.property("phase")),
        run_revision=str(run_adapter.property("revisionText")),
        evidence_revision=str(evidence_adapter.property("revisionText")),
        source_generation=str(
            run_adapter.property("sourceGenerationText")
        ),
        headline=str(root.property("headline")),
        detail=str(root.property("detail")),
        screenshot=screenshot_name,
    )


def _unapproved_interactive_action_count(root: Any) -> int:
    from PySide6.QtCore import QObject
    from PySide6.QtGui import QAccessible

    count = 0
    for item in (root, *root.findChildren(QObject)):
        interface = QAccessible.queryAccessibleInterface(item)
        if interface is None or not interface.isValid():
            continue
        if interface.role() not in {
            QAccessible.Role.Button,
            QAccessible.Role.Slider,
        }:
            continue
        name = interface.text(QAccessible.Text.Name).strip()
        if not _APPROVED_INTERACTIVE_NAMES.fullmatch(name):
            count += 1
    return count


def _read_only_context_visible(host: Any) -> bool:
    run_text = str(
        host._run_monitoring.property("diagnosticContextText")
    )
    evidence_adapter = host._evidence_and_findings
    if evidence_adapter is None:
        return False
    evidence_text = str(evidence_adapter.property("readOnlyContextText"))
    return (
        "Orders" in run_text
        and "Fills" in run_text
        and "read-only evidence traces" in evidence_text
    )


def _capture_qml_frame(host: Any, screenshot_path: Path) -> None:
    image = host.grabFramebuffer()
    if image.isNull() or not image.save(str(screenshot_path), "PNG"):
        raise RuntimeError(f"Failed to capture {screenshot_path}")


def _graphics_api_name(host: Any) -> str:
    quick_window = host.quickWindow()
    if quick_window is None:
        return "unavailable"
    graphics_api = quick_window.rendererInterface().graphicsApi()
    return getattr(graphics_api, "name", str(graphics_api))


def _write_smoke_report(
    result: PackageSmokeResult,
    report_path: Path,
) -> None:
    payload = asdict(result)
    payload["renderer_lane"] = result.renderer_lane.value
    report_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _run_interactive() -> int:
    from PySide6.QtWidgets import QApplication

    from app.event_bridge import (
        start_frontend_bridge,
        stop_frontend_bridge,
    )

    app = QApplication.instance() or QApplication([])
    bridge = start_frontend_bridge()
    os.environ["STOCKSIM_FRONTEND_V2"] = "1"
    context, window, _host = _create_production_window(
        event_bridge=bridge,
        settings_path=Path("frontend-v2-settings.json"),
    )
    window.resize(1024, 640)
    app.aboutToQuit.connect(context.run_monitoring_feature.close)
    app.aboutToQuit.connect(context.evidence_and_findings_feature.close)
    app.aboutToQuit.connect(stop_frontend_bridge)
    window.show()
    return int(app.exec())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--renderer-lane",
        choices=tuple(lane.value for lane in RendererLane),
        default=RendererLane.HARDWARE.value,
    )
    parser.add_argument("--smoke-report-dir", type=Path)
    parser.add_argument("--source-commit", default="unbound")
    parser.add_argument("--no-images", action="store_true")
    arguments = parser.parse_args(argv)
    renderer_lane = RendererLane(arguments.renderer_lane)
    configure_renderer_environment(renderer_lane)
    if arguments.smoke_report_dir is not None:
        result = run_smoke_journey(
            report_dir=arguments.smoke_report_dir,
            renderer_lane=renderer_lane,
            source_commit=arguments.source_commit,
            capture_images=not arguments.no_images,
        )
        return (
            0
            if (
                not result.errors
                and result.clean_exit
                and result.manual_trading_action_count == 0
                and result.read_only_context_visible
            )
            else 1
        )
    return _run_interactive()


if __name__ == "__main__":
    raise SystemExit(main())
