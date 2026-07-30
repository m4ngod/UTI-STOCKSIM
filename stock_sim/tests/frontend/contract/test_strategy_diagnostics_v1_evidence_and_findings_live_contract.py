from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from time import monotonic, sleep

import pytest
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication
from sqlalchemy import create_engine, text

from app.event_bridge import EventBridge
from app.features import (
    DiagnosticEvidencePackageId,
    EvidenceAndFindingsPresentationState,
    FormalDiagnosticCampaignId,
    LiveEvidenceAndFindingsAdapter,
    LiveRunMonitoringAdapter,
    LiveStrategyDiagnosticsV1ApplicationAdapter,
    ReproductionManifestId,
    StrategyRunId,
    V1JourneySelector,
)
from app.panels.diagnostics.panel import DiagnosticsPanel
from app.ui.main_window import MainWindow
from strategy_diagnostics import create_diagnostics_application
from strategy_diagnostics.diagnostic_evidence_storage import (
    JsonDiagnosticEvidenceArtifactStore,
)
from strategy_diagnostics.market_paths import ParquetMarketPathArtifactStore
from tests.frontend.contract.test_strategy_diagnostics_v1_application_read_model_live_contract import (
    NOW,
)
from tests.frontend.unit.test_diagnostics_panel import (
    _MarketStructureWorkspaceSource,
)


