from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from app.app_context import build_app_context
from app.event_bridge import EventBridge
from app.features.versioning import FeatureInterfaceVersion, FeatureModuleName


@pytest.fixture(params=("live", "fake"))
def context(request, tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "1")
    app = QApplication.instance() or QApplication([])
    bridge = EventBridge(subscribe_backend=False)
    root = build_app_context(
        settings_path=str(tmp_path / "settings.json"),
        run_monitoring_mode=request.param,
        event_bridge=bridge,
        system_health_sampling_interval=None,
    )
    yield root
    root.close()
    bridge.stop()
    app.processEvents()


def test_handshake_preserves_six_legacy_contracts_and_rejects_future_claims(context):
    catalog = context.feature_capabilities()
    assert catalog.schema_version.render() == "1.0"
    assert tuple(
        (item.descriptor.name.value, item.descriptor.version.render())
        for item in catalog.features
    ) == (
        ("StrategyLibraryFeature", "1.0"),
        ("ScenarioLabFeature", "1.0"),
        ("DiagnosticTasksFeature", "1.0"),
        ("RunMonitoringFeature", "1.2"),
        ("EvidenceAndFindingsFeature", "1.1"),
        ("SystemHealthFeature", "1.0"),
    )
    for feature in catalog.features:
        result = catalog.negotiate(
            feature.descriptor.name, feature.descriptor.version, "snapshot"
        )
        assert result.available and result.reason is None
        target = FeatureInterfaceVersion(
            1 if feature.descriptor.name is FeatureModuleName.SYSTEM_HEALTH else 2,
            1 if feature.descriptor.name is FeatureModuleName.SYSTEM_HEALTH else 0,
        )
        missing = catalog.negotiate(feature.descriptor.name, target, "snapshot")
        assert not missing.available
        assert missing.reason.code.value == "interface_not_implemented"
        assert missing.reason.message
        assert not missing.reason.retryable

    legacy = catalog.negotiate(
        FeatureModuleName.STRATEGY_LIBRARY, FeatureInterfaceVersion(1, 0),
        "select_formal_strategy_set",
    )
    assert legacy.available
    unsupported = catalog.negotiate(
        FeatureModuleName.STRATEGY_LIBRARY, FeatureInterfaceVersion(1, 0),
        "save_combination",
    )
    assert not unsupported.available
    assert unsupported.reason.code.value == "operation_not_implemented"
    assert context.strategy_library_feature.interface_version.render() == "1.0"


@pytest.mark.parametrize("context", ["live"], indirect=True)
def test_exact_legacy_asset_query_freezes_identity_and_replays_same_operation(context):
    from strategy_diagnostics.asset_queries import ExactAssetQuery, ExactStrategyAsset

    application = context.strategy_diagnostics_application
    inventory = application.read_strategy_under_test_inventory()
    entry = inventory.entries[0]
    target = ExactStrategyAsset.from_entry(entry)
    request = ExactAssetQuery.freeze(
        operation_id="exact-strategy-001",
        target=target,
        expected_revision=inventory.content_hash,
    )
    result = application.query_exact_strategy_asset(request)
    assert result.request == request
    assert result.disposition.value == "completed"
    assert result.asset == entry
    assert result.source_revision == inventory.content_hash
    assert result.reason is None
    assert result.request.target.kind.value == "legacy_strategy"
    assert result.request.target.lineage_id == entry.strategy_id
    assert result.request.target.version_id == entry.strategy_version
    assert len(result.request.frozen_input_hash) == 64
    assert application.query_exact_strategy_asset(request) == result
    assert context.strategy_library_feature.interface_version.render() == "1.0"


@pytest.mark.parametrize("context", ["live"], indirect=True)
@pytest.mark.parametrize("change,code", (
    ("revision", "stale_revision"),
    ("frozen_input", "input_hash_mismatch"),
    ("version", "asset_not_found"),
    ("content", "asset_content_mismatch"),
    ("operation", "operation_not_implemented"),
    ("operation_id", "operation_id_conflict"),
    ("empty_id", "invalid_request"),
))
def test_exact_query_rejects_mismatched_inputs_without_showing_old_asset(context, change, code):
    from dataclasses import replace
    from strategy_diagnostics.asset_queries import ExactAssetQuery, ExactStrategyAsset

    application = context.strategy_diagnostics_application
    inventory = application.read_strategy_under_test_inventory()
    target = ExactStrategyAsset.from_entry(inventory.entries[0])
    original = ExactAssetQuery.freeze(
        operation_id="initial", target=target, expected_revision=inventory.content_hash,
    )
    receipt = application.query_exact_strategy_asset(original)
    if change in {"version", "operation_id"}:
        target = replace(target, version_id="missing-immutable-version")
    if change == "content":
        target = replace(target, content_hash="0" * 64)
    request = ExactAssetQuery.freeze(
        operation_id="initial" if change == "operation_id" else "changed",
        target=target,
        expected_revision="0" * 64 if change == "revision" else inventory.content_hash,
    )
    if change == "frozen_input":
        request = replace(request, frozen_input_hash="0" * 64)
    if change == "operation":
        request = replace(request, operation="save_combination")
        request = replace(request, frozen_input_hash=request.input_hash())
    if change == "empty_id":
        request = replace(request, operation_id="")
    result = application.query_exact_strategy_asset(request)
    assert result.disposition.value == "rejected"
    assert result.request == request
    assert result.asset is None
    assert result.reason.code.value == code
    assert result.reason.message and result.reason.semantic_target
    assert not result.reason.retryable
    assert application.query_exact_strategy_asset(original) == receipt
