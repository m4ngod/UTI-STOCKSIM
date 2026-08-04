from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from threading import Event
from time import monotonic, sleep

import pytest
from sqlalchemy import create_engine, text

from app.features.run_monitoring import SourceGenerationId
from app.features.live_scenario_lab import LiveScenarioLabAdapter
from app.features.scenario_lab_application import (
    ApprovedScenarioRecipeVersionProjection,
    ApproveScenarioRecipeCommand,
    CreateAiAssistedScenarioRecipeDraftCommand,
    CreateScenarioRecipeDraftCommand,
    LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter,
    MaterializeApprovedScenarioRecipeCommand,
    RequestedExecutionAssumptionsProjection,
    RetryScenarioMaterializationCommand,
    ReviseScenarioRecipeDraftCommand,
    ScenarioLabActorId,
    ScenarioLabCommandContentIdentity,
    ScenarioLabCommandDisposition,
    ScenarioLabCommandId,
    ScenarioLabCommandMetadata,
    ScenarioLabIdempotencyIdentity,
    ScenarioRecipeAuthoringMode,
    ScenarioRecipeDataPolicy,
    ScenarioRecipeDraftPayload,
    ScenarioRecipeValidationId,
    ScenarioRecipeValidationSeverity,
    ValidateScenarioRecipeDraftCommand,
    canonical_scenario_lab_command_content_identity,
)
from app.features.scenario_lab import ScenarioLabContext
from app.event_bridge import EventBridge
from app.features.diagnostic_tasks_application import HistoricalMarketSegmentId
from strategy_diagnostics import (
    AIRecipeAssistantProviderError,
    AIRecipeAssistantRequest,
    AIRecipeAssistantResponse,
    AIRecipeDraftOutputV1,
    DeterministicFakeAIRecipeAssistant,
    InMemoryMarketPathArtifactStore,
    ScenarioRecipeV1,
    create_diagnostics_application,
)
from tests.strategy_diagnostics.test_recipe_lifecycle import (
    _RecipeFixtureSource,
    _baseline_payload,
)


class _ClaimObservingAssistant:
    def __init__(self, delegate, engine, command_id: str) -> None:
        self._delegate = delegate
        self._engine = engine
        self._command_id = command_id
        self.calls = 0
        self.observed_disposition: str | None = None

    @property
    def provider(self) -> str:
        return self._delegate.provider

    @property
    def model(self) -> str:
        return self._delegate.model

    @property
    def prompt_template_version(self) -> str:
        return self._delegate.prompt_template_version

    def draft(
        self,
        request: AIRecipeAssistantRequest,
    ) -> AIRecipeAssistantResponse:
        self.calls += 1
        with self._engine.connect() as connection:
            self.observed_disposition = connection.execute(
                text(
                    "SELECT disposition FROM diagnostic_scenario_lab_commands "
                    "WHERE command_id = :command_id"
                ),
                {"command_id": self._command_id},
            ).scalar_one_or_none()
        return self._delegate.draft(request)


class _ClaimObservingMarketPathArtifactStore(InMemoryMarketPathArtifactStore):
    def __init__(self, engine, command_id: str) -> None:
        super().__init__()
        self._engine = engine
        self._command_id = command_id
        self.observed_claim: tuple[str, str, str] | None = None

    def put(self, path):
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT command.disposition, task.phase, attempt.status "
                    "FROM diagnostic_scenario_lab_commands AS command "
                    "JOIN diagnostic_scenario_lab_task_handles AS task "
                    "ON task.command_id = command.command_id "
                    "JOIN diagnostic_scenario_materialization_attempts AS attempt "
                    "ON attempt.task_handle_id = task.task_handle_id "
                    "WHERE command.command_id = :command_id"
                ),
                {"command_id": self._command_id},
            ).one()
        self.observed_claim = tuple(row)
        return super().put(path)


class _BlockingMarketPathArtifactStore(InMemoryMarketPathArtifactStore):
    def __init__(self) -> None:
        super().__init__()
        self.started = Event()
        self.release = Event()

    def put(self, path):
        self.started.set()
        if not self.release.wait(timeout=3.0):
            raise OSError("blocking materializer fixture timed out")
        return super().put(path)


class _FailOnceMarketPathArtifactStore(InMemoryMarketPathArtifactStore):
    def __init__(self) -> None:
        super().__init__()
        self._failures_remaining = 1

    def put(self, path):
        if self._failures_remaining:
            self._failures_remaining -= 1
            raise OSError("retryable file-backed materializer fixture")
        return super().put(path)


class _ManualMaterializationScheduler:
    def __init__(self) -> None:
        self._callbacks: list[Callable[[], None]] = []

    def __call__(self, callback: Callable[[], None]) -> None:
        self._callbacks.append(callback)

    def run_all(self) -> None:
        while self._callbacks:
            self._callbacks.pop(0)()


def _metadata(
    *,
    command_id: str,
    idempotency: str,
    content: str,
    source_revision: object,
) -> ScenarioLabCommandMetadata:
    return ScenarioLabCommandMetadata(
        command_id=ScenarioLabCommandId(command_id),
        idempotency_identity=ScenarioLabIdempotencyIdentity(idempotency),
        canonical_content_identity=ScenarioLabCommandContentIdentity(content),
        expected_source_revision=source_revision,
        expected_source_generation=SourceGenerationId(1),
    )


def _payload(segment_id: object, *, name: str = "Baseline Draft") -> ScenarioRecipeDraftPayload:
    return ScenarioRecipeDraftPayload(
        name=name,
        historical_segment_id=HistoricalMarketSegmentId(str(segment_id)),
        transformations=(),
        requested_execution_assumptions=RequestedExecutionAssumptionsProjection(
            commission_bps="3",
            slippage_bps="0",
            max_fill_fraction="1",
            latency_nodes=0,
            allow_partial_fills=True,
        ),
        decision_cadence_minutes=30,
        materialization_seed=17,
        data_policy=ScenarioRecipeDataPolicy.POINT_IN_TIME,
        market_rule_profile_version="a-share-cash-equity.v1",
    )


def _canonicalize(command):
    return replace(
        command,
        metadata=replace(
            command.metadata,
            canonical_content_identity=(
                canonical_scenario_lab_command_content_identity(command)
            ),
        ),
    )


def _approve_exact_recipe(
    adapter: LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter,
    segment_id: object,
    *,
    suffix: str,
) -> ApprovedScenarioRecipeVersionProjection:
    source_revision = adapter.read_inventory().source_token
    assert source_revision is not None
    created = adapter.create_recipe_draft(
        _canonicalize(
            CreateScenarioRecipeDraftCommand(
                metadata=_metadata(
                    command_id=f"scenario-command-{suffix}-create",
                    idempotency=f"scenario-idempotency-{suffix}-create",
                    content=f"pending-{suffix}-create",
                    source_revision=source_revision,
                ),
                payload=_payload(segment_id, name=f"{suffix} Recipe"),
                author_id=ScenarioLabActorId(f"scenario-author-{suffix}"),
                authoring_mode=ScenarioRecipeAuthoringMode.MANUAL,
            )
        )
    )
    assert created.draft is not None
    source_revision = adapter.read_inventory().source_token
    assert source_revision is not None
    validated = adapter.validate_recipe_draft(
        _canonicalize(
            ValidateScenarioRecipeDraftCommand(
                metadata=_metadata(
                    command_id=f"scenario-command-{suffix}-validate",
                    idempotency=f"scenario-idempotency-{suffix}-validate",
                    content=f"pending-{suffix}-validate",
                    source_revision=source_revision,
                ),
                draft_id=created.draft.draft_id,
                expected_draft_revision=created.draft.revision,
                expected_payload_hash=created.draft.payload_hash,
            )
        )
    )
    assert validated.validation is not None
    assert validated.validation.is_valid
    source_revision = adapter.read_inventory().source_token
    assert source_revision is not None
    approved = adapter.approve_recipe(
        _canonicalize(
            ApproveScenarioRecipeCommand(
                metadata=_metadata(
                    command_id=f"scenario-command-{suffix}-approve",
                    idempotency=f"scenario-idempotency-{suffix}-approve",
                    content=f"pending-{suffix}-approve",
                    source_revision=source_revision,
                ),
                draft_id=created.draft.draft_id,
                expected_draft_revision=created.draft.revision,
                expected_payload_hash=created.draft.payload_hash,
                validation_id=validated.validation.validation_id,
                actor_id=ScenarioLabActorId(f"scenario-approver-{suffix}"),
            )
        )
    )
    assert approved.approved_version is not None
    return approved.approved_version


