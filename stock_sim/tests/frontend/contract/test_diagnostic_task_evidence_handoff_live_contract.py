from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from app.event_bridge import EventBridge
from app.features import (
    DeterministicFakeDiagnosticTasksAdapter,
    DiagnosticEvidencePackageId,
    DiagnosticTaskId,
    DiagnosticTaskPresentation,
    DiagnosticTasksContext,
    DiagnosticTasksFeature,
    EvidenceAndFindingsPresentationState,
    FormalDiagnosticCampaignId,
    LiveDiagnosticTasksAdapter,
    LiveEvidenceAndFindingsAdapter,
    LiveStrategyDiagnosticsV1ApplicationAdapter,
    LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter,
    ReproductionManifestAvailability,
    ReproductionManifestId,
    RetryFailedCampaignNode,
    StartFormalDiagnosticCampaign,
    StrategyRunId,
    V1JourneySelector,
)
from app.features.diagnostic_tasks_application import (
    DiagnosticCommandId,
    DiagnosticCommandIdempotencyKey,
)
from strategy_diagnostics import create_diagnostics_application
from strategy_diagnostics.diagnostic_evidence_storage import (
    JsonDiagnosticEvidenceArtifactStore,
)
from tests.frontend.contract.test_diagnostic_task_campaign_start_live_contract import (
    _approved_formal_task,
    _formal_live_stack,
)
from tests.frontend.contract.test_diagnostic_task_failed_node_retry_live_contract import (
    _FailFirstDecisionPTradeHost,
)
from tests.frontend.contract.test_diagnostic_task_revision_approval_live_contract import (
    _read_task,
)
from tests.frontend.contract.test_strategy_diagnostics_v1_run_monitoring_live_contract import (
    _DirectExecutor,
)


class _CorruptingEvidenceArtifactStore:
    def __init__(self, root) -> None:
        self._delegate = JsonDiagnosticEvidenceArtifactStore(root)

    def put(self, payload: Mapping[str, object]) -> str:
        return self._delegate.put(payload)

    def get(self, artifact_hash: str) -> dict[str, object]:
        payload = self._delegate.get(artifact_hash)
        return {**payload, "_integrity_test_corruption": True}


@dataclass(frozen=True)
class _EvidenceConformanceHarness:
    feature: DiagnosticTasksFeature
    complete: Callable[[DiagnosticTaskId, FormalDiagnosticCampaignId], None]
    disconnect: Callable[[], None]
    reconnect: Callable[[], None]


@dataclass(frozen=True)
class _EvidenceFailureConformanceHarness:
    feature: DiagnosticTasksFeature
    complete: Callable[[DiagnosticTaskId, FormalDiagnosticCampaignId], None]
    availability: ReproductionManifestAvailability
    expects_package: bool
    verify: Callable[[DiagnosticTaskPresentation], None]


@pytest.fixture(params=("live", "fake"))
def evidence_conformance_harness(
    request,
    tmp_path,
):
    (
        _source,
        _artifact_store,
        engine,
        application,
        application_adapter,
        initial_feature,
    ) = _formal_live_stack(tmp_path)
    if request.param == "live":
        initial_feature.close()
        bridge = EventBridge(subscribe_backend=False)
        feature = LiveDiagnosticTasksAdapter(
            application=application_adapter,
            event_bridge=bridge,
        )

        def complete(
            _task_id: DiagnosticTaskId,
            campaign_id: FormalDiagnosticCampaignId,
        ) -> None:
            application.advance_diagnostic_campaign(
                campaign_id.value,
                max_cases=64,
                nodes_per_batch=10_000,
            )

        yield _EvidenceConformanceHarness(
            feature=feature,
            complete=complete,
            disconnect=bridge.mark_disconnected,
            reconnect=bridge.mark_reconnected,
        )
        feature.close()
        bridge.stop()
        engine.dispose()
        return

    workspace = DiagnosticTasksContext.workspace()
    initial_feature.snapshot(workspace)
    inventory = initial_feature.snapshot(
        workspace
    ).last_reliable_inventory
    initial_feature.close()
    engine.dispose()
    assert inventory is not None
    fake = DeterministicFakeDiagnosticTasksAdapter(inventory=inventory)

    def complete_fake(
        task_id: DiagnosticTaskId,
        _campaign_id: FormalDiagnosticCampaignId,
    ) -> None:
        fake.advance_evidence_available(task_id)

    yield _EvidenceConformanceHarness(
        feature=fake,
        complete=complete_fake,
        disconnect=fake.advance_to_disconnected,
        reconnect=fake.advance_to_reconnected,
    )
    fake.close()


