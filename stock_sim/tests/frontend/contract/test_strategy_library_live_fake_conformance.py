from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from app.app_context import build_app_context
from app.event_bridge import EventBridge
from app.features.live_strategy_library import (
    DeterministicFakeStrategyLibraryAdapter,
    LiveStrategyLibraryAdapter,
)
from app.features.strategy_library import (
    StrategyLibraryAvailabilityFilter,
    StrategyLibraryBlockingCode,
    StrategyLibraryContext,
    StrategyLibraryFeature,
    StrategyLibraryPresentationState,
)
from app.features.strategy_library_application import (
    STRATEGY_LIBRARY_APPLICATION_INTERFACE_VERSION,
    FormalStrategySetValidation,
    FormalStrategySetValidationState,
    LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter,
    StrategyAvailability,
    StrategyAvailabilityReason,
    StrategyAvailabilityReasonCode,
    StrategyDiagnosticsV1StrategyLibraryApplication,
    StrategyLibraryApplicationAvailability,
    StrategyLibraryApplicationError,
    StrategyLibraryApplicationErrorCode,
    StrategyLibraryApplicationInventoryResult,
    StrategyLibraryApplicationVersion,
    StrategyLibraryInventory,
    ValidateFormalStrategySet,
)
from app.features.run_monitoring import (
    Completeness,
    Freshness,
    StrategyUnderTestId,
)
from app.features.strategy_diagnostics_v1_read_model import SourceRevisionToken
from strategy_diagnostics import create_diagnostics_application


def _live_feature() -> StrategyLibraryFeature:
    application = create_diagnostics_application()
    application.start()
    return LiveStrategyLibraryAdapter(
        application=(
            LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter(
                application
            )
        )
    )


def _fake_feature() -> StrategyLibraryFeature:
    application = create_diagnostics_application()
    application.start()
    result = LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter(
        application
    ).read_inventory()
    assert result.inventory is not None
    return DeterministicFakeStrategyLibraryAdapter(inventory=result.inventory)


class _ScriptedStrategyLibraryApplication:
    def __init__(
        self,
        results: tuple[StrategyLibraryApplicationInventoryResult, ...],
    ) -> None:
        self._results = list(results)
        self._last = results[-1]

    @property
    def interface_version(self) -> StrategyLibraryApplicationVersion:
        return STRATEGY_LIBRARY_APPLICATION_INTERFACE_VERSION

    def read_inventory(self) -> StrategyLibraryApplicationInventoryResult:
        if self._results:
            self._last = self._results.pop(0)
        return self._last

    def validate_formal_strategy_set(
        self,
        command: ValidateFormalStrategySet,
    ) -> FormalStrategySetValidation:
        return FormalStrategySetValidation(
            state=FormalStrategySetValidationState.UNAVAILABLE,
            selections=(),
            source_revision=command.expected_source_revision,
            reasons=(),
        )


def _authoritative_result() -> StrategyLibraryApplicationInventoryResult:
    application = create_diagnostics_application()
    application.start()
    return LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter(
        application
    ).read_inventory()


def _failed_result() -> StrategyLibraryApplicationInventoryResult:
    return StrategyLibraryApplicationInventoryResult(
        availability=StrategyLibraryApplicationAvailability.FAILED,
        inventory=None,
        source_token=None,
        observed_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
        error=StrategyLibraryApplicationError(
            code=StrategyLibraryApplicationErrorCode.INVENTORY_READ_FAILED,
            message="Authoritative Strategy inventory read failed.",
            retryable=True,
        ),
    )


def _live_scripted_feature(
    results: tuple[StrategyLibraryApplicationInventoryResult, ...],
) -> StrategyLibraryFeature:
    application = _ScriptedStrategyLibraryApplication(results)
    return LiveStrategyLibraryAdapter(
        application=application,
        clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
    )


def _fake_scripted_feature(
    results: tuple[StrategyLibraryApplicationInventoryResult, ...],
) -> StrategyLibraryFeature:
    inventory = _authoritative_result().inventory
    assert inventory is not None
    return DeterministicFakeStrategyLibraryAdapter(
        inventory=inventory,
        scripted_results=results,
        clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
    )


_SCRIPTED_FACTORIES = (_live_scripted_feature, _fake_scripted_feature)


