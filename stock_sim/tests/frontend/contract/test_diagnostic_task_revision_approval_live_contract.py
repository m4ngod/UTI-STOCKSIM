from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone

from sqlalchemy import create_engine, text

from app.features import (
    ApproveDiagnosticTaskConfiguration,
    DiagnosticActorId,
    DiagnosticCampaignCaseSelectionReference,
    DiagnosticCampaignLayer,
    DiagnosticCommandId,
    DiagnosticCommandIdempotencyKey,
    DiagnosticStrategySelectionReference,
    DiagnosticTaskConfiguration,
    DiagnosticTaskLifecycle,
    DiagnosticTasksApplicationCommandRejectionReason,
    DiagnosticTasksCommandDisposition,
    DiagnosticTasksContext,
    DiagnosticTasksPresentationState,
    DiagnosticTaskValidationState,
    LiveDiagnosticTasksAdapter,
    LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter,
    ReviseDiagnosticTaskConfiguration,
    TaskPhase,
    ValidateDiagnosticTaskConfiguration,
)
from strategy_diagnostics import create_diagnostics_application
from strategy_diagnostics.diagnostic_tasks import (
    DiagnosticTaskConfiguration as PersistedDiagnosticTaskConfiguration,
)
from strategy_diagnostics.market_paths import InMemoryMarketPathArtifactStore
from tests.frontend.contract.test_diagnostic_task_creation_live_contract import (
    _command,
    _configuration,
)
from tests.strategy_diagnostics.test_market_path_materialization import (
    _AdmittedCrossSectionFixtureSource,
    _segment,
)
from tests.strategy_diagnostics.test_recipe_lifecycle import _baseline_payload


def _persistent_three_layer_stack(tmp_path):
    source = _AdmittedCrossSectionFixtureSource()
    artifact_store = InMemoryMarketPathArtifactStore()
    engine = create_engine(
        f"sqlite:///{tmp_path / 'diagnostic-task-approval.db'}",
        future=True,
    )
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=artifact_store,
        recipe_clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
        diagnostic_task_clock=lambda: datetime(
            2030,
            1,
            2,
            tzinfo=timezone.utc,
        ),
    )
    application.start()
    application.initialize_persistence(engine)
    admission = application.admit_historical_segment(_segment().selection)
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
    application.materialize_baseline_reference_path(baseline.version_id)
    _add_isolated_and_compound_inputs(application)
    application_adapter = (
        LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(application)
    )
    feature = LiveDiagnosticTasksAdapter(application=application_adapter)
    return (
        source,
        artifact_store,
        engine,
        application,
        application_adapter,
        feature,
    )


def _add_isolated_and_compound_inputs(application: object) -> None:
    segment_id = application.list_historical_segments()[0].segment_id
    isolated = deepcopy(_baseline_payload(segment_id))
    isolated["name"] = "Volatility sensitivity"
    isolated["transformations"] = [
        {
            "transformation_id": "volatility-scaling.v1",
            "parameters": {"multiplier": "1.5"},
        }
    ]
    compound = deepcopy(_baseline_payload(segment_id))
    compound["name"] = "Volatility and liquidity compound"
    compound["transformations"] = [
        {
            "transformation_id": "volatility-scaling.v1",
            "parameters": {"multiplier": "1.5"},
        },
        {
            "transformation_id": "liquidity-stress.v1",
            "parameters": {
                "volume_multiplier": "0.5",
                "cross_sectional_concentration": "0.75",
            },
        },
    ]
    for payload in (isolated, compound):
        draft = application.create_manual_recipe_draft(
            payload,
            author="researcher",
        )
        assert application.validate_recipe_draft(draft.draft_id).is_valid
        approved = application.approve_recipe_draft(
            draft.draft_id,
            actor="owner",
        )
        application.materialize_reference_path(approved.version_id)


def _command_identity(name: str):
    return (
        DiagnosticCommandId(f"{name}-command-58"),
        DiagnosticCommandIdempotencyKey(f"{name}-idempotency-58"),
    )


def _read_task(feature, task_id):
    context = DiagnosticTasksContext(task_id=task_id)
    feature.snapshot(context)
    state = feature.snapshot(context)
    assert state.task is not None
    return state.task


