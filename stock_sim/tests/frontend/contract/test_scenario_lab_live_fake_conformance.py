from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable

import pytest

from app.app_context import build_app_context
from app.event_bridge import EventBridge
from app.features import (
    DeterministicFakeScenarioLabAdapter,
    LiveScenarioLabAdapter,
    ScenarioLabContext,
    ScenarioLabFeature,
    ScenarioLabFocusTarget,
)
from app.features.diagnostic_tasks_application import (
    ApprovedScenarioRecipeVersionId,
    CampaignCaseId,
    HistoricalMarketSegmentId,
)
from app.features.run_monitoring import (
    ScenarioSetId,
    SourceGenerationId,
    StrategyUnderTestId,
    TaskHandleId,
)
from app.features.scenario_lab_application import (
    SCENARIO_LAB_APPLICATION_INTERFACE_VERSION,
    ApproveScenarioRecipeCommand,
    ApproveScenarioRecipeResult,
    ComposeFormalScenarioSetCommand,
    ComposeFormalScenarioSetResult,
    CreateAiAssistedScenarioRecipeDraftCommand,
    CreateScenarioRecipeDraftCommand,
    CreateScenarioRecipeDraftResult,
    MaterializeApprovedScenarioRecipeCommand,
    MaterializeApprovedScenarioRecipeResult,
    ResolveScenarioExecutionAssumptionsCommand,
    ResolveScenarioExecutionAssumptionsResult,
    RequestedExecutionAssumptionsProjection,
    RetryScenarioMaterializationCommand,
    RetryScenarioMaterializationResult,
    ReviseScenarioRecipeDraftCommand,
    ReviseScenarioRecipeDraftResult,
    SelectFormalScenarioSetCommand,
    SelectFormalScenarioSetResult,
    ScenarioLabApplicationAvailability,
    ScenarioLabApplicationError,
    ScenarioLabApplicationErrorCode,
    ScenarioLabApplicationInventoryResult,
    ScenarioLabCommandDisposition,
    ScenarioLabCommandMetadata,
    ScenarioLabCommandReceipt,
    ScenarioLabActorId,
    ScenarioLabCommandContentIdentity,
    ScenarioLabCommandId,
    ScenarioLabIdempotencyIdentity,
    ScenarioLabInventory,
    ScenarioLabIntegrityState,
    ScenarioLabTaskOperation,
    ScenarioLabUnavailabilityCode,
    ScenarioLabUnavailabilityReason,
    ScenarioExecutionAssumptionTarget,
    ScenarioMaterializationAttemptId,
    ScenarioRecipeAuthoringMode,
    ScenarioRecipeDataPolicy,
    ScenarioRecipeDraftId,
    ScenarioRecipeDraftPayload,
    ScenarioRecipeParameterInput,
    ScenarioRecipeParameterKind,
    ScenarioRecipeTransformationInput,
    ScenarioRecipeValidationId,
    ValidateScenarioRecipeDraftCommand,
    ValidateScenarioRecipeDraftResult,
    LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter,
    canonical_scenario_lab_command_content_identity,
)
from app.features.strategy_diagnostics_v1_read_model import SourceRevisionToken
from strategy_diagnostics import (
    AIRecipeDraftOutputV1,
    DeterministicFakeAIRecipeAssistant,
    ScenarioRecipeV1,
)
from strategy_diagnostics.application import create_diagnostics_application
from strategy_diagnostics.market_paths import InMemoryMarketPathArtifactStore
from tests.strategy_diagnostics.test_recipe_lifecycle import _RecipeFixtureSource


def _inventory() -> ScenarioLabInventory:
    feature = DeterministicFakeScenarioLabAdapter()
    context = ScenarioLabContext()
    feature.snapshot(context)
    state = feature.snapshot(context)
    feature.close()
    assert state.last_reliable_inventory is not None
    return state.last_reliable_inventory


class _TypedScenarioLabApplication:
    def __init__(
        self,
        inventory: ScenarioLabInventory,
        scripted: tuple[ScenarioLabApplicationInventoryResult, ...] = (),
    ) -> None:
        self.inventory = inventory
        self.scripted = list(scripted)
        self.read_calls = 0
        self.result = ScenarioLabApplicationInventoryResult(
            availability=ScenarioLabApplicationAvailability.READY,
            inventory=inventory,
            source_token=SourceRevisionToken("a" * 64),
            observed_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            error=None,
        )

    @property
    def interface_version(self):
        return SCENARIO_LAB_APPLICATION_INTERFACE_VERSION

    def read_inventory(self) -> ScenarioLabApplicationInventoryResult:
        self.read_calls += 1
        if self.scripted:
            self.result = self.scripted.pop(0)
        return self.result

    @staticmethod
    def _receipt(
        metadata: ScenarioLabCommandMetadata,
        operation: ScenarioLabTaskOperation,
    ) -> ScenarioLabCommandReceipt:
        return ScenarioLabCommandReceipt(
            metadata=metadata,
            operation=operation,
            disposition=ScenarioLabCommandDisposition.UNAVAILABLE,
            message="Capability is not yet available.",
            authoritative_revision=None,
            task_handle=None,
        )

    def create_recipe_draft(self, command: CreateScenarioRecipeDraftCommand):
        return CreateScenarioRecipeDraftResult(
            self._receipt(command.metadata, ScenarioLabTaskOperation.CREATE_RECIPE_DRAFT)
        )

    def revise_recipe_draft(self, command: ReviseScenarioRecipeDraftCommand):
        return ReviseScenarioRecipeDraftResult(
            self._receipt(command.metadata, ScenarioLabTaskOperation.REVISE_RECIPE_DRAFT)
        )

    def validate_recipe_draft(self, command: ValidateScenarioRecipeDraftCommand):
        return ValidateScenarioRecipeDraftResult(
            self._receipt(command.metadata, ScenarioLabTaskOperation.VALIDATE_RECIPE_DRAFT)
        )

    def approve_recipe(self, command: ApproveScenarioRecipeCommand):
        return ApproveScenarioRecipeResult(
            self._receipt(command.metadata, ScenarioLabTaskOperation.APPROVE_RECIPE)
        )

    def materialize_reference_path(
        self, command: MaterializeApprovedScenarioRecipeCommand
    ):
        return MaterializeApprovedScenarioRecipeResult(
            self._receipt(
                command.metadata, ScenarioLabTaskOperation.MATERIALIZE_REFERENCE_PATH
            )
        )

    def retry_materialization(self, command: RetryScenarioMaterializationCommand):
        return RetryScenarioMaterializationResult(
            self._receipt(command.metadata, ScenarioLabTaskOperation.RETRY_MATERIALIZATION)
        )

    def compose_scenario_set(self, command: ComposeFormalScenarioSetCommand):
        return ComposeFormalScenarioSetResult(
            self._receipt(command.metadata, ScenarioLabTaskOperation.COMPOSE_SCENARIO_SET)
        )

    def resolve_execution_assumptions(
        self, command: ResolveScenarioExecutionAssumptionsCommand
    ):
        return ResolveScenarioExecutionAssumptionsResult(
            self._receipt(
                command.metadata,
                ScenarioLabTaskOperation.RESOLVE_EXECUTION_ASSUMPTIONS,
            )
        )

    def select_formal_scenario_set(self, command: SelectFormalScenarioSetCommand):
        return SelectFormalScenarioSetResult(
            self._receipt(
                command.metadata,
                ScenarioLabTaskOperation.SELECT_FORMAL_SCENARIO_SET,
            )
        )


def _live_feature() -> ScenarioLabFeature:
    return LiveScenarioLabAdapter(
        application=_TypedScenarioLabApplication(_inventory())
    )


def _fake_feature() -> ScenarioLabFeature:
    return DeterministicFakeScenarioLabAdapter(inventory=_inventory())


def _live_authoring_feature() -> ScenarioLabFeature:
    source = _RecipeFixtureSource()
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
        recipe_clock=lambda: datetime(2026, 1, 2, 9, 30, tzinfo=timezone.utc),
    )
    application.start()
    admission = application.admit_historical_segment(source.selection)
    assert admission.segment is not None
    return LiveScenarioLabAdapter(
        application=LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(
            application
        )
    )


def _fake_authoring_feature() -> ScenarioLabFeature:
    return DeterministicFakeScenarioLabAdapter(inventory=_inventory())


@dataclass(frozen=True, slots=True)
class _ApprovalInvalidationHarness:
    feature: ScenarioLabFeature
    invalidate_dependencies: Callable[[], None]
    make_dependencies_unavailable: Callable[[], None]


def _live_approval_invalidation_harness() -> _ApprovalInvalidationHarness:
    source = _RecipeFixtureSource()
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
        recipe_clock=lambda: datetime(2026, 1, 2, 9, 30, tzinfo=timezone.utc),
    )
    application.start()
    assert application.admit_historical_segment(source.selection).segment is not None
    feature = LiveScenarioLabAdapter(
        application=LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(
            application
        )
    )
    service = application._scenario_lab_authoring
    dependency_provider = service._dependency_provider

    def invalidate_dependencies() -> None:
        def changed_dependencies(draft, validation):
            return replace(
                dependency_provider(draft, validation),
                transformation_catalog_hash="f" * 64,
            )

        service._dependency_provider = changed_dependencies

    def make_dependencies_unavailable() -> None:
        def unavailable_dependencies(draft, validation):
            raise ValueError("exact dependency unavailable for conformance")

        service._dependency_provider = unavailable_dependencies

    return _ApprovalInvalidationHarness(
        feature,
        invalidate_dependencies,
        make_dependencies_unavailable,
    )


