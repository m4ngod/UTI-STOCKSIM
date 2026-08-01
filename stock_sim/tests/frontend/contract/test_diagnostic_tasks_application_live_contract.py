from __future__ import annotations

from datetime import datetime, timezone

from app.features import (
    DIAGNOSTIC_TASKS_APPLICATION_INTERFACE_VERSION,
    DiagnosticCampaignLayer,
    DiagnosticTasksApplicationAvailability,
    DiagnosticTasksApplicationCommandRejectionReason,
    LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter,
    StrategyDiagnosticsV1DiagnosticTasksApplication,
)
from strategy_diagnostics import create_diagnostics_application
from strategy_diagnostics.market_paths import InMemoryMarketPathArtifactStore
from tests.frontend.contract.test_diagnostic_tasks_live_fake_conformance import (
    _unavailable_commands,
)
from tests.strategy_diagnostics.test_recipe_lifecycle import (
    _baseline_payload,
    _RecipeFixtureSource,
)


def test_live_application_adapter_reads_authoritative_typed_inputs_only_from_public_behavior() -> None:
    source = _RecipeFixtureSource()
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
        recipe_clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    application.start()
    admission = application.admit_historical_segment(source.selection)
    assert admission.segment is not None
    draft = application.create_manual_recipe_draft(
        _baseline_payload(admission.segment.segment_id),
        author="researcher",
    )
    validation = application.validate_recipe_draft(draft.draft_id)
    assert validation.is_valid
    approved = application.approve_recipe_draft(draft.draft_id, actor="owner")
    materialized = application.materialize_baseline_reference_path(
        approved.version_id
    )

    adapter = LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
        application
    )

    assert isinstance(adapter, StrategyDiagnosticsV1DiagnosticTasksApplication)
    assert (
        adapter.interface_version
        == DIAGNOSTIC_TASKS_APPLICATION_INTERFACE_VERSION
    )
    result = adapter.read_inventory()

    assert result.availability is DiagnosticTasksApplicationAvailability.READY
    assert result.error is None
    assert result.inventory is not None
    assert len(result.inventory.strategies) == 2
    assert {
        item.guardrail_profile_id.value
        for item in result.inventory.strategies
    } == {
        "guardrail-profile-7616a340b156316d79f4b76c",
        "guardrail-profile-b7b800744246047283b94874",
    }
    assert tuple(
        (
            item.recipe_version_id.value,
            item.recipe_content_hash,
            item.market_scenario_id.value,
            item.campaign_case_id.value,
            item.layer,
        )
        for item in result.inventory.market_scenarios
    ) == (
        (
            approved.version_id,
            approved.content_hash,
            materialized.artifact_hash,
            application.create_diagnostic_campaign_case(
                approved.version_id,
                materialized.artifact_hash,
            ).case_id,
            DiagnosticCampaignLayer.BASELINE,
        ),
    )
    scenario = result.inventory.market_scenarios[0]
    assert scenario.historical_segment_id.value == admission.segment.segment_id
    assert scenario.source_snapshot_id.value == materialized.source_snapshot_id
    assert scenario.transformation_catalog_version
    assert scenario.market_rule_profile_version
    assert tuple(value.name for value in scenario.execution_policy_values) == (
        "allow_partial_fills",
        "commission_bps",
        "decision_cadence_minutes",
        "latency_nodes",
        "max_fill_fraction",
        "slippage_bps",
    )

    public_operations = {
        name
        for name in StrategyDiagnosticsV1DiagnosticTasksApplication.__dict__
        if not name.startswith("_")
    }
    assert public_operations == {
        "interface_version",
        "read_inventory",
        "read_diagnostic_task",
        "create_diagnostic_task",
        "revise_configuration",
        "validate_configuration",
        "approve_configuration",
        "start_formal_diagnostic_campaign",
        "pause_diagnostic_target",
        "resume_diagnostic_target",
        "cancel_diagnostic_target",
        "retry_failed_campaign_node",
    }
    commands = _unavailable_commands(result.inventory)
    created = adapter.create_diagnostic_task(commands[0])
    assert created.accepted
    assert created.task is not None
    invalid_task_commands = (
        adapter.revise_configuration(commands[1]),
        adapter.validate_configuration(commands[2]),
        adapter.approve_configuration(commands[3]),
    )
    start_rejected = adapter.start_formal_diagnostic_campaign(commands[4])
    invalid_lifecycle_commands = (
        adapter.pause_diagnostic_target(commands[5]),
        adapter.resume_diagnostic_target(commands[6]),
        adapter.cancel_diagnostic_target(commands[7]),
    )
    invalid_retry_commands = (
        adapter.retry_failed_campaign_node(commands[8]),
    )
    assert all(not item.accepted for item in invalid_task_commands)
    assert all(
        item.rejection_reason
        is DiagnosticTasksApplicationCommandRejectionReason.INVALID_COMMAND
        for item in invalid_task_commands
    )
    assert all(not item.accepted for item in invalid_lifecycle_commands)
    assert all(not item.accepted for item in invalid_retry_commands)
    assert not start_rejected.accepted
    assert start_rejected.rejection_reason is (
        DiagnosticTasksApplicationCommandRejectionReason.INVALID_COMMAND
    )
    assert all(
        item.rejection_reason
        is DiagnosticTasksApplicationCommandRejectionReason.INVALID_COMMAND
        for item in invalid_lifecycle_commands
    )
    assert all(
        item.rejection_reason
        is DiagnosticTasksApplicationCommandRejectionReason.INVALID_COMMAND
        for item in invalid_retry_commands
    )
    assert start_rejected.task is None
    assert all(item.task is None for item in invalid_lifecycle_commands)
    assert all(item.task is None for item in invalid_retry_commands)