def _live_file_backed_adapter(tmp_path):
    source = _RecipeFixtureSource()
    engine = create_engine(f"sqlite:///{tmp_path / 'scenario-authoring.sqlite'}")
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
        recipe_clock=lambda: datetime(2026, 8, 4, 9, 0, tzinfo=timezone.utc),
    )
    application.start()
    application.initialize_persistence(engine)
    admission = application.admit_historical_segment(source.selection)
    assert admission.segment is not None
    return (
        engine,
        source,
        application,
        LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(application),
        admission.segment.segment_id,
    )


def test_live_recipe_commands_are_idempotent_immutable_and_file_backed(tmp_path) -> None:
    engine, source, _application, adapter, segment_id = _live_file_backed_adapter(
        tmp_path
    )
    source_revision = adapter.read_inventory().source_token
    assert source_revision is not None
    create = _canonicalize(CreateScenarioRecipeDraftCommand(
        metadata=_metadata(
            command_id="scenario-command-create-80",
            idempotency="scenario-idempotency-create-80",
            content="scenario-content-create-80",
            source_revision=source_revision,
        ),
        payload=_payload(segment_id),
        author_id=ScenarioLabActorId("scenario-author-80"),
        authoring_mode=ScenarioRecipeAuthoringMode.MANUAL,
    ))

    created = adapter.create_recipe_draft(create)
    replayed = adapter.create_recipe_draft(
        _canonicalize(replace(
            create,
            metadata=replace(
                create.metadata,
                command_id=ScenarioLabCommandId("scenario-command-create-replay-80"),
            ),
        ))
    )

    assert created.receipt.disposition is ScenarioLabCommandDisposition.ACCEPTED
    assert created.draft is not None
    assert created.draft.revision == 1
    assert created.draft.predecessor_draft_id is None
    assert created.draft.payload == create.payload
    assert replayed == created

    conflicted = adapter.create_recipe_draft(
        _canonicalize(replace(
            create,
            metadata=replace(
                create.metadata,
                command_id=ScenarioLabCommandId("scenario-command-create-conflict-80"),
                canonical_content_identity=ScenarioLabCommandContentIdentity(
                    "scenario-content-create-different-80"
                ),
            ),
            payload=_payload(segment_id, name="Different Draft"),
        ))
    )
    assert conflicted.receipt.disposition is ScenarioLabCommandDisposition.CONFLICT
    assert conflicted.draft is None

    source_revision = adapter.read_inventory().source_token
    assert source_revision is not None
    revise = _canonicalize(ReviseScenarioRecipeDraftCommand(
        metadata=_metadata(
            command_id="scenario-command-revise-80",
            idempotency="scenario-idempotency-revise-80",
            content="scenario-content-revise-80",
            source_revision=source_revision,
        ),
        predecessor_draft_id=created.draft.draft_id,
        expected_draft_revision=1,
        payload=_payload(segment_id, name="Successor Draft"),
        author_id=ScenarioLabActorId("scenario-author-80"),
    ))
    revised = adapter.revise_recipe_draft(revise)
    assert revised.receipt.disposition is ScenarioLabCommandDisposition.ACCEPTED
    assert revised.draft is not None
    assert revised.draft.revision == 2
    assert revised.draft.predecessor_draft_id == created.draft.draft_id
    assert revised.draft.draft_id != created.draft.draft_id

    post_revise_source_revision = adapter.read_inventory().source_token
    assert post_revise_source_revision is not None
    stale = adapter.revise_recipe_draft(
        _canonicalize(replace(
            revise,
            metadata=replace(
                revise.metadata,
                command_id=ScenarioLabCommandId("scenario-command-revise-stale-80"),
                idempotency_identity=ScenarioLabIdempotencyIdentity(
                    "scenario-idempotency-revise-stale-80"
                ),
                canonical_content_identity=ScenarioLabCommandContentIdentity(
                    "scenario-content-revise-stale-80"
                ),
                expected_source_revision=post_revise_source_revision,
            ),
        ))
    )
    assert stale.receipt.disposition is ScenarioLabCommandDisposition.CONFLICT
    assert stale.authoritative_draft_revision == 2

    source_revision = adapter.read_inventory().source_token
    assert source_revision is not None
    validated = adapter.validate_recipe_draft(
        _canonicalize(ValidateScenarioRecipeDraftCommand(
            metadata=_metadata(
                command_id="scenario-command-validate-80",
                idempotency="scenario-idempotency-validate-80",
                content="scenario-content-validate-80",
                source_revision=source_revision,
            ),
            draft_id=revised.draft.draft_id,
            expected_draft_revision=2,
            expected_payload_hash=revised.draft.payload_hash,
        ))
    )
    assert validated.receipt.disposition is ScenarioLabCommandDisposition.ACCEPTED
    assert validated.validation is not None
    assert validated.validation.is_valid is True
    assert validated.validation.draft_id == revised.draft.draft_id
    assert validated.validation.draft_revision == 2
    assert validated.validation.payload_hash == revised.draft.payload_hash
    assert validated.validation.findings == ()
    dependency = validated.validation.dependencies
    assert dependency.historical_segment_id.value == segment_id
    assert dependency.historical_segment_content_hash
    assert dependency.source_snapshot_id
    assert dependency.source_snapshot_content_hash
    assert dependency.recipe_schema_hash
    assert dependency.transformation_catalog_hash
    assert dependency.market_rule_profile_hash
    assert dependency.compatibility_observations

    reopened = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
    )
    reopened.start()
    reopened.initialize_persistence(engine)
    inventory = LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(
        reopened
    ).read_inventory().inventory
    assert inventory is not None
    assert tuple(item.draft_id for item in inventory.recipe_drafts) == (
        created.draft.draft_id,
        revised.draft.draft_id,
    )
    assert tuple(item.validation_id for item in inventory.recipe_validations) == (
        validated.validation.validation_id,
    )
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM diagnostic_scenario_lab_commands")
        ).scalar_one() == 3