def _fake_approval_invalidation_harness() -> _ApprovalInvalidationHarness:
    feature = DeterministicFakeScenarioLabAdapter(inventory=_inventory())
    return _ApprovalInvalidationHarness(
        feature,
        feature.advance_to_dependency_change,
        feature.advance_to_dependency_unavailable,
    )


def _live_ai_authoring_feature() -> ScenarioLabFeature:
    source = _RecipeFixtureSource()
    probe = create_diagnostics_application(historical_source=source)
    probe.start()
    admission = probe.admit_historical_segment(source.selection)
    assert admission.segment is not None
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
        recipe_assistant=DeterministicFakeAIRecipeAssistant(
            output=AIRecipeDraftOutputV1(
                recipe=ScenarioRecipeV1(
                    name="AI conformance Draft",
                    historical_segment_id=admission.segment.segment_id,
                    transformations=(),
                    decision_cadence_minutes=30,
                    materialization_seed=80,
                )
            )
        ),
        recipe_clock=lambda: datetime(2026, 1, 2, 9, 30, tzinfo=timezone.utc),
    )
    application.start()
    assert application.admit_historical_segment(source.selection).segment is not None
    return LiveScenarioLabAdapter(
        application=LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(
            application
        )
    )


def _fake_ai_authoring_feature() -> ScenarioLabFeature:
    return DeterministicFakeScenarioLabAdapter(
        inventory=_inventory(),
        ai_authoring_available=True,
        ai_provider="deterministic-fake",
        ai_model="deterministic-recipe-fixture.v1",
    )


def _canonicalize_authoring(command):
    return replace(
        command,
        metadata=replace(
            command.metadata,
            canonical_content_identity=(
                canonical_scenario_lab_command_content_identity(command)
            ),
        ),
    )


def _authoring_payload(
    ready,
    *,
    transformations: tuple[ScenarioRecipeTransformationInput, ...] = (),
) -> ScenarioRecipeDraftPayload:
    return ScenarioRecipeDraftPayload(
        name="Wave 3 conformance Draft",
        historical_segment_id=ready.historical_segments[0].segment_id,
        transformations=transformations,
        requested_execution_assumptions=RequestedExecutionAssumptionsProjection(
            commission_bps="3",
            slippage_bps="0",
            max_fill_fraction="1",
            latency_nodes=0,
            allow_partial_fills=True,
        ),
        decision_cadence_minutes=30,
        materialization_seed=80,
        data_policy=ScenarioRecipeDataPolicy.POINT_IN_TIME,
        market_rule_profile_version="a-share-cash-equity.v1",
    )


def _authoring_metadata(
    ready,
    *,
    suffix: str,
    canonical_content_identity: str = "pending-canonical-content",
) -> ScenarioLabCommandMetadata:
    assert ready.source_revision is not None
    return ScenarioLabCommandMetadata(
        command_id=ScenarioLabCommandId(f"command-80-{suffix}"),
        idempotency_identity=ScenarioLabIdempotencyIdentity(
            f"idempotency-80-{suffix}"
        ),
        canonical_content_identity=ScenarioLabCommandContentIdentity(
            canonical_content_identity
        ),
        expected_source_revision=ready.source_revision,
        expected_source_generation=ready.source.generation,
    )


def _create_and_validate_exact_recipe(
    feature: ScenarioLabFeature,
    *,
    suffix: str,
):
    context = ScenarioLabContext()
    feature.snapshot(context)
    ready = feature.snapshot(context)
    created = feature.create_recipe_draft(
        _canonicalize_authoring(
            CreateScenarioRecipeDraftCommand(
                metadata=_authoring_metadata(
                    ready,
                    suffix=f"{suffix}-create",
                ),
                payload=_authoring_payload(ready),
                author_id=ScenarioLabActorId("actor-81"),
                authoring_mode=ScenarioRecipeAuthoringMode.MANUAL,
            )
        )
    )
    assert created.draft is not None
    after_create = feature.snapshot(context)
    validated = feature.validate_recipe_draft(
        _canonicalize_authoring(
            ValidateScenarioRecipeDraftCommand(
                metadata=_authoring_metadata(
                    after_create,
                    suffix=f"{suffix}-validate",
                ),
                draft_id=created.draft.draft_id,
                expected_draft_revision=created.draft.revision,
                expected_payload_hash=created.draft.payload_hash,
            )
        )
    )
    assert validated.validation is not None
    assert validated.validation.is_valid
    return context, created.draft, validated.validation


@pytest.mark.parametrize(
    "harness_factory",
    (_live_approval_invalidation_harness, _fake_approval_invalidation_harness),
)
@pytest.mark.parametrize(
    "transition",
    ("invalidate_dependencies", "make_dependencies_unavailable"),
)
def test_shared_dependency_change_rejects_approval_without_side_effects(
    harness_factory: Callable[[], _ApprovalInvalidationHarness],
    transition: str,
) -> None:
    harness = harness_factory()
    feature = harness.feature
    context, draft, validation = _create_and_validate_exact_recipe(
        feature,
        suffix="approval-dependency-reject",
    )
    getattr(harness, transition)()
    changed = feature.snapshot(context)
    command = _canonicalize_authoring(
        ApproveScenarioRecipeCommand(
            metadata=_authoring_metadata(
                changed,
                suffix="approval-dependency-reject-approve",
            ),
            draft_id=draft.draft_id,
            expected_draft_revision=draft.revision,
            expected_payload_hash=draft.payload_hash,
            validation_id=validation.validation_id,
            actor_id=ScenarioLabActorId("approver-81"),
        )
    )

    rejected = feature.approve_recipe(command)

    assert rejected.receipt.disposition is ScenarioLabCommandDisposition.REJECTED
    assert rejected.approved_version is None
    assert feature.snapshot(context).approved_recipe_versions == ()
    feature.close()


@pytest.mark.parametrize(
    "harness_factory",
    (_live_approval_invalidation_harness, _fake_approval_invalidation_harness),
)
@pytest.mark.parametrize(
    ("transition", "expected_authority"),
    (
        ("invalidate_dependencies", "outdated"),
        ("make_dependencies_unavailable", "unavailable"),
    ),
)
def test_shared_approved_history_survives_dependency_invalidation_and_replay(
    harness_factory: Callable[[], _ApprovalInvalidationHarness],
    transition: str,
    expected_authority: str,
) -> None:
    harness = harness_factory()
    feature = harness.feature
    context, draft, validation = _create_and_validate_exact_recipe(
        feature,
        suffix="approval-history-invalidation",
    )
    before_approval = feature.snapshot(context)
    command = _canonicalize_authoring(
        ApproveScenarioRecipeCommand(
            metadata=_authoring_metadata(
                before_approval,
                suffix="approval-history-invalidation-approve",
            ),
            draft_id=draft.draft_id,
            expected_draft_revision=draft.revision,
            expected_payload_hash=draft.payload_hash,
            validation_id=validation.validation_id,
            actor_id=ScenarioLabActorId("approver-81"),
        )
    )
    accepted = feature.approve_recipe(command)
    assert accepted.approved_version is not None
    original = accepted.approved_version

    getattr(harness, transition)()
    invalidated = feature.snapshot(context).approved_recipe_versions
    replay = feature.approve_recipe(command)

    assert len(invalidated) == 1
    historical = invalidated[0]
    assert historical.recipe_version_id == original.recipe_version_id
    assert historical.approval == original.approval
    assert historical.content_hash == original.content_hash
    assert historical.authority_state.value == expected_authority
    assert historical.can_materialize is False
    assert historical.authority_reasons
    assert historical.authority_reasons[0].corrective_guidance
    assert replay.recipe_version_id == original.recipe_version_id
    assert replay.recipe_content_hash == original.content_hash
    assert replay.approved_version == historical
    feature.close()


