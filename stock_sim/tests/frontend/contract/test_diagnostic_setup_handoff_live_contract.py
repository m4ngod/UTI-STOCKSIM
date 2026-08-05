from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import text

from app.features import (
    ApproveDiagnosticTaskConfiguration,
    DeterministicFakeDiagnosticTasksAdapter,
    DiagnosticActorId,
    DiagnosticCommandId,
    DiagnosticCommandIdempotencyKey,
    DiagnosticTaskLifecycle,
    DiagnosticTaskConfiguration,
    DiagnosticTasksContext,
    DiagnosticTasksCommandDisposition,
    LiveDiagnosticTasksAdapter,
    LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter,
    ReviseDiagnosticTaskConfiguration,
    ScenarioLabContext,
    StartFormalDiagnosticCampaign,
    ValidateDiagnosticTaskConfiguration,
)
from app.features.diagnostic_setup import (
    ApproveDiagnosticTaskConfigurationFromSetup,
    CreateDiagnosticTaskFromSetup,
    DiagnosticSetupSelectionCoordinator,
    ReviseDiagnosticTaskConfigurationFromSetup,
    ScenarioDiagnosticSelection,
    StartFormalDiagnosticCampaignFromSetup,
    ValidateDiagnosticTaskConfigurationFromSetup,
    compose_diagnostic_setup_selection_context,
)
from app.features.live_strategy_library import LiveStrategyLibraryAdapter
from app.features.run_monitoring import SourceGenerationId, StrategyUnderTestId
from app.features.scenario_lab_application import (
    ComposeFormalScenarioSetCommand,
    ResolveScenarioExecutionAssumptionsCommand,
    ScenarioExecutionAssumptionTarget,
    SelectFormalScenarioSetCommand,
)
from app.features.strategy_library import (
    SelectFormalStrategySet,
    StrategyLibraryContext,
)
from app.features.strategy_library_application import (
    LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter,
)
from tests.frontend.contract.test_diagnostic_task_creation_live_contract import (
    _command,
    _configuration as _inventory_configuration,
)
from tests.frontend.contract.test_diagnostic_task_revision_approval_live_contract import (
    _read_task,
)
from tests.frontend.contract.test_scenario_lab_formal_scenario_sets_live_contract import (
    _canonical,
    _formal_cases,
    _live_feature,
    _metadata,
)


def _create_input(command, setup):
    return CreateDiagnosticTaskFromSetup(
        command_id=command.command_id,
        idempotency_key=command.idempotency_key,
        configuration=command.configuration,
        setup_selection=setup,
    )