def test_exact_recipe_approval_is_durable_idempotent_and_file_backed(
    tmp_path,
) -> None:
    engine, source, _application, adapter, segment_id = _live_file_backed_adapter(
        tmp_path
    )
    source_revision = adapter.read_inventory().source_token
    assert source_revision is not None
    created = adapter.create_recipe_draft(
        _canonicalize(
            CreateScenarioRecipeDraftCommand(
                metadata=_metadata(
                    command_id="scenario-command-create-81",
                    idempotency="scenario-idempotency-create-81",
                    content="scenario-content-create-81",
                    source_revision=source_revision,
                ),
                payload=_payload(segment_id),
                author_id=ScenarioLabActorId("scenario-author-81"),
                authoring_mode=ScenarioRecipeAuthoringMode.MANUAL,
            )
        )
    )
    assert created.draft is not None

    source_revision = adapter.read_inventory().source_token
    assert source_revision is not None
    validated = adapter.validate_recipe_draft(
        _canonicalize(
            ValidateScenarioRecipeDraftCommand(
                metadata=_metadata(
                    command_id="scenario-command-validate-81",
                    idempotency="scenario-idempotency-validate-81",
                    content="scenario-content-validate-81",
                    source_revision=source_revision,
                ),
                draft_id=created.draft.draft_id,
                expected_draft_revision=created.draft.revision,
                expected_payload_hash=created.draft.payload_hash,
            )
        )
    )
    assert validated.validation is not None
    assert validated.validation.is_valid is True

    source_revision = adapter.read_inventory().source_token
    assert source_revision is not None
    approval = _canonicalize(
        ApproveScenarioRecipeCommand(
            metadata=_metadata(
                command_id="scenario-command-approve-81",
                idempotency="scenario-idempotency-approve-81",
                content="scenario-content-approve-81",
                source_revision=source_revision,
            ),
            draft_id=created.draft.draft_id,
            expected_draft_revision=created.draft.revision,
            expected_payload_hash=created.draft.payload_hash,
            validation_id=validated.validation.validation_id,
            actor_id=ScenarioLabActorId("scenario-approver-81"),
        )
    )
    approved = adapter.approve_recipe(approval)
    replayed = adapter.approve_recipe(
        _canonicalize(
            replace(
                approval,
                metadata=replace(
                    approval.metadata,
                    command_id=ScenarioLabCommandId(
                        "scenario-command-approve-replay-81"
                    ),
                ),
            )
        )
    )

    assert approved.receipt.disposition is ScenarioLabCommandDisposition.ACCEPTED
    assert replayed == approved
    assert approved.approved_version is not None
    version = approved.approved_version
    assert approved.recipe_version_id == version.recipe_version_id
    assert approved.recipe_content_hash == version.content_hash
    assert version.recipe_id == created.draft.recipe_id
    assert version.version_number == 1
    assert version.payload == created.draft.payload
    assert version.approval.draft_id == created.draft.draft_id
    assert version.approval.draft_revision == created.draft.revision
    assert version.approval.payload_hash == created.draft.payload_hash
    assert version.approval.validation_id == validated.validation.validation_id
    assert version.approval.recipe_content_hash == (
        validated.validation.recipe_content_hash
    )
    assert version.approval.dependencies == validated.validation.dependencies
    assert version.approval.actor_id == ScenarioLabActorId(
        "scenario-approver-81"
    )
    assert version.authority_state.value == "current"
    assert version.can_materialize is True

    source_revision = adapter.read_inventory().source_token
    assert source_revision is not None
    duplicate_command = _canonicalize(
        ApproveScenarioRecipeCommand(
            metadata=_metadata(
                command_id="scenario-command-approve-duplicate-81",
                idempotency="scenario-idempotency-approve-duplicate-81",
                content="scenario-content-approve-duplicate-81",
                source_revision=source_revision,
            ),
            draft_id=created.draft.draft_id,
            expected_draft_revision=created.draft.revision,
            expected_payload_hash=created.draft.payload_hash,
            validation_id=validated.validation.validation_id,
            actor_id=ScenarioLabActorId("different-scenario-approver-81"),
        )
    )
    duplicate = adapter.approve_recipe(duplicate_command)
    duplicate_replay = adapter.approve_recipe(duplicate_command)
    assert duplicate.receipt.disposition is ScenarioLabCommandDisposition.REJECTED
    assert duplicate_replay == duplicate
    assert duplicate.approved_version is None
    with engine.connect() as connection:
        duplicate_journal = connection.execute(
            text(
                "SELECT disposition, result_kind, result_identity "
                "FROM diagnostic_scenario_lab_commands "
                "WHERE command_id = 'scenario-command-approve-duplicate-81'"
            )
        ).one()
    assert tuple(duplicate_journal) == (
        "rejected",
        "approval_rejection",
        created.draft.draft_id.value,
    )

    reopened = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
    )
    reopened.start()
    reopened.initialize_persistence(engine)
    inventory = LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(
        reopened
    ).read_inventory().inventory
    assert inventory is not None
    assert inventory.approved_recipe_versions == (version,)
    with engine.connect() as connection:
        command = connection.execute(
            text(
                "SELECT disposition, result_kind, result_identity "
                "FROM diagnostic_scenario_lab_commands "
                "WHERE command_id = 'scenario-command-approve-81'"
            )
        ).one()
    assert tuple(command) == (
        "accepted",
        "approved_recipe_version",
        version.recipe_version_id.value,
    )

    reopened_adapter = LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(
        reopened
    )
    source_revision = reopened_adapter.read_inventory().source_token
    assert source_revision is not None
    successor = reopened_adapter.revise_recipe_draft(
        _canonicalize(
            ReviseScenarioRecipeDraftCommand(
                metadata=_metadata(
                    command_id="scenario-command-revise-version-2-81",
                    idempotency="scenario-idempotency-revise-version-2-81",
                    content="scenario-content-revise-version-2-81",
                    source_revision=source_revision,
                ),
                predecessor_draft_id=created.draft.draft_id,
                expected_draft_revision=created.draft.revision,
                payload=_payload(segment_id, name="Immutable successor v2"),
                author_id=ScenarioLabActorId("scenario-author-81"),
                based_on_recipe_version_id=version.recipe_version_id,
            )
        )
    )
    assert successor.draft is not None
    source_revision = reopened_adapter.read_inventory().source_token
    assert source_revision is not None
    successor_validation = reopened_adapter.validate_recipe_draft(
        _canonicalize(
            ValidateScenarioRecipeDraftCommand(
                metadata=_metadata(
                    command_id="scenario-command-validate-version-2-81",
                    idempotency="scenario-idempotency-validate-version-2-81",
                    content="scenario-content-validate-version-2-81",
                    source_revision=source_revision,
                ),
                draft_id=successor.draft.draft_id,
                expected_draft_revision=successor.draft.revision,
                expected_payload_hash=successor.draft.payload_hash,
            )
        )
    )
    assert successor_validation.validation is not None
    assert successor_validation.validation.is_valid
    source_revision = reopened_adapter.read_inventory().source_token
    assert source_revision is not None
    successor_approval = reopened_adapter.approve_recipe(
        _canonicalize(
            ApproveScenarioRecipeCommand(
                metadata=_metadata(
                    command_id="scenario-command-approve-version-2-81",
                    idempotency="scenario-idempotency-approve-version-2-81",
                    content="scenario-content-approve-version-2-81",
                    source_revision=source_revision,
                ),
                draft_id=successor.draft.draft_id,
                expected_draft_revision=successor.draft.revision,
                expected_payload_hash=successor.draft.payload_hash,
                validation_id=successor_validation.validation.validation_id,
                actor_id=ScenarioLabActorId("scenario-approver-81"),
            )
        )
    )
    assert successor_approval.approved_version is not None
    version_2 = successor_approval.approved_version
    assert version_2.recipe_id == version.recipe_id
    assert version_2.version_number == 2
    assert version_2.based_on_recipe_version_id == version.recipe_version_id
    assert version_2.recipe_version_id != version.recipe_version_id
    assert version_2.content_hash != version.content_hash

    reopened_again = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
    )
    reopened_again.start()
    reopened_again.initialize_persistence(engine)
    reopened_inventory = LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(
        reopened_again
    ).read_inventory().inventory
    assert reopened_inventory is not None
    assert reopened_inventory.approved_recipe_versions == (version, version_2)


def test_legacy_public_approval_remains_visible_but_cannot_gain_new_authority(
    tmp_path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-approval.sqlite'}")
    source = _RecipeFixtureSource()
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
    )
    application.start()
    application.initialize_persistence(engine)
    admission = application.admit_historical_segment(source.selection)
    assert admission.segment is not None
    draft = application.create_manual_recipe_draft(
        _baseline_payload(admission.segment.segment_id),
        author="legacy-researcher",
    )
    validation = application.validate_recipe_draft(draft.draft_id)
    assert validation.is_valid
    legacy = application.approve_recipe_draft(
        draft.draft_id,
        actor="legacy-owner",
    )

    inventory = LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(
        application
    ).read_inventory().inventory

    assert inventory is not None
    assert len(inventory.approved_recipe_versions) == 1
    projected = inventory.approved_recipe_versions[0]
    assert projected.recipe_version_id.value == legacy.version_id
    assert projected.recipe_id == legacy.recipe_id
    assert projected.version_number == legacy.version_number
    assert projected.content_hash == legacy.content_hash
    assert projected.approval.draft_id.value == draft.draft_id
    assert projected.approval.payload_hash == validation.payload_hash
    assert projected.approval.approval_id.value.startswith("recipe_approval_")
    assert projected.approval.draft_revision is None
    assert projected.approval.validation_id is None
    assert projected.approval.dependencies is None
    assert projected.authority_state.value == "unavailable"
    assert projected.can_materialize is False
    assert projected.authority_reasons

    reopened = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
    )
    reopened.start()
    reopened.initialize_persistence(engine)
    reopened_inventory = LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(
        reopened
    ).read_inventory().inventory
    assert reopened_inventory is not None
    assert reopened_inventory.approved_recipe_versions == (projected,)