@pytest.mark.parametrize(
    "feature_factory",
    (_live_authoring_feature, _fake_authoring_feature),
)
def test_shared_approval_rejects_unvalidated_invalid_hash_and_stale_drafts(
    feature_factory: Callable[[], ScenarioLabFeature],
) -> None:
    feature = feature_factory()
    context = ScenarioLabContext()
    feature.snapshot(context)
    ready = feature.snapshot(context)
    created = feature.create_recipe_draft(
        _canonicalize_authoring(
            CreateScenarioRecipeDraftCommand(
                metadata=_authoring_metadata(
                    ready,
                    suffix="approval-rejection-create",
                ),
                payload=_authoring_payload(ready),
                author_id=ScenarioLabActorId("actor-81"),
                authoring_mode=ScenarioRecipeAuthoringMode.MANUAL,
            )
        )
    )
    assert created.draft is not None
    after_create = feature.snapshot(context)
    unvalidated = feature.approve_recipe(
        _canonicalize_authoring(
            ApproveScenarioRecipeCommand(
                metadata=_authoring_metadata(
                    after_create,
                    suffix="approval-rejection-unvalidated",
                ),
                draft_id=created.draft.draft_id,
                expected_draft_revision=created.draft.revision,
                expected_payload_hash=created.draft.payload_hash,
                validation_id=ScenarioRecipeValidationId(
                    "missing-validation-81"
                ),
                actor_id=ScenarioLabActorId("approver-81"),
            )
        )
    )
    assert unvalidated.receipt.disposition is ScenarioLabCommandDisposition.REJECTED

    validated = feature.validate_recipe_draft(
        _canonicalize_authoring(
            ValidateScenarioRecipeDraftCommand(
                metadata=_authoring_metadata(
                    feature.snapshot(context),
                    suffix="approval-rejection-validate",
                ),
                draft_id=created.draft.draft_id,
                expected_draft_revision=created.draft.revision,
                expected_payload_hash=created.draft.payload_hash,
            )
        )
    )
    assert validated.validation is not None
    hash_mismatch = feature.approve_recipe(
        _canonicalize_authoring(
            ApproveScenarioRecipeCommand(
                metadata=_authoring_metadata(
                    feature.snapshot(context),
                    suffix="approval-rejection-hash",
                ),
                draft_id=created.draft.draft_id,
                expected_draft_revision=created.draft.revision,
                expected_payload_hash="f" * 64,
                validation_id=validated.validation.validation_id,
                actor_id=ScenarioLabActorId("approver-81"),
            )
        )
    )
    assert hash_mismatch.receipt.disposition is ScenarioLabCommandDisposition.CONFLICT

    revised = feature.revise_recipe_draft(
        _canonicalize_authoring(
            ReviseScenarioRecipeDraftCommand(
                metadata=_authoring_metadata(
                    feature.snapshot(context),
                    suffix="approval-rejection-revise",
                ),
                predecessor_draft_id=created.draft.draft_id,
                expected_draft_revision=created.draft.revision,
                payload=replace(
                    _authoring_payload(feature.snapshot(context)),
                    name="Stale-validation successor",
                ),
                author_id=ScenarioLabActorId("actor-81"),
            )
        )
    )
    assert revised.draft is not None
    stale = feature.approve_recipe(
        _canonicalize_authoring(
            ApproveScenarioRecipeCommand(
                metadata=_authoring_metadata(
                    feature.snapshot(context),
                    suffix="approval-rejection-stale",
                ),
                draft_id=created.draft.draft_id,
                expected_draft_revision=created.draft.revision,
                expected_payload_hash=created.draft.payload_hash,
                validation_id=validated.validation.validation_id,
                actor_id=ScenarioLabActorId("approver-81"),
            )
        )
    )
    assert stale.receipt.disposition is ScenarioLabCommandDisposition.CONFLICT
    assert stale.authoritative_draft_revision == revised.draft.revision

    before_invalid = feature.snapshot(context)
    invalid_draft = feature.create_recipe_draft(
        _canonicalize_authoring(
            CreateScenarioRecipeDraftCommand(
                metadata=_authoring_metadata(
                    before_invalid,
                    suffix="approval-rejection-invalid-create",
                ),
                payload=replace(
                    _authoring_payload(before_invalid),
                    name="Invalid approval Draft",
                    decision_cadence_minutes=45,
                ),
                author_id=ScenarioLabActorId("actor-81"),
                authoring_mode=ScenarioRecipeAuthoringMode.MANUAL,
            )
        )
    )
    assert invalid_draft.draft is not None
    invalid_validation = feature.validate_recipe_draft(
        _canonicalize_authoring(
            ValidateScenarioRecipeDraftCommand(
                metadata=_authoring_metadata(
                    feature.snapshot(context),
                    suffix="approval-rejection-invalid-validate",
                ),
                draft_id=invalid_draft.draft.draft_id,
                expected_draft_revision=invalid_draft.draft.revision,
                expected_payload_hash=invalid_draft.draft.payload_hash,
            )
        )
    )
    assert invalid_validation.validation is not None
    assert invalid_validation.validation.is_valid is False
    invalid = feature.approve_recipe(
        _canonicalize_authoring(
            ApproveScenarioRecipeCommand(
                metadata=_authoring_metadata(
                    feature.snapshot(context),
                    suffix="approval-rejection-invalid-approve",
                ),
                draft_id=invalid_draft.draft.draft_id,
                expected_draft_revision=invalid_draft.draft.revision,
                expected_payload_hash=invalid_draft.draft.payload_hash,
                validation_id=invalid_validation.validation.validation_id,
                actor_id=ScenarioLabActorId("approver-81"),
            )
        )
    )
    assert invalid.receipt.disposition is ScenarioLabCommandDisposition.REJECTED
    assert feature.snapshot(context).approved_recipe_versions == ()
    feature.close()


@pytest.mark.parametrize(
    "feature_factory",
    (_live_authoring_feature, _fake_authoring_feature),
)
def test_shared_revise_rejects_cross_recipe_and_unknown_approved_lineage(
    feature_factory: Callable[[], ScenarioLabFeature],
) -> None:
    feature = feature_factory()
    context, first_draft, first_validation = _create_and_validate_exact_recipe(
        feature,
        suffix="lineage-source",
    )
    approved = feature.approve_recipe(
        _canonicalize_authoring(
            ApproveScenarioRecipeCommand(
                metadata=_authoring_metadata(
                    feature.snapshot(context),
                    suffix="lineage-source-approve",
                ),
                draft_id=first_draft.draft_id,
                expected_draft_revision=first_draft.revision,
                expected_payload_hash=first_draft.payload_hash,
                validation_id=first_validation.validation_id,
                actor_id=ScenarioLabActorId("approver-81"),
            )
        )
    )
    assert approved.approved_version is not None

    before_second = feature.snapshot(context)
    second = feature.create_recipe_draft(
        _canonicalize_authoring(
            CreateScenarioRecipeDraftCommand(
                metadata=_authoring_metadata(
                    before_second,
                    suffix="lineage-target-create",
                ),
                payload=replace(
                    _authoring_payload(before_second),
                    name="Independent lineage target",
                ),
                author_id=ScenarioLabActorId("actor-81"),
                authoring_mode=ScenarioRecipeAuthoringMode.MANUAL,
            )
        )
    )
    assert second.draft is not None
    draft_count = len(feature.snapshot(context).recipe_drafts)

    cross_recipe = feature.revise_recipe_draft(
        _canonicalize_authoring(
            ReviseScenarioRecipeDraftCommand(
                metadata=_authoring_metadata(
                    feature.snapshot(context),
                    suffix="lineage-cross-recipe",
                ),
                predecessor_draft_id=second.draft.draft_id,
                expected_draft_revision=second.draft.revision,
                payload=replace(second.draft.payload, name="False cross lineage"),
                author_id=ScenarioLabActorId("actor-81"),
                based_on_recipe_version_id=(
                    approved.approved_version.recipe_version_id
                ),
            )
        )
    )
    unknown = feature.revise_recipe_draft(
        _canonicalize_authoring(
            ReviseScenarioRecipeDraftCommand(
                metadata=_authoring_metadata(
                    feature.snapshot(context),
                    suffix="lineage-unknown-version",
                ),
                predecessor_draft_id=second.draft.draft_id,
                expected_draft_revision=second.draft.revision,
                payload=replace(second.draft.payload, name="Unknown lineage"),
                author_id=ScenarioLabActorId("actor-81"),
                based_on_recipe_version_id=ApprovedScenarioRecipeVersionId(
                    "recipe_version_unknown_81"
                ),
            )
        )
    )

    assert cross_recipe.receipt.disposition is ScenarioLabCommandDisposition.REJECTED
    assert cross_recipe.draft is None
    assert unknown.receipt.disposition is ScenarioLabCommandDisposition.REJECTED
    assert unknown.draft is None
    assert len(feature.snapshot(context).recipe_drafts) == draft_count
    feature.close()


@pytest.mark.parametrize(
    "feature_factory",
    (_live_authoring_feature, _fake_authoring_feature),
)
def test_shared_revise_preserves_approved_lineage_across_iterative_successors(
    feature_factory: Callable[[], ScenarioLabFeature],
) -> None:
    feature = feature_factory()
    context, initial_draft, validation = _create_and_validate_exact_recipe(
        feature,
        suffix="iterative-lineage",
    )
    approved = feature.approve_recipe(
        _canonicalize_authoring(
            ApproveScenarioRecipeCommand(
                metadata=_authoring_metadata(
                    feature.snapshot(context),
                    suffix="iterative-lineage-approve",
                ),
                draft_id=initial_draft.draft_id,
                expected_draft_revision=initial_draft.revision,
                expected_payload_hash=initial_draft.payload_hash,
                validation_id=validation.validation_id,
                actor_id=ScenarioLabActorId("approver-81"),
            )
        )
    )
    assert approved.approved_version is not None
    version_id = approved.approved_version.recipe_version_id

    revision_two = feature.revise_recipe_draft(
        _canonicalize_authoring(
            ReviseScenarioRecipeDraftCommand(
                metadata=_authoring_metadata(
                    feature.snapshot(context),
                    suffix="iterative-lineage-r2",
                ),
                predecessor_draft_id=initial_draft.draft_id,
                expected_draft_revision=initial_draft.revision,
                payload=replace(initial_draft.payload, name="Lineage revision two"),
                author_id=ScenarioLabActorId("actor-81"),
                based_on_recipe_version_id=version_id,
            )
        )
    )
    assert revision_two.draft is not None
    revision_three = feature.revise_recipe_draft(
        _canonicalize_authoring(
            ReviseScenarioRecipeDraftCommand(
                metadata=_authoring_metadata(
                    feature.snapshot(context),
                    suffix="iterative-lineage-r3",
                ),
                predecessor_draft_id=revision_two.draft.draft_id,
                expected_draft_revision=revision_two.draft.revision,
                payload=replace(revision_two.draft.payload, name="Lineage revision three"),
                author_id=ScenarioLabActorId("actor-81"),
                based_on_recipe_version_id=version_id,
            )
        )
    )

    assert revision_three.receipt.disposition is ScenarioLabCommandDisposition.ACCEPTED
    assert revision_three.draft is not None
    assert revision_three.draft.revision == revision_two.draft.revision + 1
    assert revision_three.draft.based_on_recipe_version_id == version_id
    feature.close()


