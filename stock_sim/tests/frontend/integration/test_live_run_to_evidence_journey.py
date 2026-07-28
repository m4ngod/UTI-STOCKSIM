from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from concurrent.futures import Future
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from time import monotonic, sleep

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest
from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAccessible
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from sqlalchemy import create_engine

from app.event_bridge import EventBridge
from app.features import (
    APPLICATION_READ_MODEL_INTERFACE_VERSION,
    ApplicationReadAvailability,
    ApplicationReadError,
    ApplicationReadErrorCode,
    ApplicationReadModelVersion,
    ApplicationReadResult,
    DiagnosticEvidencePackageId,
    DiagnosticTaskCapabilities,
    EvidenceAndFindingsContext,
    EvidenceAndFindingsData,
    EvidenceAndFindingsPresentationState,
    EvidenceCoverage,
    ExecutionAssumption,
    FormalDiagnosticCampaignId,
    LiveEvidenceAndFindingsAdapter,
    LiveRunMonitoringAdapter,
    LiveStrategyDiagnosticsV1ApplicationAdapter,
    MarketScenarioId,
    ReadOnlyDiagnosticContext,
    ReproductionManifestId,
    ResolvedV1Journey,
    RunLifecyclePhase,
    RunMonitoringContext,
    RunMonitoringData,
    RunMonitoringPresentationState,
    RunMonitoringSelection,
    RunProgress,
    ScenarioSetId,
    SimulationTime,
    SourceRevisionToken,
    StrategyRunId,
    StrategyUnderTestId,
    TerminalOutcome,
    V1JourneySelector,
    WallTime,
)
from app.panels.diagnostics.panel import DiagnosticsPanel
from app.ui.accessibility import AccessibilityPreferences
from app.ui.journey_workspace import JourneyWorkspaceHost
from strategy_diagnostics import (
    QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
    QUENTX_SCENARIO_NATIVE_STRATEGY_VERSION,
    create_diagnostics_application,
)
from strategy_diagnostics.diagnostic_evidence_storage import (
    JsonDiagnosticEvidenceArtifactStore,
)
from strategy_diagnostics.market_paths import ParquetMarketPathArtifactStore
from tests.frontend.contract.test_strategy_diagnostics_v1_application_read_model_live_contract import (
    NOW,
)
from tests.frontend.contract.test_strategy_diagnostics_v1_evidence_and_findings_live_contract import (
    _persist_real_formal_v1_through_application,
)
from tests.frontend.unit.test_diagnostics_panel import (
    _MarketStructureWorkspaceSource,
)

UTC = timezone.utc


class _DirectExecutor:
    def submit(self, fn, /, *args, **kwargs):
        future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as error:  # noqa: BLE001 - Future semantics
            future.set_exception(error)
        return future

    def shutdown(self, wait=True, *, cancel_futures=False):
        return None


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _settle(app: QApplication) -> None:
    app.processEvents()
    app.processEvents()


def _wait_for(predicate, app: QApplication, message: str) -> None:
    deadline = monotonic() + 8
    while monotonic() < deadline:
        _settle(app)
        if predicate():
            return
        sleep(0.01)
    raise AssertionError(message)


def _visible_text(root: QObject) -> str:
    return " ".join(
        str(item.property("text"))
        for item in root.findChildren(QObject)
        if item.metaObject().indexOfProperty("text") >= 0
        and item.property("visible")
        and item.property("text")
    )


def _accessible_text(item: QObject, kind: QAccessible.Text) -> str:
    interface = QAccessible.queryAccessibleInterface(item)
    assert interface is not None and interface.isValid()
    return interface.text(kind)


def _contrast_ratio(first, second) -> float:
    def luminance(color) -> float:
        values = []
        for channel in (color.redF(), color.greenF(), color.blueF()):
            values.append(
                channel / 12.92
                if channel <= 0.04045
                else ((channel + 0.055) / 1.055) ** 2.4
            )
        return 0.2126 * values[0] + 0.7152 * values[1] + 0.0722 * values[2]

    bright, dark = sorted(
        (luminance(first), luminance(second)),
        reverse=True,
    )
    return (bright + 0.05) / (dark + 0.05)


def _close_workspace(host: JourneyWorkspaceHost) -> None:
    host.close_adapter()
    host.close()


def _focus_with_keyboard(
    host: JourneyWorkspaceHost,
    target: QQuickItem,
    app: QApplication,
    *,
    backwards: bool = False,
) -> None:
    for _ in range(40):
        if target.property("activeFocus"):
            return
        QTest.keyClick(
            host,
            Qt.Key.Key_Tab,
            (
                Qt.KeyboardModifier.ShiftModifier
                if backwards
                else Qt.KeyboardModifier.NoModifier
            ),
        )
        _settle(app)
    raise AssertionError(
        f"keyboard focus did not reach {target.property('objectName')!r}"
    )