def test_recipe_approval_rejects_nonexact_validation_without_side_effects(
    tmp_path,
) -> None:
    _engine, _source, _application, adapter, segment_id = (
        _live_file_backed_adapter(tmp_path)
    )
    source_revision = adapter.read_inventory().source_token
    assert source_revision is not None
    created = adapter.create_recipe_draft(
        _canonicalize(
            CreateScenarioRecipeDraftCommand(
                metadata=_metadata(
                    command_id="scenario-command-create-rejected-81",
                    idempotency="scenario-idempotency-create-rejected-81",
                    content="scenario-content-create-rejected-81",
                    source_revision=source_revision,
                ),
                payload=_payload(segment_id),
                author_id=ScenarioLabActorId("scenario-author-81"),
                authoring_mode=ScenarioRecipeAuthoringMode.MANUAL,
            )
        )
    )
    assert created.draft is not None
    source_revision = adapter.read_inventory().source_token
    assert source_revision is not None
    rejected = adapter.approve_recipe(
        _canonicalize(
            ApproveScenarioRecipeCommand(
                metadata=_metadata(
                    command_id="scenario-command-approve-rejected-81",
                    idempotency="scenario-idempotency-approve-rejected-81",
                    content="scenario-content-approve-rejected-81",
                    source_revision=source_revision,
                ),
                draft_id=created.draft.draft_id,
                expected_draft_revision=created.draft.revision,
                expected_payload_hash=created.draft.payload_hash,
                validation_id=ScenarioRecipeValidationId(
                    "recipe-validation-not-authoritative-81"
                ),
                actor_id=ScenarioLabActorId("scenario-approver-81"),
            )
        )
    )
    assert rejected.receipt.disposition is ScenarioLabCommandDisposition.REJECTED
    assert rejected.approved_version is None
    inventory = adapter.read_inventory().inventory
    assert inventory is not None
    assert inventory.approved_recipe_versions == ()


def test_recipe_approval_recovers_after_version_persisted_before_command_terminal(
    tmp_path,
    monkeypatch,
) -> None:
    engine, _source, application, adapter, segment_id = (
        _live_file_backed_adapter(tmp_path)
    )
    source_revision = adapter.read_inventory().source_token
    assert source_revision is not None
    created = adapter.create_recipe_draft(
        _canonicalize(
            CreateScenarioRecipeDraftCommand(
                metadata=_metadata(
                    command_id="scenario-command-create-recovery-81",
                    idempotency="scenario-idempotency-create-recovery-81",
                    content="scenario-content-create-recovery-81",
                    source_revision=source_revision,
                ),
                payload=_payload(segment_id),
                author_id=ScenarioLabActorId("scenario-author-81"),
                authoring_mode=ScenarioRecipeAuthoringMode.MANUAL,
            )
        )
    )
    assert created.draft is not None
    source_revision = adapter.read_inventory().source_token
    assert source_revision is not None
    validated = adapter.validate_recipe_draft(
        _canonicalize(
            ValidateScenarioRecipeDraftCommand(
                metadata=_metadata(
                    command_id="scenario-command-validate-recovery-81",
                    idempotency="scenario-idempotency-validate-recovery-81",
                    content="scenario-content-validate-recovery-81",
                    source_revision=source_revision,
                ),
                draft_id=created.draft.draft_id,
                expected_draft_revision=created.draft.revision,
                expected_payload_hash=created.draft.payload_hash,
            )
        )
    )
    assert validated.validation is not None
    source_revision = adapter.read_inventory().source_token
    assert source_revision is not None
    command = _canonicalize(
        ApproveScenarioRecipeCommand(
            metadata=_metadata(
                command_id="scenario-command-approve-recovery-81",
                idempotency="scenario-idempotency-approve-recovery-81",
                content="scenario-content-approve-recovery-81",
                source_revision=source_revision,
            ),
            draft_id=created.draft.draft_id,
            expected_draft_revision=created.draft.revision,
            expected_payload_hash=created.draft.payload_hash,
            validation_id=validated.validation.validation_id,
            actor_id=ScenarioLabActorId("scenario-approver-81"),
        )
    )
    repository = application._scenario_lab_authoring._repository
    complete_command = repository.complete_command

    def crash_before_command_terminal(command_id, **kwargs):
        if kwargs.get("result_kind") == "approved_recipe_version":
            raise RuntimeError("injected crash after immutable Recipe approval")
        return complete_command(command_id, **kwargs)

    monkeypatch.setattr(repository, "complete_command", crash_before_command_terminal)
    with pytest.raises(RuntimeError, match="after immutable Recipe approval"):
        adapter.approve_recipe(command)
    monkeypatch.setattr(repository, "complete_command", complete_command)

    recovered = adapter.approve_recipe(command)

    assert recovered.receipt.disposition is ScenarioLabCommandDisposition.ACCEPTED
    assert recovered.approved_version is not None
    assert application.list_approved_scenario_recipes() == (
        application.get_recipe_version(
            recovered.approved_version.recipe_version_id.value
        ),
    )
    with engine.connect() as connection:
        stored = connection.execute(
            text(
                "SELECT disposition, result_kind, result_identity "
                "FROM diagnostic_scenario_lab_commands "
                "WHERE command_id = 'scenario-command-approve-recovery-81'"
            )
        ).one()
    assert tuple(stored) == (
        "accepted",
        "approved_recipe_version",
        recovered.approved_version.recipe_version_id.value,
    )


@pytest.mark.parametrize(
    ("dependency_transition", "expected_authority"),
    (
        ("changed", "outdated"),
        ("incompatible", "incompatible"),
        ("unavailable", "unavailable"),
    ),
)
def test_approved_recipe_dependency_change_retains_history_but_loses_authority(
    tmp_path,
    monkeypatch,
    dependency_transition: str,
    expected_authority: str,
) -> None:
    _engine, _source, application, adapter, segment_id = (
        _live_file_backed_adapter(tmp_path)
    )
    source_revision = adapter.read_inventory().source_token
    assert source_revision is not None
    created = adapter.create_recipe_draft(
        _canonicalize(
            CreateScenarioRecipeDraftCommand(
                metadata=_metadata(
                    command_id="scenario-command-create-invalidation-81",
                    idempotency="scenario-idempotency-create-invalidation-81",
                    content="scenario-content-create-invalidation-81",
                    source_revision=source_revision,
                ),
                payload=_payload(segment_id),
                author_id=ScenarioLabActorId("scenario-author-81"),
                authoring_mode=ScenarioRecipeAuthoringMode.MANUAL,
            )
        )
    )
    assert created.draft is not None
    source_revision = adapter.read_inventory().source_token
    assert source_revision is not None
    validated = adapter.validate_recipe_draft(
        _canonicalize(
            ValidateScenarioRecipeDraftCommand(
                metadata=_metadata(
                    command_id="scenario-command-validate-invalidation-81",
                    idempotency="scenario-idempotency-validate-invalidation-81",
                    content="scenario-content-validate-invalidation-81",
                    source_revision=source_revision,
                ),
                draft_id=created.draft.draft_id,
                expected_draft_revision=created.draft.revision,
                expected_payload_hash=created.draft.payload_hash,
            )
        )
    )
    assert validated.validation is not None
    source_revision = adapter.read_inventory().source_token
    assert source_revision is not None
    approved = adapter.approve_recipe(
        _canonicalize(
            ApproveScenarioRecipeCommand(
                metadata=_metadata(
                    command_id="scenario-command-approve-invalidation-81",
                    idempotency="scenario-idempotency-approve-invalidation-81",
                    content="scenario-content-approve-invalidation-81",
                    source_revision=source_revision,
                ),
                draft_id=created.draft.draft_id,
                expected_draft_revision=created.draft.revision,
                expected_payload_hash=created.draft.payload_hash,
                validation_id=validated.validation.validation_id,
                actor_id=ScenarioLabActorId("scenario-approver-81"),
            )
        )
    )
    assert approved.approved_version is not None
    original_projection = approved.approved_version
    original_domain = application.get_recipe_version(
        original_projection.recipe_version_id.value
    )
    service = application._scenario_lab_authoring
    dependency_provider = service._dependency_provider

    def changed_dependencies(draft, validation):
        if dependency_transition == "unavailable":
            raise ValueError("exact dependency unavailable for acceptance")
        dependencies = dependency_provider(draft, validation)
        if dependency_transition == "incompatible":
            return replace(
                dependencies,
                compatibility_observations=(
                    (
                        "transformation:acceptance-fixture",
                        "incompatible",
                        "The current implementation is incompatible.",
                    ),
                ),
            )
        return replace(dependencies, transformation_catalog_hash="f" * 64)

    monkeypatch.setattr(service, "_dependency_provider", changed_dependencies)

    refreshed = adapter.read_inventory().inventory
    assert refreshed is not None
    assert len(refreshed.approved_recipe_versions) == 1
    outdated = refreshed.approved_recipe_versions[0]
    assert outdated.recipe_version_id == original_projection.recipe_version_id
    assert outdated.approval == original_projection.approval
    assert outdated.authority_state.value == expected_authority
    assert outdated.can_materialize is False
    assert outdated.authority_reasons
    assert application.get_recipe_version(
        outdated.recipe_version_id.value
    ) == original_domain