@pytest.fixture(params=("live", "fake"))
def retry_evidence_conformance_harness(
    request,
    tmp_path,
):
    (
        _source,
        _artifact_store,
        engine,
        application,
        _application_adapter,
        initial_feature,
    ) = _formal_live_stack(
        tmp_path,
        ptrade_host=_FailFirstDecisionPTradeHost(),
    )
    if request.param == "live":

        def complete(
            _task_id: DiagnosticTaskId,
            campaign_id: FormalDiagnosticCampaignId,
        ) -> None:
            application.advance_diagnostic_campaign(
                campaign_id.value,
                max_cases=64,
                nodes_per_batch=10_000,
            )

        yield _EvidenceConformanceHarness(
            feature=initial_feature,
            complete=complete,
            disconnect=lambda: None,
            reconnect=lambda: None,
        )
        initial_feature.close()
        engine.dispose()
        return

    workspace = DiagnosticTasksContext.workspace()
    initial_feature.snapshot(workspace)
    inventory = initial_feature.snapshot(
        workspace
    ).last_reliable_inventory
    initial_feature.close()
    engine.dispose()
    assert inventory is not None
    fake = DeterministicFakeDiagnosticTasksAdapter(
        inventory=inventory,
        fail_first_campaign_node=True,
    )

    def complete_fake(
        task_id: DiagnosticTaskId,
        _campaign_id: FormalDiagnosticCampaignId,
    ) -> None:
        fake.advance_evidence_available(task_id)

    yield _EvidenceConformanceHarness(
        feature=fake,
        complete=complete_fake,
        disconnect=lambda: None,
        reconnect=lambda: None,
    )
    fake.close()


@pytest.fixture(
    params=("live-failed", "fake-failed", "live-partial", "fake-partial")
)
def evidence_failure_conformance_harness(
    request,
    tmp_path,
):
    lane, state = request.param.split("-", maxsplit=1)
    evidence_root = tmp_path / f"{state}-evidence"
    evidence_store = (
        _CorruptingEvidenceArtifactStore(evidence_root)
        if state == "failed"
        else JsonDiagnosticEvidenceArtifactStore(evidence_root)
    )
    (
        _source,
        _artifact_store,
        engine,
        application,
        _application_adapter,
        initial_feature,
    ) = _formal_live_stack(
        tmp_path,
        evidence_artifact_store=evidence_store,
    )
    availability = (
        ReproductionManifestAvailability.FAILED
        if state == "failed"
        else ReproductionManifestAvailability.PARTIAL
    )
    if lane == "live":

        def complete(
            _task_id: DiagnosticTaskId,
            campaign_id: FormalDiagnosticCampaignId,
        ) -> None:
            if state == "partial":
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "CREATE TRIGGER reject_wave2_manifest_insert "
                            "BEFORE INSERT ON "
                            "diagnostic_reproduction_manifests "
                            "BEGIN SELECT RAISE("
                            "ABORT, 'manifest integrity failure'); END"
                        )
                    )
            application.advance_diagnostic_campaign(
                campaign_id.value,
                max_cases=64,
                nodes_per_batch=10_000,
            )

        def verify(task: DiagnosticTaskPresentation) -> None:
            if state == "failed":
                assert task.handoff.evidence_package_id is None
                return
            assert task.handoff.evidence_package_id is not None
            package = application.diagnostic_evidence_status(
                task.handoff.evidence_package_id.value
            )
            assert task.handoff.campaign_id is not None
            assert package.campaign_id == task.handoff.campaign_id.value
            assert (
                application.reproduction_manifests(
                    package.evidence_package_id
                )
                == ()
            )

        yield _EvidenceFailureConformanceHarness(
            feature=initial_feature,
            complete=complete,
            availability=availability,
            expects_package=state == "partial",
            verify=verify,
        )
        initial_feature.close()
        engine.dispose()
        return

    workspace = DiagnosticTasksContext.workspace()
    initial_feature.snapshot(workspace)
    inventory = initial_feature.snapshot(
        workspace
    ).last_reliable_inventory
    initial_feature.close()
    engine.dispose()
    assert inventory is not None
    fake = DeterministicFakeDiagnosticTasksAdapter(inventory=inventory)

    def complete_fake(
        task_id: DiagnosticTaskId,
        _campaign_id: FormalDiagnosticCampaignId,
    ) -> None:
        if state == "failed":
            fake.advance_evidence_failed(task_id)
        else:
            fake.advance_evidence_partial(task_id)

    yield _EvidenceFailureConformanceHarness(
        feature=fake,
        complete=complete_fake,
        availability=availability,
        expects_package=state == "partial",
        verify=lambda _task: None,
    )
    fake.close()