def test_live_revision_validation_approval_persist_and_invalidate(tmp_path) -> None:
    (
        source,
        artifact_store,
        engine,
        _application,
        _application_adapter,
        feature,
    ) = _persistent_three_layer_stack(tmp_path)
    workspace = DiagnosticTasksContext.workspace()
    feature.snapshot(workspace)
    inventory = feature.snapshot(workspace).last_reliable_inventory
    assert inventory is not None
    full_configuration = _configuration(inventory)
    baseline_configuration = DiagnosticTaskConfiguration.create(
        strategy_selections=full_configuration.strategy_selections,
        campaign_case_selections=tuple(
            item
            for item in full_configuration.campaign_case_selections
            if item.layer is DiagnosticCampaignLayer.BASELINE
        ),
    )
    created = feature.create_diagnostic_task(
        _command(
            baseline_configuration,
            command_id="create-command-58",
            idempotency_key="create-idempotency-58",
        )
    )
    assert created.affected_task_id is not None
    task_id = created.affected_task_id
    assert _read_task(feature, task_id).revision == 2

    revise_id, revise_key = _command_identity("revise")
    revised = feature.revise_configuration(
        ReviseDiagnosticTaskConfiguration(
            command_id=revise_id,
            idempotency_key=revise_key,
            task_id=task_id,
            expected_revision=2,
            configuration=full_configuration,
        )
    )

    assert revised.disposition is (
        DiagnosticTasksCommandDisposition.SYNCHRONOUS_COMPLETION
    )
    assert revised.task_handle is None
    assert revised.current_revision == 3
    replay = feature.revise_configuration(
        ReviseDiagnosticTaskConfiguration(
            command_id=revise_id,
            idempotency_key=revise_key,
            task_id=task_id,
            expected_revision=2,
            configuration=full_configuration,
        )
    )
    assert replay.disposition is DiagnosticTasksCommandDisposition.IDEMPOTENT_REPLAY
    assert replay.current_revision == 3

    validate_id, validate_key = _command_identity("validate")
    validation = feature.validate_configuration(
        ValidateDiagnosticTaskConfiguration(
            command_id=validate_id,
            idempotency_key=validate_key,
            task_id=task_id,
            expected_revision=3,
        )
    )

    assert validation.disposition is (
        DiagnosticTasksCommandDisposition.ASYNCHRONOUS_ACCEPTANCE
    )
    assert validation.task_handle is not None
    assert validation.task_handle.phase is TaskPhase.QUEUED
    validated_task = _read_task(feature, task_id)
    assert validated_task.revision == 3
    assert validated_task.lifecycle is DiagnosticTaskLifecycle.AWAITING_APPROVAL
    assert validated_task.validation.state is DiagnosticTaskValidationState.VALID
    assert validated_task.validation.validated_revision == 3
    assert (
        validated_task.validation.configuration_content_identity
        == full_configuration.content_identity
    )
    assert validated_task.validation.validation_id is not None
    assert validated_task.validation.validation_revision == 1
    assert validated_task.validation.policy_identities
    assert validated_task.validation.findings == ()
    assert validated_task.task_handles[-1].phase is TaskPhase.COMPLETED
    assert validated_task.capabilities.can_revise
    assert validated_task.capabilities.can_validate
    assert validated_task.capabilities.can_approve

    approve_id, approve_key = _command_identity("approve")
    approved = feature.approve_configuration(
        ApproveDiagnosticTaskConfiguration(
            command_id=approve_id,
            idempotency_key=approve_key,
            task_id=task_id,
            expected_revision=3,
            validation_id=validated_task.validation.validation_id,
            validation_revision=(
                validated_task.validation.validation_revision
            ),
            validated_revision=3,
            configuration_content_id=full_configuration.content_identity,
            actor_id=DiagnosticActorId("research-owner"),
        )
    )

    assert approved.disposition is (
        DiagnosticTasksCommandDisposition.SYNCHRONOUS_COMPLETION
    )
    assert approved.task_handle is None
    approved_task = _read_task(feature, task_id)
    assert approved_task.lifecycle is DiagnosticTaskLifecycle.APPROVED
    assert approved_task.approval is not None
    assert approved_task.approval.approved_revision == 3
    assert (
        approved_task.approval.configuration_content_identity
        == full_configuration.content_identity
    )
    assert (
        approved_task.approval.validation_id
        == approved_task.validation.validation_id
    )
    assert approved_task.approval.validation_revision == 1
    assert approved_task.approval.policy_identities
    assert approved_task.approval.actor_identity == DiagnosticActorId(
        "research-owner"
    )
    assert approved_task.capabilities.can_revise
    assert approved_task.capabilities.can_validate
    assert not approved_task.capabilities.can_approve
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM diagnostic_recipe_approvals")
        ).scalar_one() == 3
        assert connection.execute(
            text("SELECT COUNT(*) FROM diagnostic_campaigns")
        ).scalar_one() == 0

    with engine.begin() as connection:
        findings_json = connection.execute(
            text(
                "SELECT findings_json FROM diagnostic_task_validations "
                "WHERE validation_id = :validation_id"
            ),
            {
                "validation_id": (
                    approved_task.validation.validation_id.value
                )
            },
        ).scalar_one()
        connection.execute(
            text(
                "UPDATE diagnostic_task_validations "
                "SET findings_json = '{}' "
                "WHERE validation_id = :validation_id"
            ),
            {
                "validation_id": (
                    approved_task.validation.validation_id.value
                )
            },
        )
    degraded = feature.snapshot(DiagnosticTasksContext(task_id=task_id))
    assert degraded.presentation is DiagnosticTasksPresentationState.DEGRADED
    assert degraded.task == approved_task
    assert degraded.error is not None
    assert degraded.error.code == "diagnostic_task_read_failed"
    assert "JSON" not in degraded.error.message
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE diagnostic_task_validations "
                "SET findings_json = :findings_json "
                "WHERE validation_id = :validation_id"
            ),
            {
                "findings_json": findings_json,
                "validation_id": (
                    approved_task.validation.validation_id.value
                ),
            },
        )

    feature.close()
    restarted_application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=artifact_store,
        recipe_clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
        diagnostic_task_clock=lambda: datetime(
            2030,
            1,
            4,
            tzinfo=timezone.utc,
        ),
    )
    restarted_application.start()
    restarted_application.initialize_persistence(engine)
    restarted = LiveDiagnosticTasksAdapter(
        application=LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
            restarted_application
        )
    )
    restored = _read_task(restarted, task_id)
    assert restored.validation == approved_task.validation
    assert restored.approval == approved_task.approval

    invalidate_id, invalidate_key = _command_identity("invalidate")
    invalidated = restarted.revise_configuration(
        ReviseDiagnosticTaskConfiguration(
            command_id=invalidate_id,
            idempotency_key=invalidate_key,
            task_id=task_id,
            expected_revision=3,
            configuration=baseline_configuration,
        )
    )
    assert invalidated.current_revision == 4
    corrected = _read_task(restarted, task_id)
    assert corrected.revision == 4
    assert corrected.lifecycle is DiagnosticTaskLifecycle.DRAFT
    assert (
        corrected.validation.state
        is DiagnosticTaskValidationState.NOT_VALIDATED
    )
    assert corrected.approval is None
    assert corrected.configuration == baseline_configuration
    assert corrected.capabilities.can_revise
    assert corrected.capabilities.can_validate
    assert not corrected.capabilities.can_approve
    restarted.close()