def test_validation_findings_are_typed_and_bind_the_last_reliable_draft(
    tmp_path,
) -> None:
    _engine, _source, _application, adapter, segment_id = _live_file_backed_adapter(
        tmp_path
    )
    source_revision = adapter.read_inventory().source_token
    assert source_revision is not None
    created = adapter.create_recipe_draft(
        _canonicalize(CreateScenarioRecipeDraftCommand(
            metadata=_metadata(
                command_id="scenario-command-invalid-create-80",
                idempotency="scenario-idempotency-invalid-create-80",
                content="scenario-content-invalid-create-80",
                source_revision=source_revision,
            ),
            payload=replace(
                _payload(segment_id),
                decision_cadence_minutes=45,
            ),
            author_id=ScenarioLabActorId("scenario-author-80"),
            authoring_mode=ScenarioRecipeAuthoringMode.MANUAL,
        ))
    )
    assert created.draft is not None
    source_revision = adapter.read_inventory().source_token
    assert source_revision is not None
    validation = adapter.validate_recipe_draft(
        _canonicalize(ValidateScenarioRecipeDraftCommand(
            metadata=_metadata(
                command_id="scenario-command-invalid-validate-80",
                idempotency="scenario-idempotency-invalid-validate-80",
                content="scenario-content-invalid-validate-80",
                source_revision=source_revision,
            ),
            draft_id=created.draft.draft_id,
            expected_draft_revision=1,
            expected_payload_hash=created.draft.payload_hash,
        ))
    )

    assert validation.receipt.disposition is ScenarioLabCommandDisposition.ACCEPTED
    assert validation.validation is not None
    assert validation.validation.is_valid is False
    assert validation.validation.findings
    finding = validation.validation.findings[0]
    assert finding.path
    assert finding.rule_code == "bounds.invalid"
    assert finding.severity is ScenarioRecipeValidationSeverity.ERROR
    assert finding.explanation
    assert finding.correction
    assert finding.retryable is False
    assert finding.different_input_required is True
    inventory = adapter.read_inventory().inventory
    assert inventory is not None
    assert inventory.recipe_drafts[-1] == created.draft
    assert inventory.recipe_validations[-1] == validation.validation


def test_ai_assisted_draft_requires_and_preserves_the_backend_audit() -> None:
    source = _RecipeFixtureSource()
    probe = create_diagnostics_application(historical_source=source)
    probe.start()
    probe_admission = probe.admit_historical_segment(source.selection)
    assert probe_admission.segment is not None
    segment_id = probe_admission.segment.segment_id
    assistant = DeterministicFakeAIRecipeAssistant(
        output=AIRecipeDraftOutputV1(
            recipe=ScenarioRecipeV1(
                name="Audited AI Draft",
                historical_segment_id=segment_id,
                transformations=(),
                decision_cadence_minutes=30,
                materialization_seed=17,
            )
        )
    )
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
        recipe_assistant=assistant,
        recipe_clock=lambda: datetime(2026, 8, 4, 9, 0, tzinfo=timezone.utc),
    )
    application.start()
    admission = application.admit_historical_segment(source.selection)
    assert admission.segment is not None
    adapter = LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(application)
    inventory_result = adapter.read_inventory()
    assert inventory_result.inventory is not None
    assert inventory_result.inventory.authoring_capabilities.ai_authoring_available
    assert inventory_result.inventory.authoring_capabilities.ai_provider == (
        "deterministic-fake"
    )
    source_revision = inventory_result.source_token
    assert source_revision is not None
    command = _canonicalize(
        CreateAiAssistedScenarioRecipeDraftCommand(
            metadata=_metadata(
                command_id="scenario-command-ai-create-80",
                idempotency="scenario-idempotency-ai-create-80",
                content="pending-ai-content-80",
                source_revision=source_revision,
            ),
            intent="Draft the exact admitted baseline.",
            author_id=ScenarioLabActorId("scenario-ai-author-80"),
        )
    )

    accepted = adapter.author_recipe_with_ai(command)

    assert accepted.receipt.disposition is ScenarioLabCommandDisposition.ACCEPTED
    assert accepted.draft is not None
    assert accepted.draft.authoring_mode is ScenarioRecipeAuthoringMode.AI_ASSISTED
    assert accepted.draft.assistant_attempt_id is not None
    audit = application.get_ai_recipe_audit(accepted.draft.assistant_attempt_id)
    assert audit.attempt.provider == "deterministic-fake"
    assert audit.attempt.model
    assert audit.attempt.prompt_template_version
    assert audit.attempt.response_hash
    after_ai = adapter.read_inventory().inventory
    assert after_ai is not None
    assert after_ai.approved_recipe_versions == ()
    assert application.scenario_recipe_approval_history() == ()

    replayed = adapter.author_recipe_with_ai(
        replace(
            command,
            metadata=replace(
                command.metadata,
                command_id=ScenarioLabCommandId(
                    "scenario-command-ai-create-replay-80"
                ),
            ),
        )
    )
    assert replayed == accepted

    current_revision = adapter.read_inventory().source_token
    assert current_revision is not None
    tampered = _canonicalize(
        CreateScenarioRecipeDraftCommand(
            metadata=_metadata(
                command_id="scenario-command-ai-tampered-80",
                idempotency="scenario-idempotency-ai-tampered-80",
                content="pending-ai-tampered-content-80",
                source_revision=current_revision,
            ),
            payload=_payload(segment_id, name="Tampered AI Draft"),
            author_id=ScenarioLabActorId("scenario-ai-author-80"),
            authoring_mode=ScenarioRecipeAuthoringMode.AI_ASSISTED,
            assistant_attempt_id=accepted.draft.assistant_attempt_id,
        )
    )
    rejected = adapter.create_recipe_draft(tampered)
    assert rejected.receipt.disposition is ScenarioLabCommandDisposition.REJECTED
    assert rejected.draft is None
    assert "audited AI result" in rejected.receipt.message


def test_typed_ai_command_is_claimed_before_provider_and_replays_one_audit(
    tmp_path,
) -> None:
    source = _RecipeFixtureSource()
    probe = create_diagnostics_application(historical_source=source)
    probe.start()
    probe_admission = probe.admit_historical_segment(source.selection)
    assert probe_admission.segment is not None
    engine = create_engine(f"sqlite:///{tmp_path / 'ai-command-success.sqlite'}")
    command_id = "scenario-command-ai-claimed-before-provider-80"
    assistant = _ClaimObservingAssistant(
        DeterministicFakeAIRecipeAssistant(
            output=AIRecipeDraftOutputV1(
                recipe=ScenarioRecipeV1(
                    name="Durably claimed AI Draft",
                    historical_segment_id=probe_admission.segment.segment_id,
                    transformations=(),
                    decision_cadence_minutes=30,
                    materialization_seed=17,
                )
            )
        ),
        engine,
        command_id,
    )
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
        recipe_assistant=assistant,
    )
    application.start()
    application.initialize_persistence(engine)
    assert application.admit_historical_segment(source.selection).segment is not None
    adapter = LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(application)
    source_revision = adapter.read_inventory().source_token
    assert source_revision is not None
    command = _canonicalize(
        CreateAiAssistedScenarioRecipeDraftCommand(
            metadata=_metadata(
                command_id=command_id,
                idempotency="scenario-idempotency-ai-claimed-80",
                content="pending-ai-claimed-content-80",
                source_revision=source_revision,
            ),
            intent="Draft the exact admitted baseline once.",
            author_id=ScenarioLabActorId("scenario-ai-author-80"),
        )
    )

    accepted = adapter.author_recipe_with_ai(command)
    replayed = adapter.author_recipe_with_ai(
        replace(
            command,
            metadata=replace(
                command.metadata,
                command_id=ScenarioLabCommandId(
                    "scenario-command-ai-claimed-replay-80"
                ),
            ),
        )
    )

    assert accepted.receipt.disposition is ScenarioLabCommandDisposition.ACCEPTED
    assert accepted.draft is not None
    assert assistant.observed_disposition == "pending"
    assert assistant.calls == 1
    assert replayed == accepted
    assert accepted.draft.assistant_attempt_id is not None
    audit = application.get_ai_recipe_audit(accepted.draft.assistant_attempt_id)
    assert audit.attempt.attempt_id == accepted.draft.assistant_attempt_id
    with engine.connect() as connection:
        stored = connection.execute(
            text(
                "SELECT disposition, result_kind, result_identity FROM "
                "diagnostic_scenario_lab_commands WHERE command_id = :command_id"
            ),
            {"command_id": command_id},
        ).one()
    assert tuple(stored) == (
        "accepted",
        "recipe_draft",
        accepted.draft.draft_id.value,
    )