def test_live_exact_setup_selection_is_bound_through_approval(tmp_path) -> None:
    _, _, engine, application, scenario_feature = _live_feature(tmp_path)
    lab_context = ScenarioLabContext()
    scenario_feature.snapshot(lab_context)
    ready = scenario_feature.snapshot(lab_context)
    baseline, isolated, compound = _formal_cases(ready)
    composed = scenario_feature.compose_scenario_set(
        _canonical(
            ComposeFormalScenarioSetCommand(
                metadata=_metadata(ready, "compose-handoff-84"),
                baseline_case_id=baseline.scenario_id,
                isolated_case_ids=tuple(item.scenario_id for item in isolated),
                compound_case_ids=tuple(item.scenario_id for item in compound),
            )
        )
    )
    assert composed.scenario_set is not None

    after_compose = scenario_feature.snapshot(lab_context)
    strategy_ids = tuple(
        StrategyUnderTestId(item.strategy_id)
        for item in application.read_strategy_under_test_inventory().entries
    )
    decision_time = next(
        item.start_time
        for item in after_compose.reference_paths
        if item.path_id == baseline.path_id
    )
    resolved = scenario_feature.resolve_execution_assumptions(
        _canonical(
            ResolveScenarioExecutionAssumptionsCommand(
                metadata=_metadata(after_compose, "resolve-handoff-84"),
                scenario_set_id=composed.scenario_set.scenario_set_id,
                targets=tuple(
                    ScenarioExecutionAssumptionTarget(
                        strategy_id=strategy_id,
                        campaign_case_id=case_id,
                        decision_time=decision_time,
                    )
                    for strategy_id in strategy_ids
                    for case_id in composed.scenario_set.case_ids
                ),
            )
        )
    )
    assert resolved.resolution is not None
    after_resolution = scenario_feature.snapshot(lab_context)
    selected = scenario_feature.select_formal_scenario_set(
        _canonical(
            SelectFormalScenarioSetCommand(
                metadata=_metadata(after_resolution, "select-handoff-84"),
                scenario_set_id=composed.scenario_set.scenario_set_id,
                case_ids=composed.scenario_set.case_ids,
                originating_view_revision=after_resolution.revision,
                execution_resolution_id=resolved.resolution.resolution_id,
            )
        )
    )
    assert selected.selection_context is not None

    strategy_feature = LiveStrategyLibraryAdapter(
        application=LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter(
            application
        )
    )
    strategy_context = StrategyLibraryContext()
    strategy_feature.snapshot(strategy_context)
    strategy_ready = strategy_feature.snapshot(strategy_context)
    assert strategy_ready.source_revision is not None
    strategy_selected = strategy_feature.select_formal_strategy_set(
        SelectFormalStrategySet(
            strategy_ids=tuple(item.strategy_id for item in strategy_ready.entries),
            guardrail_profile_ids=tuple(
                item.guardrail_profile.profile_id for item in strategy_ready.entries
            ),
            expected_source_revision=strategy_ready.source_revision,
            expected_source_generation=SourceGenerationId(
                strategy_ready.source.generation.value
            ),
            originating_view_revision=strategy_ready.revision,
        )
    )
    assert strategy_selected.selection is not None
    selected_cases = tuple(
        next(
            item
            for item in after_resolution.market_scenarios
            if item.scenario_id == case_id
        )
        for case_id in composed.scenario_set.case_ids
    )
    setup = compose_diagnostic_setup_selection_context(
        strategy_selected.selection,
        ScenarioDiagnosticSelection(
            context=selected.selection_context,
            scenario_set=composed.scenario_set,
            market_scenarios=selected_cases,
            execution_resolution=resolved.resolution,
        ),
    )

    coordinator = DiagnosticSetupSelectionCoordinator()
    coordinator.observe(setup)
    task_feature = LiveDiagnosticTasksAdapter(
        application=LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
            application,
            setup_selection_provider=coordinator.current,
        )
    )
    create_command = _command(
            setup.configuration,
            command_id="create-handoff-84",
            idempotency_key="create-handoff-idempotency-84",
    )
    created = task_feature.create_diagnostic_task(
        CreateDiagnosticTaskFromSetup(
            command_id=create_command.command_id,
            idempotency_key=create_command.idempotency_key,
            configuration=create_command.configuration,
            setup_selection=setup,
        )
    )
    assert created.affected_task_id is not None, (
        created.message,
        created.rejection_reason,
    )
    task = _read_task(task_feature, created.affected_task_id)
    validated = task_feature.validate_configuration(
        ValidateDiagnosticTaskConfigurationFromSetup(
            command_id=DiagnosticCommandId("validate-handoff-84"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "validate-handoff-idempotency-84"
            ),
            task_id=task.task_id,
            expected_revision=task.revision,
            setup_selection=setup,
        )
    )
    assert validated.disposition is (
        DiagnosticTasksCommandDisposition.ASYNCHRONOUS_ACCEPTANCE
    )
    task = _read_task(task_feature, task.task_id)
    assert task.validation.validation_id is not None
    assert task.validation.state.value == "valid", task.validation.findings
    approved = task_feature.approve_configuration(
        ApproveDiagnosticTaskConfigurationFromSetup(
            command_id=DiagnosticCommandId("approve-handoff-84"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "approve-handoff-idempotency-84"
            ),
            task_id=task.task_id,
            expected_revision=task.revision,
            validation_id=task.validation.validation_id,
            validation_revision=task.validation.validation_revision,
            validated_revision=task.validation.validated_revision,
            configuration_content_id=(
                task.validation.configuration_content_identity
            ),
            actor_id=DiagnosticActorId("wave3-owner"),
            setup_selection=setup,
        )
    )
    assert approved.disposition is (
        DiagnosticTasksCommandDisposition.SYNCHRONOUS_COMPLETION
    ), (approved.message, approved.rejection_reason, task.validation)
    approved_task = _read_task(task_feature, task.task_id)
    assert approved_task.approval is not None
    with engine.connect() as connection:
        validation_binding = connection.execute(
            text(
                "SELECT dependency_binding_id, dependency_binding_hash, "
                "dependency_binding_json FROM "
                "diagnostic_task_validation_dependency_bindings "
                "WHERE task_id = :task_id AND invalidated_at_utc IS NULL"
            ),
            {"task_id": task.task_id.value},
        ).mappings().one()
        approval_binding = connection.execute(
            text(
                "SELECT dependency_binding_id, dependency_binding_hash FROM "
                "diagnostic_task_approval_dependency_bindings "
                "WHERE task_id = :task_id AND invalidated_at_utc IS NULL"
            ),
            {"task_id": task.task_id.value},
        ).mappings().one()
    assert approval_binding["dependency_binding_id"] == (
        validation_binding["dependency_binding_id"]
    )
    assert approval_binding["dependency_binding_hash"] == (
        validation_binding["dependency_binding_hash"]
    )
    assert validation_binding["dependency_binding_hash"] in tuple(
        item.value for item in approved_task.approval.policy_identities
    )
    assert selected.selection_context.selection_context_id.value in str(
        validation_binding["dependency_binding_json"]
    )

    successor_source = scenario_feature.snapshot(lab_context)
    successor = scenario_feature.compose_scenario_set(
        _canonical(
            ComposeFormalScenarioSetCommand(
                metadata=_metadata(successor_source, "successor-drift-84"),
                baseline_case_id=baseline.scenario_id,
                isolated_case_ids=tuple(item.scenario_id for item in isolated),
                compound_case_ids=tuple(item.scenario_id for item in compound),
            )
        )
    )
    assert successor.scenario_set is not None
    invalidated = _read_task(task_feature, task.task_id)
    assert invalidated.lifecycle is DiagnosticTaskLifecycle.DRAFT
    assert invalidated.approval is None
    rejected_start = task_feature.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaignFromSetup(
            command_id=DiagnosticCommandId("start-after-drift-84"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "start-after-drift-idempotency-84"
            ),
            task_id=task.task_id,
            expected_revision=invalidated.revision,
            approved_revision=approved_task.revision,
            setup_selection=setup,
        )
    )
    assert rejected_start.disposition is DiagnosticTasksCommandDisposition.REJECTED
    with engine.connect() as connection:
        invalidation = connection.execute(
            text(
                "SELECT reason_code, expected_binding_hash, "
                "observed_binding_hash FROM "
                "diagnostic_task_selection_dependency_invalidations "
                "WHERE task_id = :task_id"
            ),
            {"task_id": task.task_id.value},
        ).mappings().one()
    assert invalidation["reason_code"] == "authoritative_dependency_mismatch"
    assert invalidation["expected_binding_hash"] == (
        validation_binding["dependency_binding_hash"]
    )
    assert invalidation["observed_binding_hash"] == "unavailable"

    task_feature.close()
    strategy_feature.close()
    scenario_feature.close()
    engine.dispose()


