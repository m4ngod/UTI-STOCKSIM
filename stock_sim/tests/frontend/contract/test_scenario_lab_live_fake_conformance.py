from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
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
    ScenarioRecipeValidationId,
    ValidateScenarioRecipeDraftCommand,
    ValidateScenarioRecipeDraftResult,
)
from app.features.strategy_diagnostics_v1_read_model import SourceRevisionToken


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
    assert not ready.capabilities.can_create_recipe_draft
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


@pytest.mark.parametrize("feature_factory", (_live_feature, _fake_feature))
def test_shared_read_body_keeps_recipe_mutations_typed_unavailable(
    feature_factory: Callable[[], ScenarioLabFeature],
) -> None:
    feature = feature_factory()
    context = ScenarioLabContext()
    feature.snapshot(context)
    ready = feature.snapshot(context)
    assert ready.source_revision is not None
    def metadata(operation: str) -> ScenarioLabCommandMetadata:
        return ScenarioLabCommandMetadata(
            command_id=ScenarioLabCommandId(f"command-79-{operation}"),
            idempotency_identity=ScenarioLabIdempotencyIdentity(
                f"idempotency-79-{operation}"
            ),
            canonical_content_identity=ScenarioLabCommandContentIdentity(
                f"content-79-{operation}"
            ),
            expected_source_revision=ready.source_revision,
            expected_source_generation=SourceGenerationId(1),
        )

    payload = ScenarioRecipeDraftPayload(
        name="Wave 3 fixture",
        historical_segment_id=HistoricalMarketSegmentId("segment-79"),
        transformations=(),
        requested_execution_assumptions=RequestedExecutionAssumptionsProjection(
            commission_bps="1.0",
            slippage_bps="2.0",
            max_fill_fraction="0.25",
            latency_nodes=1,
            allow_partial_fills=True,
        ),
        decision_cadence_minutes=5,
        materialization_seed=79,
        data_policy=ScenarioRecipeDataPolicy.POINT_IN_TIME,
        market_rule_profile_version="cn-a-v1",
    )

    results = (
        feature.create_recipe_draft(
            CreateScenarioRecipeDraftCommand(
                metadata("create"),
                payload,
                ScenarioLabActorId("actor-79"),
                ScenarioRecipeAuthoringMode.MANUAL,
            )
        ),
        feature.revise_recipe_draft(
            ReviseScenarioRecipeDraftCommand(
                metadata("revise"),
                ScenarioRecipeDraftId("draft-79"),
                1,
                payload,
                ScenarioLabActorId("actor-79"),
            )
        ),
        feature.validate_recipe_draft(
            ValidateScenarioRecipeDraftCommand(
                metadata("validate"),
                ScenarioRecipeDraftId("draft-79"),
                1,
                "payload-hash-79",
            )
        ),
        feature.approve_recipe(
            ApproveScenarioRecipeCommand(
                metadata("approve"),
                ScenarioRecipeDraftId("draft-79"),
                1,
                "payload-hash-79",
                ScenarioRecipeValidationId("validation-79"),
                ScenarioLabActorId("actor-79"),
            )
        ),
        feature.materialize_reference_path(
            MaterializeApprovedScenarioRecipeCommand(
                metadata("materialize"),
                ApprovedScenarioRecipeVersionId("recipe-79"),
                "recipe-content-79",
            )
        ),
        feature.retry_materialization(
            RetryScenarioMaterializationCommand(
                metadata("retry"),
                ScenarioMaterializationAttemptId("attempt-79"),
                TaskHandleId("task-79"),
            )
        ),
        feature.compose_scenario_set(
            ComposeFormalScenarioSetCommand(
                metadata("compose"),
                CampaignCaseId("baseline-79"),
                (CampaignCaseId("isolated-79"),),
                (CampaignCaseId("compound-79"),),
            )
        ),
        feature.resolve_execution_assumptions(
            ResolveScenarioExecutionAssumptionsCommand(
                metadata("resolve"),
                (
                    ScenarioExecutionAssumptionTarget(
                        StrategyUnderTestId("strategy-79"),
                        CampaignCaseId("baseline-79"),
                    ),
                ),
            )
        ),
        feature.select_formal_scenario_set(
            SelectFormalScenarioSetCommand(
                metadata("select"),
                ScenarioSetId("set-79"),
                (CampaignCaseId("baseline-79"),),
                ready.revision,
            )
        ),
    )

    assert all(
        result.receipt.disposition is ScenarioLabCommandDisposition.UNAVAILABLE
        for result in results
    )
    assert tuple(result.receipt.operation for result in results) == tuple(
        ScenarioLabTaskOperation
    )
    assert all(result.receipt.task_handle is None for result in results)
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
    harness.feature.close()
    harness.cleanup()
