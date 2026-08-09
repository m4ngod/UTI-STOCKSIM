from __future__ import annotations

import json
from dataclasses import fields

import pytest

from app.features.diagnostic_tasks_application import (
    ApprovedScenarioRecipeVersionId,
    DiagnosticTaskConfigurationContentId,
)
from app.features.evidence_and_findings import (
    DiagnosticEvidencePackageId,
    EvidenceComparisonId,
    EvidenceRecordId,
    FindingId,
    SensitivityBreakpointId,
)
from app.features.run_monitoring import (
    DiagnosticTaskId,
    FormalDiagnosticCampaignId,
    ReproductionManifestId,
    ScenarioSetId,
    SourceGenerationId,
    StrategyRunId,
    StrategyUnderTestId,
    TaskHandleId,
)
from app.features.scenario_lab import ScenarioLabFocusTarget
from app.features.scenario_lab_application import (
    ReferenceMarketPathId,
    ScenarioRecipeDraftId,
)
from app.journey_recovery import (
    JOURNEY_CONTEXT_VERSION,
    JOURNEY_DESTINATIONS,
    JourneyContext,
    JourneyApprovedRecipeReference,
    JourneyDiagnosticSelection,
    JourneyEvidenceSelection,
    JourneyFocusReturnToken,
    JourneyPresentationSelection,
    JourneyRecoveryReason,
    JourneyRecipeDraftReference,
    JourneyScenarioSelection,
    JourneySourceIdentity,
    JourneyStrategyReference,
    JourneyStrategySelection,
    JourneyViewMode,
    JourneyWorkspaceBookmark,
    JourneyWorkspaceRoute,
    encode_journey_workspace_bookmark,
    restore_journey_workspace_bookmark,
)
from app.app_context import build_app_context


def _complete_bookmark() -> JourneyWorkspaceBookmark:
    return JourneyWorkspaceBookmark(
        last_route=JourneyWorkspaceRoute.SYSTEM_HEALTH,
        diagnostic_task_id=DiagnosticTaskId("diagnostic-task-113"),
        scenario_focus_target=ScenarioLabFocusTarget.MARKET_SCENARIO,
        scenario_focus_identity="market-scenario-113",
        strategy_selection=JourneyStrategySelection(
            strategy_under_test=JourneyStrategyReference(
                StrategyUnderTestId("strategy-primary-113"), "7.2"
            ),
            comparison_strategies=(
                JourneyStrategyReference(
                    StrategyUnderTestId("strategy-comparison-113"), "6.4"
                ),
            ),
        ),
        scenario_selection=JourneyScenarioSelection(
            reference_market_path_ids=(
                ReferenceMarketPathId("reference-path-113"),
            ),
            recipe_drafts=(
                JourneyRecipeDraftReference(
                    ScenarioRecipeDraftId("recipe-draft-113"),
                    4,
                ),
            ),
            approved_recipe_versions=(
                JourneyApprovedRecipeReference(
                    ApprovedScenarioRecipeVersionId(
                        "approved-recipe-version-113"
                    ),
                    5,
                ),
            ),
            materialized_scenario_set_id=ScenarioSetId("scenario-set-113"),
        ),
        diagnostic_selection=JourneyDiagnosticSelection(
            task_id=DiagnosticTaskId("diagnostic-task-113"),
            task_revision=9,
            configuration_content_id=DiagnosticTaskConfigurationContentId(
                "configuration-content-113"
            ),
            task_handle_id=TaskHandleId("task-handle-113"),
            campaign_id=FormalDiagnosticCampaignId("campaign-113"),
            campaign_revision=3,
            run_id=StrategyRunId("run-113"),
        ),
        evidence_selection=JourneyEvidenceSelection(
            evidence_package_id=DiagnosticEvidencePackageId(
                "evidence-package-113"
            ),
            evidence_id=EvidenceRecordId("evidence-113"),
            comparison_id=EvidenceComparisonId("comparison-113"),
            finding_id=FindingId("finding-113"),
            sensitivity_breakpoint_id=SensitivityBreakpointId(
                "breakpoint-113"
            ),
            reproduction_manifest_id=ReproductionManifestId("manifest-113"),
        ),
        presentation=JourneyPresentationSelection(
            selected_identity="finding-113",
            view_mode=JourneyViewMode.FINDINGS,
            focus_return_token=JourneyFocusReturnToken(
                route=JourneyWorkspaceRoute.SYSTEM_HEALTH,
                control="diagnostic-context",
                identity="diagnostic-task-113",
            ),
        ),
    )