def test_typed_ai_command_recovers_existing_audit_after_pre_journal_crash(
    tmp_path,
    monkeypatch,
) -> None:
    source = _RecipeFixtureSource()
    probe = create_diagnostics_application(historical_source=source)
    probe.start()
    probe_admission = probe.admit_historical_segment(source.selection)
    assert probe_admission.segment is not None
    engine = create_engine(f"sqlite:///{tmp_path / 'ai-command-recovery.sqlite'}")
    command_id = "scenario-command-ai-audit-recovery-80"
    assistant = _ClaimObservingAssistant(
        DeterministicFakeAIRecipeAssistant(
            output=AIRecipeDraftOutputV1(
                recipe=ScenarioRecipeV1(
                    name="Recoverable audited AI Draft",
                    historical_segment_id=probe_admission.segment.segment_id,
                    transformations=(),
                    decision_cadence_minutes=30,
                    materialization_seed=17,
                )
            )
        ),
        engine,
        command_id,
    )
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
        recipe_assistant=assistant,
    )
    application.start()
    application.initialize_persistence(engine)
    assert application.admit_historical_segment(source.selection).segment is not None
    adapter = LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(application)
    source_revision = adapter.read_inventory().source_token
    assert source_revision is not None
    command = _canonicalize(
        CreateAiAssistedScenarioRecipeDraftCommand(
            metadata=_metadata(
                command_id=command_id,
                idempotency="scenario-idempotency-ai-audit-recovery-80",
                content="pending-ai-audit-recovery-content-80",
                source_revision=source_revision,
            ),
            intent="Draft the exact admitted baseline once.",
            author_id=ScenarioLabActorId("scenario-ai-author-80"),
        )
    )
    repository = application._scenario_lab_authoring._repository
    add_draft_revision = repository.add_draft_revision

    def crash_before_draft_journal(record):
        raise RuntimeError("injected crash after durable AI audit")

    monkeypatch.setattr(repository, "add_draft_revision", crash_before_draft_journal)
    with pytest.raises(RuntimeError, match="after durable AI audit"):
        adapter.author_recipe_with_ai(command)
    monkeypatch.setattr(repository, "add_draft_revision", add_draft_revision)

    recovered = adapter.author_recipe_with_ai(command)

    assert recovered.receipt.disposition is ScenarioLabCommandDisposition.ACCEPTED
    assert recovered.draft is not None
    assert assistant.calls == 1
    assert recovered.draft.assistant_attempt_id is not None
    audit = application.get_ai_recipe_audit(recovered.draft.assistant_attempt_id)
    assert audit.attempt.draft_id == recovered.draft.draft_id.value


def test_typed_ai_provider_failure_is_terminal_and_idempotently_replayed(
    tmp_path,
) -> None:
    source = _RecipeFixtureSource()
    engine = create_engine(f"sqlite:///{tmp_path / 'ai-command-failure.sqlite'}")
    command_id = "scenario-command-ai-provider-failure-80"
    assistant = _ClaimObservingAssistant(
        DeterministicFakeAIRecipeAssistant(
            error=AIRecipeAssistantProviderError("provider unavailable")
        ),
        engine,
        command_id,
    )
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
        recipe_assistant=assistant,
    )
    application.start()
    application.initialize_persistence(engine)
    assert application.admit_historical_segment(source.selection).segment is not None
    adapter = LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(application)
    source_revision = adapter.read_inventory().source_token
    assert source_revision is not None
    command = _canonicalize(
        CreateAiAssistedScenarioRecipeDraftCommand(
            metadata=_metadata(
                command_id=command_id,
                idempotency="scenario-idempotency-ai-provider-failure-80",
                content="pending-ai-provider-failure-content-80",
                source_revision=source_revision,
            ),
            intent="Draft the exact admitted baseline once.",
            author_id=ScenarioLabActorId("scenario-ai-author-80"),
        )
    )

    rejected = adapter.author_recipe_with_ai(command)
    replayed = adapter.author_recipe_with_ai(
        replace(
            command,
            metadata=replace(
                command.metadata,
                command_id=ScenarioLabCommandId(
                    "scenario-command-ai-provider-failure-replay-80"
                ),
            ),
        )
    )

    assert rejected.receipt.disposition is ScenarioLabCommandDisposition.REJECTED
    assert rejected.draft is None
    assert assistant.observed_disposition == "pending"
    assert assistant.calls == 1
    assert replayed == rejected
    with engine.connect() as connection:
        stored = connection.execute(
            text(
                "SELECT disposition, result_kind, result_identity FROM "
                "diagnostic_scenario_lab_commands WHERE command_id = :command_id"
            ),
            {"command_id": command_id},
        ).one()
    assert stored[0] == "rejected"
    assert stored[1] == "ai_authoring_attempt"
    assert str(stored[2]).startswith("ai_recipe_attempt_")
    audit = application.get_ai_recipe_audit(str(stored[2]))
    assert audit.attempt.status == "provider_error"
    reopened = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
    )
    reopened.start()
    reopened.initialize_persistence(engine)
    replayed_after_reopen = (
        LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(reopened)
        .author_recipe_with_ai(command)
    )
    assert replayed_after_reopen == rejected


def test_pending_durable_command_recovers_the_immutable_result_after_reopen(
    tmp_path,
) -> None:
    engine, source, _application, adapter, segment_id = _live_file_backed_adapter(
        tmp_path
    )
    source_revision = adapter.read_inventory().source_token
    assert source_revision is not None
    command = _canonicalize(
        CreateScenarioRecipeDraftCommand(
            metadata=_metadata(
                command_id="scenario-command-recovery-80",
                idempotency="scenario-idempotency-recovery-80",
                content="pending-recovery-content-80",
                source_revision=source_revision,
            ),
            payload=_payload(segment_id, name="Recoverable Draft"),
            author_id=ScenarioLabActorId("scenario-author-80"),
            authoring_mode=ScenarioRecipeAuthoringMode.MANUAL,
        )
    )
    accepted = adapter.create_recipe_draft(command)
    assert accepted.draft is not None
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE diagnostic_scenario_lab_commands SET "
                "disposition = 'pending', "
                "message = 'Scenario Lab command accepted for durable execution.', "
                "result_kind = NULL, result_identity = NULL, "
                "completed_at_utc = NULL "
                "WHERE command_id = 'scenario-command-recovery-80'"
            )
        )

    reopened = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
    )
    reopened.start()
    reopened.initialize_persistence(engine)
    recovered = LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(
        reopened
    ).create_recipe_draft(
        replace(
            command,
            metadata=replace(
                command.metadata,
                command_id=ScenarioLabCommandId(
                    "scenario-command-recovery-retry-80"
                ),
            ),
        )
    )

    assert recovered == accepted
    with engine.connect() as connection:
        stored = connection.execute(
            text(
                "SELECT disposition, result_kind, result_identity "
                "FROM diagnostic_scenario_lab_commands "
                "WHERE command_id = 'scenario-command-recovery-80'"
            )
        ).one()
    assert stored == (
        "accepted",
        "recipe_draft",
        accepted.draft.draft_id.value,
    )