def _configured_setup_harness(tmp_path, kind: str):
    _, _, engine, application, scenario_feature = _live_feature(tmp_path)
    context = ScenarioLabContext()
    scenario_feature.snapshot(context)
    ready = scenario_feature.snapshot(context)
    baseline, isolated, compound = _formal_cases(ready)
    composed = scenario_feature.compose_scenario_set(
        _canonical(
            ComposeFormalScenarioSetCommand(
                metadata=_metadata(ready, f"compose-shared-{kind}-84"),
                baseline_case_id=baseline.scenario_id,
                isolated_case_ids=tuple(item.scenario_id for item in isolated),
                compound_case_ids=tuple(item.scenario_id for item in compound),
            )
        )
    )
    assert composed.scenario_set is not None
    after_compose = scenario_feature.snapshot(context)
    strategy_ids = tuple(
        StrategyUnderTestId(item.strategy_id)
        for item in application.read_strategy_under_test_inventory().entries
    )
    decision_time = next(
        item.start_time
        for item in after_compose.reference_paths
        if item.path_id == baseline.path_id
    )
    resolved = scenario_feature.resolve_execution_assumptions(
        _canonical(
            ResolveScenarioExecutionAssumptionsCommand(
                metadata=_metadata(after_compose, f"resolve-shared-{kind}-84"),
                scenario_set_id=composed.scenario_set.scenario_set_id,
                targets=tuple(
                    ScenarioExecutionAssumptionTarget(
                        strategy_id=strategy_id,
                        campaign_case_id=case_id,
                        decision_time=decision_time,
                    )
                    for strategy_id in strategy_ids
                    for case_id in composed.scenario_set.case_ids
                ),
            )
        )
    )
    assert resolved.resolution is not None
    after_resolution = scenario_feature.snapshot(context)
    selected = scenario_feature.select_formal_scenario_set(
        _canonical(
            SelectFormalScenarioSetCommand(
                metadata=_metadata(after_resolution, f"select-shared-{kind}-84"),
                scenario_set_id=composed.scenario_set.scenario_set_id,
                case_ids=composed.scenario_set.case_ids,
                originating_view_revision=after_resolution.revision,
                execution_resolution_id=resolved.resolution.resolution_id,
            )
        )
    )
    assert selected.selection_context is not None
    strategy_feature = LiveStrategyLibraryAdapter(
        application=LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter(
            application
        )
    )
    strategy_context = StrategyLibraryContext()
    strategy_feature.snapshot(strategy_context)
    strategy_ready = strategy_feature.snapshot(strategy_context)
    assert strategy_ready.source_revision is not None
    strategy_selected = strategy_feature.select_formal_strategy_set(
        SelectFormalStrategySet(
            strategy_ids=tuple(item.strategy_id for item in strategy_ready.entries),
            guardrail_profile_ids=tuple(
                item.guardrail_profile.profile_id for item in strategy_ready.entries
            ),
            expected_source_revision=strategy_ready.source_revision,
            expected_source_generation=SourceGenerationId(
                strategy_ready.source.generation.value
            ),
            originating_view_revision=strategy_ready.revision,
        )
    )
    assert strategy_selected.selection is not None
    setup = compose_diagnostic_setup_selection_context(
        strategy_selected.selection,
        ScenarioDiagnosticSelection(
            context=selected.selection_context,
            scenario_set=composed.scenario_set,
            market_scenarios=tuple(
                next(
                    item
                    for item in after_resolution.market_scenarios
                    if item.scenario_id == case_id
                )
                for case_id in composed.scenario_set.case_ids
            ),
            execution_resolution=resolved.resolution,
        ),
    )
    coordinator = DiagnosticSetupSelectionCoordinator()
    coordinator.observe(setup)
    live = LiveDiagnosticTasksAdapter(
        application=LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
            application,
            setup_selection_provider=coordinator.current,
        )
    )
    if kind == "live":
        feature = live
    else:
        workspace = DiagnosticTasksContext.workspace()
        live.snapshot(workspace)
        inventory = live.snapshot(workspace).last_reliable_inventory
        assert inventory is not None
        live.close()
        feature = DeterministicFakeDiagnosticTasksAdapter(
            inventory=inventory,
            setup_selection_provider=coordinator.current,
        )
    return (
        feature,
        setup,
        coordinator,
        strategy_feature,
        scenario_feature,
        engine,
    )