def _rendered_evidence_identity_graph(
    host: JourneyWorkspaceHost,
    root: QObject,
    data: EvidenceAndFindingsData,
    app: QApplication,
) -> str:
    adapter = host._evidence_and_findings
    assert adapter is not None
    rendered: list[str] = []
    for candidate in data.candidates:
        candidate_id = candidate.identity.value
        adapter.selectCandidate(candidate_id)
        expected_candidate_graph = {
            candidate_id,
            *(
                record.identity.value
                for record in candidate.evidence
            ),
            *(
                comparison.identity.value
                for comparison in candidate.comparisons
            ),
            *(curve.identity for curve in candidate.curves),
            *(
                finding.identity.value
                for finding in candidate.findings
            ),
            *(
                breakpoint.identity.value
                for finding in candidate.findings
                for breakpoint in finding.sensitivity_breakpoints
            ),
        }

        def current_text() -> str:
            return "\n".join(
                (
                    _visible_text(root),
                    adapter.pinnedIdentitiesText,
                    " ".join(adapter.findingIdentities),
                    adapter.comparisonText,
                    adapter.breakpointsText,
                    adapter.provenanceText,
                    adapter.curveCatalogText,
                )
            )

        _wait_for(
            lambda: (
                adapter.selectedCandidateIdentity == candidate_id
                and all(
                    identity in current_text()
                    for identity in expected_candidate_graph
                )
            ),
            app,
            f"candidate {candidate_id} identity graph did not settle in QML",
        )
        rendered.append(current_text())
        for property_name in (
            "evidenceInitialFocusItem",
            "evidenceSecondCandidateFocusItem",
            "evidenceFindingFocusItem",
            "evidenceAlternateFindingFocusItem",
        ):
            item = root.property(property_name)
            if item is not None:
                rendered.append(
                    _accessible_text(item, QAccessible.Text.Name)
                )
    return "\n".join(rendered)


def _evidence_identity_sets(
    data: EvidenceAndFindingsData,
) -> dict[str, frozenset[str]]:
    return {
        "candidates": frozenset(
            candidate.identity.value for candidate in data.candidates
        ),
        "metrics": frozenset(
            record.identity.value
            for candidate in data.candidates
            for record in candidate.evidence
        ),
        "comparisons": frozenset(
            comparison.identity.value
            for candidate in data.candidates
            for comparison in candidate.comparisons
        ),
        "curves": frozenset(
            curve.identity
            for candidate in data.candidates
            for curve in candidate.curves
        ),
        "breakpoints": frozenset(
            breakpoint.identity.value
            for candidate in data.candidates
            for finding in candidate.findings
            for breakpoint in finding.sensitivity_breakpoints
        ),
        "findings": frozenset(
            finding.identity.value
            for candidate in data.candidates
            for finding in candidate.findings
        ),
    }