def test_stale_revision_and_invalid_validation_reject_without_campaign(
    tmp_path,
) -> None:
    (
        _source,
        _artifact_store,
        engine,
        _application,
        _application_adapter,
        feature,
    ) = _persistent_three_layer_stack(tmp_path)
    workspace = DiagnosticTasksContext.workspace()
    feature.snapshot(workspace)
    inventory = feature.snapshot(workspace).last_reliable_inventory
    assert inventory is not None
    full_configuration = _configuration(inventory)
    baseline_configuration = DiagnosticTaskConfiguration.create(
        strategy_selections=full_configuration.strategy_selections,
        campaign_case_selections=tuple(
            item
            for item in full_configuration.campaign_case_selections
            if item.layer is DiagnosticCampaignLayer.BASELINE
        ),
    )
    created = feature.create_diagnostic_task(
        _command(
            baseline_configuration,
            command_id="invalid-create-command-58",
            idempotency_key="invalid-create-idempotency-58",
        )
    )
    assert created.affected_task_id is not None
    task_id = created.affected_task_id
    stale_id, stale_key = _command_identity("stale-revise")

    stale = feature.revise_configuration(
        ReviseDiagnosticTaskConfiguration(
            command_id=stale_id,
            idempotency_key=stale_key,
            task_id=task_id,
            expected_revision=1,
            configuration=full_configuration,
        )
    )

    assert stale.disposition is DiagnosticTasksCommandDisposition.REJECTED
    assert stale.rejection_reason is (
        DiagnosticTasksApplicationCommandRejectionReason.STALE_EXPECTED_REVISION
    )
    assert stale.current_revision == 2
    assert stale.task_handle is None
    validate_id, validate_key = _command_identity("invalid-validate")
    validation = feature.validate_configuration(
        ValidateDiagnosticTaskConfiguration(
            command_id=validate_id,
            idempotency_key=validate_key,
            task_id=task_id,
            expected_revision=2,
        )
    )
    assert validation.accepted
    invalid_task = _read_task(feature, task_id)
    assert invalid_task.validation.state is DiagnosticTaskValidationState.INVALID
    assert {
        finding.code.value for finding in invalid_task.validation.findings
    } >= {
        "campaign.layer.isolated_sensitivity_required",
        "campaign.layer.compound_required",
    }
    approve_id, approve_key = _command_identity("invalid-approve")
    rejected_approval = feature.approve_configuration(
        ApproveDiagnosticTaskConfiguration(
            command_id=approve_id,
            idempotency_key=approve_key,
            task_id=task_id,
            expected_revision=2,
            validation_id=invalid_task.validation.validation_id,
            validation_revision=(
                invalid_task.validation.validation_revision
            ),
            validated_revision=2,
            configuration_content_id=baseline_configuration.content_identity,
            actor_id=DiagnosticActorId("research-owner"),
        )
    )
    assert rejected_approval.disposition is (
        DiagnosticTasksCommandDisposition.REJECTED
    )
    assert rejected_approval.rejection_reason is (
        DiagnosticTasksApplicationCommandRejectionReason.VALIDATION_FAILED
    )
    assert rejected_approval.task_handle is None
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT COUNT(*) FROM diagnostic_campaigns"
        ).scalar_one() == 0
    feature.close()


