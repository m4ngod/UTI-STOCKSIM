from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone
from threading import Event, Thread

import pytest

from app.app_context import build_app_context
from app.event_bridge import EventBridge
from app.features.live_strategy_library import (
    DeterministicFakeStrategyLibraryAdapter,
    LiveStrategyLibraryAdapter,
)
from app.features.strategy_library import (
    CompareStrategies,
    SelectFormalStrategySet,
    StrategyComparisonDisposition,
    StrategyLibraryAvailabilityFilter,
    StrategyLibraryBlockingCode,
    StrategyLibraryContext,
    StrategyLibraryFeature,
    StrategyLibraryFocusTarget,
    StrategyLibraryPresentationState,
    StrategySelectionDisposition,
    StrategySelectionBookmark,
    StrategySelectionStatus,
)
from app.features.diagnostic_tasks_application import GuardrailProfileId
from app.features.strategy_library_application import (
    STRATEGY_LIBRARY_APPLICATION_INTERFACE_VERSION,
    FormalStrategySelectionReference,
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
    StrategyLibraryEntry,
    StrategyLibraryInventory,
    ValidateFormalStrategySet,
)
from app.features.run_monitoring import (
    Completeness,
    Freshness,
    SourceGenerationId,
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
        inventory = self._last.inventory
        source_token = self._last.source_token
        if inventory is None or source_token is None:
            state = FormalStrategySetValidationState.UNAVAILABLE
            selections = ()
        elif command.expected_source_revision != source_token:
            state = FormalStrategySetValidationState.SOURCE_CONFLICT
            selections = ()
        else:
            expected = tuple(
                _formal_reference(item)
                for item in inventory.entries
                if item.required_for_v1_formal_campaign
            )
            ready = all(
                item.formal_campaign_eligible
                and item.availability
                is StrategyAvailability.FORMAL_CAMPAIGN_READY
                for item in inventory.entries
                if item.required_for_v1_formal_campaign
            )
            if set(command.selections) != set(expected):
                state = FormalStrategySetValidationState.INVALID
                selections = ()
            elif not ready:
                state = FormalStrategySetValidationState.UNAVAILABLE
                selections = ()
            else:
                state = FormalStrategySetValidationState.VALID
                selections = expected
        return FormalStrategySetValidation(
            state=state,
            selections=selections,
            source_revision=command.expected_source_revision,
            reasons=(),
        )


def _authoritative_result() -> StrategyLibraryApplicationInventoryResult:
    application = create_diagnostics_application()
    application.start()
    return LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter(
        application
    ).read_inventory()


def _formal_reference(
    entry: StrategyLibraryEntry,
) -> FormalStrategySelectionReference:
    profile = entry.guardrail_profile
    assert profile is not None
    return FormalStrategySelectionReference(
        strategy_id=entry.strategy_id,
        strategy_version=entry.strategy_version,
        manifest_content_hash=entry.compatibility.content_hash,
        guardrail_profile_id=profile.profile_id,
        guardrail_profile_version=profile.profile_version,
        dependency_identities=entry.dependencies,
    )


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


def _live_inventory_feature(
    inventory: StrategyLibraryInventory,
) -> StrategyLibraryFeature:
    result = replace(
        _authoritative_result(),
        inventory=inventory,
        availability=StrategyLibraryApplicationAvailability.READY,
    )
    return _live_scripted_feature((result,))


def _fake_inventory_feature(
    inventory: StrategyLibraryInventory,
) -> StrategyLibraryFeature:
    return DeterministicFakeStrategyLibraryAdapter(inventory=inventory)


_INVENTORY_FACTORIES = (_live_inventory_feature, _fake_inventory_feature)


def _ready_state(feature: StrategyLibraryFeature):
    context = StrategyLibraryContext()
    feature.snapshot(context)
    return context, feature.snapshot(context)


@pytest.mark.parametrize("feature_factory", [_live_feature, _fake_feature])
def test_live_and_fake_compare_and_select_exact_formal_strategy_set(
    feature_factory: Callable[[], StrategyLibraryFeature],
) -> None:
    feature = feature_factory()
    context, ready = _ready_state(feature)
    assert ready.source_revision is not None
    strategy_ids = tuple(entry.strategy_id for entry in ready.entries)
    guardrail_ids = tuple(
        entry.guardrail_profile.profile_id for entry in ready.entries
    )

    comparison = feature.compare_strategies(
        CompareStrategies(
            strategy_ids=strategy_ids,
            expected_source_revision=ready.source_revision,
            expected_source_generation=ready.source.generation,
        )
    )
    selected = feature.select_formal_strategy_set(
        SelectFormalStrategySet(
            strategy_ids=strategy_ids,
            guardrail_profile_ids=guardrail_ids,
            expected_source_revision=ready.source_revision,
            expected_source_generation=ready.source.generation,
            originating_view_revision=ready.revision,
        )
    )
    projected = feature.snapshot(context)

    assert comparison.disposition is StrategyComparisonDisposition.AVAILABLE
    assert comparison.entries == ready.entries
    assert selected.disposition is StrategySelectionDisposition.SELECTED
    assert selected.selection is not None
    assert len(selected.selection.selections) == 2
    assert len(selected.selection.context_identity) == 64
    assert projected.selection == selected.selection
    assert projected.selection_status is StrategySelectionStatus.CURRENT
    assert projected.capabilities.can_compare
    assert projected.capabilities.can_select_formal_strategy_set
    feature.close()


@pytest.mark.parametrize("feature_factory", [_live_feature, _fake_feature])
@pytest.mark.parametrize("invalid_kind", ("duplicate", "unknown", "guardrail"))
def test_invalid_selection_does_not_mutate_current_selection_or_revision(
    feature_factory: Callable[[], StrategyLibraryFeature],
    invalid_kind: str,
) -> None:
    feature = feature_factory()
    context, ready = _ready_state(feature)
    assert ready.source_revision is not None
    guardrails = tuple(
        entry.guardrail_profile.profile_id for entry in ready.entries
    )
    selected = feature.select_formal_strategy_set(
        SelectFormalStrategySet(
            strategy_ids=tuple(entry.strategy_id for entry in ready.entries),
            guardrail_profile_ids=guardrails,
            expected_source_revision=ready.source_revision,
            expected_source_generation=ready.source.generation,
            originating_view_revision=ready.revision,
        )
    )
    current = feature.snapshot(context)
    assert selected.selection is not None

    if invalid_kind == "duplicate":
        invalid_strategy_ids = (ready.entries[0].strategy_id,) * 2
        invalid_guardrail_ids = (guardrails[0],) * 2
    elif invalid_kind == "unknown":
        invalid_strategy_ids = (
            StrategyUnderTestId("unknown-strategy"),
            ready.entries[1].strategy_id,
        )
        invalid_guardrail_ids = guardrails
    else:
        invalid_strategy_ids = tuple(
            entry.strategy_id for entry in ready.entries
        )
        invalid_guardrail_ids = (
            GuardrailProfileId("unknown-guardrail"),
            guardrails[1],
        )
    rejected = feature.select_formal_strategy_set(
        SelectFormalStrategySet(
            strategy_ids=invalid_strategy_ids,
            guardrail_profile_ids=invalid_guardrail_ids,
            expected_source_revision=ready.source_revision,
            expected_source_generation=ready.source.generation,
            originating_view_revision=current.revision,
        )
    )
    unchanged = feature.snapshot(context)

    assert rejected.disposition is StrategySelectionDisposition.INVALID_SELECTION
    assert unchanged.selection == selected.selection
    assert unchanged.revision == current.revision
    feature.close()


@pytest.mark.parametrize("feature_factory", _INVENTORY_FACTORIES)
def test_unavailable_formal_set_rejection_does_not_mutate_view(
    feature_factory: Callable[[StrategyLibraryInventory], StrategyLibraryFeature],
) -> None:
    result = _authoritative_result()
    assert result.inventory is not None
    first = result.inventory.entries[0]
    unavailable_inventory = replace(
        result.inventory,
        entries=(
            replace(
                first,
                formal_campaign_eligible=False,
                availability=StrategyAvailability.UNAVAILABLE,
            ),
            *result.inventory.entries[1:],
        ),
    )
    feature = feature_factory(unavailable_inventory)
    context, partial = _ready_state(feature)
    assert partial.source_revision is not None
    assert not partial.capabilities.can_select_formal_strategy_set

    rejected = feature.select_formal_strategy_set(
        SelectFormalStrategySet(
            strategy_ids=tuple(
                item.strategy_id
                for item in partial.last_reliable_inventory.entries
            ),
            guardrail_profile_ids=tuple(
                item.guardrail_profile.profile_id
                for item in partial.last_reliable_inventory.entries
            ),
            expected_source_revision=partial.source_revision,
            expected_source_generation=partial.source.generation,
            originating_view_revision=partial.revision,
        )
    )
    unchanged = feature.snapshot(context)

    assert rejected.disposition is StrategySelectionDisposition.UNAVAILABLE
    assert unchanged is partial
    assert unchanged.selection is None
    feature.close()


@pytest.mark.parametrize("feature_factory", [_live_feature, _fake_feature])
def test_selection_rejects_old_generation_and_view_revision(
    feature_factory: Callable[[], StrategyLibraryFeature],
) -> None:
    feature = feature_factory()
    _, ready = _ready_state(feature)
    assert ready.source_revision is not None
    command = SelectFormalStrategySet(
        strategy_ids=tuple(entry.strategy_id for entry in ready.entries),
        guardrail_profile_ids=tuple(
            entry.guardrail_profile.profile_id for entry in ready.entries
        ),
        expected_source_revision=ready.source_revision,
        expected_source_generation=SourceGenerationId(
            ready.source.generation.value + 1
        ),
        originating_view_revision=ready.revision - 1,
    )

    rejected = feature.select_formal_strategy_set(command)

    assert rejected.disposition is StrategySelectionDisposition.SOURCE_CONFLICT
    assert rejected.selection is None
    feature.close()


def test_selection_validation_disconnect_cannot_publish_current() -> None:
    bridge = EventBridge(subscribe_backend=False)
    result = _authoritative_result()

    class DisconnectingApplication:
        @property
        def interface_version(self) -> StrategyLibraryApplicationVersion:
            return STRATEGY_LIBRARY_APPLICATION_INTERFACE_VERSION

        def read_inventory(self) -> StrategyLibraryApplicationInventoryResult:
            return result

        def validate_formal_strategy_set(
            self,
            command: ValidateFormalStrategySet,
        ) -> FormalStrategySetValidation:
            bridge.mark_disconnected()
            return FormalStrategySetValidation(
                state=FormalStrategySetValidationState.VALID,
                selections=command.selections,
                source_revision=command.expected_source_revision,
                reasons=(),
            )

    feature = LiveStrategyLibraryAdapter(
        application=DisconnectingApplication(),
        event_bridge=bridge,
    )
    context, ready = _ready_state(feature)
    assert ready.source_revision is not None

    rejected = feature.select_formal_strategy_set(
        SelectFormalStrategySet(
            strategy_ids=tuple(item.strategy_id for item in ready.entries),
            guardrail_profile_ids=tuple(
                item.guardrail_profile.profile_id for item in ready.entries
            ),
            expected_source_revision=ready.source_revision,
            expected_source_generation=ready.source.generation,
            originating_view_revision=ready.revision,
        )
    )
    disconnected = feature.snapshot(context)

    assert rejected.disposition is StrategySelectionDisposition.SOURCE_CONFLICT
    assert rejected.selection is None
    assert disconnected.selection_status is not StrategySelectionStatus.CURRENT
    assert disconnected.presentation is (
        StrategyLibraryPresentationState.DISCONNECTED
    )
    feature.close()
    bridge.stop()


@pytest.mark.parametrize("feature_factory", [_live_feature, _fake_feature])
def test_repeating_the_same_selection_is_deterministic_without_revision_noise(
    feature_factory: Callable[[], StrategyLibraryFeature],
) -> None:
    feature = feature_factory()
    context, ready = _ready_state(feature)
    assert ready.source_revision is not None
    command = SelectFormalStrategySet(
        strategy_ids=tuple(entry.strategy_id for entry in ready.entries),
        guardrail_profile_ids=tuple(
            entry.guardrail_profile.profile_id for entry in ready.entries
        ),
        expected_source_revision=ready.source_revision,
        expected_source_generation=ready.source.generation,
        originating_view_revision=ready.revision,
    )

    first = feature.select_formal_strategy_set(command)
    projected = feature.snapshot(context)
    second = feature.select_formal_strategy_set(command)
    unchanged = feature.snapshot(context)

    assert first.selection is not None
    assert second.selection == first.selection
    assert unchanged is projected
    assert unchanged.revision == projected.revision
    feature.close()


@pytest.mark.parametrize("feature_factory", [_live_feature, _fake_feature])
def test_bookmark_reopen_rereads_stable_identities_under_new_generation(
    feature_factory: Callable[[], StrategyLibraryFeature],
) -> None:
    original = feature_factory()
    _, ready = _ready_state(original)
    assert ready.source_revision is not None
    result = original.select_formal_strategy_set(
        SelectFormalStrategySet(
            strategy_ids=tuple(entry.strategy_id for entry in ready.entries),
            guardrail_profile_ids=tuple(
                entry.guardrail_profile.profile_id for entry in ready.entries
            ),
            expected_source_revision=ready.source_revision,
            expected_source_generation=ready.source.generation,
            originating_view_revision=ready.revision,
        )
    )
    assert result.selection is not None
    bookmark = StrategySelectionBookmark(
        selections=result.selection.selections,
        source_generation=result.selection.source_generation,
        focus_target=StrategyLibraryFocusTarget.STRATEGY_DETAILS,
        focus_strategy_id=result.selection.selections[0].strategy_id,
    )
    original.close()

    reopened = feature_factory()
    context = StrategyLibraryContext(
        focus_strategy_id=bookmark.focus_strategy_id,
        selection_bookmark=bookmark,
    )
    loading = reopened.snapshot(context)
    restored = reopened.snapshot(context)

    assert loading.presentation is StrategyLibraryPresentationState.LOADING
    assert restored.selection is not None
    assert restored.selection_status is StrategySelectionStatus.CURRENT
    assert restored.source.generation.value > ready.source.generation.value
    assert restored.selection.source_generation == restored.source.generation
    assert restored.focus_restoration_id == bookmark.focus_strategy_id
    assert tuple(
        item.strategy_id for item in restored.selection.selections
    ) == bookmark.strategy_ids
    reopened.close()


def test_bookmark_validation_runs_outside_adapter_lock() -> None:
    result = _authoritative_result()
    assert result.inventory is not None
    seed = DeterministicFakeStrategyLibraryAdapter(inventory=result.inventory)
    _, ready = _ready_state(seed)
    assert ready.source_revision is not None
    selected = seed.select_formal_strategy_set(
        SelectFormalStrategySet(
            strategy_ids=tuple(item.strategy_id for item in ready.entries),
            guardrail_profile_ids=tuple(
                item.guardrail_profile.profile_id for item in ready.entries
            ),
            expected_source_revision=ready.source_revision,
            expected_source_generation=ready.source.generation,
            originating_view_revision=ready.revision,
        )
    )
    assert selected.selection is not None
    bookmark = StrategySelectionBookmark(
        selections=selected.selection.selections,
    )
    seed.close()
    bridge = EventBridge(subscribe_backend=False)
    callback_completed = Event()

    class DisconnectingApplication:
        @property
        def interface_version(self) -> StrategyLibraryApplicationVersion:
            return STRATEGY_LIBRARY_APPLICATION_INTERFACE_VERSION

        def read_inventory(self) -> StrategyLibraryApplicationInventoryResult:
            return result

        def validate_formal_strategy_set(
            self,
            command: ValidateFormalStrategySet,
        ) -> FormalStrategySetValidation:
            worker = Thread(
                target=lambda: (
                    bridge.mark_disconnected(),
                    callback_completed.set(),
                )
            )
            worker.start()
            assert callback_completed.wait(timeout=2)
            worker.join(timeout=2)
            return FormalStrategySetValidation(
                state=FormalStrategySetValidationState.VALID,
                selections=command.selections,
                source_revision=command.expected_source_revision,
                reasons=(),
            )

    feature = LiveStrategyLibraryAdapter(
        application=DisconnectingApplication(),
        event_bridge=bridge,
    )
    context = StrategyLibraryContext(selection_bookmark=bookmark)
    feature.snapshot(context)
    state = feature.snapshot(context)

    assert callback_completed.is_set()
    assert state.selection_status is not StrategySelectionStatus.CURRENT
    assert state.presentation is StrategyLibraryPresentationState.DISCONNECTED
    feature.close()
    bridge.stop()


@pytest.mark.parametrize(
    "changed_fact",
    ("version", "manifest", "guardrail", "dependency"),
)
@pytest.mark.parametrize("feature_factory", _INVENTORY_FACTORIES)
def test_bookmark_reopen_never_floats_exact_authoritative_identity(
    changed_fact: str,
    feature_factory: Callable[[StrategyLibraryInventory], StrategyLibraryFeature],
) -> None:
    base_result = _authoritative_result()
    assert base_result.inventory is not None
    original = feature_factory(base_result.inventory)
    _, ready = _ready_state(original)
    assert ready.source_revision is not None
    assert ready.last_reliable_inventory is not None
    selected = original.select_formal_strategy_set(
        SelectFormalStrategySet(
            strategy_ids=tuple(item.strategy_id for item in ready.entries),
            guardrail_profile_ids=tuple(
                item.guardrail_profile.profile_id for item in ready.entries
            ),
            expected_source_revision=ready.source_revision,
            expected_source_generation=ready.source.generation,
            originating_view_revision=ready.revision,
        )
    )
    assert selected.selection is not None
    bookmark = StrategySelectionBookmark(
        selections=selected.selection.selections,
    )
    inventory = ready.last_reliable_inventory
    entry = inventory.entries[0]
    profile = entry.guardrail_profile
    assert profile is not None
    if changed_fact == "version":
        changed = replace(entry, strategy_version=f"{entry.strategy_version}.next")
    elif changed_fact == "manifest":
        changed = replace(
            entry,
            compatibility=replace(entry.compatibility, content_hash="a" * 64),
        )
    elif changed_fact == "guardrail":
        changed = replace(
            entry,
            guardrail_profile=replace(
                profile,
                profile_version=f"{profile.profile_version}.next",
            ),
        )
    else:
        changed = replace(
            entry,
            dependencies=(
                replace(entry.dependencies[0], content_hash="b" * 64),
                *entry.dependencies[1:],
            ),
        )
    original.close()

    reopened = feature_factory(
        replace(
            inventory,
            entries=(changed, *inventory.entries[1:]),
        )
    )
    context = StrategyLibraryContext(selection_bookmark=bookmark)
    reopened.snapshot(context)
    conflict = reopened.snapshot(context)

    assert conflict.selection is None
    assert conflict.selection_status is StrategySelectionStatus.CONFLICT
    assert "explicit reselection" in conflict.selection_message.casefold()
    reopened.close()


@pytest.mark.parametrize("feature_factory", [_live_feature, _fake_feature])
def test_missing_bookmark_identity_is_typed_unavailable_with_guidance(
    feature_factory: Callable[[], StrategyLibraryFeature],
) -> None:
    feature = feature_factory()
    context = StrategyLibraryContext(
        selection_bookmark=StrategySelectionBookmark(
            selections=(
                FormalStrategySelectionReference(
                    strategy_id=StrategyUnderTestId("retired-strategy"),
                    strategy_version="retired.v1",
                    manifest_content_hash="f" * 64,
                    guardrail_profile_id=GuardrailProfileId(
                        "retired-guardrail"
                    ),
                    guardrail_profile_version="retired.v1",
                    dependency_identities=(),
                ),
            ),
        )
    )

    feature.snapshot(context)
    unavailable = feature.snapshot(context)

    assert unavailable.selection is None
    assert unavailable.selection_status is StrategySelectionStatus.UNAVAILABLE
    assert "unavailable" in unavailable.selection_message.casefold()
    assert "reread" in unavailable.selection_message.casefold()
    feature.close()


@pytest.mark.parametrize(
    "changed_fact",
    ("version", "manifest", "guardrail", "dependency"),
)
def test_authoritative_selection_dependency_change_marks_old_context_stale(
    changed_fact: str,
) -> None:
    reliable = _authoritative_result()
    assert reliable.inventory is not None
    first = reliable.inventory.entries[0]
    profile = first.guardrail_profile
    assert profile is not None
    if changed_fact == "version":
        changed = replace(first, strategy_version=f"{first.strategy_version}.next")
    elif changed_fact == "manifest":
        changed = replace(
            first,
            compatibility=replace(
                first.compatibility,
                content_hash="a" * 64,
            ),
        )
    elif changed_fact == "guardrail":
        changed = replace(
            first,
            guardrail_profile=replace(
                profile,
                profile_version=f"{profile.profile_version}.next",
            ),
        )
    else:
        changed = replace(
            first,
            dependencies=(
                replace(first.dependencies[0], content_hash="b" * 64),
                *first.dependencies[1:],
            ),
        )
    changed_inventory = replace(
        reliable.inventory,
        entries=(changed, *reliable.inventory.entries[1:]),
    )
    changed_result = replace(
        reliable,
        inventory=changed_inventory,
        source_token=SourceRevisionToken("c" * 64),
    )
    feature = DeterministicFakeStrategyLibraryAdapter(
        inventory=reliable.inventory,
        scripted_results=(reliable, changed_result),
    )
    context, ready = _ready_state(feature)
    assert ready.source_revision is not None
    selected = feature.select_formal_strategy_set(
        SelectFormalStrategySet(
            strategy_ids=tuple(entry.strategy_id for entry in ready.entries),
            guardrail_profile_ids=tuple(
                entry.guardrail_profile.profile_id for entry in ready.entries
            ),
            expected_source_revision=ready.source_revision,
            expected_source_generation=ready.source.generation,
            originating_view_revision=ready.revision,
        )
    )
    assert selected.selection is not None

    stale = feature.snapshot(context)

    assert stale.selection == selected.selection
    assert stale.selection_status is StrategySelectionStatus.STALE
    assert stale.source_revision == changed_result.source_token
    assert any(
        reason.code is StrategyLibraryBlockingCode.FORMAL_SELECTION_STALE
        for reason in stale.blocking_reasons
    )
    feature.close()


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


@pytest.mark.parametrize(
    "harness_factory",
    [_live_connection_harness, _fake_connection_harness],
)
def test_selected_formal_set_is_explicitly_stale_across_reconnect(
    harness_factory: Callable[[], _ConnectionHarness],
) -> None:
    harness = harness_factory()
    feature = harness.feature
    context, ready = _ready_state(feature)
    assert ready.source_revision is not None
    selected = feature.select_formal_strategy_set(
        SelectFormalStrategySet(
            strategy_ids=tuple(entry.strategy_id for entry in ready.entries),
            guardrail_profile_ids=tuple(
                entry.guardrail_profile.profile_id for entry in ready.entries
            ),
            expected_source_revision=ready.source_revision,
            expected_source_generation=ready.source.generation,
            originating_view_revision=ready.revision,
        )
    )
    assert selected.selection is not None

    harness.disconnect()
    disconnected = feature.snapshot(context)
    harness.reconnect()
    recovered = feature.snapshot(context)

    assert disconnected.selection == selected.selection
    assert disconnected.selection_status is StrategySelectionStatus.STALE
    assert recovered.selection == selected.selection
    assert recovered.selection_status is StrategySelectionStatus.STALE
    assert recovered.capabilities.can_select_formal_strategy_set
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
    assert partial.capabilities.can_compare
    assert not partial.capabilities.can_select_formal_strategy_set
    assert not filtered.capabilities.can_select_formal_strategy_set
    feature.close()


@pytest.mark.parametrize("feature_factory", _SCRIPTED_FACTORIES)
def test_empty_inventory_disables_compare_and_formal_selection(
    feature_factory: Callable[
        [tuple[StrategyLibraryApplicationInventoryResult, ...]],
        StrategyLibraryFeature,
    ],
) -> None:
    result = _authoritative_result()
    assert result.inventory is not None
    empty = replace(
        result,
        availability=StrategyLibraryApplicationAvailability.EMPTY,
        inventory=replace(result.inventory, entries=()),
        source_token=SourceRevisionToken("e" * 64),
    )
    feature = feature_factory((empty,))
    context = StrategyLibraryContext()

    feature.snapshot(context)
    state = feature.snapshot(context)

    assert state.presentation is StrategyLibraryPresentationState.EMPTY
    assert not state.capabilities.can_compare
    assert not state.capabilities.can_select_formal_strategy_set
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


def test_app_context_persists_and_rereads_exact_formal_set_on_product_reopen(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "1")
    settings_path = str(tmp_path / "settings.json")
    first = build_app_context(
        settings_path=settings_path,
        run_monitoring_mode="fake",
    )
    feature = first.strategy_library_feature
    feature.snapshot(first.strategy_library_context)
    ready = feature.snapshot(first.strategy_library_context)
    assert ready.source_revision is not None
    selected = feature.select_formal_strategy_set(
        SelectFormalStrategySet(
            strategy_ids=tuple(item.strategy_id for item in ready.entries),
            guardrail_profile_ids=tuple(
                item.guardrail_profile.profile_id for item in ready.entries
            ),
            expected_source_revision=ready.source_revision,
            expected_source_generation=ready.source.generation,
            originating_view_revision=ready.revision,
        )
    )
    assert selected.selection is not None
    persisted = StrategySelectionBookmark(
        selections=selected.selection.selections,
        source_generation=selected.selection.source_generation,
        focus_strategy_id=selected.selection.selections[0].strategy_id,
    )
    first.persist_strategy_library_bookmark(persisted)
    feature.close()
    first.diagnostic_tasks_feature.close()
    first.run_monitoring_feature.close()
    first.evidence_and_findings_feature.close()

    reopened = build_app_context(
        settings_path=settings_path,
        run_monitoring_mode="fake",
    )
    assert reopened.strategy_library_context.selection_bookmark == persisted
    assert reopened.strategy_library_context.focus_strategy_id == (
        persisted.focus_strategy_id
    )
    reopened.strategy_library_feature.snapshot(
        reopened.strategy_library_context
    )
    restored = reopened.strategy_library_feature.snapshot(
        reopened.strategy_library_context
    )

    assert restored.selection is not None
    assert restored.selection.selections == persisted.selections
    assert restored.selection_status is StrategySelectionStatus.CURRENT
    assert restored.source.generation != persisted.source_generation
    assert restored.focus_restoration_id == persisted.focus_strategy_id
    reopened.strategy_library_feature.close()
    reopened.diagnostic_tasks_feature.close()
    reopened.run_monitoring_feature.close()
    reopened.evidence_and_findings_feature.close()


@pytest.mark.parametrize("persisted_value", ("null", "{}", "42"))
def test_app_context_ignores_malformed_persisted_strategy_bookmark(
    tmp_path,
    monkeypatch,
    persisted_value: str,
) -> None:
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "1")
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        '{"strategy_library_bookmark_json": ' + persisted_value + "}",
        encoding="utf-8",
    )

    context = build_app_context(
        settings_path=str(settings_path),
        run_monitoring_mode="fake",
    )

    assert context.strategy_library_context.selection_bookmark is None
    context.strategy_library_feature.close()
    context.diagnostic_tasks_feature.close()
    context.run_monitoring_feature.close()
    context.evidence_and_findings_feature.close()