def test_journey_rail_registry_has_only_the_six_approved_destinations() -> None:
    assert tuple(item.route for item in JOURNEY_DESTINATIONS) == tuple(
        JourneyWorkspaceRoute
    )
    assert tuple(item.label for item in JOURNEY_DESTINATIONS) == (
        "Strategy Library",
        "Scenario Lab",
        "Diagnostic Tasks",
        "Run Monitoring",
        "Evidence & Findings",
        "System Health",
    )
    forbidden = {"market", "account", "positions", "orders", "fills"}
    assert forbidden.isdisjoint(
        " ".join(item.label.lower() for item in JOURNEY_DESTINATIONS).split()
    )


def test_journey_context_is_immutable_typed_versioned_and_status_free() -> None:
    bookmark = _complete_bookmark()
    context = JourneyContext(
        context_revision=12,
        route=bookmark.last_route,
        strategy_selection=bookmark.strategy_selection,
        scenario_selection=bookmark.scenario_selection,
        diagnostic_selection=bookmark.diagnostic_selection,
        evidence_selection=bookmark.evidence_selection,
        presentation=bookmark.presentation,
        source_identities=(
            JourneySourceIdentity(
                identity="diagnostics-application-113",
                revision="source-r19",
                generation=SourceGenerationId(8),
            ),
        ),
    )

    assert context.version == JOURNEY_CONTEXT_VERSION
    assert context.diagnostic_selection is not None
    assert context.diagnostic_selection.task_handle_id == TaskHandleId(
        "task-handle-113"
    )
    assert {
        item.name for item in fields(JourneyDiagnosticSelection)
    }.isdisjoint({"phase", "progress", "status", "error", "freshness_age"})
    with pytest.raises(AttributeError):
        context.context_revision = 13  # type: ignore[misc]


def test_wave_3_bookmark_migration_is_lossless_deterministic_and_idempotent() -> None:
    wave_3_payload = json.dumps(
        {
            "schema_version": "1.0",
            "last_route": "scenario_lab",
            "diagnostic_task_id": "diagnostic-task-wave-3-85",
            "scenario_focus_target": "reference_path",
            "scenario_focus_identity": "reference-path-wave-3-85",
        },
        separators=(",", ":"),
        sort_keys=True,
    )

    migrated = restore_journey_workspace_bookmark(wave_3_payload)
    remigrated = restore_journey_workspace_bookmark(migrated.canonical_payload)

    assert migrated.migrated is True
    assert migrated.recovery.reason is JourneyRecoveryReason.EXACT
    assert migrated.bookmark.last_route is JourneyWorkspaceRoute.SCENARIO_LAB
    assert migrated.bookmark.diagnostic_task_id == DiagnosticTaskId(
        "diagnostic-task-wave-3-85"
    )
    assert migrated.bookmark.scenario_focus_target is (
        ScenarioLabFocusTarget.REFERENCE_PATH
    )
    assert migrated.bookmark.scenario_focus_identity == (
        "reference-path-wave-3-85"
    )
    assert migrated.bookmark.presentation.focus_return_token == (
        JourneyFocusReturnToken(
            route=JourneyWorkspaceRoute.SCENARIO_LAB,
            control="scenarioLabPath-reference-path-wave-3-85",
            identity="reference-path-wave-3-85",
        )
    )
    assert remigrated.bookmark == migrated.bookmark
    assert remigrated.canonical_payload == migrated.canonical_payload
    assert remigrated.migrated is False


def test_v2_bookmark_persists_only_durable_identity_and_presentation_data() -> None:
    raw = json.loads(encode_journey_workspace_bookmark(_complete_bookmark()))
    encoded_names = set(json.dumps(raw).lower().replace('"', " ").split())

    assert raw["schema_version"] == "2.0"
    assert raw["diagnostic"]["task_handle_id"] == "task-handle-113"
    for forbidden in (
        "subscription",
        "qobject",
        "qabstractitemmodel",
        "viewstate",
        "progress",
        "status",
        "raw_error",
        "freshness_age",
        "source_generation",
    ):
        assert forbidden not in encoded_names