def test_completed_formal_task_hands_real_evidence_to_existing_feature(
    tmp_path,
) -> None:
    (
        _source,
        _artifact_store,
        engine,
        application,
        _application_adapter,
        diagnostic_tasks,
    ) = _formal_live_stack(tmp_path)
    approved = _approved_formal_task(diagnostic_tasks)
    accepted = diagnostic_tasks.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId("start-command-63"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "start-idempotency-63"
            ),
            task_id=approved.task_id,
            expected_revision=approved.revision,
            approved_revision=approved.revision,
        )
    )
    assert accepted.affected_campaign_id is not None
    campaign_id = accepted.affected_campaign_id
    task_context = DiagnosticTasksContext(approved.task_id)
    pending = diagnostic_tasks.snapshot(task_context)
    assert pending.task is not None
    assert pending.task.handoff.evidence_package_id is None
    assert pending.task.handoff.reproduction_manifest_id is None
    assert pending.reproduction_manifest_availability is (
        ReproductionManifestAvailability.NOT_YET_AVAILABLE
    )

    completed_campaign = application.advance_diagnostic_campaign(
        campaign_id.value,
        max_cases=64,
        nodes_per_batch=10_000,
    )

    assert completed_campaign.status == "completed"
    completed = _read_task(diagnostic_tasks, approved.task_id)
    assert completed.handoff.evidence_package_id is not None
    assert completed.handoff.reproduction_manifest_id is not None
    package_id = completed.handoff.evidence_package_id
    manifest_id = completed.handoff.reproduction_manifest_id
    package = application.diagnostic_evidence_status(package_id.value)
    manifests = application.reproduction_manifests(package_id.value)
    assert package.campaign_id == campaign_id.value
    assert manifests
    assert {item.evidence_package_id for item in manifests} == {
        package_id.value
    }
    selected_manifest = next(
        item for item in manifests if item.manifest_id == manifest_id.value
    )
    handed_run_ids = {
        run.run_id.value
        for node in completed.handoff.campaign_nodes
        for attempt in node.attempts
        for run in attempt.runs
    }
    handed_manifest_by_run = {
        run.run_id.value: run.reproduction_manifest_id.value
        for node in completed.handoff.campaign_nodes
        for attempt in node.attempts
        for run in attempt.runs
        if run.reproduction_manifest_id is not None
    }
    assert {item.run_id for item in manifests} == handed_run_ids
    assert handed_manifest_by_run == {
        item.run_id: item.manifest_id for item in manifests
    }
    assert selected_manifest.run_id in handed_run_ids

    read_model = LiveStrategyDiagnosticsV1ApplicationAdapter(
        application,
        engine,
        clock=lambda: datetime(2030, 1, 3, tzinfo=timezone.utc),
    )
    selector = V1JourneySelector(
        campaign_id=FormalDiagnosticCampaignId(campaign_id.value),
        run_id=StrategyRunId(selected_manifest.run_id),
        evidence_package_id=DiagnosticEvidencePackageId(package_id.value),
        manifest_id=ReproductionManifestId(manifest_id.value),
    )
    resolved = read_model.resolve_journey(selector)
    assert resolved.value is not None
    bridge = EventBridge(subscribe_backend=False)
    evidence = LiveEvidenceAndFindingsAdapter(
        application_read_model=read_model,
        event_bridge=bridge,
        journey_selector=selector,
        clock=lambda: datetime(2030, 1, 3, tzinfo=timezone.utc),
        executor=_DirectExecutor(),
    )

    state = evidence.snapshot(resolved.value.evidence_context)

    assert state.presentation is EvidenceAndFindingsPresentationState.READY
    assert state.last_reliable_data is not None
    assert state.last_reliable_data.evidence_package_id == package_id
    assert (
        state.last_reliable_data.selection.reproduction_manifest_id
        == manifest_id
    )
    task_state = diagnostic_tasks.snapshot(task_context)
    assert task_state.reproduction_manifest_availability is (
        ReproductionManifestAvailability.AVAILABLE
    )
    assert task_state.reproduction_manifest_id == manifest_id
    evidence.close()
    bridge.stop()
    diagnostic_tasks.close()
    engine.dispose()