def test_live_validation_emits_typed_findings_for_each_authority_mismatch(
    tmp_path,
) -> None:
    (
        _source,
        _artifact_store,
        engine,
        _application,
        _application_adapter,
        feature,
    ) = _persistent_three_layer_stack(tmp_path)
    workspace = DiagnosticTasksContext.workspace()
    feature.snapshot(workspace)
    inventory = feature.snapshot(workspace).last_reliable_inventory
    assert inventory is not None
    full_configuration = _configuration(inventory)
    baseline_configuration = DiagnosticTaskConfiguration.create(
        strategy_selections=full_configuration.strategy_selections,
        campaign_case_selections=tuple(
            item
            for item in full_configuration.campaign_case_selections
            if item.layer is DiagnosticCampaignLayer.BASELINE
        ),
    )
    created = feature.create_diagnostic_task(
        _command(
            baseline_configuration,
            command_id="authority-finding-create-command-58",
            idempotency_key="authority-finding-create-key-58",
        )
    )
    assert created.affected_task_id is not None
    persisted_task_id = created.affected_task_id.value
    with engine.begin() as connection:
        stored_json = connection.execute(
            text(
                "SELECT configuration_json FROM diagnostic_tasks "
                "WHERE task_id = :task_id"
            ),
            {"task_id": persisted_task_id},
        ).scalar_one()
        stored = PersistedDiagnosticTaskConfiguration.from_storage_dict(
            json.loads(str(stored_json))
        )
        tampered = replace(
            stored,
            content_identity="pending",
            strategy_selections=(
                replace(
                    stored.strategy_selections[0],
                    strategy_version="tampered-version",
                    compatibility_manifest_hash="sha256:tampered-manifest",
                ),
                *stored.strategy_selections[1:],
            ),
            campaign_case_selections=(
                replace(
                    stored.campaign_case_selections[0],
                    recipe_content_hash="sha256:tampered-recipe",
                ),
            ),
        )
        tampered = replace(
            tampered,
            content_identity=tampered.calculated_content_identity(),
        )
        connection.execute(
            text(
                "UPDATE diagnostic_tasks "
                "SET configuration_content_id = :content_identity, "
                "configuration_json = :configuration_json "
                "WHERE task_id = :task_id"
            ),
            {
                "content_identity": tampered.content_identity,
                "configuration_json": json.dumps(
                    tampered.to_storage_dict(),
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                "task_id": persisted_task_id,
            },
        )

    validate_id, validate_key = _command_identity("authority-findings")
    result = feature.validate_configuration(
        ValidateDiagnosticTaskConfiguration(
            command_id=validate_id,
            idempotency_key=validate_key,
            task_id=created.affected_task_id,
            expected_revision=2,
        )
    )

    assert result.accepted
    task = _read_task(feature, created.affected_task_id)
    assert task.validation.state is DiagnosticTaskValidationState.INVALID
    by_code = {
        finding.code.value: finding
        for finding in task.validation.findings
    }
    assert "configuration.authoritative_integrity" not in by_code
    assert isinstance(
        by_code["strategy.version_mismatch"].reference,
        DiagnosticStrategySelectionReference,
    )
    assert isinstance(
        by_code["strategy.compatibility_manifest_mismatch"].reference,
        DiagnosticStrategySelectionReference,
    )
    assert isinstance(
        by_code["campaign.recipe_content_hash_mismatch"].reference,
        DiagnosticCampaignCaseSelectionReference,
    )
    feature.close()


def test_live_pending_validation_disables_and_rejects_approval_until_recovery(
    tmp_path,
) -> None:
    (
        _source,
        _artifact_store,
        engine,
        application,
        _application_adapter,
        feature,
    ) = _persistent_three_layer_stack(tmp_path)
    workspace = DiagnosticTasksContext.workspace()
    feature.snapshot(workspace)
    inventory = feature.snapshot(workspace).last_reliable_inventory
    assert inventory is not None
    configuration = _configuration(inventory)
    created = feature.create_diagnostic_task(
        _command(
            configuration,
            command_id="pending-live-create-command-58",
            idempotency_key="pending-live-create-key-58",
        )
    )
    assert created.affected_task_id is not None
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER reject_live_validation_completion "
            "BEFORE UPDATE ON diagnostic_task_handles "
            "WHEN NEW.result_code = "
            "'diagnostic_task_configuration_valid' "
            "BEGIN SELECT RAISE(FAIL, 'injected live completion failure'); "
            "END"
        )
    validate_id, validate_key = _command_identity("pending-live-validate")
    accepted = feature.validate_configuration(
        ValidateDiagnosticTaskConfiguration(
            command_id=validate_id,
            idempotency_key=validate_key,
            task_id=created.affected_task_id,
            expected_revision=2,
        )
    )
    assert accepted.accepted
    pending = _read_task(feature, created.affected_task_id)
    assert pending.validation.state is DiagnosticTaskValidationState.VALID
    assert pending.validation.task_handle_id is not None
    pending_handle = next(
        handle
        for handle in pending.task_handles
        if handle.identity == pending.validation.task_handle_id
    )
    assert pending_handle.phase is TaskPhase.QUEUED
    assert not pending.capabilities.can_approve
    approve_id, approve_key = _command_identity("pending-live-approve")
    rejected = feature.approve_configuration(
        ApproveDiagnosticTaskConfiguration(
            command_id=approve_id,
            idempotency_key=approve_key,
            task_id=created.affected_task_id,
            expected_revision=2,
            validation_id=pending.validation.validation_id,
            validation_revision=pending.validation.validation_revision,
            validated_revision=2,
            configuration_content_id=configuration.content_identity,
            actor_id=DiagnosticActorId("research-owner"),
        )
    )
    assert rejected.rejection_reason is (
        DiagnosticTasksApplicationCommandRejectionReason.VALIDATION_PENDING
    )
    assert rejected.retryable
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "DROP TRIGGER reject_live_validation_completion"
        )
    application.initialize_persistence(engine)
    recovered = _read_task(feature, created.affected_task_id)
    recovered_handle = next(
        handle
        for handle in recovered.task_handles
        if handle.identity == recovered.validation.task_handle_id
    )
    assert recovered_handle.phase is TaskPhase.COMPLETED
    assert recovered.capabilities.can_approve
    feature.close()