def test_materialization_is_claimed_atomically_and_replays_after_reopen(
    tmp_path,
) -> None:
    source = _RecipeFixtureSource()
    engine = create_engine(f"sqlite:///{tmp_path / 'materialization-82.sqlite'}")
    materialize_command_id = "scenario-command-materialize-82"
    scheduler = _ManualMaterializationScheduler()
    store = _ClaimObservingMarketPathArtifactStore(
        engine,
        materialize_command_id,
    )
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=store,
        recipe_clock=lambda: datetime(2026, 8, 4, 9, 0, tzinfo=timezone.utc),
        materialization_scheduler=scheduler,
    )
    application.start()
    application.initialize_persistence(engine)
    admission = application.admit_historical_segment(source.selection)
    assert admission.segment is not None
    adapter = LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(application)

    source_revision = adapter.read_inventory().source_token
    assert source_revision is not None
    created = adapter.create_recipe_draft(
        _canonicalize(
            CreateScenarioRecipeDraftCommand(
                metadata=_metadata(
                    command_id="scenario-command-materialize-create-82",
                    idempotency="scenario-idempotency-materialize-create-82",
                    content="pending-materialize-create-content-82",
                    source_revision=source_revision,
                ),
                payload=_payload(admission.segment.segment_id),
                author_id=ScenarioLabActorId("scenario-author-82"),
                authoring_mode=ScenarioRecipeAuthoringMode.MANUAL,
            )
        )
    )
    assert created.draft is not None
    source_revision = adapter.read_inventory().source_token
    assert source_revision is not None
    validated = adapter.validate_recipe_draft(
        _canonicalize(
            ValidateScenarioRecipeDraftCommand(
                metadata=_metadata(
                    command_id="scenario-command-materialize-validate-82",
                    idempotency="scenario-idempotency-materialize-validate-82",
                    content="pending-materialize-validate-content-82",
                    source_revision=source_revision,
                ),
                draft_id=created.draft.draft_id,
                expected_draft_revision=created.draft.revision,
                expected_payload_hash=created.draft.payload_hash,
            )
        )
    )
    assert validated.validation is not None
    assert validated.validation.is_valid
    source_revision = adapter.read_inventory().source_token
    assert source_revision is not None
    approved = adapter.approve_recipe(
        _canonicalize(
            ApproveScenarioRecipeCommand(
                metadata=_metadata(
                    command_id="scenario-command-materialize-approve-82",
                    idempotency="scenario-idempotency-materialize-approve-82",
                    content="pending-materialize-approve-content-82",
                    source_revision=source_revision,
                ),
                draft_id=created.draft.draft_id,
                expected_draft_revision=created.draft.revision,
                expected_payload_hash=created.draft.payload_hash,
                validation_id=validated.validation.validation_id,
                actor_id=ScenarioLabActorId("scenario-approver-82"),
            )
        )
    )
    assert approved.approved_version is not None
    source_revision = adapter.read_inventory().source_token
    assert source_revision is not None
    command = _canonicalize(
        MaterializeApprovedScenarioRecipeCommand(
            metadata=_metadata(
                command_id=materialize_command_id,
                idempotency="scenario-idempotency-materialize-82",
                content="pending-materialize-content-82",
                source_revision=source_revision,
            ),
            recipe_version_id=approved.approved_version.recipe_version_id,
            expected_recipe_content_hash=approved.approved_version.content_hash,
        )
    )

    accepted = adapter.materialize_reference_path(command)

    assert accepted.receipt.disposition is ScenarioLabCommandDisposition.ACCEPTED
    assert accepted.receipt.task_handle is not None
    assert accepted.path_id is None
    assert accepted.attempt_id is not None
    with engine.connect() as connection:
        queued_claim = connection.execute(
            text(
                "SELECT command.disposition, task.phase, attempt.status "
                "FROM diagnostic_scenario_lab_commands AS command "
                "JOIN diagnostic_scenario_lab_task_handles AS task "
                "ON task.command_id = command.command_id "
                "JOIN diagnostic_scenario_materialization_attempts AS attempt "
                "ON attempt.task_handle_id = task.task_handle_id "
                "WHERE command.command_id = :command_id"
            ),
            {"command_id": materialize_command_id},
        ).one()
    assert tuple(queued_claim) == ("accepted", "queued", "queued")
    assert store.observed_claim is None
    scheduler.run_all()
    assert store.observed_claim == ("accepted", "running", "running")
    completed = adapter.materialize_reference_path(command)
    assert completed.path_id is not None
    assert completed.receipt.task_handle is not None
    with engine.connect() as connection:
        command_row = connection.execute(
            text(
                "SELECT disposition, result_kind, result_identity, result_json "
                "FROM diagnostic_scenario_lab_commands "
                "WHERE command_id = :command_id"
            ),
            {"command_id": materialize_command_id},
        ).one()
        task_row = connection.execute(
            text(
                "SELECT phase, progress_value, result_kind, result_identity "
                "FROM diagnostic_scenario_lab_task_handles "
                "WHERE command_id = :command_id"
            ),
            {"command_id": materialize_command_id},
        ).one()
        attempt_row = connection.execute(
            text(
                "SELECT status, reference_path_identity, attempt_number "
                "FROM diagnostic_scenario_materialization_attempts "
                "WHERE attempt_id = :attempt_id"
            ),
            {"attempt_id": accepted.attempt_id.value},
        ).one()
    assert tuple(command_row[:3]) == (
        "accepted",
        "materialization_attempt",
        accepted.attempt_id.value,
    )
    approval = approved.approved_version.approval
    dependencies = approval.dependencies
    assert approval.validation_id is not None
    assert dependencies is not None
    binding = json.loads(str(command_row[3]))
    assert binding == {
        "approved_recipe_version_id": (
            approved.approved_version.recipe_version_id.value
        ),
        "approval_id": approval.approval_id.value,
        "attempt_id": accepted.attempt_id.value,
        "recipe_content_hash": approved.approved_version.content_hash,
        "task_handle_id": accepted.receipt.task_handle.identity.value,
        "validation_dependencies": {
            "causality_rule_identities": list(
                dependencies.causality_rule_identities
            ),
            "compatibility_observations": [
                [
                    observation.subject,
                    observation.state.value,
                    observation.explanation,
                ]
                for observation in dependencies.compatibility_observations
            ],
            "data_policy": dependencies.data_policy.value.replace("_", "-"),
            "historical_segment_content_hash": (
                dependencies.historical_segment_content_hash
            ),
            "historical_segment_id": dependencies.historical_segment_id.value,
            "market_rule_profile_hash": dependencies.market_rule_profile_hash,
            "market_rule_profile_version": (
                dependencies.market_rule_profile_version
            ),
            "recipe_schema_hash": dependencies.recipe_schema_hash,
            "recipe_schema_identity": dependencies.recipe_schema_identity,
            "source_snapshot_content_hash": (
                dependencies.source_snapshot_content_hash
            ),
            "source_snapshot_id": dependencies.source_snapshot_id.value,
            "transformation_catalog_hash": (
                dependencies.transformation_catalog_hash
            ),
            "transformation_catalog_version": (
                dependencies.transformation_catalog_version
            ),
            "transformation_implementation_identities": list(
                dependencies.transformation_implementation_identities
            ),
        },
        "validation_id": approval.validation_id.value,
    }
    assert tuple(task_row) == (
        "completed",
        1.0,
        "reference_market_path",
        completed.path_id.value,
    )
    assert tuple(attempt_row) == ("completed", completed.path_id.value, 1)

    reopened_scheduler = _ManualMaterializationScheduler()
    reopened = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=store,
        recipe_clock=lambda: datetime(2026, 8, 4, 9, 0, tzinfo=timezone.utc),
        materialization_scheduler=reopened_scheduler,
    )
    reopened.start()
    reopened.initialize_persistence(engine)
    reopened_adapter = LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(
        reopened
    )
    reopened_inventory = reopened_adapter.read_inventory().inventory
    assert reopened_inventory is not None
    assert reopened_inventory.task_handles == (completed.receipt.task_handle,)
    assert completed.path_id in tuple(
        item.path_id for item in reopened_inventory.reference_paths
    )
    replayed = reopened_adapter.materialize_reference_path(
        _canonicalize(
            replace(
                command,
                metadata=replace(
                    command.metadata,
                    command_id=ScenarioLabCommandId(
                        "scenario-command-materialize-replay-after-reopen-82"
                    ),
                ),
            )
        )
    )
    assert replayed == completed
    with engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT COUNT(*) FROM diagnostic_scenario_lab_task_handles"
            )
        ).scalar_one() == 1
        assert connection.execute(
            text(
                "SELECT COUNT(*) FROM "
                "diagnostic_scenario_materialization_attempts"
            )
        ).scalar_one() == 1

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE diagnostic_scenario_lab_task_handles SET "
                "phase = 'running', progress_value = 0.25, "
                "result_kind = NULL, result_identity = NULL, "
                "updated_at_utc = created_at_utc "
                "WHERE command_id = :command_id"
            ),
            {"command_id": materialize_command_id},
        )
        connection.execute(
            text(
                "UPDATE diagnostic_scenario_materialization_attempts SET "
                "status = 'running', reference_path_identity = NULL, "
                "completed_at_utc = NULL WHERE attempt_id = :attempt_id"
            ),
            {"attempt_id": accepted.attempt_id.value},
        )
    recovered_scheduler = _ManualMaterializationScheduler()
    recovered_application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=store,
        recipe_clock=lambda: datetime(2026, 8, 4, 9, 0, tzinfo=timezone.utc),
        materialization_scheduler=recovered_scheduler,
    )
    recovered_application.start()
    recovered_application.initialize_persistence(engine)
    recovered_adapter = LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(
        recovered_application
    )
    recovered_scheduler.run_all()
    recovered = recovered_adapter.materialize_reference_path(command)
    assert recovered == completed
    with engine.connect() as connection:
        recovered_task = connection.execute(
            text(
                "SELECT phase, result_identity FROM "
                "diagnostic_scenario_lab_task_handles "
                "WHERE command_id = :command_id"
            ),
            {"command_id": materialize_command_id},
        ).one()
    assert tuple(recovered_task) == ("completed", completed.path_id.value)