def test_live_and_fake_share_available_handoff_and_recovery_conformance(
    evidence_conformance_harness: _EvidenceConformanceHarness,
) -> None:
    feature = evidence_conformance_harness.feature
    approved = _approved_formal_task(feature)
    accepted = feature.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId("start-command-63-conformance"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "start-idempotency-63-conformance"
            ),
            task_id=approved.task_id,
            expected_revision=approved.revision,
            approved_revision=approved.revision,
        )
    )
    assert accepted.affected_campaign_id is not None
    task_context = DiagnosticTasksContext(approved.task_id)
    pending = _read_task(feature, approved.task_id)
    assert pending.handoff.reproduction_manifest_availability is (
        ReproductionManifestAvailability.NOT_YET_AVAILABLE
    )
    assert pending.handoff.evidence_error is None

    evidence_conformance_harness.complete(
        approved.task_id,
        accepted.affected_campaign_id,
    )
    available = _read_task(feature, approved.task_id)
    assert available.lifecycle.value == "completed"
    assert available.handoff.campaign_id == accepted.affected_campaign_id
    assert available.handoff.evidence_package_id is not None
    assert available.handoff.reproduction_manifest_id is not None
    assert available.handoff.evidence_error is None
    assert available.handoff.reproduction_manifest_availability is (
        ReproductionManifestAvailability.AVAILABLE
    )
    handed_manifests = tuple(
        run.reproduction_manifest_id
        for node in available.handoff.campaign_nodes
        for attempt in node.attempts
        for run in attempt.runs
    )
    assert handed_manifests
    assert all(item is not None for item in handed_manifests)
    assert len(set(handed_manifests)) == len(handed_manifests)

    evidence_conformance_harness.disconnect()
    disconnected = feature.snapshot(task_context)
    assert disconnected.task == available
    assert disconnected.reproduction_manifest_availability is (
        ReproductionManifestAvailability.AVAILABLE
    )
    assert (
        disconnected.reproduction_manifest_id
        == available.handoff.reproduction_manifest_id
    )

    evidence_conformance_harness.reconnect()
    reconnected = feature.snapshot(task_context)
    assert reconnected.task == available
    assert reconnected.reproduction_manifest_availability is (
        ReproductionManifestAvailability.AVAILABLE
    )
    assert (
        reconnected.reproduction_manifest_id
        == available.handoff.reproduction_manifest_id
    )