def test_file_backed_formal_campaign_reopens_and_traces_exact_ids_through_qml(
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    """The certification path is persistence -> production adapter -> QML."""

    database_path = tmp_path / "diagnostics.sqlite3"
    artifact_root = tmp_path / "artifacts"
    (
        application,
        engine,
        original_campaign,
        original_run,
        original_package,
        original_manifest,
        original_manifests,
    ) = _persist_real_formal_v1_through_application(
        database_path,
        artifact_root,
        seal_evidence=True,
        register_cleanup=request.addfinalizer,
    )
    assert original_package is not None
    assert original_manifest is not None
    pre_shutdown_payload = original_package.sealed_payload()
    sealed_manifest_references = tuple(
        pre_shutdown_payload["reproduction_manifests"]
    )
    assert original_manifests
    assert {
        str(item["reproduction_manifest_id"])
        for item in sealed_manifest_references
    } == {item.evidence_reference_id for item in original_manifests}
    pre_shutdown_artifact_hashes = {
        original_package.artifact_hash,
        str(pre_shutdown_payload["measurement_artifact_hash"]),
    }
    pre_shutdown_manifest_ids: set[str] = set()
    pre_shutdown_run_ids: set[str] = set()
    for item in original_manifests:
        specification = item.specification
        # The sealed evidence-reference identity is verified above at the
        # Application boundary. QML exposes the durable persisted manifest ID
        # in provenance and uses the sealed reference internally to join the
        # evidence graph; it must not invent a second visible manifest ID.
        pre_shutdown_manifest_ids.add(item.manifest_id)
        pre_shutdown_run_ids.add(item.run_id)
        pre_shutdown_artifact_hashes.update(
            {
                item.run_artifact_hash,
                item.evidence_artifact_hash,
                item.measurement_artifact_hash,
                item.manifest_content_hash,
                specification.materialization_hash,
                specification.recipe_content_hash,
            }
        )

    # The helper has already disposed the first engine and returned a new
    # Application/engine pair. Re-read every top-level durable identity from
    # the reopened files before any frontend object exists.
    campaign = application.diagnostic_campaign_status(original_campaign.campaign_id)
    run = application.strategy_run_status(original_run.run_id)
    package = application.diagnostic_evidence_status(
        original_package.evidence_package_id
    )
    manifests = application.reproduction_manifests(original_package.evidence_package_id)
    manifest = next(
        item for item in manifests if item.manifest_id == original_manifest.manifest_id
    )
    assert campaign == original_campaign
    assert run == original_run
    assert package == original_package
    assert manifest == original_manifest

    clock_state = [NOW]
    read_model = LiveStrategyDiagnosticsV1ApplicationAdapter(
        application,
        engine,
        clock=lambda: clock_state[0],
    )
    selector = V1JourneySelector(
        campaign_id=FormalDiagnosticCampaignId(campaign.campaign_id),
        run_id=StrategyRunId(run.run_id),
        evidence_package_id=DiagnosticEvidencePackageId(package.evidence_package_id),
        manifest_id=ReproductionManifestId(manifest.manifest_id),
    )
    resolved_result = read_model.resolve_journey(selector)
    assert resolved_result.value is not None
    journey = resolved_result.value
    bridge = EventBridge(subscribe_backend=False)
    request.addfinalizer(bridge.stop)
    executor = _DirectExecutor()
    run_feature = LiveRunMonitoringAdapter(
        application_read_model=read_model,
        event_bridge=bridge,
        journey_selector=selector,
        clock=lambda: clock_state[0],
        executor=executor,
    )
    request.addfinalizer(run_feature.close)
    evidence_feature = LiveEvidenceAndFindingsAdapter(
        application_read_model=read_model,
        event_bridge=bridge,
        journey_selector=selector,
        clock=lambda: clock_state[0],
        executor=executor,
    )
    request.addfinalizer(evidence_feature.close)
    app = _app()
    preferences = AccessibilityPreferences(
        text_scale=2.0,
        reduced_motion=True,
        high_contrast=True,
    )
    host = JourneyWorkspaceHost(
        run_feature,
        context=journey.run_context,
        evidence_feature=evidence_feature,
        evidence_context=journey.evidence_context,
        accessibility_preferences=preferences,
    )
    request.addfinalizer(lambda: _close_workspace(host))
    host.resize(1280, 720)
    host.show()
    _wait_for(
        lambda: (
            run_feature.snapshot(journey.run_context).presentation
            is RunMonitoringPresentationState.TERMINAL
            and evidence_feature.snapshot(journey.evidence_context).presentation
            is EvidenceAndFindingsPresentationState.READY
        ),
        app,
        "reopened persisted V1 journey did not become QML-ready",
    )

    run_state = run_feature.snapshot(journey.run_context)
    evidence_state = evidence_feature.snapshot(journey.evidence_context)
    run_data = run_state.last_reliable_data
    evidence_data = evidence_state.last_reliable_data
    assert run_data is not None
    assert evidence_data is not None
    selection = evidence_data.selection
    durable_top_level = {
        original_campaign.campaign_id,
        original_manifest.case_id,
        original_run.run_id,
        original_run.specification.strategy_id,
        original_run.specification.recipe_version_id,
        original_package.evidence_package_id,
        original_manifest.manifest_id,
        original_manifest.run_artifact_hash,
    } | (
        pre_shutdown_manifest_ids
        | pre_shutdown_run_ids
        | pre_shutdown_artifact_hashes
    )
    assert selection.campaign_id.value == campaign.campaign_id
    assert selection.run_id.value == run.run_id
    assert selection.strategy_id.value == run.specification.strategy_id
    assert selection.approved_recipe_id.value == (run.specification.recipe_version_id)
    assert selection.reproduction_manifest_id.value == manifest.manifest_id
    assert evidence_data.evidence_package_id.value == package.evidence_package_id
    assert run_data.terminal_outcome is TerminalOutcome.COMPLETED

    expected_candidate_ids = {
        f"{item['strategy_id']}@{item['strategy_version']}"
        for item in pre_shutdown_payload["metrics"]
    }
    expected_metric_ids = {
        str(item["metric_id"])
        for item in pre_shutdown_payload["metrics"]
    }
    expected_comparison_ids = {
        str(item["comparison_id"])
        for item in pre_shutdown_payload["comparisons"]
    }
    expected_curve_ids = {
        str(item["curve_id"])
        for item in pre_shutdown_payload["sensitivity_curves"]
    }
    expected_breakpoint_ids = {
        str(item["breakpoint_id"])
        for item in pre_shutdown_payload["sensitivity_breakpoints"]
    }
    expected_finding_ids = {
        str(item["finding_id"])
        for item in pre_shutdown_payload["diagnostic_findings"]
    }
    candidate_ids = {
        candidate.identity.value for candidate in evidence_data.candidates
    }
    metric_ids = {
        record.identity.value
        for candidate in evidence_data.candidates
        for record in candidate.evidence
    }
    comparison_ids = {
        comparison.identity.value
        for candidate in evidence_data.candidates
        for comparison in candidate.comparisons
    }
    curve_ids = {
        curve.identity
        for candidate in evidence_data.candidates
        for curve in candidate.curves
    }
    breakpoint_ids = {
        breakpoint.identity.value
        for candidate in evidence_data.candidates
        for finding in candidate.findings
        for breakpoint in finding.sensitivity_breakpoints
    }
    finding_ids = {
        finding.identity.value
        for candidate in evidence_data.candidates
        for finding in candidate.findings
    }
    assert candidate_ids == expected_candidate_ids
    assert metric_ids == expected_metric_ids
    assert comparison_ids == expected_comparison_ids
    assert curve_ids == expected_curve_ids
    assert breakpoint_ids == expected_breakpoint_ids
    assert finding_ids == expected_finding_ids
    expected_identity_sets = {
        "candidates": frozenset(expected_candidate_ids),
        "metrics": frozenset(expected_metric_ids),
        "comparisons": frozenset(expected_comparison_ids),
        "curves": frozenset(expected_curve_ids),
        "breakpoints": frozenset(expected_breakpoint_ids),
        "findings": frozenset(expected_finding_ids),
    }
    assert _evidence_identity_sets(evidence_data) == expected_identity_sets

    root = host.rootObject()
    tokens = root.findChild(QObject, "designTokens")
    assert tokens.property("textScale") == 2.0
    assert tokens.property("durationForMotion") == 0
    assert tokens.property("highContrast") is True
    surface = tokens.property("surface")
    assert _contrast_ratio(tokens.property("textPrimary"), surface) >= 4.5
    assert _contrast_ratio(tokens.property("textMuted"), surface) >= 4.5
    assert _contrast_ratio(tokens.property("focus"), surface) >= 3.0
    run_route = root.findChild(QQuickItem, "runMonitoringRouteNavigation")
    evidence_route = root.findChild(
        QQuickItem,
        "evidenceAndFindingsRouteNavigation",
    )
    run_status = root.findChild(QObject, "runMonitoringAccessibleStatus")
    assert (
        "terminal"
        in _accessible_text(
            run_status,
            QAccessible.Text.Name,
        ).casefold()
    )
    assert run_route.property("activeFocus") is True
    _focus_with_keyboard(host, evidence_route, app)
    assert evidence_route.property("activeFocus") is True
    QTest.keyClick(host, Qt.Key.Key_Return)
    _settle(app)
    assert root.property("activeRoute") == "evidence_and_findings"

    candidate_item = root.property("evidenceInitialFocusItem")
    finding_item = root.property("evidenceFindingFocusItem")
    evidence_status = root.findChild(QObject, "evidenceAccessibleStatus")
    narrative = root.findChild(QObject, "evidenceChartAccessibleNarrative")
    table = root.findChild(QObject, "evidenceChartAccessibleTable")
    assert candidate_item.property("activeFocus") is True
    assert candidate_item.property("focusVisible") is True
    initial_candidate_name = _accessible_text(
        candidate_item,
        QAccessible.Text.Name,
    )
    assert evidence_data.candidates[0].identity.value in initial_candidate_name
    assert selection.run_id.value in _visible_text(root)
    assert selection.campaign_id.value in _visible_text(root)
    assert selection.reproduction_manifest_id.value in _visible_text(root)
    if finding_item is not None:
        finding_name = _accessible_text(finding_item, QAccessible.Text.Name)
        assert evidence_data.candidates[0].findings[0].identity.value in finding_name
    narrative_name = _accessible_text(narrative, QAccessible.Text.Name)
    table_name = _accessible_text(table, QAccessible.Text.Name)
    narrative_revision = narrative_name.splitlines()[0].split()[-1]
    assert narrative_revision in table_name

    _focus_with_keyboard(host, run_route, app, backwards=True)
    assert run_route.property("activeFocus") is True
    QTest.keyClick(host, Qt.Key.Key_Return)
    _settle(app)
    assert root.property("activeRoute") == "run_monitoring"
    assert run_route.property("activeFocus") is True
    _focus_with_keyboard(host, evidence_route, app)
    QTest.keyClick(host, Qt.Key.Key_Return)
    _settle(app)
    assert root.property("activeRoute") == "evidence_and_findings"
    candidate_item = root.property("evidenceInitialFocusItem")
    assert candidate_item.property("activeFocus") is True

    expected_identity_graph = (
        durable_top_level
        | candidate_ids
        | metric_ids
        | comparison_ids
        | curve_ids
        | breakpoint_ids
        | finding_ids
    )
    rendered_graph = _rendered_evidence_identity_graph(
        host,
        root,
        evidence_data,
        app,
    )
    for identity in expected_identity_graph:
        assert identity in rendered_graph
    focused_candidate_id = evidence_data.candidates[-1].identity.value
    focused_candidate = root.property(
        (
            "evidenceSecondCandidateFocusItem"
            if len(evidence_data.candidates) > 1
            else "evidenceInitialFocusItem"
        )
    )
    assert focused_candidate is not None
    _focus_with_keyboard(host, focused_candidate, app)
    expected_focus_object_name = focused_candidate.property("objectName")
    assert focused_candidate_id in _accessible_text(
        focused_candidate,
        QAccessible.Text.Name,
    )

    accepted_run = run_state.last_reliable_data
    accepted_evidence = evidence_state.last_reliable_data
    old_generation = bridge.connection_generation
    bridge.mark_disconnected()
    _settle(app)
    disconnected_run = run_feature.snapshot(journey.run_context)
    disconnected_evidence = evidence_feature.snapshot(journey.evidence_context)
    assert disconnected_run.freshness.value == "disconnected"
    assert disconnected_evidence.freshness.value == "disconnected"
    assert disconnected_run.last_reliable_data is accepted_run
    assert disconnected_evidence.last_reliable_data is accepted_evidence
    disconnected_focus = host.quickWindow().activeFocusItem()
    assert disconnected_focus is not None
    assert (
        disconnected_focus.property("objectName")
        == expected_focus_object_name
    )
    assert disconnected_evidence.last_reliable_data is not None
    assert (
        _evidence_identity_sets(disconnected_evidence.last_reliable_data)
        == expected_identity_sets
    )
    qml_adapter = host._evidence_and_findings
    assert qml_adapter is not None
    assert set(qml_adapter.candidateIdentities) == candidate_ids
    disconnected_graph = _rendered_evidence_identity_graph(
        host,
        root,
        evidence_data,
        app,
    )
    for identity in expected_identity_graph:
        assert identity in disconnected_graph
    disconnected_evidence_announcement = " ".join(
        (
            _accessible_text(evidence_status, QAccessible.Text.Name),
            _accessible_text(
                evidence_status,
                QAccessible.Text.Description,
            ),
        )
    ).casefold()
    assert "disconnected" in disconnected_evidence_announcement
    assert (
        "disconnected"
        in _accessible_text(
            run_status,
            QAccessible.Text.Description,
        ).casefold()
    )

    connection = bridge.mark_reconnected()
    _settle(app)
    before_old = (
        run_feature.snapshot(journey.run_context).revision,
        evidence_feature.snapshot(journey.evidence_context).revision,
    )
    bridge.on_snapshot({"run_id": run.run_id}, generation=old_generation)
    bridge.flush(force=True)
    _settle(app)
    assert (
        run_feature.snapshot(journey.run_context).revision,
        evidence_feature.snapshot(journey.evidence_context).revision,
    ) == before_old
    old_generation_graph = _rendered_evidence_identity_graph(
        host,
        root,
        evidence_data,
        app,
    )
    for identity in expected_identity_graph:
        assert identity in old_generation_graph
    bridge.on_snapshot(
        {"run_id": run.run_id},
        generation=connection.generation,
    )
    bridge.flush(force=True)
    _wait_for(
        lambda: (
            run_feature.snapshot(journey.run_context).freshness.value == "fresh"
            and evidence_feature.snapshot(journey.evidence_context).freshness.value
            == "fresh"
        ),
        app,
        "reconnected journey did not accept an authoritative current generation",
    )
    recovered_run = run_feature.snapshot(journey.run_context)
    recovered_evidence = evidence_feature.snapshot(journey.evidence_context)
    assert recovered_run.last_reliable_data == accepted_run
    assert recovered_evidence.last_reliable_data == accepted_evidence
    assert recovered_run.presentation is RunMonitoringPresentationState.TERMINAL
    assert recovered_evidence.last_reliable_data is not None
    assert (
        _evidence_identity_sets(recovered_evidence.last_reliable_data)
        == expected_identity_sets
    )
    _wait_for(
        lambda: root.property("evidenceScreenState") == "ready",
        app,
        "reconnected evidence did not reach the ready QML projection",
    )
    recovered_evidence_announcement = " ".join(
        (
            _accessible_text(evidence_status, QAccessible.Text.Name),
            _accessible_text(
                evidence_status,
                QAccessible.Text.Description,
            ),
        )
    ).casefold()
    assert "ready" in recovered_evidence_announcement
    assert "fresh" in recovered_evidence_announcement
    assert (
        "fresh"
        in _accessible_text(
            run_status,
            QAccessible.Text.Description,
        ).casefold()
    )
    assert selection.run_id.value in _visible_text(root)
    assert selection.reproduction_manifest_id.value in _visible_text(root)
    recovered_focus = host.quickWindow().activeFocusItem()
    assert recovered_focus is not None
    assert recovered_focus.property("focusVisible") is True
    assert recovered_focus.property("objectName") == expected_focus_object_name
    recovered_graph = _rendered_evidence_identity_graph(
        host,
        root,
        evidence_data,
        app,
    )
    for identity in expected_identity_graph:
        assert identity in recovered_graph

    host.close_adapter()
    host.close()
    _settle(app)
    remounted = JourneyWorkspaceHost(
        run_feature,
        context=journey.run_context,
        evidence_feature=evidence_feature,
        evidence_context=journey.evidence_context,
        accessibility_preferences=preferences,
    )
    request.addfinalizer(lambda: _close_workspace(remounted))
    remounted.resize(1280, 720)
    remounted.show()
    _settle(app)
    remounted_root = remounted.rootObject()
    remounted_run_route = remounted_root.findChild(
        QQuickItem,
        "runMonitoringRouteNavigation",
    )
    assert remounted_run_route.property("activeFocus") is True
    assert selection.run_id.value in _visible_text(remounted_root)
    assert (
        "terminal"
        in _accessible_text(
            remounted_root.findChild(
                QObject,
                "runMonitoringAccessibleStatus",
            ),
            QAccessible.Text.Name,
        ).casefold()
    )
    assert run_feature.snapshot(journey.run_context).last_reliable_data == accepted_run
    assert (
        evidence_feature.snapshot(journey.evidence_context).last_reliable_data
        == accepted_evidence
    )
    assert (
        _evidence_identity_sets(
            evidence_feature.snapshot(
                journey.evidence_context
            ).last_reliable_data
        )
        == expected_identity_sets
    )
    remounted_evidence_route = remounted_root.findChild(
        QQuickItem,
        "evidenceAndFindingsRouteNavigation",
    )
    _focus_with_keyboard(
        remounted,
        remounted_evidence_route,
        app,
    )
    QTest.keyClick(remounted, Qt.Key.Key_Return)
    _settle(app)
    assert remounted_root.property("activeRoute") == "evidence_and_findings"
    remounted_initial_focus = remounted_root.property(
        "evidenceInitialFocusItem"
    )
    assert remounted_initial_focus.property("activeFocus") is True
    remounted_graph = _rendered_evidence_identity_graph(
        remounted,
        remounted_root,
        evidence_data,
        app,
    )
    for identity in expected_identity_graph:
        assert identity in remounted_graph

    remounted.close_adapter()
    remounted.close()
    run_feature.close()
    evidence_feature.close()
    bridge.stop()
    engine.dispose()
    with pytest.raises(RuntimeError, match="closed"):
        run_feature.snapshot(journey.run_context)


class _PersistedRunApplicationReadModel:
    """Typed read model whose source of truth is one real persisted V1 run."""

    def __init__(
        self,
        application,
        *,
        run_context: RunMonitoringContext,
        clock,
    ) -> None:
        self._application = application
        self._run_context = run_context
        self._clock = clock
        selection = run_context.selection
        assert selection is not None and selection.run_id is not None
        self._journey = ResolvedV1Journey(
            run_context=run_context,
            evidence_context=EvidenceAndFindingsContext.no_selection(),
            evidence_package_id=None,
            campaign_case_id=MarketScenarioId(f"standalone:{selection.run_id.value}"),
            campaign_layer=EvidenceCoverage.BASELINE,
        )

    @property
    def interface_version(self) -> ApplicationReadModelVersion:
        return APPLICATION_READ_MODEL_INTERFACE_VERSION

    def resolve_journey(
        self,
        selector: V1JourneySelector,
    ) -> ApplicationReadResult[ResolvedV1Journey]:
        selection = self._run_context.selection
        assert selection is not None
        if (
            selector.campaign_id != selection.campaign_id
            or selector.run_id != selection.run_id
        ):
            return ApplicationReadResult(
                availability=ApplicationReadAvailability.NOT_FOUND,
                source_token=None,
                source_observed_at=self._clock(),
                value=None,
                error=ApplicationReadError(
                    code=ApplicationReadErrorCode.SELECTION_NOT_FOUND,
                    message="The persisted Strategy Run is not selected.",
                    retryable=False,
                ),
            )
        return ApplicationReadResult(
            availability=ApplicationReadAvailability.READY,
            source_token=SourceRevisionToken(
                hashlib.sha256(f"journey:{selection.run_id.value}".encode()).hexdigest()
            ),
            source_observed_at=self._clock(),
            value=self._journey,
            error=None,
        )

    def read_run(
        self,
        journey: ResolvedV1Journey,
    ) -> ApplicationReadResult[RunMonitoringData]:
        if journey != self._journey:
            raise ValueError("persisted run journey mismatch")
        selection = self._run_context.selection
        assert selection is not None and selection.run_id is not None
        snapshot = self._application.strategy_run_status(selection.run_id.value)
        current = snapshot.current_simulation_time
        assert current is not None
        lifecycle = {
            "running": RunLifecyclePhase.RUNNING,
            "paused": RunLifecyclePhase.PAUSED,
            "completed": RunLifecyclePhase.COMPLETED,
            "failed": RunLifecyclePhase.FAILED,
            "cancelled": RunLifecyclePhase.CANCELED,
        }[snapshot.status]
        terminal = {
            "completed": TerminalOutcome.COMPLETED,
            "failed": TerminalOutcome.FAILED,
            "cancelled": TerminalOutcome.CANCELED,
        }.get(snapshot.status)
        assumptions = ()
        resolved_conditions = snapshot.specification.resolved_execution_conditions
        if resolved_conditions is not None:
            assumptions = tuple(
                ExecutionAssumption(
                    name=item.name,
                    requested_value=item.requested_value,
                    effective_value=item.effective_value,
                    override_reason=item.override_reason,
                )
                for item in resolved_conditions.resolutions
            )
        data = RunMonitoringData(
            selection=selection,
            strategy_id=StrategyUnderTestId(snapshot.specification.strategy_id),
            market_scenario_id=self._journey.campaign_case_id,
            scenario_set_id=ScenarioSetId(
                f"standalone:{snapshot.specification.recipe_version_id}"
            ),
            reproduction_manifest_id=None,
            task_id=None,
            lifecycle=lifecycle,
            terminal_outcome=terminal,
            progress=RunProgress(
                current_node_id=(f"{snapshot.run_id}:{snapshot.processed_node_count}"),
                current_node_label=(
                    f"persisted run · {snapshot.processed_node_count}/"
                    f"{snapshot.total_node_count}"
                ),
                completed=snapshot.processed_node_count,
                total=snapshot.total_node_count,
            ),
            simulation_time=SimulationTime(
                sim_day=len(
                    {
                        point.simulation_time.date()
                        for point in snapshot.equity_curve
                        if point.simulation_time <= current
                    }
                ),
                instant=(
                    current
                    if current.tzinfo is not None
                    else current.replace(tzinfo=UTC)
                ),
            ),
            wall_time=WallTime(
                started_at=None,
                observed_at=self._clock(),
                elapsed=timedelta(0),
            ),
            execution_assumptions=assumptions,
            alerts=(),
            context=ReadOnlyDiagnosticContext(
                market=(
                    f"materialization {snapshot.specification.materialization_hash}",
                ),
                account=(f"cash {snapshot.cash}",),
                positions=tuple(
                    f"{item.instrument} · {item.shares} shares"
                    for item in snapshot.positions
                ),
                orders=tuple(
                    f"{item.order_id} · {item.status}" for item in snapshot.orders
                ),
                fills=tuple(
                    f"{item.fill_id} · {item.shares} @ {item.price}"
                    for item in snapshot.fills
                ),
            ),
            capabilities=DiagnosticTaskCapabilities(False, False, False),
            active_task=None,
        )
        return ApplicationReadResult(
            availability=ApplicationReadAvailability.PARTIAL,
            source_token=SourceRevisionToken(
                hashlib.sha256(repr(snapshot).encode("utf-8")).hexdigest()
            ),
            source_observed_at=self._clock(),
            value=data,
            error=ApplicationReadError(
                code=ApplicationReadErrorCode.EVIDENCE_PENDING,
                message=(
                    "The independent persisted run has no sealed Formal "
                    "Campaign evidence."
                ),
                retryable=True,
            ),
        )

    def read_evidence(
        self,
        journey: ResolvedV1Journey,
    ) -> ApplicationReadResult[EvidenceAndFindingsData]:
        if journey != self._journey:
            raise ValueError("persisted run journey mismatch")
        return ApplicationReadResult(
            availability=ApplicationReadAvailability.PENDING,
            source_token=None,
            source_observed_at=self._clock(),
            value=None,
            error=ApplicationReadError(
                code=ApplicationReadErrorCode.EVIDENCE_PENDING,
                message="Formal Campaign evidence is not part of this scenario.",
                retryable=True,
            ),
        )


def _start_independent_persisted_run(
    database_path: Path,
    artifact_root: Path,
    *,
    register_cleanup: Callable[[Callable[[], None]], None],
):
    engine = create_engine(f"sqlite:///{database_path}", future=True)
    register_cleanup(engine.dispose)
    source = _MarketStructureWorkspaceSource()
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=ParquetMarketPathArtifactStore(
            artifact_root / "market-paths"
        ),
        evidence_artifact_store=JsonDiagnosticEvidenceArtifactStore(artifact_root),
        recipe_clock=lambda: NOW,
    )
    application.start()
    application.initialize_persistence(engine)
    panel = DiagnosticsPanel(application)
    admitted = panel.admit_historical_segment(
        market="mainland-a-share",
        start_date="2024-01-02",
        end_date="2024-01-02",
    )
    panel.create_baseline_recipe(
        name="Independent persisted run",
        segment_id=str(admitted["segment"]["segment_id"]),
        author="researcher",
        cadence_minutes=30,
        seed=29,
        commission_bps="3",
        slippage_bps="5",
    )
    assert panel.validate_current_recipe()["is_valid"] is True
    approved = panel.approve_current_recipe(actor="owner")
    materialized = panel.materialize_current_recipe()
    started = application.start_baseline_strategy_run(
        str(approved["version_id"]),
        str(materialized["artifact_hash"]),
        initial_cash=Decimal(100000),
        order_shares=1000,
        replica_id="issue-52-independent-persisted-run",
        strategy_id=QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
        strategy_version=QUENTX_SCENARIO_NATIVE_STRATEGY_VERSION,
    )
    running = application.advance_strategy_run(started.run_id)
    assert running.status == "running"
    assert running.current_simulation_time is not None
    return application, engine, running


