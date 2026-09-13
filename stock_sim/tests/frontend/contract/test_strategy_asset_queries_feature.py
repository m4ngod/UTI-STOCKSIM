from __future__ import annotations

from concurrent.futures import Executor, Future
from dataclasses import replace

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QFontDatabase

from app.app_context import build_app_context
from app.event_bridge import EventBridge
from app.features.versioning import FeatureInterfaceVersion, FeatureModuleName
from strategy_diagnostics import create_diagnostics_application
from app.features.strategy_asset_contract import ExactAssetQuery


class ManualExecutor(Executor):
    """Control the external scheduling boundary, not an application collaborator."""

    def __init__(self):
        self.jobs = []

    def submit(self, fn, /, *args, **kwargs):
        future = Future()
        self.jobs.append((future, fn, args, kwargs))
        return future

    def run_next(self):
        future, fn, args, kwargs = self.jobs.pop(0)
        if future.set_running_or_notify_cancel():
            try:
                future.set_result(fn(*args, **kwargs))
            except BaseException as error:
                future.set_exception(error)

    def fail_next(self):
        future, _, _, _ = self.jobs.pop(0)
        future.set_exception(OSError("private-source-path-must-not-leak"))


@pytest.fixture(params=("live", "fake"))
def composed(request, tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "1")
    app = QApplication.instance() or QApplication([])
    if not QFontDatabase.families():
        # The offscreen sandbox has no system font enumeration. Read an existing
        # Windows font into this test application only; no install/settings write.
        font_id = QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
        assert font_id >= 0, "QML visual evidence requires a real readable CJK font"
        app.setFont(QFont("Microsoft YaHei UI", 10))
    application = create_diagnostics_application()
    application.start()
    inventory = application.read_strategy_under_test_inventory()
    mode, dataset = request.param if isinstance(request.param, tuple) else (request.param, "normal")
    if dataset == "empty":
        assert mode == "fake"
        inventory = replace(inventory, entries=())
    executor = ManualExecutor()
    bridge = EventBridge(subscribe_backend=False)
    root = build_app_context(
        settings_path=str(tmp_path / "settings.json"),
        run_monitoring_mode=mode,
        strategy_diagnostics_application=application if mode == "live" else None,
        strategy_asset_fixture=inventory if mode == "fake" else None,
        strategy_asset_query_executor=executor,
        event_bridge=bridge,
        system_health_sampling_interval=None,
    )
    yield root, executor, bridge, inventory
    root.close()
    bridge.stop()
    app.processEvents()


def test_same_exact_query_dataset_crosses_composed_live_and_fake(composed):
    root, executor, bridge, inventory = composed
    feature = root.strategy_library_queries
    states = []
    subscription = feature.subscribe(states.append)
    pending = feature.refresh()
    assert pending.phase.value == "loading"
    executor.run_next()
    ready = feature.snapshot()
    assert ready.source_revision == inventory.content_hash
    assert len(ready.assets) == len(inventory.entries)
    target = ready.assets[0].reference
    request = ExactAssetQuery.freeze(
        operation_id="same-query-dataset", target=target,
        expected_revision=ready.source_revision,
    )
    pending = feature.query_exact_asset(request, ready.source_generation)
    assert pending.phase.value == "loading"
    assert pending.request == request and pending.result is None
    executor.run_next()
    result = feature.snapshot()
    assert result.phase.value == "ready"
    assert result.result.request == request
    assert result.result.disposition.value == "completed"
    assert result.result.asset.strategy_id.value == target.lineage_id
    assert result.result.asset.strategy_version == target.version_id
    assert [state.revision for state in states] == sorted(set(state.revision for state in states))
    assert states[-1] == result
    subscription.dispose()
    assert subscription.disposed
    if root.strategy_diagnostics_application is not None:
        from strategy_diagnostics.asset_queries import ExactAssetQuery as ApplicationQuery, ExactStrategyAsset
        entry = next(entry for entry in inventory.entries if entry.strategy_id == target.lineage_id)
        application_request = ApplicationQuery.freeze(operation_id=request.operation_id,
            target=ExactStrategyAsset.from_entry(entry), expected_revision=request.expected_revision)
        assert application_request.frozen_input_hash == request.frozen_input_hash
        application_result = root.strategy_diagnostics_application.query_exact_strategy_asset(application_request)
        assert application_result.asset == entry
        assert application_result.source_revision == result.result.source_revision