def _persist_real_formal_v1_through_application(
    database_path: Path,
    artifact_root: Path,
    *,
    seal_evidence: bool,
    register_cleanup: Callable[[Callable[[], None]], None],
):
    engine = create_engine(f"sqlite:///{database_path}", future=True)
    register_cleanup(engine.dispose)
    source = _MarketStructureWorkspaceSource()
    paths = ParquetMarketPathArtifactStore(artifact_root / "market-paths")
    evidence_store = JsonDiagnosticEvidenceArtifactStore(artifact_root)
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=paths,
        evidence_artifact_store=evidence_store,
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
    common = {
        "segment_id": str(admitted["segment"]["segment_id"]),
        "author": "researcher",
        "cadence_minutes": 30,
        "seed": 17,
        "commission_bps": "3",
        "slippage_bps": "5",
    }

    panel.create_baseline_recipe(name="Live evidence baseline", **common)
    panel.validate_current_recipe()
    panel.approve_current_recipe(actor="owner")
    panel.materialize_current_recipe()
    panel.run_baseline_campaign(
        initial_cash="100000",
        order_shares=1000,
        campaign_replica_id="live-evidence-baseline",
    )

    def approve_materialize_and_stage() -> None:
        validation = panel.validate_current_recipe()
        assert validation["is_valid"] is True
        panel.approve_current_recipe(actor="owner")
        panel.materialize_current_recipe()
        panel.stage_current_materialization_as_sensitivity_case()

    for level, strength in enumerate(("0.10", "0.20"), start=1):
        panel.create_trend_regime_recipe(
            name=f"Live trend level {level}",
            direction="bullish",
            strength=strength,
            **common,
        )
        approve_materialize_and_stage()
    for level, multiplier in enumerate(("0.75", "1.25"), start=1):
        panel.create_volatility_recipe(
            name=f"Live volatility level {level}",
            multiplier=multiplier,
            **common,
        )
        approve_materialize_and_stage()
    for level, shock_fraction in enumerate(("0.02", "0.04"), start=1):
        panel.create_shock_recovery_recipe(
            name=f"Live shock level {level}",
            direction="bearish",
            gap_fraction="0.01",
            shock_fraction=shock_fraction,
            shock_duration_bars=1,
            persistence_duration_bars=0,
            recovery_duration_bars=1,
            **common,
        )
        approve_materialize_and_stage()
    for level, breadth in enumerate(("0.25", "0.75"), start=1):
        panel.create_market_structure_recipe(
            name=f"Live structure level {level}",
            breadth_target=breadth,
            dispersion_fraction="0.02",
            sector_concentration="0.75",
            **common,
        )
        approve_materialize_and_stage()
    for level, multiplier in enumerate(("0.50", "1.50"), start=1):
        panel.create_liquidity_recipe(
            name=f"Live liquidity level {level}",
            volume_multiplier=multiplier,
            cross_sectional_concentration="0.50",
            **common,
        )
        approve_materialize_and_stage()
    for level, slippage in enumerate(("25", "100"), start=1):
        panel.create_execution_stress_recipe(
            name=f"Live execution level {level}",
            override_commission_bps="8",
            override_slippage_bps=slippage,
            override_max_fill_fraction="1",
            override_latency_nodes=0,
            override_allow_partial_fills=True,
            rejection_mode="none",
            **common,
        )
        approve_materialize_and_stage()

    panel.plan_isolated_sensitivity_set(
        initial_cash="100000",
        order_shares=1000,
        sensitivity_set_replica_id="live-evidence-isolated",
    )
    panel.create_compound_recipe(
        name="Live evidence compound",
        transformations=(
            {
                "transformation_id": "trend-regime.v1",
                "parameters": {
                    "direction": "bearish",
                    "strength": "0.20",
                },
            },
            {
                "transformation_id": "volatility-scaling.v1",
                "parameters": {"multiplier": "1.25"},
            },
        ),
        **common,
    )
    panel.validate_current_recipe()
    panel.approve_current_recipe(actor="owner")
    panel.materialize_current_recipe()
    panel.stage_current_materialization_as_compound_case()
    planned = panel.plan_diagnostic_campaign(
        initial_cash="100000",
        order_shares=1000,
        campaign_replica_id="live-evidence-formal",
    )
    assert planned["campaign_type"] == "formal_diagnostic_campaign"
    completed = panel.resume_diagnostic_campaign()
    assert completed["status"] == "completed"

    campaign = application.diagnostic_campaign_status(
        str(completed["campaign_id"])
    )
    package = (
        application.build_diagnostic_evidence(campaign.campaign_id)
        if seal_evidence
        else None
    )
    manifests = (
        tuple(
            application.reproduction_manifests(
                package.evidence_package_id
            )
        )
        if package is not None
        else ()
    )
    manifest = manifests[0] if manifests else None
    if manifest is not None:
        selected_run = application.strategy_run_status(manifest.run_id)
    else:
        first_campaign = next(
            attempt.campaign
            for case in campaign.cases
            for attempt in reversed(case.attempts)
            if attempt.campaign is not None
        )
        assert first_campaign is not None
        members = first_campaign.to_dict()["members"]
        assert isinstance(members, list)
        assert members
        selected_member = members[0]
        assert isinstance(selected_member, dict)
        selected_run = application.strategy_run_status(
            str(selected_member["run_id"])
        )
    engine.dispose()

    reopened_engine = create_engine(
        f"sqlite:///{database_path}",
        future=True,
    )
    register_cleanup(reopened_engine.dispose)
    reopened_paths = ParquetMarketPathArtifactStore(
        artifact_root / "market-paths"
    )
    assert (
        reopened_paths.get(
            selected_run.specification.materialization_hash
        ).artifact_hash
        == selected_run.specification.materialization_hash
    )
    reopened = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=reopened_paths,
        evidence_artifact_store=JsonDiagnosticEvidenceArtifactStore(
            artifact_root
        ),
        recipe_clock=lambda: NOW,
    )
    reopened.start()
    migration = reopened.initialize_persistence(reopened_engine)
    assert migration.current_revision == "0012_reproduction_manifests"
    return (
        reopened,
        reopened_engine,
        campaign,
        selected_run,
        package,
        manifest,
        manifests,
    )