@pytest.mark.parametrize(
    "feature_factory",
    (_live_authoring_feature, _fake_authoring_feature),
)
def test_shared_exact_approval_replay_and_immutable_successor_version_history(
    feature_factory: Callable[[], ScenarioLabFeature],
) -> None:
    feature = feature_factory()
    context = ScenarioLabContext()
    feature.snapshot(context)
    ready = feature.snapshot(context)
    created = feature.create_recipe_draft(
        _canonicalize_authoring(
            CreateScenarioRecipeDraftCommand(
                metadata=_authoring_metadata(
                    ready,
                    suffix="approval-create",
                ),
                payload=_authoring_payload(ready),
                author_id=ScenarioLabActorId("actor-81"),
                authoring_mode=ScenarioRecipeAuthoringMode.MANUAL,
            )
        )
    )
    assert created.draft is not None

    after_create = feature.snapshot(context)
    validated = feature.validate_recipe_draft(
        _canonicalize_authoring(
            ValidateScenarioRecipeDraftCommand(
                metadata=_authoring_metadata(
                    after_create,
                    suffix="approval-validate",
                ),
                draft_id=created.draft.draft_id,
                expected_draft_revision=created.draft.revision,
                expected_payload_hash=created.draft.payload_hash,
            )
        )
    )
    assert validated.validation is not None
    assert validated.validation.is_valid is True

    after_validate = feature.snapshot(context)
    approval_command = _canonicalize_authoring(
        ApproveScenarioRecipeCommand(
            metadata=_authoring_metadata(
                after_validate,
                suffix="approval-accept",
            ),
            draft_id=created.draft.draft_id,
            expected_draft_revision=created.draft.revision,
            expected_payload_hash=created.draft.payload_hash,
            validation_id=validated.validation.validation_id,
            actor_id=ScenarioLabActorId("approver-81"),
        )
    )
    first = feature.approve_recipe(approval_command)
    replay = feature.approve_recipe(
        _canonicalize_authoring(
            replace(
                approval_command,
                metadata=replace(
                    approval_command.metadata,
                    command_id=ScenarioLabCommandId(
                        "command-81-approval-replay"
                    ),
                ),
            )
        )
    )
    conflicted = feature.approve_recipe(
        _canonicalize_authoring(
            replace(
                approval_command,
                metadata=replace(
                    approval_command.metadata,
                    command_id=ScenarioLabCommandId(
                        "command-81-approval-conflict"
                    ),
                ),
                actor_id=ScenarioLabActorId("different-approver-81"),
            )
        )
    )
    command_identity_conflicted = feature.approve_recipe(
        _canonicalize_authoring(
            replace(
                approval_command,
                metadata=replace(
                    _authoring_metadata(
                        feature.snapshot(context),
                        suffix="approval-command-identity-collision",
                    ),
                    command_id=approval_command.metadata.command_id,
                ),
                actor_id=ScenarioLabActorId("command-collision-approver-81"),
            )
        )
    )

    assert first.receipt.disposition is ScenarioLabCommandDisposition.ACCEPTED
    assert replay == first
    assert conflicted.receipt.disposition is ScenarioLabCommandDisposition.CONFLICT
    assert conflicted.approved_version is None
    assert (
        command_identity_conflicted.receipt.disposition
        is ScenarioLabCommandDisposition.CONFLICT
    )
    assert "command identity" in command_identity_conflicted.receipt.message.casefold()
    assert command_identity_conflicted.approved_version is None
    assert first.approved_version is not None
    version_one = first.approved_version
    assert version_one.version_number == 1
    assert version_one.recipe_id == created.draft.recipe_id
    assert version_one.approval.validation_id == (
        validated.validation.validation_id
    )
    assert version_one.approval.dependencies == (
        validated.validation.dependencies
    )
    assert version_one.authority_state.value == "current"
    assert version_one.can_materialize is True

    after_first_approval = feature.snapshot(context)
    assert after_first_approval.approved_recipe_versions == (version_one,)
    assert after_first_approval.capabilities.can_approve_recipe is False
    assert after_first_approval.capabilities.can_materialize_reference_path is False

    revised = feature.revise_recipe_draft(
        _canonicalize_authoring(
            ReviseScenarioRecipeDraftCommand(
                metadata=_authoring_metadata(
                    after_first_approval,
                    suffix="approval-successor",
                ),
                predecessor_draft_id=created.draft.draft_id,
                expected_draft_revision=created.draft.revision,
                payload=replace(
                    _authoring_payload(after_first_approval),
                    name="Wave 3 successor conformance Draft",
                ),
                author_id=ScenarioLabActorId("actor-81"),
                based_on_recipe_version_id=version_one.recipe_version_id,
            )
        )
    )
    assert revised.draft is not None
    assert revised.draft.based_on_recipe_version_id == (
        version_one.recipe_version_id
    )

    after_revise = feature.snapshot(context)
    successor_validation = feature.validate_recipe_draft(
        _canonicalize_authoring(
            ValidateScenarioRecipeDraftCommand(
                metadata=_authoring_metadata(
                    after_revise,
                    suffix="approval-successor-validation",
                ),
                draft_id=revised.draft.draft_id,
                expected_draft_revision=revised.draft.revision,
                expected_payload_hash=revised.draft.payload_hash,
            )
        )
    )
    assert successor_validation.validation is not None
    after_successor_validation = feature.snapshot(context)
    successor_approval = feature.approve_recipe(
        _canonicalize_authoring(
            ApproveScenarioRecipeCommand(
                metadata=_authoring_metadata(
                    after_successor_validation,
                    suffix="approval-successor-accept",
                ),
                draft_id=revised.draft.draft_id,
                expected_draft_revision=revised.draft.revision,
                expected_payload_hash=revised.draft.payload_hash,
                validation_id=successor_validation.validation.validation_id,
                actor_id=ScenarioLabActorId("approver-81"),
            )
        )
    )
    assert successor_approval.approved_version is not None
    version_two = successor_approval.approved_version
    assert version_two.version_number == 2
    assert version_two.recipe_id == version_one.recipe_id
    assert version_two.recipe_version_id != version_one.recipe_version_id
    assert version_two.content_hash != version_one.content_hash
    assert version_two.based_on_recipe_version_id == version_one.recipe_version_id
    assert feature.snapshot(context).approved_recipe_versions == (
        version_one,
        version_two,
    )
    feature.close()


@pytest.mark.parametrize(
    "feature_factory",
    (_live_authoring_feature, _fake_authoring_feature),
)
def test_shared_authoring_rejects_a_canonical_identity_that_does_not_match_the_body(
    feature_factory: Callable[[], ScenarioLabFeature],
) -> None:
    feature = feature_factory()
    context = ScenarioLabContext()
    feature.snapshot(context)
    ready = feature.snapshot(context)
    command = CreateScenarioRecipeDraftCommand(
        metadata=_authoring_metadata(
            ready,
            suffix="canonical-mismatch",
            canonical_content_identity="0" * 64,
        ),
        payload=_authoring_payload(ready),
        author_id=ScenarioLabActorId("actor-80"),
        authoring_mode=ScenarioRecipeAuthoringMode.MANUAL,
    )

    result = feature.create_recipe_draft(command)

    assert result.receipt.disposition is ScenarioLabCommandDisposition.REJECTED
    assert "canonical" in result.receipt.message.casefold()
    assert feature.snapshot(context).recipe_drafts == ()
    feature.close()