def test_connection_generation_discards_late_results_and_rejects_old_source(composed):
    root, executor, bridge, inventory = composed
    feature = root.strategy_library_queries
    feature.refresh()
    executor.run_next()
    ready = feature.snapshot()
    request = ExactAssetQuery.freeze(operation_id="before-reconnect", target=ready.assets[0].reference,
                                    expected_revision=ready.source_revision)
    feature.query_exact_asset(request, ready.source_generation)
    bridge.mark_disconnected()
    assert feature.snapshot().freshness.value == "disconnected"
    bridge.mark_reconnected()
    reconnected = feature.snapshot()
    assert reconnected.source_generation.value > ready.source_generation.value
    executor.run_next()
    assert feature.snapshot() == reconnected
    rejected = feature.query_exact_asset(request, ready.source_generation)
    assert rejected.result.disposition.value == "rejected"
    assert rejected.result.request == request
    assert rejected.result.asset is None
    assert rejected.result.reason.code.value == "stale_source_generation"
    assert not executor.jobs


def test_new_observation_clears_old_content_and_disposal_suppresses_queued_delivery(composed):
    root, executor, bridge, inventory = composed
    feature = root.strategy_library_queries
    feature.refresh()
    executor.run_next()
    ready = feature.snapshot()
    first = ExactAssetQuery.freeze(operation_id="observe-first", target=ready.assets[0].reference,
                                  expected_revision=ready.source_revision)
    second = ExactAssetQuery.freeze(operation_id="observe-second", target=ready.assets[1].reference,
                                   expected_revision=ready.source_revision)
    states = []
    subscription = feature.subscribe(states.append)
    feature.query_exact_asset(first, ready.source_generation)
    pending_second = feature.query_exact_asset(second, ready.source_generation)
    assert pending_second.request.target == second.target and pending_second.result is None
    executor.run_next()
    assert feature.snapshot() == pending_second
    count = len(states)
    subscription.dispose()
    executor.run_next()
    assert len(states) == count
    assert feature.snapshot().result.request == second
    assert feature.snapshot().result.asset.strategy_id.value == second.target.lineage_id
    replay = []
    replacement = feature.subscribe(replay.append)
    assert replay[-1].result.request == second
    replacement.dispose()


def test_worker_read_failure_is_typed_and_retains_stale_inventory(composed):
    root, executor, bridge, inventory = composed
    feature = root.strategy_library_queries
    feature.refresh()
    executor.run_next()
    ready = feature.snapshot()
    feature.refresh()
    executor.fail_next()
    failed = feature.snapshot()
    assert failed.phase.value == "failed"
    assert failed.freshness.value == "stale"
    assert failed.assets == ready.assets
    assert failed.error.code.value == "source_unavailable" and failed.error.retryable
    assert "private-source-path" not in failed.error.message
    feature.refresh()
    executor.run_next()
    assert feature.snapshot().phase.value == "ready"
    assert feature.snapshot().error is None


def test_query_extension_is_explicit_and_does_not_activate_future_feature(composed):
    root, executor, bridge, inventory = composed
    catalog = root.feature_capabilities()
    result = catalog.negotiate_extension(FeatureModuleName.STRATEGY_LIBRARY, "exact_assets",
                                         FeatureInterfaceVersion(1, 0), "query_exact_asset")
    assert result.available and result.reason is None
    missing = catalog.negotiate_extension(FeatureModuleName.STRATEGY_LIBRARY, "exact_assets",
                                          FeatureInterfaceVersion(1, 0), "save_combination")
    assert not missing.available and missing.reason.code.value == "operation_not_implemented"
    future = catalog.negotiate(FeatureModuleName.STRATEGY_LIBRARY,
                               FeatureInterfaceVersion(2, 0), "save_combination")
    assert not future.available
    assert root.strategy_library_feature.interface_version.render() == "1.0"