def test_parameterized_recipe_is_not_dropped_from_authoritative_inventory() -> None:
    source = _RecipeFixtureSource()
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
        recipe_clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    application.start()
    admission = application.admit_historical_segment(source.selection)
    assert admission.segment is not None
    payload = _baseline_payload(admission.segment.segment_id)
    payload["transformations"] = [
        {
            "transformation_id": "execution-stress.v1",
            "parameters": {"commission_bps": "20"},
        }
    ]
    draft = application.create_manual_recipe_draft(payload, author="researcher")
    assert application.validate_recipe_draft(draft.draft_id).is_valid
    approved = application.approve_recipe_draft(draft.draft_id, actor="owner")
    materialized = application.materialize_reference_path(approved.version_id)

    result = LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
        application
    ).read_inventory()

    assert result.inventory is not None
    matching = tuple(
        item
        for item in result.inventory.market_scenarios
        if item.recipe_version_id.value == approved.version_id
    )
    assert len(matching) == 1
    assert matching[0].market_scenario_id.value == materialized.artifact_hash
    assert matching[0].layer is DiagnosticCampaignLayer.ISOLATED_SENSITIVITY
    assert tuple(
        item.family for item in matching[0].applied_transformations
    ) == ("execution-stress",)
    transformation = matching[0].applied_transformations[0]
    assert transformation.transformation_id == "execution-stress.v1"
    assert transformation.implementation_version
    assert tuple(
        (item.name, item.value) for item in transformation.parameters
    ) == (("commission_bps", "20"),)
    provenance = matching[0].materialization_provenance
    assert provenance.expander_version == materialized.expander_version
    assert provenance.source_resolution == materialized.source_resolution
    assert provenance.runtime_resolution == materialized.runtime_resolution
    assert provenance.numeric_tolerance == materialized.numeric_tolerance
    assert (
        provenance.normalization_provenance
        == materialized.normalization_provenance
    )


def test_live_inventory_read_does_not_materialize_an_unmaterialized_recipe() -> None:
    source = _RecipeFixtureSource()
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
        recipe_clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    application.start()
    admission = application.admit_historical_segment(source.selection)
    assert admission.segment is not None

    baseline_draft = application.create_manual_recipe_draft(
        _baseline_payload(admission.segment.segment_id),
        author="researcher",
    )
    assert application.validate_recipe_draft(baseline_draft.draft_id).is_valid
    baseline = application.approve_recipe_draft(
        baseline_draft.draft_id,
        actor="owner",
    )
    materialized = application.materialize_baseline_reference_path(
        baseline.version_id
    )

    stress_payload = _baseline_payload(admission.segment.segment_id)
    stress_payload["name"] = "Unmaterialized execution stress"
    stress_payload["transformations"] = [
        {
            "transformation_id": "execution-stress.v1",
            "parameters": {"commission_bps": "20"},
        }
    ]
    stress_draft = application.create_manual_recipe_draft(
        stress_payload,
        author="researcher",
    )
    assert application.validate_recipe_draft(stress_draft.draft_id).is_valid
    stress = application.approve_recipe_draft(stress_draft.draft_id, actor="owner")
    assert stress.version_id != baseline.version_id

    adapter = LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
        application
    )
    paths_before = application.list_materialized_market_paths()

    first = adapter.read_inventory()
    second = adapter.read_inventory()

    assert application.list_materialized_market_paths() == paths_before
    assert tuple(item.artifact_hash for item in paths_before) == (
        materialized.artifact_hash,
    )
    assert first.inventory == second.inventory
    assert first.source_token == second.source_token
    assert first.availability is second.availability
    assert first.inventory is not None
    assert tuple(
        item.recipe_version_id.value
        for item in first.inventory.market_scenarios
    ) == (baseline.version_id,)