@pytest.mark.parametrize("feature_factory", [_live_feature, _fake_feature])
def test_live_and_fake_browse_search_and_filter_typed_inventory(
    feature_factory: Callable[[], StrategyLibraryFeature],
) -> None:
    feature = feature_factory()
    loading = feature.snapshot(StrategyLibraryContext())
    ready = feature.snapshot(StrategyLibraryContext())

    assert loading.presentation is StrategyLibraryPresentationState.LOADING
    assert ready.presentation is StrategyLibraryPresentationState.READY
    assert ready.freshness is Freshness.FRESH
    assert ready.completeness is Completeness.COMPLETE
    assert len(ready.entries) == 2
    assert ready.last_reliable_inventory is not None
    assert ready.source_revision is not None
    assert all(item.formal_campaign_eligible for item in ready.entries)

    searched = feature.snapshot(
        StrategyLibraryContext(search_text="live minute")
    )
    assert len(searched.entries) == 1
    assert "Live Minute" in searched.entries[0].display.display_name

    lifecycle_capability = ready.entries[0].compatibility.lifecycle_callbacks[0]
    capability_search = feature.snapshot(
        StrategyLibraryContext(search_text=lifecycle_capability)
    )
    assert capability_search.entries
    assert all(
        lifecycle_capability in item.compatibility.lifecycle_callbacks
        for item in capability_search.entries
    )

    filtered = feature.snapshot(
        StrategyLibraryContext(
            availability_filter=(
                StrategyLibraryAvailabilityFilter.FORMAL_CAMPAIGN_READY
            )
        )
    )
    assert len(filtered.entries) == 2

    capability_context = StrategyLibraryContext(
        required_capabilities=("get_history",),
        focus_strategy_id=ready.entries[1].strategy_id,
    )
    feature.snapshot(capability_context)
    capability_filtered = feature.snapshot(capability_context)
    assert len(capability_filtered.entries) == 2
    assert capability_filtered.focus_restoration_id == ready.entries[1].strategy_id
    feature.close()


@pytest.mark.parametrize("feature_factory", [_live_feature, _fake_feature])
def test_live_and_fake_subscription_dispose_and_close_are_idempotent(
    feature_factory: Callable[[], StrategyLibraryFeature],
) -> None:
    feature = feature_factory()
    context = StrategyLibraryContext()
    feature.snapshot(context)
    observed = []

    subscription = feature.subscribe(context, observed.append)
    feature.snapshot(context)

    assert observed
    delivered = len(observed)
    subscription.dispose()
    subscription.dispose()
    feature.snapshot(context)
    assert len(observed) == delivered
    feature.close()
    feature.close()


@pytest.mark.parametrize("feature_factory", _SCRIPTED_FACTORIES)
def test_failed_first_read_is_typed_failed_not_empty(
    feature_factory: Callable[
        [tuple[StrategyLibraryApplicationInventoryResult, ...]],
        StrategyLibraryFeature,
    ],
) -> None:
    feature = feature_factory((_failed_result(),))
    context = StrategyLibraryContext()

    feature.snapshot(context)
    failed = feature.snapshot(context)

    assert failed.presentation is StrategyLibraryPresentationState.FAILED
    assert failed.completeness is Completeness.UNKNOWN
    assert failed.last_reliable_inventory is None
    assert failed.entries == ()
    assert failed.error is not None
    assert failed.error.retryable
    feature.close()


@pytest.mark.parametrize("feature_factory", _SCRIPTED_FACTORIES)
def test_failed_refresh_retains_last_reliable_inventory_as_stale(
    feature_factory: Callable[
        [tuple[StrategyLibraryApplicationInventoryResult, ...]],
        StrategyLibraryFeature,
    ],
) -> None:
    reliable_result = _authoritative_result()
    feature = feature_factory((reliable_result, _failed_result()))
    context = StrategyLibraryContext()

    feature.snapshot(context)
    reliable = feature.snapshot(context)
    stale = feature.snapshot(context)

    assert reliable.presentation is StrategyLibraryPresentationState.READY
    assert stale.presentation is StrategyLibraryPresentationState.STALE
    assert stale.freshness is Freshness.STALE
    assert stale.last_reliable_inventory == reliable.last_reliable_inventory
    assert stale.entries == reliable.entries
    assert stale.error is not None
    feature.close()


@pytest.mark.parametrize("feature_factory", _SCRIPTED_FACTORIES)
def test_duplicate_source_revision_is_quarantined(
    feature_factory: Callable[
        [tuple[StrategyLibraryApplicationInventoryResult, ...]],
        StrategyLibraryFeature,
    ],
) -> None:
    result = _authoritative_result()
    feature = feature_factory((result, result))
    context = StrategyLibraryContext()

    feature.snapshot(context)
    reliable = feature.snapshot(context)
    duplicate = feature.snapshot(context)

    assert duplicate is reliable
    assert duplicate.revision == reliable.revision
    feature.close()