@pytest.mark.parametrize(
    "feature_factory",
    (_live_authoring_feature, _fake_authoring_feature),
)
def test_shared_authoring_keeps_same_body_distinct_across_different_commands(
    feature_factory: Callable[[], ScenarioLabFeature],
) -> None:
    feature = feature_factory()
    context = ScenarioLabContext()
    feature.snapshot(context)
    ready = feature.snapshot(context)
    first_command = _canonicalize_authoring(
        CreateScenarioRecipeDraftCommand(
            metadata=_authoring_metadata(ready, suffix="same-body-first"),
            payload=_authoring_payload(ready),
            author_id=ScenarioLabActorId("actor-80"),
            authoring_mode=ScenarioRecipeAuthoringMode.MANUAL,
        )
    )
    first = feature.create_recipe_draft(first_command)
    assert first.draft is not None
    after_first = feature.snapshot(context)
    second_command = _canonicalize_authoring(
        replace(
            first_command,
            metadata=_authoring_metadata(
                after_first,
                suffix="same-body-second",
            ),
        )
    )
    assert (
        first_command.metadata.canonical_content_identity
        == second_command.metadata.canonical_content_identity
    )

    second = feature.create_recipe_draft(second_command)

    assert first.receipt.disposition is ScenarioLabCommandDisposition.ACCEPTED
    assert second.receipt.disposition is ScenarioLabCommandDisposition.ACCEPTED
    assert second.draft is not None
    assert first.draft.draft_id != second.draft.draft_id
    assert first.draft.recipe_id != second.draft.recipe_id
    assert first.draft.payload_hash == second.draft.payload_hash
    feature.close()


@pytest.mark.parametrize(
    "feature_factory",
    (_live_authoring_feature, _fake_authoring_feature),
)
def test_shared_validation_keeps_same_body_distinct_across_different_commands(
    feature_factory: Callable[[], ScenarioLabFeature],
) -> None:
    feature = feature_factory()
    context = ScenarioLabContext()
    feature.snapshot(context)
    ready = feature.snapshot(context)
    created = feature.create_recipe_draft(
        _canonicalize_authoring(
            CreateScenarioRecipeDraftCommand(
                metadata=_authoring_metadata(ready, suffix="validation-source"),
                payload=_authoring_payload(ready),
                author_id=ScenarioLabActorId("actor-80"),
                authoring_mode=ScenarioRecipeAuthoringMode.MANUAL,
            )
        )
    )
    assert created.draft is not None
    after_create = feature.snapshot(context)
    first_command = _canonicalize_authoring(
        ValidateScenarioRecipeDraftCommand(
            metadata=_authoring_metadata(
                after_create,
                suffix="same-validation-first",
            ),
            draft_id=created.draft.draft_id,
            expected_draft_revision=created.draft.revision,
            expected_payload_hash=created.draft.payload_hash,
        )
    )
    first = feature.validate_recipe_draft(first_command)
    assert first.validation is not None
    after_first = feature.snapshot(context)
    second_command = _canonicalize_authoring(
        replace(
            first_command,
            metadata=_authoring_metadata(
                after_first,
                suffix="same-validation-second",
            ),
        )
    )
    assert (
        first_command.metadata.canonical_content_identity
        == second_command.metadata.canonical_content_identity
    )

    second = feature.validate_recipe_draft(second_command)

    assert second.receipt.disposition is ScenarioLabCommandDisposition.ACCEPTED
    assert second.validation is not None
    assert first.validation.validation_id != second.validation.validation_id
    assert first.validation.draft_id == second.validation.draft_id
    assert first.validation.payload_hash == second.validation.payload_hash
    feature.close()


@pytest.mark.parametrize(
    "feature_factory",
    (_live_authoring_feature, _fake_authoring_feature),
)
def test_shared_authoring_rejects_registered_transformation_parameter_bounds(
    feature_factory: Callable[[], ScenarioLabFeature],
) -> None:
    feature = feature_factory()
    context = ScenarioLabContext()
    feature.snapshot(context)
    ready = feature.snapshot(context)
    assert ready.transformation_catalog is not None
    transformation_id = next(
        item.transformation_id
        for item in ready.transformation_catalog.entries
        if item.transformation_id == "volatility-scaling.v1"
    )
    command = CreateScenarioRecipeDraftCommand(
        metadata=_authoring_metadata(ready, suffix="parameter-bounds-create"),
        payload=_authoring_payload(
            ready,
            transformations=(
                ScenarioRecipeTransformationInput(
                    transformation_id=transformation_id,
                    parameters=(
                        ScenarioRecipeParameterInput(
                            name="multiplier",
                            kind=ScenarioRecipeParameterKind.DECIMAL,
                            value=Decimal("3"),
                        ),
                    ),
                ),
            ),
        ),
        author_id=ScenarioLabActorId("actor-80"),
        authoring_mode=ScenarioRecipeAuthoringMode.MANUAL,
    )
    created = feature.create_recipe_draft(_canonicalize_authoring(command))
    assert created.draft is not None
    after_create = feature.snapshot(context)
    validation_command = ValidateScenarioRecipeDraftCommand(
        metadata=_authoring_metadata(
            after_create,
            suffix="parameter-bounds-validate",
        ),
        draft_id=created.draft.draft_id,
        expected_draft_revision=created.draft.revision,
        expected_payload_hash=created.draft.payload_hash,
    )

    result = feature.validate_recipe_draft(
        _canonicalize_authoring(validation_command)
    )

    assert result.receipt.disposition is ScenarioLabCommandDisposition.ACCEPTED
    assert result.validation is not None
    assert result.validation.is_valid is False
    assert "transformation.parameter-bounds" in {
        finding.rule_code for finding in result.validation.findings
    }
    feature.close()


@pytest.mark.parametrize(
    "feature_factory",
    (_live_ai_authoring_feature, _fake_ai_authoring_feature),
)
def test_shared_ai_authoring_body_exposes_configured_capability_and_audited_draft(
    feature_factory: Callable[[], ScenarioLabFeature],
) -> None:
    feature = feature_factory()
    context = ScenarioLabContext()
    feature.snapshot(context)
    ready = feature.snapshot(context)
    assert ready.capabilities.can_create_ai_assisted_recipe_draft
    assert ready.last_reliable_inventory is not None
    authoring = ready.last_reliable_inventory.authoring_capabilities
    assert authoring.ai_authoring_available
    assert authoring.ai_provider
    assert authoring.ai_model
    command = CreateAiAssistedScenarioRecipeDraftCommand(
        metadata=_authoring_metadata(ready, suffix="ai-create"),
        intent="Draft the exact admitted baseline for diagnostic review.",
        author_id=ScenarioLabActorId("scenario-ai-author-80"),
    )
    command = _canonicalize_authoring(command)

    accepted = feature.author_recipe_with_ai(command)
    replayed = feature.author_recipe_with_ai(
        replace(
            command,
            metadata=replace(
                command.metadata,
                command_id=ScenarioLabCommandId("command-80-ai-create-replay"),
            ),
        )
    )

    assert accepted.receipt.disposition is ScenarioLabCommandDisposition.ACCEPTED
    assert accepted.draft is not None
    assert accepted.draft.authoring_mode is ScenarioRecipeAuthoringMode.AI_ASSISTED
    assert accepted.draft.assistant_attempt_id
    assert replayed == accepted
    feature.close()


@pytest.mark.parametrize(
    "feature_factory",
    (_live_authoring_feature, _fake_authoring_feature),
)
def test_shared_ai_authoring_body_fails_closed_without_a_configured_provider(
    feature_factory: Callable[[], ScenarioLabFeature],
) -> None:
    feature = feature_factory()
    context = ScenarioLabContext()
    feature.snapshot(context)
    ready = feature.snapshot(context)
    assert not ready.capabilities.can_create_ai_assisted_recipe_draft
    command = CreateAiAssistedScenarioRecipeDraftCommand(
        metadata=_authoring_metadata(ready, suffix="ai-unconfigured"),
        intent="Draft the exact admitted baseline.",
        author_id=ScenarioLabActorId("scenario-ai-author-80"),
    )

    result = feature.author_recipe_with_ai(_canonicalize_authoring(command))

    assert result.receipt.disposition is ScenarioLabCommandDisposition.UNAVAILABLE
    assert result.draft is None
    feature.close()


@pytest.mark.parametrize(
    "feature_factory",
    (_live_ai_authoring_feature, _fake_ai_authoring_feature),
)
def test_shared_ai_authoring_rejects_a_tampered_payload_for_an_audited_attempt(
    feature_factory: Callable[[], ScenarioLabFeature],
) -> None:
    feature = feature_factory()
    context = ScenarioLabContext()
    feature.snapshot(context)
    ready = feature.snapshot(context)
    ai_command = _canonicalize_authoring(
        CreateAiAssistedScenarioRecipeDraftCommand(
            metadata=_authoring_metadata(ready, suffix="ai-audit-source"),
            intent="Draft the exact admitted baseline.",
            author_id=ScenarioLabActorId("scenario-ai-author-80"),
        )
    )
    authored = feature.author_recipe_with_ai(ai_command)
    assert authored.draft is not None
    assert authored.draft.assistant_attempt_id is not None
    after_ai = feature.snapshot(context)
    tampered = _canonicalize_authoring(
        CreateScenarioRecipeDraftCommand(
            metadata=_authoring_metadata(after_ai, suffix="ai-audit-tamper"),
            payload=replace(authored.draft.payload, name="Tampered AI payload"),
            author_id=authored.draft.author_id,
            authoring_mode=ScenarioRecipeAuthoringMode.AI_ASSISTED,
            assistant_attempt_id=authored.draft.assistant_attempt_id,
        )
    )

    result = feature.create_recipe_draft(tampered)

    assert result.receipt.disposition is ScenarioLabCommandDisposition.REJECTED
    assert result.draft is None
    assert "audited AI result" in result.receipt.message
    feature.close()


