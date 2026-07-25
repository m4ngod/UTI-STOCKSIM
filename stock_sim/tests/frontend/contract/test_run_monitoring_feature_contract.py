from dataclasses import FrozenInstanceError, fields, is_dataclass
from datetime import datetime, timedelta, timezone

import pytest

from app.app_context import build_app_context
from app.features import (
    ACTIVE_FEATURE_INTERFACES,
    Completeness,
    DeterministicFakeRunMonitoringAdapter,
    FeatureModuleName,
    FormalDiagnosticCampaignId,
    Freshness,
    RUN_MONITORING_INTERFACE_VERSION,
    RunMonitoringContext,
    RunMonitoringFeature,
    RunMonitoringPresentationState,
    RunMonitoringSelection,
    RunMonitoringViewState,
    SourceKind,
    StrategyRunId,
    ViewPhase,
)


def test_wave_zero_reserves_six_feature_names_and_activates_only_run_monitoring():
    assert tuple(member.value for member in FeatureModuleName) == (
        "StrategyLibraryFeature",
        "ScenarioLabFeature",
        "DiagnosticTasksFeature",
        "RunMonitoringFeature",
        "EvidenceAndFindingsFeature",
        "SystemHealthFeature",
    )
    assert tuple(descriptor.name for descriptor in ACTIVE_FEATURE_INTERFACES) == (
        FeatureModuleName.RUN_MONITORING,
    )
    assert ACTIVE_FEATURE_INTERFACES[0].version == RUN_MONITORING_INTERFACE_VERSION
    assert RUN_MONITORING_INTERFACE_VERSION.render() == "1.0"


def test_fake_snapshot_starts_as_typed_loading_state():
    adapter = DeterministicFakeRunMonitoringAdapter()
    context = RunMonitoringContext.no_selection()

    state = adapter.snapshot(context)

    assert isinstance(state, RunMonitoringViewState)
    assert state.interface_version == RUN_MONITORING_INTERFACE_VERSION
    assert state.revision == 1
    assert state.observed_at == datetime(2030, 1, 1, tzinfo=timezone.utc)
    assert state.freshness is Freshness.AWAITING_FIRST_STATE
    assert state.age == timedelta(0)
    assert state.freshness_threshold == timedelta(seconds=5)
    assert state.source.kind is SourceKind.DETERMINISTIC_FAKE
    assert state.source.identity == "frontend-v2-run-monitoring-fake"
    assert state.context == context
    assert state.phase is ViewPhase.LOADING
    assert state.presentation is RunMonitoringPresentationState.LOADING
    assert state.last_reliable_data is None
    assert state.error is None
    assert state.completeness is Completeness.UNKNOWN

    with pytest.raises(FrozenInstanceError):
        state.revision = 2  # type: ignore[misc]


def test_campaign_and_run_identities_travel_as_one_typed_selection():
    campaign_id = FormalDiagnosticCampaignId("FDC-001")
    run_id = StrategyRunId("RUN-001")
    selection = RunMonitoringSelection(
        campaign_id=campaign_id,
        run_id=run_id,
    )

    context = RunMonitoringContext.for_run(selection)

    assert context.selection is selection
    assert context.selection.campaign_id is campaign_id
    assert context.selection.run_id is run_id
    with pytest.raises(TypeError, match="FormalDiagnosticCampaignId"):
        RunMonitoringSelection(
            campaign_id=run_id,  # type: ignore[arg-type]
            run_id=campaign_id,  # type: ignore[arg-type]
        )


def test_fake_subscription_advances_loading_to_no_selection_empty_without_sleep():
    timestamps = iter(
        (
            datetime(2030, 1, 1, tzinfo=timezone.utc),
            datetime(2030, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
        )
    )
    adapter = DeterministicFakeRunMonitoringAdapter(clock=timestamps.__next__)
    context = RunMonitoringContext.no_selection()
    observed: list[RunMonitoringViewState] = []

    subscription = adapter.subscribe(context, observed.append)
    empty = adapter.advance_to_empty(context)

    assert isinstance(adapter, RunMonitoringFeature)
    assert [state.presentation for state in observed] == [
        RunMonitoringPresentationState.LOADING,
        RunMonitoringPresentationState.EMPTY,
    ]
    assert empty is observed[-1]
    assert adapter.snapshot(context) is empty
    assert empty.revision == 2
    assert empty.observed_at == datetime(
        2030, 1, 1, 0, 0, 1, tzinfo=timezone.utc
    )
    assert empty.freshness is Freshness.FRESH
    assert empty.phase is ViewPhase.READY
    assert empty.completeness is Completeness.EMPTY
    assert empty.last_reliable_data is None
    assert empty.error is None

    subscription.dispose()
    adapter.close()


def test_subscription_disposal_and_adapter_close_are_repeatable_and_final():
    adapter = DeterministicFakeRunMonitoringAdapter()
    no_selection = RunMonitoringContext.no_selection()
    observed: list[RunMonitoringViewState] = []

    subscription = adapter.subscribe(no_selection, observed.append)
    subscription.dispose()
    subscription.dispose()
    adapter.advance_to_empty(no_selection)

    assert subscription.disposed is True
    assert [state.presentation for state in observed] == [
        RunMonitoringPresentationState.LOADING
    ]

    active_subscription = adapter.subscribe(
        RunMonitoringContext.for_run(
            RunMonitoringSelection(
                campaign_id=FormalDiagnosticCampaignId("FDC-001"),
                run_id=StrategyRunId("RUN-001"),
            )
        ),
        lambda _state: None,
    )
    adapter.close()
    adapter.close()

    assert active_subscription.disposed is True
    with pytest.raises(RuntimeError, match="closed"):
        adapter.snapshot(no_selection)


def test_app_context_composes_the_run_monitoring_feature_interface(tmp_path):
    context = build_app_context(settings_path=str(tmp_path / "settings.json"))

    feature = context.run_monitoring_feature

    assert isinstance(feature, RunMonitoringFeature)
    assert (
        feature.snapshot(RunMonitoringContext.no_selection()).presentation
        is RunMonitoringPresentationState.LOADING
    )
    feature.close()


def test_external_seam_exposes_only_typed_approved_operations():
    public_interface = {
        name
        for name in RunMonitoringFeature.__dict__
        if not name.startswith("_")
    }
    assert public_interface == {
        "interface_version",
        "snapshot",
        "subscribe",
        "close",
    }

    state = DeterministicFakeRunMonitoringAdapter().snapshot(
        RunMonitoringContext.no_selection()
    )
    values = list(_walk_typed_values(state))

    assert not any(isinstance(value, (dict, list, set, bytearray)) for value in values)
    assert not any(
        type(value).__module__.startswith("PySide6")
        or type(value).__name__ == "RuntimeGateway"
        for value in values
    )


def _walk_typed_values(value):
    yield value
    if is_dataclass(value) and not isinstance(value, type):
        for field in fields(value):
            yield from _walk_typed_values(getattr(value, field.name))
    elif isinstance(value, tuple):
        for item in value:
            yield from _walk_typed_values(item)