@pytest.mark.parametrize("feature_factory", _SCRIPTED_FACTORIES)
def test_lower_entity_revision_is_quarantined(
    feature_factory: Callable[
        [tuple[StrategyLibraryApplicationInventoryResult, ...]],
        StrategyLibraryFeature,
    ],
) -> None:
    reliable_result = _authoritative_result()
    assert reliable_result.inventory is not None
    older_inventory = replace(
        reliable_result.inventory,
        entries=tuple(
            replace(item, entity_revision=0)
            for item in reliable_result.inventory.entries
        ),
    )
    older_result = replace(
        reliable_result,
        inventory=older_inventory,
        source_token=SourceRevisionToken("0" * 64),
    )
    feature = feature_factory((reliable_result, older_result))
    context = StrategyLibraryContext()

    feature.snapshot(context)
    reliable = feature.snapshot(context)
    quarantined = feature.snapshot(context)

    assert quarantined is reliable
    assert quarantined.source_revision == reliable.source_revision
    assert all(item.entity_revision == 1 for item in quarantined.entries)
    feature.close()


class _ConnectionHarness:
    def __init__(
        self,
        feature: StrategyLibraryFeature,
        disconnect: Callable[[], object],
        reconnect: Callable[[], object],
        old_generation_invalidation: Callable[[], object],
    ) -> None:
        self.feature = feature
        self.disconnect = disconnect
        self.reconnect = reconnect
        self.old_generation_invalidation = old_generation_invalidation


def _live_connection_harness() -> _ConnectionHarness:
    bridge = EventBridge(subscribe_backend=False)
    application = create_diagnostics_application()
    application.start()
    feature = LiveStrategyLibraryAdapter(
        application=LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter(
            application
        ),
        event_bridge=bridge,
    )
    return _ConnectionHarness(
        feature,
        bridge.mark_disconnected,
        bridge.mark_reconnected,
        lambda: (
            bridge.on_snapshot({"kind": "strategy-library"}, generation=1),
            bridge.flush(force=True),
        ),
    )


def _fake_connection_harness() -> _ConnectionHarness:
    result = _authoritative_result()
    assert result.inventory is not None
    feature = DeterministicFakeStrategyLibraryAdapter(
        inventory=result.inventory
    )
    return _ConnectionHarness(
        feature,
        feature.advance_to_disconnected,
        feature.advance_to_reconnected,
        lambda: feature.deliver_invalidation(generation=1),
    )


@pytest.mark.parametrize(
    "harness_factory",
    [_live_connection_harness, _fake_connection_harness],
)
def test_reconnect_stays_stale_until_authoritative_reread(
    harness_factory: Callable[[], _ConnectionHarness],
) -> None:
    harness = harness_factory()
    feature = harness.feature
    context = StrategyLibraryContext()
    feature.snapshot(context)
    reliable = feature.snapshot(context)
    observed = []
    subscription = feature.subscribe(context, observed.append)

    harness.disconnect()
    disconnected = feature.snapshot(context)
    harness.reconnect()
    recovered = feature.snapshot(context)

    assert disconnected.presentation is (
        StrategyLibraryPresentationState.DISCONNECTED
    )
    assert disconnected.freshness is Freshness.DISCONNECTED
    assert disconnected.entries == reliable.entries
    assert recovered.freshness is Freshness.FRESH
    assert recovered.source.generation.value == 2
    assert any(
        state.source.generation.value == 2
        and state.freshness is Freshness.STALE
        for state in observed
    )
    subscription.dispose()
    feature.close()


@pytest.mark.parametrize(
    "harness_factory",
    [_live_connection_harness, _fake_connection_harness],
)
def test_old_generation_invalidation_is_quarantined(
    harness_factory: Callable[[], _ConnectionHarness],
) -> None:
    harness = harness_factory()
    feature = harness.feature
    context = StrategyLibraryContext()
    feature.snapshot(context)
    feature.snapshot(context)
    harness.disconnect()
    harness.reconnect()
    current = feature.snapshot(context)

    harness.old_generation_invalidation()
    quarantined = feature.snapshot(context)

    assert quarantined is current
    assert quarantined.source.generation.value == 2
    feature.close()