@pytest.mark.parametrize(
    "feature_factory",
    (_live_ai_authoring_feature, _fake_ai_authoring_feature),
)
def test_shared_ai_draft_revision_is_a_manual_successor_with_no_attempt_identity(
    feature_factory: Callable[[], ScenarioLabFeature],
) -> None:
    feature = feature_factory()
    context = ScenarioLabContext()
    feature.snapshot(context)
    ready = feature.snapshot(context)
    authored = feature.author_recipe_with_ai(
        _canonicalize_authoring(
            CreateAiAssistedScenarioRecipeDraftCommand(
                metadata=_authoring_metadata(ready, suffix="ai-revise-source"),
                intent="Draft the exact admitted baseline.",
                author_id=ScenarioLabActorId("scenario-ai-author-80"),
            )
        )
    )
    assert authored.draft is not None
    after_ai = feature.snapshot(context)
    revised = feature.revise_recipe_draft(
        _canonicalize_authoring(
            ReviseScenarioRecipeDraftCommand(
                metadata=_authoring_metadata(after_ai, suffix="ai-revise"),
                predecessor_draft_id=authored.draft.draft_id,
                expected_draft_revision=authored.draft.revision,
                payload=replace(
                    authored.draft.payload,
                    name="Human-reviewed AI successor",
                ),
                author_id=ScenarioLabActorId("scenario-human-reviewer-80"),
            )
        )
    )

    assert revised.receipt.disposition is ScenarioLabCommandDisposition.ACCEPTED
    assert revised.draft is not None
    assert revised.draft.authoring_mode is ScenarioRecipeAuthoringMode.MANUAL
    assert revised.draft.assistant_attempt_id is None
    feature.close()


@pytest.mark.parametrize("feature_factory", (_live_feature, _fake_feature))
def test_shared_read_body_covers_loading_ready_identity_and_immutability(
    feature_factory: Callable[[], ScenarioLabFeature],
) -> None:
    feature = feature_factory()
    context = ScenarioLabContext()

    loading = feature.snapshot(context)
    ready = feature.snapshot(context)

    assert loading.presentation.value == "loading"
    assert ready.presentation.value == "ready"
    assert ready.revision > loading.revision
    assert ready.source_revision is not None
    assert ready.source.generation.value == 1
    assert ready.historical_segments
    assert ready.reference_paths
    assert ready.market_scenarios
    assert ready.transformation_catalog is not None
    assert ready.reference_paths[0].path_id.value != ready.market_scenarios[0].scenario_id.value
    assert ready.market_scenarios[0].scenario_id.value.startswith("campaign-case-")
    assert ready.reference_paths[0].reconstructed
    assert "not recorded microstructure" in ready.reference_paths[0].reconstruction_notice
    assert ready.reference_paths[0].preview is not None
    assert len(ready.reference_paths[0].preview.nodes) <= ready.reference_paths[0].preview.bounded_node_limit
    assert ready.capabilities.can_create_recipe_draft
    assert not ready.capabilities.can_revise_recipe_draft
    assert not ready.capabilities.can_validate_recipe_draft
    assert not ready.capabilities.can_materialize_reference_path
    assert ready.historical_segments[0].admission_state.value == "admitted"
    assert ready.historical_segments[0].quality_state.value == "passed"
    assert ready.market_scenarios[0].unavailability_reasons[0].code is (
        ScenarioLabUnavailabilityCode.EXECUTION_ASSUMPTIONS_UNRESOLVED
    )
    with pytest.raises(FrozenInstanceError):
        ready.reference_paths[0].seed = 999  # type: ignore[misc]
    feature.close()


@pytest.mark.parametrize("feature_factory", (_live_feature, _fake_feature))
def test_shared_read_body_covers_search_subscription_dispose_and_close(
    feature_factory: Callable[[], ScenarioLabFeature],
) -> None:
    feature = feature_factory()
    context = ScenarioLabContext(search_text="volatility")
    delivered = []

    loading = feature.snapshot(context)
    subscription = feature.subscribe(context, delivered.append)
    ready = feature.snapshot(context)

    assert loading.revision < ready.revision
    assert ready.transformation_catalog is not None
    assert ready.transformation_catalog.entries[0].family == "volatility"
    assert delivered
    subscription.dispose()
    subscription.dispose()
    feature.close()
    feature.close()
    with pytest.raises(RuntimeError, match="closed"):
        feature.snapshot(context)


@pytest.mark.parametrize("feature_factory", (_live_feature, _fake_feature))
def test_shared_read_body_filters_only_typed_view_state(
    feature_factory: Callable[[], ScenarioLabFeature],
) -> None:
    feature = feature_factory()

    feature.snapshot(ScenarioLabContext())
    feature.snapshot(ScenarioLabContext())
    no_market = feature.snapshot(ScenarioLabContext(markets=("missing",)))
    no_layer = feature.snapshot(ScenarioLabContext(layers=("compound",)))
    recorded_only = feature.snapshot(ScenarioLabContext(reconstructed=False))
    path_only = feature.snapshot(
        ScenarioLabContext(
            markets=("cn-a",),
            search_text="deterministic-5m-to-30s",
        )
    )
    scenario_only = feature.snapshot(
        ScenarioLabContext(
            markets=("cn-a",),
            search_text="campaign-case-",
        )
    )
    source_only = feature.snapshot(
        ScenarioLabContext(sources=("snapshot-cn-a-2026-01",))
    )
    recipe_only = feature.snapshot(
        ScenarioLabContext(recipe_versions=("recipe-version-baseline-v1",))
    )
    family_only = feature.snapshot(
        ScenarioLabContext(transformation_families=("volatility",))
    )
    compatible_only = feature.snapshot(
        ScenarioLabContext(compatibilities=("compatible",))
    )
    reproducible_only = feature.snapshot(
        ScenarioLabContext(reproducibilities=("reproducible",))
    )
    missing_source = feature.snapshot(
        ScenarioLabContext(sources=("missing-source",))
    )

    assert no_market.historical_segments == ()
    assert no_market.reference_paths == ()
    assert no_market.market_scenarios == ()
    assert no_layer.historical_segments
    assert no_layer.reference_paths
    assert no_layer.market_scenarios == ()
    assert recorded_only.historical_segments
    assert recorded_only.reference_paths == ()
    assert path_only.historical_segments == ()
    assert path_only.reference_paths
    assert scenario_only.historical_segments == ()
    assert scenario_only.market_scenarios
    assert source_only.historical_segments
    assert source_only.reference_paths
    assert source_only.market_scenarios
    assert recipe_only.market_scenarios
    assert family_only.reference_paths == ()
    assert family_only.market_scenarios == ()
    assert family_only.transformation_catalog is not None
    assert family_only.transformation_catalog.entries[0].family == "volatility"
    assert compatible_only.reference_paths
    assert compatible_only.market_scenarios
    assert reproducible_only.reference_paths
    assert reproducible_only.market_scenarios
    assert missing_source.historical_segments == ()
    assert missing_source.reference_paths == ()
    assert missing_source.market_scenarios == ()
    feature.close()