def test_retry_preserves_failed_history_and_manifests_only_accepted_attempts(
    retry_evidence_conformance_harness: _EvidenceConformanceHarness,
) -> None:
    diagnostic_tasks = retry_evidence_conformance_harness.feature
    approved = _approved_formal_task(diagnostic_tasks)
    accepted = diagnostic_tasks.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId("start-command-63-retry"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "start-idempotency-63-retry"
            ),
            task_id=approved.task_id,
            expected_revision=approved.revision,
            approved_revision=approved.revision,
        )
    )
    assert accepted.affected_campaign_id is not None
    failed = _read_task(diagnostic_tasks, approved.task_id)
    failed_node = next(
        node
        for node in failed.handoff.campaign_nodes
        if node.lifecycle.value == "failed"
    )
    failed_attempt = failed_node.attempts[-1]
    retried = diagnostic_tasks.retry_failed_campaign_node(
        RetryFailedCampaignNode(
            command_id=DiagnosticCommandId("retry-command-63"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "retry-idempotency-63"
            ),
            task_id=approved.task_id,
            campaign_node_id=failed_node.campaign_node_id,
            failed_attempt_id=failed_attempt.attempt_id,
            expected_revision=failed_node.revision,
        )
    )
    assert retried.accepted

    retry_evidence_conformance_harness.complete(
        approved.task_id,
        accepted.affected_campaign_id,
    )
    completed = _read_task(diagnostic_tasks, approved.task_id)

    assert completed.lifecycle.value == "completed"
    assert completed.handoff.ready_for_evidence_and_findings
    completed_retried_node = next(
        node
        for node in completed.handoff.campaign_nodes
        if node.campaign_node_id == failed_node.campaign_node_id
    )
    assert completed_retried_node.attempts[0].attempt_id == (
        failed_attempt.attempt_id
    )
    assert all(
        run.reproduction_manifest_id is None
        for run in completed_retried_node.attempts[0].runs
    )
    assert completed_retried_node.active_attempt_id is not None
    accepted_run_ids = {
        run.run_id.value
        for node in completed.handoff.campaign_nodes
        for attempt in node.attempts
        if attempt.attempt_id == node.active_attempt_id
        for run in attempt.runs
    }
    accepted_manifest_ids = {
        run.reproduction_manifest_id.value
        for node in completed.handoff.campaign_nodes
        for attempt in node.attempts
        if attempt.attempt_id == node.active_attempt_id
        for run in attempt.runs
        if run.reproduction_manifest_id is not None
    }
    assert accepted_run_ids
    assert len(accepted_run_ids) == len(accepted_manifest_ids)


def test_complete_evidence_handoff_survives_application_reopen(tmp_path) -> None:
    evidence_root = tmp_path / "evidence"
    (
        source,
        artifact_store,
        engine,
        application,
        _application_adapter,
        diagnostic_tasks,
    ) = _formal_live_stack(
        tmp_path,
        evidence_artifact_store=JsonDiagnosticEvidenceArtifactStore(
            evidence_root
        ),
    )
    approved = _approved_formal_task(diagnostic_tasks)
    accepted = diagnostic_tasks.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId("start-command-63-reopen"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "start-idempotency-63-reopen"
            ),
            task_id=approved.task_id,
            expected_revision=approved.revision,
            approved_revision=approved.revision,
        )
    )
    assert accepted.affected_campaign_id is not None
    campaign = application.advance_diagnostic_campaign(
        accepted.affected_campaign_id.value,
        max_cases=64,
        nodes_per_batch=10_000,
    )
    assert campaign.status == "completed"
    before = _read_task(diagnostic_tasks, approved.task_id)
    assert before.handoff.ready_for_evidence_and_findings
    diagnostic_tasks.close()

    restarted_application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=artifact_store,
        evidence_artifact_store=JsonDiagnosticEvidenceArtifactStore(
            evidence_root
        ),
        recipe_clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
        diagnostic_task_clock=lambda: datetime(
            2030,
            1,
            4,
            tzinfo=timezone.utc,
        ),
    )
    restarted_application.start()
    migration = restarted_application.initialize_persistence(engine)
    assert migration.current_revision == (
        "0021_diagnostic_selection_dependency_invalidation"
    )
    restarted = LiveDiagnosticTasksAdapter(
        application=(
            LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
                restarted_application
            )
        )
    )

    restored = _read_task(restarted, approved.task_id)

    assert restored.lifecycle == before.lifecycle
    assert restored.handoff == before.handoff
    assert restored.task_handles == before.task_handles
    assert restored.handoff.evidence_package_id is not None
    assert restored.handoff.reproduction_manifest_id is not None
    package = restarted_application.diagnostic_evidence_status(
        restored.handoff.evidence_package_id.value
    )
    manifests = restarted_application.reproduction_manifests(
        package.evidence_package_id
    )
    assert package.campaign_id == restored.handoff.campaign_id.value
    assert {
        item.manifest_id for item in manifests
    } == {
        run.reproduction_manifest_id.value
        for node in restored.handoff.campaign_nodes
        for attempt in node.attempts
        for run in attempt.runs
        if run.reproduction_manifest_id is not None
    }
    restarted.close()
    engine.dispose()