def test_unavailable_status_families_remain_visible_as_partial_inventory() -> None:
    result = _authoritative_result()
    assert result.inventory is not None
    template = result.inventory.entries[0]
    status_reasons = (
        (
            StrategyAvailability.UNAVAILABLE,
            StrategyAvailabilityReasonCode.APPLICATION_NOT_READY,
        ),
        (
            StrategyAvailability.OUTDATED,
            StrategyAvailabilityReasonCode.COMPATIBILITY_SURFACE_OUTDATED,
        ),
        (
            StrategyAvailability.INCOMPATIBLE,
            StrategyAvailabilityReasonCode.COMPATIBILITY_MANIFEST_MISMATCH,
        ),
        (
            StrategyAvailability.MISSING_DEPENDENCY,
            StrategyAvailabilityReasonCode.REQUIRED_DEPENDENCY_MISSING,
        ),
    )
    blocked = tuple(
        replace(
            template,
            strategy_id=StrategyUnderTestId(f"blocked-strategy-{index}"),
            availability=status,
            formal_campaign_eligible=False,
            availability_reasons=(
                StrategyAvailabilityReason(
                    code=reason_code,
                    summary="This formal Strategy remains visible but blocked.",
                    corrective_guidance="Restore the named backend dependency.",
                ),
            ),
        )
        for index, (status, reason_code) in enumerate(status_reasons, start=1)
    )
    inventory = replace(
        result.inventory,
        entries=(result.inventory.entries[1], *blocked),
    )
    feature = DeterministicFakeStrategyLibraryAdapter(inventory=inventory)

    feature.snapshot(StrategyLibraryContext())
    partial = feature.snapshot(StrategyLibraryContext())

    assert partial.presentation is StrategyLibraryPresentationState.PARTIAL
    assert partial.completeness is Completeness.PARTIAL
    assert {
        item.code for item in partial.blocking_reasons
    } == {StrategyLibraryBlockingCode.INVENTORY_PARTIAL}
    assert StrategyLibraryBlockingCode.INVENTORY_READ_FAILED not in {
        item.code for item in partial.blocking_reasons
    }
    assert {item.availability for item in partial.entries} == {
        StrategyAvailability.FORMAL_CAMPAIGN_READY,
        StrategyAvailability.UNAVAILABLE,
        StrategyAvailability.OUTDATED,
        StrategyAvailability.INCOMPATIBLE,
        StrategyAvailability.MISSING_DEPENDENCY,
    }
    assert sum(item.formal_campaign_eligible for item in partial.entries) == 1
    feature.close()


@pytest.mark.parametrize("feature_factory", _SCRIPTED_FACTORIES)
def test_partial_inventory_remains_partial_across_typed_filter_contexts(
    feature_factory: Callable[
        [tuple[StrategyLibraryApplicationInventoryResult, ...]],
        StrategyLibraryFeature,
    ],
) -> None:
    result = _authoritative_result()
    assert result.inventory is not None
    unavailable = replace(
        result.inventory.entries[0],
        formal_campaign_eligible=False,
        availability=StrategyAvailability.UNAVAILABLE,
    )
    partial_result = replace(
        result,
        availability=StrategyLibraryApplicationAvailability.PARTIAL,
        inventory=replace(
            result.inventory,
            entries=(unavailable, result.inventory.entries[1]),
        ),
    )
    feature = feature_factory((partial_result,))
    base_context = StrategyLibraryContext()

    feature.snapshot(base_context)
    partial = feature.snapshot(base_context)
    filtered_context = StrategyLibraryContext(search_text="QuentX 5.2.3")
    filtered = feature.snapshot(filtered_context)

    assert partial.presentation is StrategyLibraryPresentationState.PARTIAL
    assert filtered.presentation is StrategyLibraryPresentationState.PARTIAL
    assert filtered.completeness is Completeness.PARTIAL
    assert len(filtered.entries) == 1
    feature.close()


def test_app_context_composes_strategy_library_as_the_fourth_feature(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "1")

    context = build_app_context(
        settings_path=str(tmp_path / "settings.json"),
        run_monitoring_mode="fake",
    )

    assert isinstance(context.strategy_library_feature, StrategyLibraryFeature)
    assert context.strategy_library_feature.interface_version.render() == "1.0"
    assert context.strategy_library_context == StrategyLibraryContext()
    context.strategy_library_feature.close()
    context.diagnostic_tasks_feature.close()
    context.run_monitoring_feature.close()
    context.evidence_and_findings_feature.close()