@pytest.mark.parametrize(
    "feature_factory",
    (_live_authoring_feature, _fake_authoring_feature),
)
def test_shared_authoring_body_activates_drafts_and_keeps_future_mutations_unavailable(
    feature_factory: Callable[[], ScenarioLabFeature],
) -> None:
    feature = feature_factory()
    context = ScenarioLabContext()
    feature.snapshot(context)
    ready = feature.snapshot(context)
    assert ready.source_revision is not None
    def metadata(
        operation: str,
        source_revision: SourceRevisionToken,
    ) -> ScenarioLabCommandMetadata:
        return ScenarioLabCommandMetadata(
            command_id=ScenarioLabCommandId(f"command-80-{operation}"),
            idempotency_identity=ScenarioLabIdempotencyIdentity(
                f"idempotency-80-{operation}"
            ),
            canonical_content_identity=ScenarioLabCommandContentIdentity(
                f"content-80-{operation}"
            ),
            expected_source_revision=source_revision,
            expected_source_generation=SourceGenerationId(1),
        )

    payload = ScenarioRecipeDraftPayload(
        name="Wave 3 fixture",
        historical_segment_id=ready.historical_segments[0].segment_id,
        transformations=(),
        requested_execution_assumptions=RequestedExecutionAssumptionsProjection(
            commission_bps="1.0",
            slippage_bps="2.0",
            max_fill_fraction="0.25",
            latency_nodes=1,
            allow_partial_fills=True,
        ),
        decision_cadence_minutes=30,
        materialization_seed=80,
        data_policy=ScenarioRecipeDataPolicy.POINT_IN_TIME,
        market_rule_profile_version="a-share-cash-equity.v1",
    )

    created = feature.create_recipe_draft(
        _canonicalize_authoring(CreateScenarioRecipeDraftCommand(
            metadata("create", ready.source_revision),
            payload,
            ScenarioLabActorId("actor-80"),
            ScenarioRecipeAuthoringMode.MANUAL,
        ))
    )
    assert created.receipt.disposition is ScenarioLabCommandDisposition.ACCEPTED
    assert created.draft is not None
    after_create = feature.snapshot(context)
    assert after_create.source_revision is not None
    assert after_create.recipe_drafts == (created.draft,)
    assert after_create.capabilities.can_revise_recipe_draft
    assert after_create.capabilities.can_validate_recipe_draft

    revised = feature.revise_recipe_draft(
        _canonicalize_authoring(ReviseScenarioRecipeDraftCommand(
            metadata("revise", after_create.source_revision),
            created.draft.draft_id,
            created.draft.revision,
            replace(payload, name="Wave 3 successor fixture"),
            ScenarioLabActorId("actor-80"),
        ))
    )
    assert revised.receipt.disposition is ScenarioLabCommandDisposition.ACCEPTED
    assert revised.draft is not None
    after_revise = feature.snapshot(context)
    assert after_revise.source_revision is not None

    validated = feature.validate_recipe_draft(
        _canonicalize_authoring(ValidateScenarioRecipeDraftCommand(
            metadata("validate", after_revise.source_revision),
            revised.draft.draft_id,
            revised.draft.revision,
            revised.draft.payload_hash,
        ))
    )
    assert validated.receipt.disposition is ScenarioLabCommandDisposition.ACCEPTED
    assert validated.validation is not None
    after_validate = feature.snapshot(context)
    assert after_validate.recipe_validations == (validated.validation,)
    assert after_validate.source_revision is not None

    approval_result = feature.approve_recipe(
        _canonicalize_authoring(
            ApproveScenarioRecipeCommand(
                metadata("approve", after_validate.source_revision),
                revised.draft.draft_id,
                revised.draft.revision,
                revised.draft.payload_hash,
                validated.validation.validation_id,
                ScenarioLabActorId("actor-80"),
            )
        )
    )
    assert approval_result.receipt.disposition is (
        ScenarioLabCommandDisposition.ACCEPTED
    )
    assert approval_result.approved_version is not None
    future_results = (
        feature.materialize_reference_path(
            MaterializeApprovedScenarioRecipeCommand(
                metadata("materialize", after_validate.source_revision),
                ApprovedScenarioRecipeVersionId("recipe-80"),
                "recipe-content-80",
            )
        ),
        feature.retry_materialization(
            RetryScenarioMaterializationCommand(
                metadata("retry", after_validate.source_revision),
                ScenarioMaterializationAttemptId("attempt-80"),
                TaskHandleId("task-80"),
            )
        ),
        feature.compose_scenario_set(
            ComposeFormalScenarioSetCommand(
                metadata("compose", after_validate.source_revision),
                CampaignCaseId("baseline-80"),
                (CampaignCaseId("isolated-80"),),
                (CampaignCaseId("compound-80"),),
            )
        ),
        feature.resolve_execution_assumptions(
            ResolveScenarioExecutionAssumptionsCommand(
                metadata("resolve", after_validate.source_revision),
                (
                    ScenarioExecutionAssumptionTarget(
                        StrategyUnderTestId("strategy-80"),
                        CampaignCaseId("baseline-80"),
                    ),
                ),
            )
        ),
        feature.select_formal_scenario_set(
            SelectFormalScenarioSetCommand(
                metadata("select", after_validate.source_revision),
                ScenarioSetId("set-80"),
                (CampaignCaseId("baseline-80"),),
                after_validate.revision,
            )
        ),
    )

    assert all(
        result.receipt.disposition is ScenarioLabCommandDisposition.UNAVAILABLE
        for result in future_results
    )
    assert tuple(result.receipt.operation for result in future_results) == tuple(
        ScenarioLabTaskOperation
    )[4:]
    assert all(result.receipt.task_handle is None for result in future_results)
    feature.close()


def _failed_result() -> ScenarioLabApplicationInventoryResult:
    return ScenarioLabApplicationInventoryResult(
        availability=ScenarioLabApplicationAvailability.FAILED,
        inventory=None,
        source_token=None,
        observed_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        error=ScenarioLabApplicationError(
            code=ScenarioLabApplicationErrorCode.INVENTORY_READ_FAILED,
            message="fixture first-read failure",
            retryable=True,
        ),
    )


def _live_failed_feature() -> ScenarioLabFeature:
    return LiveScenarioLabAdapter(
        application=_TypedScenarioLabApplication(
            _inventory(),
            scripted=(_failed_result(),),
        )
    )


def _fake_failed_feature() -> ScenarioLabFeature:
    return DeterministicFakeScenarioLabAdapter(
        inventory=_inventory(),
        scripted_results=(_failed_result(),),
    )


@pytest.mark.parametrize(
    "feature_factory",
    (_live_failed_feature, _fake_failed_feature),
)
def test_shared_read_body_exposes_structured_first_read_failure(
    feature_factory: Callable[[], ScenarioLabFeature],
) -> None:
    feature = feature_factory()
    context = ScenarioLabContext()

    assert feature.snapshot(context).presentation.value == "loading"
    failed = feature.snapshot(context)

    assert failed.presentation.value == "failed"
    assert failed.error is not None
    assert failed.error.code == "scenario_lab_inventory_read_failed"
    assert failed.error.retryable
    assert failed.last_reliable_inventory is None
    feature.close()


def _ready_result(
    inventory: ScenarioLabInventory,
) -> ScenarioLabApplicationInventoryResult:
    return ScenarioLabApplicationInventoryResult(
        availability=ScenarioLabApplicationAvailability.READY,
        inventory=inventory,
        source_token=SourceRevisionToken("a" * 64),
        observed_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        error=None,
    )


def _live_stale_feature() -> ScenarioLabFeature:
    inventory = _inventory()
    return LiveScenarioLabAdapter(
        application=_TypedScenarioLabApplication(
            inventory,
            scripted=(_ready_result(inventory), _failed_result()),
        )
    )


def _fake_stale_feature() -> ScenarioLabFeature:
    inventory = _inventory()
    return DeterministicFakeScenarioLabAdapter(
        inventory=inventory,
        scripted_results=(_ready_result(inventory), _failed_result()),
    )


@pytest.mark.parametrize("feature_factory", (_live_stale_feature, _fake_stale_feature))
def test_shared_read_body_retains_last_reliable_inventory_on_structured_failure(
    feature_factory: Callable[[], ScenarioLabFeature],
) -> None:
    feature = feature_factory()
    context = ScenarioLabContext()
    assert feature.snapshot(context).presentation.value == "loading"
    ready = feature.snapshot(context)
    stale = feature.snapshot(context)

    assert stale.presentation.value == "stale"
    assert stale.historical_segments == ready.historical_segments
    assert stale.last_reliable_inventory == ready.last_reliable_inventory
    assert stale.error is not None
    assert stale.error.retryable
    feature.close()


def _empty_inventory() -> ScenarioLabInventory:
    return replace(
        _inventory(),
        historical_segments=(),
        reference_paths=(),
        market_scenarios=(),
    )


def _live_empty_feature() -> ScenarioLabFeature:
    return LiveScenarioLabAdapter(
        application=_TypedScenarioLabApplication(_empty_inventory())
    )


def _fake_empty_feature() -> ScenarioLabFeature:
    return DeterministicFakeScenarioLabAdapter(inventory=_empty_inventory())


@pytest.mark.parametrize("feature_factory", (_live_empty_feature, _fake_empty_feature))
def test_shared_read_body_exposes_honest_empty_inventory(
    feature_factory: Callable[[], ScenarioLabFeature],
) -> None:
    feature = feature_factory()
    context = ScenarioLabContext()
    assert feature.snapshot(context).presentation.value == "loading"
    empty = feature.snapshot(context)

    assert empty.presentation.value == "empty"
    assert empty.historical_segments == ()
    assert empty.reference_paths == ()
    assert empty.market_scenarios == ()
    assert empty.transformation_catalog is not None
    feature.close()


@pytest.mark.parametrize("feature_factory", (_live_feature, _fake_feature))
def test_shared_read_body_restores_only_an_exact_visible_focus_identity(
    feature_factory: Callable[[], ScenarioLabFeature],
) -> None:
    path_id = _inventory().reference_paths[0].path_id.value
    visible_context = ScenarioLabContext(
        focus_target=ScenarioLabFocusTarget.REFERENCE_PATH,
        focus_identity=path_id,
    )
    hidden_context = replace(visible_context, search_text="no-match")
    feature = feature_factory()
    feature.snapshot(visible_context)
    visible = feature.snapshot(visible_context)
    hidden = feature.snapshot(hidden_context)

    assert visible.focus_restoration_identity == path_id
    assert hidden.focus_restoration_identity is None
    feature.close()


def test_live_adapter_refreshes_only_for_scenario_lab_invalidations() -> None:
    bridge = EventBridge(subscribe_backend=False)
    application = _TypedScenarioLabApplication(_inventory())
    feature = LiveScenarioLabAdapter(
        application=application,
        event_bridge=bridge,
    )
    context = ScenarioLabContext()
    feature.snapshot(context)
    feature.snapshot(context)
    reads = application.read_calls

    bridge.on_snapshot({"kind": "run-monitoring"}, generation=1)
    bridge.flush(force=True)
    assert application.read_calls == reads

    bridge.on_snapshot({"kind": "scenario-lab"}, generation=1)
    bridge.flush(force=True)
    assert application.read_calls == reads + 1
    feature.close()
    bridge.stop()