@pytest.mark.parametrize(
    "payload",
    (
        "",
        "[]",
        '{"schema_version":"2.0","last_route":"orders"}',
        (
            '{"schema_version":"2.0","last_route":"system_health",'
            '"diagnostic":{"task_handle_id":"__import__(\'os\')"}}'
        ),
    ),
)
def test_invalid_bookmark_has_explicit_safe_recovery(payload: str) -> None:
    restored = restore_journey_workspace_bookmark(payload)

    assert restored.bookmark == JourneyWorkspaceBookmark()
    assert restored.recovery.reason is JourneyRecoveryReason.INVALID_BOOKMARK
    assert restored.bookmark.last_route is JourneyWorkspaceRoute.STRATEGY_LIBRARY
    assert restored.recovery.safe_route is JourneyWorkspaceRoute.STRATEGY_LIBRARY


def test_app_context_migrates_wave_3_and_composes_feature_contexts_from_v2(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "1")
    settings_path = tmp_path / "settings.json"
    bookmark = _complete_bookmark()
    settings_path.write_text(
        json.dumps(
            {
                "journey_workspace_bookmark_json": (
                    encode_journey_workspace_bookmark(bookmark)
                )
            }
        ),
        encoding="utf-8",
    )

    context = build_app_context(
        settings_path=str(settings_path),
        run_monitoring_mode="fake",
        runtime_gateway=object(),
    )
    try:
        assert context.journey_workspace_restore.bookmark == bookmark
        assert context.journey_workspace_restore.recovery.reason is (
            JourneyRecoveryReason.EXACT
        )
        assert context.diagnostic_tasks_context.task_id == DiagnosticTaskId(
            "diagnostic-task-113"
        )
        assert context.run_monitoring_context.selection is not None
        assert context.run_monitoring_context.selection.campaign_id == (
            FormalDiagnosticCampaignId("campaign-113")
        )
        assert context.run_monitoring_context.selection.run_id == StrategyRunId(
            "run-113"
        )
        assert context.evidence_and_findings_context.selection is not None
        assert context.evidence_and_findings_context.selection.strategy_id == (
            StrategyUnderTestId("strategy-primary-113")
        )
        assert (
            context.evidence_and_findings_context.selection.reproduction_manifest_id
            == ReproductionManifestId("manifest-113")
        )
        diagnostic = context.system_health_context.diagnostic
        assert diagnostic is not None
        assert diagnostic.task_handle_id == TaskHandleId("task-handle-113")
        assert diagnostic.evidence_package_id == DiagnosticEvidencePackageId(
            "evidence-package-113"
        )
        assert diagnostic.finding_id == FindingId("finding-113")
        assert diagnostic.sensitivity_breakpoint_id == SensitivityBreakpointId(
            "breakpoint-113"
        )
    finally:
        for feature in (
            context.strategy_library_feature,
            context.scenario_lab_feature,
            context.diagnostic_tasks_feature,
            context.run_monitoring_feature,
            context.evidence_and_findings_feature,
            context.system_health_feature,
        ):
            feature.close()

    wave_3_payload = json.dumps(
        {
            "schema_version": "1.0",
            "last_route": "scenario_lab",
            "diagnostic_task_id": "diagnostic-task-wave-3-85",
            "scenario_focus_target": "reference_path",
            "scenario_focus_identity": "reference-path-wave-3-85",
        }
    )
    settings_path.write_text(
        json.dumps({"journey_workspace_bookmark_json": wave_3_payload}),
        encoding="utf-8",
    )
    migrated_context = build_app_context(
        settings_path=str(settings_path),
        run_monitoring_mode="fake",
        runtime_gateway=object(),
    )
    try:
        assert migrated_context.journey_workspace_restore.migrated is True
        saved = json.loads(settings_path.read_text(encoding="utf-8"))
        assert json.loads(saved["journey_workspace_bookmark_json"])[
            "schema_version"
        ] == "2.0"
    finally:
        for feature in (
            migrated_context.strategy_library_feature,
            migrated_context.scenario_lab_feature,
            migrated_context.diagnostic_tasks_feature,
            migrated_context.run_monitoring_feature,
            migrated_context.evidence_and_findings_feature,
            migrated_context.system_health_feature,
        ):
            feature.close()