def test_real_persisted_run_advances_running_to_completed_at_feature_seam(
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    application, engine, running = _start_independent_persisted_run(
        tmp_path / "run.sqlite3",
        tmp_path / "run-artifacts",
        register_cleanup=request.addfinalizer,
    )
    clock_state = [datetime(2030, 3, 1, 12, 0, tzinfo=UTC)]
    run_context = RunMonitoringContext.for_run(
        RunMonitoringSelection(
            campaign_id=FormalDiagnosticCampaignId(
                f"standalone:{running.specification.recipe_version_id}"
            ),
            run_id=StrategyRunId(running.run_id),
        )
    )
    read_model = _PersistedRunApplicationReadModel(
        application,
        run_context=run_context,
        clock=lambda: clock_state[0],
    )
    selection = run_context.selection
    assert selection is not None and selection.run_id is not None
    resolved = read_model.resolve_journey(
        V1JourneySelector(
            campaign_id=selection.campaign_id,
            run_id=selection.run_id,
        )
    )
    assert resolved.value is not None
    assert read_model.read_run(resolved.value).value is not None
    bridge = EventBridge(subscribe_backend=False)
    request.addfinalizer(bridge.stop)
    feature = LiveRunMonitoringAdapter(
        application_read_model=read_model,
        event_bridge=bridge,
        clock=lambda: clock_state[0],
        executor=_DirectExecutor(),
    )
    request.addfinalizer(feature.close)
    initial = feature.snapshot(run_context)
    assert initial.presentation is RunMonitoringPresentationState.ACTIVE
    assert initial.last_reliable_data is not None
    assert initial.last_reliable_data.lifecycle is RunLifecyclePhase.RUNNING
    app = _app()
    host = JourneyWorkspaceHost(feature, context=run_context)
    request.addfinalizer(lambda: _close_workspace(host))
    host.resize(1280, 720)
    host.show()
    _settle(app)
    root = host.rootObject()
    assert running.run_id in _visible_text(root)

    completed = application.complete_strategy_run(running.run_id)
    assert completed.status == "completed"
    clock_state[0] += timedelta(seconds=1)
    bridge.on_snapshot(
        {"run_id": running.run_id},
        generation=bridge.connection_generation,
    )
    bridge.flush(force=True)
    _wait_for(
        lambda: (
            feature.snapshot(run_context).presentation
            is RunMonitoringPresentationState.TERMINAL
        ),
        app,
        "public Application completion did not reach Run Monitoring",
    )
    terminal = feature.snapshot(run_context)
    assert terminal.last_reliable_data is not None
    assert terminal.last_reliable_data.selection.run_id.value == running.run_id
    assert terminal.last_reliable_data.terminal_outcome is (TerminalOutcome.COMPLETED)
    assert terminal.last_reliable_data.progress.completed == (
        terminal.last_reliable_data.progress.total
    )
    assert (
        "terminal"
        in _accessible_text(
            root.findChild(QObject, "runMonitoringAccessibleStatus"),
            QAccessible.Text.Name,
        ).casefold()
    )
    assert running.run_id in _visible_text(root)

    host.close_adapter()
    host.close()
    feature.close()
    bridge.stop()
    engine.dispose()