def test_live_adapter_refreshes_each_subscribed_context_against_its_own_token() -> None:
    bridge = EventBridge(subscribe_backend=False)
    inventory = _inventory()
    application = _TypedScenarioLabApplication(inventory)
    feature = LiveScenarioLabAdapter(application=application, event_bridge=bridge)
    first = ScenarioLabContext(search_text="volatility")
    second = ScenarioLabContext(search_text="campaign-case")
    first_states = []
    second_states = []

    first_subscription = feature.subscribe(first, first_states.append)
    feature.snapshot(first)
    second_subscription = feature.subscribe(second, second_states.append)
    feature.snapshot(second)
    application.result = replace(
        application.result,
        source_token=SourceRevisionToken("b" * 64),
    )
    reads = application.read_calls

    bridge.on_snapshot({"kind": "scenario-lab"}, generation=1)
    bridge.flush(force=True)

    assert application.read_calls == reads + 2
    assert first_states[-1].source_revision == SourceRevisionToken("b" * 64)
    assert second_states[-1].source_revision == SourceRevisionToken("b" * 64)

    first_subscription.dispose()
    reads = application.read_calls
    application.result = replace(
        application.result,
        source_token=SourceRevisionToken("c" * 64),
    )
    bridge.on_snapshot({"kind": "scenario-lab"}, generation=1)
    bridge.flush(force=True)
    assert application.read_calls == reads + 1
    assert second_states[-1].source_revision == SourceRevisionToken("c" * 64)

    second_subscription.dispose()
    feature.close()
    bridge.stop()


class _PartialConnectionHarness:
    def __init__(
        self,
        feature: ScenarioLabFeature,
        disconnect: Callable[[], object],
        cleanup: Callable[[], object],
    ) -> None:
        self.feature = feature
        self.disconnect = disconnect
        self.cleanup = cleanup


def _partial_inventory() -> ScenarioLabInventory:
    inventory = _inventory()
    failed_path = replace(
        inventory.reference_paths[0],
        integrity=ScenarioLabIntegrityState.FAILED,
        preview=None,
        unavailability_reasons=(
            ScenarioLabUnavailabilityReason(
                code=ScenarioLabUnavailabilityCode.PATH_INTEGRITY_FAILED,
                summary="Fixture integrity failure.",
                corrective_guidance="Re-materialize the fixture path.",
            ),
        ),
    )
    return replace(inventory, reference_paths=(failed_path,))


def _partial_result() -> ScenarioLabApplicationInventoryResult:
    inventory = _partial_inventory()
    return ScenarioLabApplicationInventoryResult(
        availability=ScenarioLabApplicationAvailability.PARTIAL,
        inventory=inventory,
        source_token=SourceRevisionToken("b" * 64),
        observed_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        error=None,
    )


def _live_partial_connection_harness() -> _PartialConnectionHarness:
    bridge = EventBridge(subscribe_backend=False)
    feature = LiveScenarioLabAdapter(
        application=_TypedScenarioLabApplication(
            _partial_inventory(),
            scripted=(_partial_result(),),
        ),
        event_bridge=bridge,
    )
    return _PartialConnectionHarness(
        feature,
        bridge.mark_disconnected,
        bridge.stop,
    )


def _fake_partial_connection_harness() -> _PartialConnectionHarness:
    feature = DeterministicFakeScenarioLabAdapter(
        inventory=_partial_inventory(),
        scripted_results=(_partial_result(),),
    )
    return _PartialConnectionHarness(
        feature,
        feature.advance_to_disconnected,
        lambda: None,
    )


@pytest.mark.parametrize(
    "harness_factory",
    (_live_partial_connection_harness, _fake_partial_connection_harness),
)
def test_shared_connection_body_retains_partial_truth_for_new_contexts(
    harness_factory: Callable[[], _PartialConnectionHarness],
) -> None:
    harness = harness_factory()
    harness.feature.snapshot(ScenarioLabContext())
    partial = harness.feature.snapshot(ScenarioLabContext())
    assert partial.presentation.value == "partial"
    assert partial.completeness.value == "partial"

    harness.disconnect()
    retained = harness.feature.snapshot(
        ScenarioLabContext(search_text="reference")
    )

    assert retained.presentation.value == "disconnected"
    assert retained.completeness.value == "partial"
    assert retained.last_reliable_inventory is not None
    harness.feature.close()
    harness.cleanup()


def replace_result_source(
    token: SourceRevisionToken | None,
    inventory: ScenarioLabInventory,
) -> ScenarioLabApplicationInventoryResult:
    return ScenarioLabApplicationInventoryResult(
        availability=ScenarioLabApplicationAvailability.READY,
        inventory=inventory,
        source_token=token,
        observed_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        error=None,
    )


def test_app_context_composes_scenario_lab_as_the_fifth_independent_feature(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "1")
    context = build_app_context(
        settings_path=str(tmp_path / "settings.json"),
        run_monitoring_mode="fake",
    )

    assert isinstance(context.scenario_lab_feature, ScenarioLabFeature)
    assert context.scenario_lab_feature.interface_version.render() == "1.0"
    assert context.scenario_lab_context == ScenarioLabContext()
    assert context.scenario_lab_feature is not context.strategy_library_feature
    context.strategy_library_feature.close()
    context.scenario_lab_feature.close()
    context.diagnostic_tasks_feature.close()
    context.run_monitoring_feature.close()
    context.evidence_and_findings_feature.close()


class _ConnectionHarness:
    def __init__(
        self,
        feature: ScenarioLabFeature,
        disconnect: Callable[[], object],
        reconnect: Callable[[], object],
        old_generation_invalidation: Callable[[], object],
        cleanup: Callable[[], object],
    ) -> None:
        self.feature = feature
        self.disconnect = disconnect
        self.reconnect = reconnect
        self.old_generation_invalidation = old_generation_invalidation
        self.cleanup = cleanup


def _live_connection_harness() -> _ConnectionHarness:
    bridge = EventBridge(subscribe_backend=False)
    feature = LiveScenarioLabAdapter(
        application=_TypedScenarioLabApplication(_inventory()),
        event_bridge=bridge,
    )
    return _ConnectionHarness(
        feature,
        bridge.mark_disconnected,
        bridge.mark_reconnected,
        lambda: (
            bridge.on_snapshot({"kind": "scenario-lab"}, generation=1),
            bridge.flush(force=True),
        ),
        bridge.stop,
    )


def _fake_connection_harness() -> _ConnectionHarness:
    feature = DeterministicFakeScenarioLabAdapter(inventory=_inventory())
    return _ConnectionHarness(
        feature,
        feature.advance_to_disconnected,
        feature.advance_to_reconnected,
        lambda: feature.deliver_invalidation(generation=1),
        lambda: None,
    )


@pytest.mark.parametrize(
    "harness_factory",
    (_live_connection_harness, _fake_connection_harness),
)
def test_shared_connection_body_retains_data_rereads_and_quarantines_old_generation(
    harness_factory: Callable[[], _ConnectionHarness],
) -> None:
    harness = harness_factory()
    context = ScenarioLabContext()
    harness.feature.snapshot(context)
    ready = harness.feature.snapshot(context)

    harness.disconnect()
    disconnected = harness.feature.snapshot(context)
    assert disconnected.presentation.value == "disconnected"
    assert disconnected.historical_segments == ready.historical_segments
    assert disconnected.freshness.value == "disconnected"

    harness.reconnect()
    reconnected = harness.feature.snapshot(context)
    assert reconnected.presentation.value == "ready"
    assert reconnected.source.generation.value > ready.source.generation.value
    assert reconnected.source_revision == ready.source_revision

    revision = reconnected.revision
    harness.old_generation_invalidation()
    quarantined = harness.feature.snapshot(context)
    assert quarantined.revision == revision
    assert quarantined.source.generation == reconnected.source.generation
    assert reconnected.source_revision is not None
    stale_generation_command = _canonicalize_authoring(
        CreateScenarioRecipeDraftCommand(
            ScenarioLabCommandMetadata(
                command_id=ScenarioLabCommandId("command-80-old-generation"),
                idempotency_identity=ScenarioLabIdempotencyIdentity(
                    "idempotency-80-old-generation"
                ),
                canonical_content_identity=ScenarioLabCommandContentIdentity(
                    "pending-old-generation"
                ),
                expected_source_revision=reconnected.source_revision,
                expected_source_generation=ready.source.generation,
            ),
            ScenarioRecipeDraftPayload(
                name="Old generation Draft",
                historical_segment_id=reconnected.historical_segments[0].segment_id,
                transformations=(),
                requested_execution_assumptions=(
                    RequestedExecutionAssumptionsProjection(
                        commission_bps="3",
                        slippage_bps="0",
                        max_fill_fraction="1",
                        latency_nodes=0,
                        allow_partial_fills=True,
                    )
                ),
                decision_cadence_minutes=30,
                materialization_seed=80,
                data_policy=ScenarioRecipeDataPolicy.POINT_IN_TIME,
                market_rule_profile_version="a-share-cash-equity.v1",
            ),
            ScenarioLabActorId("actor-80"),
            ScenarioRecipeAuthoringMode.MANUAL,
        )
    )
    stale_result = harness.feature.create_recipe_draft(stale_generation_command)
    assert stale_result.receipt.disposition is ScenarioLabCommandDisposition.CONFLICT
    assert "old-generation" in stale_result.receipt.message
    harness.feature.close()
    harness.cleanup()