def test_real_sealed_v1_evidence_is_visible_in_production_qml(
    tmp_path,
    request: pytest.FixtureRequest,
) -> None:
    (
        application,
        engine,
        campaign,
        selected_run,
        package,
        manifest,
        _manifests,
    ) = _persist_real_formal_v1_through_application(
        tmp_path / "diagnostics.sqlite3",
        tmp_path / "artifacts",
        seal_evidence=True,
        register_cleanup=request.addfinalizer,
    )
    assert package is not None
    assert manifest is not None
    clock_state = [NOW]
    read_model = LiveStrategyDiagnosticsV1ApplicationAdapter(
        application,
        engine,
        clock=lambda: clock_state[0],
    )
    selector = V1JourneySelector(
        campaign_id=FormalDiagnosticCampaignId(campaign.campaign_id),
        run_id=StrategyRunId(selected_run.run_id),
        evidence_package_id=DiagnosticEvidencePackageId(
            package.evidence_package_id
        ),
        manifest_id=ReproductionManifestId(manifest.manifest_id),
    )
    resolved = read_model.resolve_journey(selector)
    assert resolved.value is not None

    bridge = EventBridge(subscribe_backend=False)
    run_feature = LiveRunMonitoringAdapter(
        application_read_model=read_model,
        event_bridge=bridge,
        journey_selector=selector,
        clock=lambda: clock_state[0],
    )
    evidence_feature = LiveEvidenceAndFindingsAdapter(
        application_read_model=read_model,
        event_bridge=bridge,
        journey_selector=selector,
        clock=lambda: clock_state[0],
    )
    app = QApplication.instance() or QApplication([])
    window = MainWindow(
        run_monitoring_feature=run_feature,
        run_monitoring_context=resolved.value.run_context,
        evidence_and_findings_feature=evidence_feature,
        evidence_and_findings_context=resolved.value.evidence_context,
        frontend_v2_enabled=True,
    )
    root = window.centralWidget().rootObject()
    root.setProperty("activeRoute", "evidence_and_findings")

    deadline = monotonic() + 5
    while monotonic() < deadline:
        app.processEvents()
        state = evidence_feature.snapshot(resolved.value.evidence_context)
        if (
            state.presentation
            is EvidenceAndFindingsPresentationState.READY
            and state.last_reliable_data is not None
        ):
            break
        sleep(0.01)
    else:
        raise AssertionError("real V1 evidence did not become QML-ready")

    data = state.last_reliable_data
    assert data is not None
    assert data.selection == resolved.value.evidence_context.selection
    assert data.evidence_package_id == selector.evidence_package_id
    assert data.selection.campaign_id.value == campaign.campaign_id
    assert data.selection.run_id.value == selected_run.run_id
    assert (
        data.selection.strategy_id.value
        == selected_run.specification.strategy_id
    )
    assert data.selection.market_scenario_id == resolved.value.campaign_case_id
    assert (
        data.selection.approved_recipe_id.value
        == selected_run.specification.recipe_version_id
    )
    assert data.selection.reproduction_manifest_id == selector.manifest_id

    sealed = package.sealed_payload()
    records_by_id = {
        record.identity.value: record
        for candidate in data.candidates
        for record in candidate.evidence
    }
    metric_ids = {
        record.identity.value
        for candidate in data.candidates
        for record in candidate.evidence
    }
    assert {
        record.dimension.value
        for candidate in data.candidates
        for record in candidate.evidence
    }.issuperset(
        {"return", "risk", "execution", "exposure", "stability"}
    )
    comparison_ids = {
        comparison.identity.value
        for candidate in data.candidates
        for comparison in candidate.comparisons
    }
    finding_ids = {
        finding.identity.value
        for candidate in data.candidates
        for finding in candidate.findings
    }
    curve_ids = {
        curve.identity
        for candidate in data.candidates
        for curve in candidate.curves
    }
    assert metric_ids == {item["metric_id"] for item in sealed["metrics"]}
    coverage_by_layer = {
        "baseline": "baseline",
        "isolated_sensitivity": "isolated_sensitivity",
        "compound": "compound_scenario",
    }
    for metric in sealed["metrics"]:
        mapped = records_by_id[metric["metric_id"]]
        assert mapped.value == str(metric["value"])
        assert mapped.coverage.value == coverage_by_layer[metric["layer"]]
        assert mapped.unit
        assert metric["run_id"] in mapped.interpretation

    comparisons_by_id = {
        comparison.identity.value: comparison
        for candidate in data.candidates
        for comparison in candidate.comparisons
    }
    assert comparison_ids == {
        item["comparison_id"] for item in sealed["comparisons"]
    }
    metric_edge_counts = {metric_id: 0 for metric_id in metric_ids}
    for comparison in sealed["comparisons"]:
        mapped = comparisons_by_id[comparison["comparison_id"]]
        assert (
            mapped.reference_evidence_id.value
            == comparison["control_metric_id"]
        )
        assert (
            mapped.observed_evidence_id.value
            == comparison["subject_metric_id"]
        )
        assert str(comparison["delta"]) in mapped.interpretation
        metric_edge_counts[comparison["control_metric_id"]] += 1
        metric_edge_counts[comparison["subject_metric_id"]] += 1
    assert max(metric_edge_counts.values()) > 1

    breakpoints_by_id = {
        breakpoint.identity.value: breakpoint
        for candidate in data.candidates
        for finding in candidate.findings
        for breakpoint in finding.sensitivity_breakpoints
    }
    assert set(breakpoints_by_id) == {
        item["breakpoint_id"]
        for item in sealed["sensitivity_breakpoints"]
    }
    for breakpoint in sealed["sensitivity_breakpoints"]:
        mapped = breakpoints_by_id[breakpoint["breakpoint_id"]]
        assert {
            item.value for item in mapped.evidence_ids
        } == set(breakpoint["metric_ids"])
        assert mapped.threshold == (
            f"{breakpoint['threshold']['operator']} "
            f"{breakpoint['threshold']['value']}"
        )

    findings_by_id = {
        finding.identity.value: finding
        for candidate in data.candidates
        for finding in candidate.findings
    }
    assert finding_ids == {
        item["finding_id"] for item in sealed["diagnostic_findings"]
    }
    for finding in sealed["diagnostic_findings"]:
        mapped = findings_by_id[finding["finding_id"]]
        assert mapped.title == finding["statement"]
        assert {
            item.value for item in mapped.evidence_ids
        } == set(finding["metric_ids"])
        assert {
            item.value for item in mapped.comparison_ids
        } == set(finding["comparison_ids"])
        assert {
            item.identity.value
            for item in mapped.sensitivity_breakpoints
        } == set(finding["breakpoint_ids"])

    curves_by_id = {
        curve.identity: curve
        for candidate in data.candidates
        for curve in candidate.curves
    }
    assert curve_ids == {
        item["curve_id"] for item in sealed["sensitivity_curves"]
    }
    for curve in sealed["sensitivity_curves"]:
        mapped = curves_by_id[curve["curve_id"]]
        assert mapped.metric_name == curve["metric_name"]
        assert mapped.strategy_id.value == curve["strategy_id"]
        assert mapped.strategy_version == curve["strategy_version"]
        assert [
            (
                point.case_id.value,
                point.run_id.value,
                point.evidence_id.value,
                point.value,
                point.reproduction_manifest_id.value,
            )
            for point in mapped.points
        ] == [
            (
                point["case_id"],
                point["run_id"],
                point["metric_id"],
                str(point["value"]),
                point["reproduction_manifest_id"],
            )
            for point in curve["points"]
        ]

    uncharted_curve_ids = {
        item["curve_id"] for item in sealed["sensitivity_curves"]
    } - {
        item["curve_id"] for item in sealed["sensitivity_breakpoints"]
    }
    assert uncharted_curve_ids
    assert all(
        curves_by_id[identity].chart is None
        and all(
            point.evidence_id.value in records_by_id
            for point in curves_by_id[identity].points
        )
        for identity in uncharted_curve_ids
    )

    qt_adapter = window.centralWidget()._evidence_and_findings
    assert package.evidence_package_id in qt_adapter.pinnedIdentitiesText
    assert manifest.manifest_id in qt_adapter.pinnedIdentitiesText
    assert comparison_ids
    qml_comparison_ids = set()
    qml_breakpoint_ids = set()
    qml_assumptions = []
    qml_provenance = []
    for candidate in data.candidates:
        qt_adapter.selectCandidate(candidate.identity.value)
        app.processEvents()
        qml_comparison_ids.update(
            comparison_ids.intersection(qt_adapter.comparisonText.split())
        )
        qml_breakpoint_ids.update(
            set(breakpoints_by_id).intersection(
                qt_adapter.breakpointsText.split()
            )
        )
        qml_assumptions.append(qt_adapter.assumptionsText)
        qml_provenance.append(qt_adapter.provenanceText)
    assert qml_comparison_ids == comparison_ids
    assert qml_breakpoint_ids == set(breakpoints_by_id)
    assert all("requested " in value and "effective " in value for value in qml_assumptions)
    assert all("reproduction-manifest" in value for value in qml_provenance)
    assert curve_ids
    curve_catalog_text = qt_adapter.curveCatalogText
    for candidate in data.candidates:
        for curve in candidate.curves:
            for expected in (
                curve.identity,
                curve.transformation_family,
                curve.transformation_id,
                curve.strategy_id.value,
                curve.strategy_version,
                curve.metric_name,
                curve.unit,
            ):
                assert expected in curve_catalog_text
            if curve.axis is not None:
                for expected in (
                    curve.axis.parameter_name,
                    curve.axis.value_type,
                    curve.axis.order,
                ):
                    assert expected in curve_catalog_text
            for point in curve.points:
                for expected in (
                    point.case_id.value,
                    point.run_id.value,
                    point.evidence_id.value,
                    point.value,
                    point.run_artifact_hash,
                    point.reproduction_manifest_id.value,
                ):
                    assert expected in curve_catalog_text
                for parameter_name, parameter_value in point.parameters:
                    assert parameter_name in curve_catalog_text
                    assert parameter_value in curve_catalog_text
    curve_catalog = root.findChild(QObject, "evidenceCurveCatalog")
    assert curve_catalog is not None
    assert curve_catalog.property("text") == qt_adapter.curveCatalogText
    assert {
        item.order_id for item in selected_run.orders
    }.issubset(set(qt_adapter.readOnlyContextText.split()))
    assert {
        item.fill_id for item in selected_run.fills
    }.issubset(set(qt_adapter.readOnlyContextText.split()))
    assert "Quick Experiment — exploratory only" in qt_adapter.coverageText
    assert "composite score" not in qt_adapter.curveCatalogText.casefold()

    accepted_data = state.last_reliable_data
    accepted_revision = state.revision
    clock_state[0] = NOW + timedelta(seconds=6)
    stale = evidence_feature.snapshot(resolved.value.evidence_context)
    assert stale.revision == accepted_revision + 1
    assert stale.freshness.value == "stale"
    assert stale.last_reliable_data is accepted_data

    bridge.mark_disconnected()
    disconnected = evidence_feature.snapshot(resolved.value.evidence_context)
    assert disconnected.freshness.value == "disconnected"
    assert disconnected.last_reliable_data is accepted_data

    connection = bridge.mark_reconnected()
    awaiting = evidence_feature.snapshot(resolved.value.evidence_context)
    assert awaiting.freshness.value == "stale"
    assert awaiting.last_reliable_data is accepted_data

    bridge.on_snapshot(
        {"run_id": selected_run.run_id},
        generation=connection.generation,
    )
    bridge.flush(force=True)
    deadline = monotonic() + 5
    while monotonic() < deadline:
        app.processEvents()
        recovered = evidence_feature.snapshot(
            resolved.value.evidence_context
        )
        if recovered.freshness.value == "fresh":
            break
        sleep(0.01)
    else:
        raise AssertionError("real V1 evidence did not recover after reconnect")
    assert recovered.last_reliable_data == accepted_data
    assert (
        recovered.last_reliable_data.evidence_package_id
        == selector.evidence_package_id
    )

    with engine.begin() as connection_handle:
        connection_handle.execute(
            text(
                "UPDATE diagnostic_reproduction_manifests "
                "SET manifest_content_hash = :changed "
                "WHERE manifest_id = :manifest_id"
            ),
            {"changed": "0" * 64, "manifest_id": manifest.manifest_id},
        )
    bridge.on_snapshot(
        {"run_id": selected_run.run_id},
        generation=connection.generation,
    )
    bridge.flush(force=True)
    deadline = monotonic() + 5
    while monotonic() < deadline:
        app.processEvents()
        integrity_failed = evidence_feature.snapshot(
            resolved.value.evidence_context
        )
        if (
            integrity_failed.error is not None
            and not integrity_failed.error.retryable
        ):
            break
        sleep(0.01)
    else:
        raise AssertionError("real V1 integrity failure was not published")
    assert integrity_failed.presentation.value == "failed"
    assert integrity_failed.last_reliable_data is None
    assert integrity_failed.error is not None
    assert (
        integrity_failed.error.code
        == "strategy_diagnostics_integrity_failed"
    )
    deadline = monotonic() + 2
    while (
        monotonic() < deadline
        and root.property("evidenceScreenState") != "failed"
    ):
        app.processEvents()
        sleep(0.01)
    assert root.property("evidenceScreenState") == "failed"

    window.close()
    run_feature.close()
    evidence_feature.close()
    bridge.stop()
    engine.dispose()