def test_backend_materialization_continues_after_feature_disconnect_and_close(
    tmp_path,
) -> None:
    source = _RecipeFixtureSource()
    engine = create_engine(f"sqlite:///{tmp_path / 'materialization-live-82.sqlite'}")
    store = _BlockingMarketPathArtifactStore()
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=store,
        recipe_clock=lambda: datetime(2026, 8, 4, 9, 0, tzinfo=timezone.utc),
    )
    application.start()
    application.initialize_persistence(engine)
    admission = application.admit_historical_segment(source.selection)
    assert admission.segment is not None
    application_adapter = LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(
        application
    )
    version = _approve_exact_recipe(
        application_adapter,
        admission.segment.segment_id,
        suffix="background-82",
    )
    bridge = EventBridge(subscribe_backend=False)
    feature = LiveScenarioLabAdapter(
        application=application_adapter,
        event_bridge=bridge,
    )
    context = ScenarioLabContext()
    feature.snapshot(context)
    ready = feature.snapshot(context)
    assert ready.source_revision is not None
    command = _canonicalize(
        MaterializeApprovedScenarioRecipeCommand(
            metadata=_metadata(
                command_id="scenario-command-background-materialize-82",
                idempotency="scenario-idempotency-background-materialize-82",
                content="pending-background-materialize-82",
                source_revision=ready.source_revision,
            ),
            recipe_version_id=version.recipe_version_id,
            expected_recipe_content_hash=version.content_hash,
        )
    )

    try:
        accepted = feature.materialize_reference_path(command)
        handle = accepted.receipt.task_handle
        assert accepted.path_id is None
        assert handle is not None
        assert not handle.terminal
        assert store.started.wait(timeout=1.0)
        with engine.connect() as connection:
            assert tuple(
                connection.execute(
                    text(
                        "SELECT phase, progress_value FROM "
                        "diagnostic_scenario_lab_task_handles "
                        "WHERE task_handle_id = :task_handle_id"
                    ),
                    {"task_handle_id": handle.identity.value},
                ).one()
            ) == ("running", 0.25)
        bridge.mark_disconnected()
        feature.close()
        store.release.set()
        deadline = monotonic() + 3.0
        terminal_row = None
        while monotonic() < deadline:
            with engine.connect() as connection:
                terminal_row = connection.execute(
                    text(
                        "SELECT phase, result_identity FROM "
                        "diagnostic_scenario_lab_task_handles "
                        "WHERE task_handle_id = :task_handle_id"
                    ),
                    {"task_handle_id": handle.identity.value},
                ).one()
            if terminal_row[0] == "completed":
                break
            sleep(0.01)
        assert terminal_row is not None
        assert terminal_row[0] == "completed"

        reopened = create_diagnostics_application(
            historical_source=source,
            market_data_source=source,
            artifact_store=store,
            recipe_clock=lambda: datetime(
                2026, 8, 4, 9, 0, tzinfo=timezone.utc
            ),
        )
        reopened.start()
        reopened.initialize_persistence(engine)
        inventory = LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(
            reopened
        ).read_inventory().inventory
        assert inventory is not None
        reopened_handle = next(
            item
            for item in inventory.task_handles
            if item.identity == handle.identity
        )
        assert reopened_handle.terminal
        assert reopened_handle.result_identity is not None
        assert reopened_handle.result_identity.value == terminal_row[1]
    finally:
        store.release.set()
        feature.close()
        bridge.stop()


def test_file_backed_retry_lineage_survives_reopen(tmp_path) -> None:
    source = _RecipeFixtureSource()
    engine = create_engine(f"sqlite:///{tmp_path / 'materialization-retry-82.sqlite'}")
    store = _FailOnceMarketPathArtifactStore()
    scheduler = _ManualMaterializationScheduler()
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=store,
        recipe_clock=lambda: datetime(2026, 8, 4, 9, 0, tzinfo=timezone.utc),
        materialization_scheduler=scheduler,
    )
    application.start()
    application.initialize_persistence(engine)
    admission = application.admit_historical_segment(source.selection)
    assert admission.segment is not None
    adapter = LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(application)
    version = _approve_exact_recipe(
        adapter,
        admission.segment.segment_id,
        suffix="retry-reopen-82",
    )
    source_revision = adapter.read_inventory().source_token
    assert source_revision is not None
    materialize = _canonicalize(
        MaterializeApprovedScenarioRecipeCommand(
            metadata=_metadata(
                command_id="scenario-command-retry-reopen-materialize-82",
                idempotency="scenario-idempotency-retry-reopen-materialize-82",
                content="pending-retry-reopen-materialize-82",
                source_revision=source_revision,
            ),
            recipe_version_id=version.recipe_version_id,
            expected_recipe_content_hash=version.content_hash,
        )
    )
    queued_failure = adapter.materialize_reference_path(materialize)
    assert queued_failure.receipt.task_handle is not None
    scheduler.run_all()
    failed = adapter.materialize_reference_path(materialize)
    assert failed.receipt.task_handle is not None
    assert failed.receipt.task_handle.terminal
    assert failed.receipt.task_handle.retryable
    assert failed.attempt_id is not None
    source_revision = adapter.read_inventory().source_token
    assert source_revision is not None
    retry = _canonicalize(
        RetryScenarioMaterializationCommand(
            metadata=_metadata(
                command_id="scenario-command-retry-reopen-retry-82",
                idempotency="scenario-idempotency-retry-reopen-retry-82",
                content="pending-retry-reopen-retry-82",
                source_revision=source_revision,
            ),
            predecessor_attempt_id=failed.attempt_id,
            predecessor_task_handle_id=failed.receipt.task_handle.identity,
        )
    )
    queued_retry = adapter.retry_materialization(retry)
    assert queued_retry.receipt.task_handle is not None
    scheduler.run_all()
    completed_retry = adapter.retry_materialization(retry)
    assert completed_retry.path_id is not None
    assert completed_retry.receipt.task_handle is not None
    assert completed_retry.receipt.task_handle.terminal
    assert (
        completed_retry.receipt.task_handle.predecessor_task_handle_id
        == failed.receipt.task_handle.identity
    )

    reopened = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=store,
        recipe_clock=lambda: datetime(2026, 8, 4, 9, 0, tzinfo=timezone.utc),
        materialization_scheduler=_ManualMaterializationScheduler(),
    )
    reopened.start()
    reopened.initialize_persistence(engine)
    inventory = LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(
        reopened
    ).read_inventory().inventory
    assert inventory is not None
    assert inventory.task_handles == (
        failed.receipt.task_handle,
        completed_retry.receipt.task_handle,
    )
    assert completed_retry.path_id in tuple(
        item.path_id for item in inventory.reference_paths
    )
    with engine.connect() as connection:
        lineage = tuple(
            tuple(row)
            for row in connection.execute(
                text(
                    "SELECT attempt_id, predecessor_attempt_id, attempt_number, "
                    "status FROM diagnostic_scenario_materialization_attempts "
                    "ORDER BY attempt_number"
                )
            )
        )
    assert lineage == (
        (failed.attempt_id.value, None, 1, "failed"),
        (
            completed_retry.attempt_id.value,
            failed.attempt_id.value,
            2,
            "completed",
        ),
    )