@pytest.mark.parametrize("kind", ("live", "fake"))
def test_live_and_fake_share_exact_setup_invalidation_contract(
    tmp_path,
    kind: str,
) -> None:
    feature, setup, coordinator, strategy_feature, scenario_feature, engine = (
        _configured_setup_harness(tmp_path, kind)
    )
    command = _command(
        setup.configuration,
        command_id=f"shared-create-{kind}-84",
        idempotency_key=f"shared-create-key-{kind}-84",
    )
    created = feature.create_diagnostic_task(_create_input(command, setup))
    replayed = feature.create_diagnostic_task(_create_input(command, setup))
    assert created.affected_task_id is not None, (
        created.message,
        created.rejection_reason,
    )
    assert replayed.disposition is DiagnosticTasksCommandDisposition.IDEMPOTENT_REPLAY
    conflict = feature.create_diagnostic_task(
        _create_input(
            replace(
            command,
            idempotency_key=DiagnosticCommandIdempotencyKey(
                f"shared-create-conflict-key-{kind}-84"
            ),
            ),
            setup,
        )
    )
    assert conflict.disposition is DiagnosticTasksCommandDisposition.REJECTED

    task = _read_task(feature, created.affected_task_id)
    validated = feature.validate_configuration(
        ValidateDiagnosticTaskConfigurationFromSetup(
            command_id=DiagnosticCommandId(f"shared-validate-{kind}-84"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                f"shared-validate-key-{kind}-84"
            ),
            task_id=task.task_id,
            expected_revision=task.revision,
            setup_selection=setup,
        )
    )
    assert validated.rejection_reason is None
    task = _read_task(feature, task.task_id)
    assert task.validation.validation_id is not None
    approved = feature.approve_configuration(
        ApproveDiagnosticTaskConfigurationFromSetup(
            command_id=DiagnosticCommandId(f"shared-approve-{kind}-84"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                f"shared-approve-key-{kind}-84"
            ),
            task_id=task.task_id,
            expected_revision=task.revision,
            validation_id=task.validation.validation_id,
            validation_revision=task.validation.validation_revision,
            validated_revision=task.validation.validated_revision,
            configuration_content_id=(
                task.validation.configuration_content_identity
            ),
            actor_id=DiagnosticActorId("shared-wave3-owner"),
            setup_selection=setup,
        )
    )
    assert approved.rejection_reason is None
    approved_task = _read_task(feature, task.task_id)
    successor_strategy = replace(
        setup.strategy_selection,
        context_identity=(
            setup.strategy_selection.context_identity + f"-successor-{kind}"
        ),
        originating_view_revision=(
            setup.strategy_selection.originating_view_revision + 1
        ),
    )
    successor = compose_diagnostic_setup_selection_context(
        successor_strategy,
        setup.scenario_selection,
    )
    assert successor.configuration == setup.configuration
    coordinator.observe(successor)
    invalidated = _read_task(feature, approved_task.task_id)
    assert invalidated.lifecycle is DiagnosticTaskLifecycle.DRAFT
    assert invalidated.approval is None
    assert invalidated.handoff.campaign_id is None

    binding_conflict = feature.create_diagnostic_task(
        _create_input(command, successor)
    )
    assert binding_conflict.disposition is (
        DiagnosticTasksCommandDisposition.REJECTED
    )
    rejected_start = feature.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaignFromSetup(
            command_id=DiagnosticCommandId(f"shared-start-stale-{kind}-84"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                f"shared-start-stale-key-{kind}-84"
            ),
            task_id=approved_task.task_id,
            expected_revision=approved_task.revision,
            approved_revision=approved_task.revision,
            setup_selection=successor,
        )
    )
    assert rejected_start.disposition is DiagnosticTasksCommandDisposition.REJECTED
    invalidated = _read_task(feature, approved_task.task_id)
    assert invalidated.lifecycle is DiagnosticTaskLifecycle.DRAFT
    assert invalidated.approval is None
    assert invalidated.handoff.campaign_id is None

    corrected_revision = feature.revise_configuration(
        ReviseDiagnosticTaskConfigurationFromSetup(
            command_id=DiagnosticCommandId(
                f"shared-corrected-revise-{kind}-84"
            ),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                f"shared-corrected-revise-key-{kind}-84"
            ),
            task_id=invalidated.task_id,
            expected_revision=invalidated.revision,
            configuration=successor.configuration,
            setup_selection=successor,
        )
    )
    assert corrected_revision.rejection_reason is None
    corrected_task = _read_task(feature, invalidated.task_id)
    corrected_validation = feature.validate_configuration(
        ValidateDiagnosticTaskConfigurationFromSetup(
            command_id=DiagnosticCommandId(
                f"shared-corrected-validate-{kind}-84"
            ),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                f"shared-corrected-validate-key-{kind}-84"
            ),
            task_id=corrected_task.task_id,
            expected_revision=corrected_task.revision,
            setup_selection=successor,
        )
    )
    assert corrected_validation.rejection_reason is None
    corrected_task = _read_task(feature, corrected_task.task_id)
    assert corrected_task.validation.validation_id is not None
    corrected_approval = feature.approve_configuration(
        ApproveDiagnosticTaskConfigurationFromSetup(
            command_id=DiagnosticCommandId(
                f"shared-corrected-approve-{kind}-84"
            ),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                f"shared-corrected-approve-key-{kind}-84"
            ),
            task_id=corrected_task.task_id,
            expected_revision=corrected_task.revision,
            validation_id=corrected_task.validation.validation_id,
            validation_revision=(
                corrected_task.validation.validation_revision
            ),
            validated_revision=corrected_task.validation.validated_revision,
            configuration_content_id=(
                corrected_task.validation.configuration_content_identity
            ),
            actor_id=DiagnosticActorId("shared-corrected-wave3-owner"),
            setup_selection=successor,
        )
    )
    assert corrected_approval.rejection_reason is None
    corrected_task = _read_task(feature, corrected_task.task_id)
    assert corrected_task.approval is not None
    started = feature.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaignFromSetup(
            command_id=DiagnosticCommandId(
                f"shared-corrected-start-{kind}-84"
            ),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                f"shared-corrected-start-key-{kind}-84"
            ),
            task_id=corrected_task.task_id,
            expected_revision=corrected_task.revision,
            approved_revision=corrected_task.revision,
            setup_selection=successor,
        )
    )
    assert started.rejection_reason is None
    running = _read_task(feature, corrected_task.task_id)
    assert running.handoff.campaign_id is not None
    campaign_identity = running.handoff.campaign_id
    coordinator.observe(setup)
    terminally_bound = _read_task(feature, corrected_task.task_id)
    assert terminally_bound.lifecycle is DiagnosticTaskLifecycle.RUNNING
    assert terminally_bound.handoff.campaign_id == campaign_identity
    assert terminally_bound.approval == running.approval

    workspace = DiagnosticTasksContext.workspace()
    feature.snapshot(workspace)
    inventory = feature.snapshot(workspace).last_reliable_inventory
    assert inventory is not None
    legacy_configuration = _inventory_configuration(inventory)
    legacy = feature.create_diagnostic_task(
        _command(
            legacy_configuration,
            command_id=f"shared-legacy-create-{kind}-84",
            idempotency_key=f"shared-legacy-create-key-{kind}-84",
        )
    )
    assert legacy.affected_task_id is not None
    legacy_task = _read_task(feature, legacy.affected_task_id)
    legacy_validate_command = ValidateDiagnosticTaskConfiguration(
        command_id=DiagnosticCommandId(f"shared-legacy-validate-{kind}-84"),
        idempotency_key=DiagnosticCommandIdempotencyKey(
            f"shared-legacy-validate-key-{kind}-84"
        ),
        task_id=legacy_task.task_id,
        expected_revision=legacy_task.revision,
    )
    legacy_validated = feature.validate_configuration(
        legacy_validate_command
    )
    assert legacy_validated.rejection_reason is None
    coordinator.observe(successor)
    assert feature.validate_configuration(legacy_validate_command).disposition is (
        DiagnosticTasksCommandDisposition.IDEMPOTENT_REPLAY
    )
    legacy_task = _read_task(feature, legacy_task.task_id)
    assert legacy_task.validation.validation_id is not None
    legacy_approve_command = ApproveDiagnosticTaskConfiguration(
        command_id=DiagnosticCommandId(f"shared-legacy-approve-{kind}-84"),
        idempotency_key=DiagnosticCommandIdempotencyKey(
            f"shared-legacy-approve-key-{kind}-84"
        ),
        task_id=legacy_task.task_id,
        expected_revision=legacy_task.revision,
        validation_id=legacy_task.validation.validation_id,
        validation_revision=legacy_task.validation.validation_revision,
        validated_revision=legacy_task.validation.validated_revision,
        configuration_content_id=(
            legacy_task.validation.configuration_content_identity
        ),
        actor_id=DiagnosticActorId("shared-legacy-wave2-owner"),
    )
    legacy_approved = feature.approve_configuration(legacy_approve_command)
    assert legacy_approved.rejection_reason is None
    coordinator.observe(None)
    assert feature.approve_configuration(legacy_approve_command).disposition is (
        DiagnosticTasksCommandDisposition.IDEMPOTENT_REPLAY
    )
    legacy_task = _read_task(feature, legacy_task.task_id)
    assert legacy_task.lifecycle is DiagnosticTaskLifecycle.APPROVED
    legacy_start_command = StartFormalDiagnosticCampaign(
        command_id=DiagnosticCommandId(f"shared-legacy-start-{kind}-84"),
        idempotency_key=DiagnosticCommandIdempotencyKey(
            f"shared-legacy-start-key-{kind}-84"
        ),
        task_id=legacy_task.task_id,
        expected_revision=legacy_task.revision,
        approved_revision=legacy_task.revision,
    )
    legacy_started = feature.start_formal_diagnostic_campaign(
        legacy_start_command
    )
    assert legacy_started.rejection_reason is None
    coordinator.observe(setup)
    assert feature.start_formal_diagnostic_campaign(
        legacy_start_command
    ).disposition is DiagnosticTasksCommandDisposition.IDEMPOTENT_REPLAY
    legacy_task = _read_task(feature, legacy_task.task_id)
    assert legacy_task.lifecycle is DiagnosticTaskLifecycle.RUNNING
    if kind == "live":
        with engine.connect() as connection:
            legacy_binding_counts = tuple(
                connection.execute(
                    text(
                        f"SELECT COUNT(*) FROM {table_name} "
                        "WHERE task_id = :task_id"
                    ),
                    {"task_id": legacy_task.task_id.value},
                ).scalar_one()
                for table_name in (
                    "diagnostic_task_setup_dependency_bindings",
                    "diagnostic_task_validation_dependency_bindings",
                    "diagnostic_task_approval_dependency_bindings",
                    "diagnostic_task_selection_dependency_invalidations",
                )
            )
        assert legacy_binding_counts == (0, 0, 0, 0)

    feature.close()
    strategy_feature.close()
    scenario_feature.close()
    engine.dispose()