def test_real_v1_run_without_sealed_evidence_stays_honestly_pending_in_qml(
    tmp_path,
    request: pytest.FixtureRequest,
) -> None:
    (
        application,
        engine,
        campaign,
        selected_run,
        _package,
        _manifest,
        _manifests,
    ) = _persist_real_formal_v1_through_application(
        tmp_path / "diagnostics-pending.sqlite3",
        tmp_path / "artifacts-pending",
        seal_evidence=False,
        register_cleanup=request.addfinalizer,
    )

    read_model = LiveStrategyDiagnosticsV1ApplicationAdapter(
        application,
        engine,
        clock=lambda: NOW,
    )
    selector = V1JourneySelector(
        campaign_id=FormalDiagnosticCampaignId(campaign.campaign_id),
        run_id=StrategyRunId(selected_run.run_id),
    )
    resolved = read_model.resolve_journey(selector)
    assert resolved.value is not None

    bridge = EventBridge(subscribe_backend=False)
    evidence_feature = LiveEvidenceAndFindingsAdapter(
        application_read_model=read_model,
        event_bridge=bridge,
        journey_selector=selector,
        clock=lambda: NOW,
    )
    run_feature = LiveRunMonitoringAdapter(
        application_read_model=read_model,
        event_bridge=bridge,
        journey_selector=selector,
        clock=lambda: NOW,
    )
    app = QApplication.instance() or QApplication([])
    window = MainWindow(
        run_monitoring_feature=run_feature,
        run_monitoring_context=resolved.value.run_context,
        evidence_and_findings_feature=evidence_feature,
        evidence_and_findings_context=resolved.value.evidence_context,
        frontend_v2_enabled=True,
    )
    root = window.centralWidget().rootObject()
    root.setProperty("activeRoute", "evidence_and_findings")

    deadline = monotonic() + 5
    while monotonic() < deadline:
        app.processEvents()
        pending = evidence_feature.snapshot(
            resolved.value.evidence_context
        )
        if (
            pending.error is not None
            and pending.error.code == "diagnostic_evidence_pending"
        ):
            break
        sleep(0.01)
    else:
        raise AssertionError("real V1 pending evidence was not published")
    assert pending.presentation.value == "loading"
    assert pending.last_reliable_data is None
    assert pending.error is not None
    assert pending.error.retryable
    assert root.property("evidenceScreenState") == "loading"

    window.close()
    run_feature.close()
    evidence_feature.close()
    bridge.stop()
    engine.dispose()