def test_query_extension_public_types_do_not_leak_backend_or_concurrency_objects():
    from app.features.strategy_asset_queries import StrategyAssetQueriesAdapter
    from app.features.strategy_asset_contract import StrategyAssetQueriesFeature
    from tests.frontend.contract.test_strategy_diagnostics_v1_frontend_v2_integration_gate import (
        _transitive_interface_graph, _public_type_graph_violations,
    )
    assert _public_type_graph_violations(_transitive_interface_graph(StrategyAssetQueriesFeature, StrategyAssetQueriesAdapter)) == ()


def test_same_target_retains_verified_content_during_loading_and_transient_failure(composed):
    root, executor, bridge, inventory = composed
    feature = root.strategy_library_queries
    feature.refresh()
    executor.run_next()
    ready = feature.snapshot()
    request = ExactAssetQuery.freeze(operation_id="keep-content", target=ready.assets[0].reference,
                                    expected_revision=ready.source_revision)
    feature.query_exact_asset(request, ready.source_generation)
    executor.run_next()
    first = feature.snapshot().result
    pending = feature.query_exact_asset(replace(request, operation_id="read-again"), ready.source_generation)
    assert pending.retained_content == first
    assert pending.content_freshness.value == "stale"
    assert pending.result is None
    executor.fail_next()
    failed = feature.snapshot()
    assert failed.retained_content == first
    assert failed.content_freshness.value == "stale"
    assert failed.result.reason.code.value == "source_unavailable"
    other = replace(request, operation_id="other-target", target=ready.assets[1].reference)
    pending_other = feature.query_exact_asset(other, ready.source_generation)
    assert pending_other.retained_content is None
    assert pending_other.result is None


def test_rejected_query_does_not_publish_unread_catalog_rows_as_fresh(composed):
    root, executor, bridge, inventory = composed
    feature = root.strategy_library_queries
    feature.refresh()
    executor.run_next()
    ready = feature.snapshot()
    request = ExactAssetQuery.freeze(operation_id="wrong-directory-revision", target=ready.assets[0].reference,
                                    expected_revision="0" * 64)
    feature.query_exact_asset(request, ready.source_generation)
    executor.run_next()
    failed = feature.snapshot()
    assert failed.result.reason.code.value == "stale_revision"
    assert failed.freshness.value == "stale"
    assert failed.source_revision == ready.source_revision
    feature.refresh()
    executor.run_next()
    assert feature.snapshot().freshness.value == "fresh"


@pytest.mark.parametrize("change,field", (("missing_target", "target"), ("bad_kind", "target/kind"),
                                        ("missing_id", "operation_id")))
def test_malformed_query_classification_survives_feature_projection(composed, change, field):
    root, executor, bridge, inventory = composed
    feature = root.strategy_library_queries
    feature.refresh()
    executor.run_next()
    ready = feature.snapshot()
    request = ExactAssetQuery.freeze(operation_id="bad-feature-request", target=ready.assets[0].reference,
                                    expected_revision=ready.source_revision)
    if change == "missing_target":
        request = replace(request, target=None)
    elif change == "bad_kind":
        request = replace(request, target=replace(request.target, kind="combination"))
    else:
        request = replace(request, operation_id=[])
    feature.query_exact_asset(request, ready.source_generation)
    executor.run_next()
    rejected = feature.snapshot().result
    assert rejected.request == request
    assert rejected.asset is None
    assert rejected.reason.code.value == "invalid_request"
    assert rejected.reason.semantic_target == field
    assert not rejected.reason.retryable