def test_live_and_fake_share_failed_and_partial_evidence_conformance(
    evidence_failure_conformance_harness: (
        _EvidenceFailureConformanceHarness
    ),
) -> None:
    diagnostic_tasks = evidence_failure_conformance_harness.feature
    approved = _approved_formal_task(diagnostic_tasks)
    accepted = diagnostic_tasks.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId("start-command-63-failure-state"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "start-idempotency-63-failure-state"
            ),
            task_id=approved.task_id,
            expected_revision=approved.revision,
            approved_revision=approved.revision,
        )
    )
    assert accepted.affected_campaign_id is not None
    evidence_failure_conformance_harness.complete(
        approved.task_id,
        accepted.affected_campaign_id,
    )
    terminal = _read_task(diagnostic_tasks, approved.task_id)

    assert terminal.lifecycle.value == "completed"
    assert terminal.handoff.campaign_id == accepted.affected_campaign_id
    assert terminal.handoff.campaign_lifecycle.value == "completed"
    assert (
        terminal.handoff.evidence_package_id is not None
    ) is evidence_failure_conformance_harness.expects_package
    assert terminal.handoff.reproduction_manifest_id is None
    assert terminal.handoff.evidence_error is not None
    assert (
        terminal.handoff.evidence_error.code
        == "diagnostic_evidence_integrity_failed"
    )
    assert not terminal.handoff.evidence_error.retryable
    assert terminal.handoff.reproduction_manifest_availability is (
        evidence_failure_conformance_harness.availability
    )
    terminal_view = diagnostic_tasks.snapshot(
        DiagnosticTasksContext(approved.task_id)
    )
    assert terminal_view.reproduction_manifest_availability is (
        evidence_failure_conformance_harness.availability
    )
    assert all(
        run.reproduction_manifest_id is None
        for node in terminal.handoff.campaign_nodes
        for attempt in node.attempts
        for run in attempt.runs
    )
    assert all(handle.identity.value for handle in terminal.task_handles)
    evidence_failure_conformance_harness.verify(terminal)


def test_duplicate_manifest_identity_graph_fails_closed(
    tmp_path,
    monkeypatch,
) -> None:
    (
        _source,
        _artifact_store,
        engine,
        application,
        _application_adapter,
        diagnostic_tasks,
    ) = _formal_live_stack(tmp_path)
    approved = _approved_formal_task(diagnostic_tasks)
    accepted = diagnostic_tasks.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId("start-command-63-duplicate"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "start-idempotency-63-duplicate"
            ),
            task_id=approved.task_id,
            expected_revision=approved.revision,
            approved_revision=approved.revision,
        )
    )
    assert accepted.affected_campaign_id is not None
    real_manifests_for = application._reproduction.manifests_for

    def duplicate_manifests(evidence_package_id: str):
        manifests = real_manifests_for(evidence_package_id)
        assert manifests
        return (*manifests, manifests[0])

    monkeypatch.setattr(
        application._reproduction,
        "manifests_for",
        duplicate_manifests,
    )

    campaign = application.advance_diagnostic_campaign(
        accepted.affected_campaign_id.value,
        max_cases=64,
        nodes_per_batch=10_000,
    )
    failed_closed = _read_task(diagnostic_tasks, approved.task_id)

    assert campaign.status == "completed"
    assert failed_closed.lifecycle.value == "completed"
    assert failed_closed.handoff.campaign_id == accepted.affected_campaign_id
    assert failed_closed.handoff.evidence_package_id is not None
    assert failed_closed.handoff.reproduction_manifest_id is None
    assert failed_closed.handoff.evidence_error is not None
    assert (
        failed_closed.handoff.evidence_error.code
        == "diagnostic_evidence_integrity_failed"
    )
    assert not failed_closed.handoff.evidence_error.retryable
    assert failed_closed.handoff.reproduction_manifest_availability is (
        ReproductionManifestAvailability.PARTIAL
    )
    assert all(
        run.reproduction_manifest_id is None
        for node in failed_closed.handoff.campaign_nodes
        for attempt in node.attempts
        for run in attempt.runs
    )
    diagnostic_tasks.close()
    engine.dispose()
