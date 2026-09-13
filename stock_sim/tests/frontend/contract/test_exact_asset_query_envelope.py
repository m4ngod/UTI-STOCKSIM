"""Public application-query seam: malformed boundaries and immutable read receipts."""

from dataclasses import replace

import pytest

from strategy_diagnostics.asset_queries import ExactAssetQuery, ExactStrategyAsset, ExactStrategyQueries
from strategy_diagnostics.persistence import DIAGNOSTIC_SCHEMA_REVISION
from strategy_diagnostics.strategy_inventory import build_strategy_under_test_inventory


@pytest.fixture
def inventory():
    return build_strategy_under_test_inventory(
        guardrail_profiles=(), persistence_migration_revision=DIAGNOSTIC_SCHEMA_REVISION,
    )


def frozen_request(inventory, operation_id="envelope-query"):
    return ExactAssetQuery.freeze(
        operation_id=operation_id, target=ExactStrategyAsset.from_entry(inventory.entries[0]),
        expected_revision=inventory.content_hash,
    )


@pytest.mark.parametrize("field,value,semantic_target", (
    ("operation_id", None, "operation_id"),
    ("operation_id", [], "operation_id"),
    ("target", None, "target"),
    ("target", {"kind": "legacy_strategy"}, "target"),
    ("expected_revision", None, "expected_revision"),
    ("expected_revision", "not-a-digest", "expected_revision"),
    ("frozen_input_hash", None, "frozen_input_hash"),
))
def test_malformed_envelopes_return_field_reasons_without_reading_source(inventory, field, value, semantic_target):
    def unexpected_read():
        pytest.fail("Malformed envelopes must be rejected before touching the source")

    queries = ExactStrategyQueries(unexpected_read)
    request = replace(frozen_request(inventory), **{field: value})
    result = queries.query(request)
    assert result.request is request
    assert result.asset is None
    assert result.disposition.value == "rejected"
    assert result.reason.code.value == "invalid_request"
    assert result.reason.semantic_target == semantic_target


@pytest.mark.parametrize("field,value", (
    ("kind", "combination"), ("lineage_id", ""), ("version_id", None),
    ("content_hash", "not-a-digest"),
))
def test_malformed_exact_targets_return_structured_restrictions(inventory, field, value):
    request = frozen_request(inventory)
    target = replace(request.target, **{field: value})
    result = ExactStrategyQueries(lambda: inventory).query(replace(request, target=target))
    assert result.asset is None
    assert result.reason.code.value == "invalid_request"
    assert result.reason.semantic_target == "target/" + field


def test_application_source_failure_is_sanitized_and_receipt_does_not_change_on_replay(inventory):
    source_available = False

    def read():
        if not source_available:
            raise OSError("private-filesystem-location-must-not-leak")
        return inventory

    queries = ExactStrategyQueries(read)
    request = frozen_request(inventory)
    failed = queries.query(request)
    assert failed.asset is None and failed.source_revision is None
    assert failed.reason.code.value == "source_unavailable"
    assert failed.reason.retryable
    assert "private-filesystem" not in failed.reason.message
    source_available = True
    assert queries.query(request) == failed
    retry = queries.query(replace(request, operation_id="explicit-retry"))
    assert retry.disposition.value == "completed"


def test_receipt_replay_keeps_original_source_revision_but_new_id_observes_changed_source(inventory):
    current = inventory
    queries = ExactStrategyQueries(lambda: current)
    request = frozen_request(inventory)
    first = queries.query(request)
    current = replace(inventory, entries=inventory.entries[1:])
    assert current.content_hash != first.source_revision
    assert queries.query(request) is first
    later = queries.query(replace(request, operation_id="new-source-read"))
    assert later.asset is None and later.reason.code.value == "stale_revision"
    assert later.source_revision == current.content_hash


def test_material_hash_ignores_display_readiness_and_dependency_order(inventory):
    entry = inventory.entries[0]
    reference = ExactStrategyAsset.from_entry(entry)
    observed = replace(
        entry, display=replace(entry.display, display_name="Renamed only"),
        entity_revision=entry.entity_revision + 1,
        formal_campaign_eligible=not entry.formal_campaign_eligible,
        dependencies=tuple(replace(item, available=not item.available, compatible=not item.compatible)
                           for item in reversed(entry.dependencies)),
    )
    assert ExactStrategyAsset.from_entry(observed) == reference


@pytest.mark.parametrize("part", ("source", "policy", "compatibility", "dependency", "version"))
def test_material_changes_cannot_reuse_the_exact_content_reference(inventory, part):
    entry = inventory.entries[0]
    reference = ExactStrategyAsset.from_entry(entry)
    changes = {
        "source": {"source": replace(entry.source, content_sha256="1" * 64)},
        "policy": {"candidate_data_policy": "changed-candidate-policy"},
        "compatibility": {"compatibility": replace(entry.compatibility, content_hash="2" * 64)},
        "dependency": {"dependencies": (replace(entry.dependencies[0], content_hash="3" * 64), *entry.dependencies[1:])},
        "version": {"strategy_version": "changed-immutable-version"},
    }
    assert ExactStrategyAsset.from_entry(replace(entry, **changes[part])).content_hash != reference.content_hash
