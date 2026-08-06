"""Wave 3 Strategy Diagnostics V1 + Frontend V2 source integration gate.

This gate is deliberately not a release-certification claim.  It keeps the
shared conformance, persisted tracer, backend regression, and existing
Frontend V2 gates executable from one fail-closed manifest.  Issue #88 owns
the Wave 3 installed-offline release certification, evidence, and artifacts.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from app.features import (
    ACTIVE_FEATURE_INTERFACES,
    DIAGNOSTIC_TASKS_APPLICATION_INTERFACE_VERSION,
    SCENARIO_LAB_APPLICATION_INTERFACE_VERSION,
    STRATEGY_LIBRARY_APPLICATION_INTERFACE_VERSION,
)


@dataclass(frozen=True, slots=True)
class IntegrationGateGroup:
    """One independently reproducible pytest invocation."""

    name: str
    pytest_targets: tuple[str, ...]
    pytest_args: tuple[str, ...] = ()
    fresh_sqlite: bool = False
    clean_python: bool = False


@dataclass(frozen=True, slots=True)
class IntegrationGateValidation:
    """Static validation result for the checked-in gate manifest."""

    ok: bool
    errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IntegrationGateExecution:
    """Process result for one group without hiding its exact invocation."""

    group: str
    command: tuple[str, ...]
    returncode: int
    junit_path: Path | None = None
    stdout_path: Path | None = None
    stderr_path: Path | None = None


@dataclass(frozen=True, slots=True)
class PersistedTracerCoverage:
    """One source-bound acceptance category within the real live tracer seam."""

    requirement: str
    pytest_targets: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PersistedProductTracer:
    """The source-bound Seam-1 suite and its production-QML primary path."""

    source_path: Path
    function_name: str
    required_markers: tuple[str, ...]
    forbidden_markers: tuple[str, ...]
    coverage: tuple[PersistedTracerCoverage, ...]

    @property
    def pytest_target(self) -> str:
        return f"{self.source_path.as_posix()}::{self.function_name}"

    @property
    def pytest_targets(self) -> tuple[str, ...]:
        return (
            self.pytest_target,
            *(
                target
                for category in self.coverage
                for target in category.pytest_targets
            ),
        )


PERSISTED_PRODUCT_TRACER = PersistedProductTracer(
    source_path=Path(
        "tests/frontend/integration/test_diagnostic_tasks_workspace_route.py"
    ),
    function_name=(
        "test_live_qml_tracer_recovers_retries_and_reopens_exact_evidence"
    ),
    required_markers=(
        "LiveStrategyLibraryAdapter",
        "LiveScenarioLabAdapter",
        "LiveDiagnosticTasksAdapter",
        "LiveRunMonitoringAdapter",
        "LiveEvidenceAndFindingsAdapter",
        "LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter",
        "LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter",
        "LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter",
        "ParquetMarketPathArtifactStore",
        "JourneyWorkspaceHost",
        "createRecipeDraft",
        "validateRecipeDraft",
        "approveRecipeValidation",
        "materializeApprovedRecipeVersion",
        "strategy_run_status",
        "resolved_execution_conditions",
        "STOCKSIM_WAVE3_IDENTITY_LEDGER",
        "create_diagnostics_application",
        "create_engine",
        "engine.dispose()",
        "restarted_engine",
        "durable_identity_graph",
        "expected_durable_identity_graph",
    ),
    forbidden_markers=(
        "DeterministicFakeStrategyLibraryAdapter",
        "DeterministicFakeScenarioLabAdapter",
        "DeterministicFakeDiagnosticTasksAdapter",
        "DeterministicFakeRunMonitoringAdapter",
        "DeterministicFakeEvidenceAndFindingsAdapter",
        "DictionaryFixtureApplicationReadModel",
        "_LiveJourneyQueries",
        "Repository",
        "session.execute",
    ),
    coverage=(
        PersistedTracerCoverage(
            requirement="authoritative-strategy-library-slice",
            pytest_targets=(
                (
                    "tests/frontend/integration/"
                    "test_strategy_library_workspace_route.py::"
                    "test_live_strategy_library_traces_public_inventory_into_qml"
                ),
            ),
        ),
        PersistedTracerCoverage(
            requirement=(
                "authoritative-scenario-recipe-materialization-and-formal-set"
            ),
            pytest_targets=(
                (
                    "tests/frontend/contract/"
                    "test_scenario_lab_live_fake_conformance.py::"
                    "test_shared_materializes_exact_approved_recipe_with_persistent_task_handle"
                ),
            ),
        ),
        PersistedTracerCoverage(
            requirement="typed-diagnostic-setup-selection-handoff",
            pytest_targets=(
                (
                    "tests/frontend/contract/"
                    "test_diagnostic_setup_handoff_live_contract.py::"
                    "test_live_exact_setup_selection_is_bound_through_approval"
                ),
            ),
        ),
        PersistedTracerCoverage(
            requirement=(
                "bounded-dependency-change-revalidation-and-reapproval"
            ),
            pytest_targets=(
                (
                    "tests/frontend/contract/"
                    "test_scenario_lab_live_fake_conformance.py::"
                    "test_shared_dependency_change_rejects_approval_without_side_effects"
                ),
                (
                    "tests/frontend/contract/"
                    "test_scenario_lab_live_fake_conformance.py::"
                    "test_shared_approved_history_survives_dependency_invalidation_and_replay"
                ),
                (
                    "tests/frontend/contract/"
                    "test_diagnostic_setup_handoff_live_contract.py::"
                    "test_live_and_fake_share_exact_setup_invalidation_contract"
                ),
            ),
        ),
        PersistedTracerCoverage(
            requirement=(
                "quick-experiment-and-execution-assumption-run-facts"
            ),
            pytest_targets=(
                (
                    "tests/frontend/contract/"
                    "test_scenario_lab_formal_scenario_sets_live_contract.py::"
                    "test_live_composition_classifies_complete_formal_and_selective_quick_sets"
                ),
                (
                    "tests/frontend/contract/"
                    "test_diagnostic_setup_selection_context.py::"
                    "test_setup_composition_fails_closed_for_stale_quick_or_unresolved_scenario"
                ),
                (
                    "tests/frontend/contract/"
                    "test_scenario_lab_formal_scenario_sets_live_contract.py::"
                    "test_live_resolution_and_selection_bind_exact_assumptions_and_activation"
                ),
                (
                    "tests/strategy_diagnostics/test_strategy_runs.py::"
                    "test_ptrade_configuration_requests_and_effective_conditions_are_run_evidence"
                ),
            ),
        ),
        PersistedTracerCoverage(
            requirement="authoritative-input-and-exact-revision",
            pytest_targets=(
                (
                    "tests/frontend/contract/"
                    "test_diagnostic_task_creation_live_contract.py::"
                    "test_invalid_create_and_atomic_acceptance_failure_have_no_side_effect"
                ),
                (
                    "tests/frontend/contract/"
                    "test_diagnostic_task_revision_approval_live_contract.py::"
                    "test_live_revision_validation_approval_persist_and_invalidate"
                ),
                (
                    "tests/frontend/contract/"
                    "test_diagnostic_task_revision_approval_live_contract.py::"
                    "test_stale_revision_and_invalid_validation_reject_without_campaign"
                ),
                (
                    "tests/frontend/contract/"
                    "test_diagnostic_task_revision_approval_live_contract.py::"
                    "test_live_validation_emits_typed_findings_for_each_authority_mismatch"
                ),
                (
                    "tests/frontend/contract/"
                    "test_diagnostic_task_campaign_start_live_contract.py::"
                    "test_incomplete_formal_input_is_rejected_before_start_side_effects"
                ),
            ),
        ),
        PersistedTracerCoverage(
            requirement=(
                "terminal-evidence-finding-breakpoint-manifest-identities"
            ),
            pytest_targets=(
                (
                    "tests/frontend/contract/"
                    "test_strategy_diagnostics_v1_evidence_and_findings_live_contract.py::"
                    "test_real_sealed_v1_evidence_is_visible_in_production_qml"
                ),
            ),
        ),
        PersistedTracerCoverage(
            requirement="command-identity-idempotency-and-recovery",
            pytest_targets=(
                (
                    "tests/frontend/contract/"
                    "test_diagnostic_task_creation_live_contract.py::"
                    "test_live_create_is_durable_idempotent_and_reopens_without_a_campaign"
                ),
                (
                    "tests/frontend/contract/"
                    "test_diagnostic_task_campaign_start_live_contract.py::"
                    "test_start_exact_approved_revision_persists_one_formal_campaign_and_handoff"
                ),
                (
                    "tests/frontend/contract/"
                    "test_diagnostic_task_campaign_start_live_contract.py::"
                    "test_retry_after_handoff_persistence_failure_does_not_advance_another_case"
                ),
                (
                    "tests/frontend/contract/"
                    "test_diagnostic_task_campaign_start_live_contract.py::"
                    "test_concurrent_same_idempotency_claims_one_durable_start_continuation"
                ),
                (
                    "tests/frontend/contract/"
                    "test_diagnostic_tasks_recovery_live_contract.py::"
                    "test_pre_campaign_commands_replay_after_application_restart"
                ),
                (
                    "tests/frontend/contract/"
                    "test_diagnostic_tasks_live_fake_conformance.py::"
                    "test_lost_response_requires_lookup_and_same_key_recovers_acceptance"
                ),
            ),
        ),
        PersistedTracerCoverage(
            requirement="lifecycle-retry-terminal-and-order-isolation",
            pytest_targets=(
                (
                    "tests/frontend/contract/"
                    "test_diagnostic_task_lifecycle_live_contract.py::"
                    "test_live_lifecycle_survives_reopen_and_gates_real_campaign_execution"
                ),
                (
                    "tests/frontend/contract/"
                    "test_diagnostic_task_lifecycle_live_contract.py::"
                    "test_application_reopen_completes_durably_accepted_lifecycle_command"
                ),
                (
                    "tests/frontend/contract/"
                    "test_diagnostic_task_lifecycle_live_contract.py::"
                    "test_later_terminal_command_supersedes_older_queued_lifecycle_handle"
                ),
                (
                    "tests/frontend/contract/"
                    "test_diagnostic_task_lifecycle_live_contract.py::"
                    "test_live_paused_node_blocks_ordered_runner_until_resume"
                ),
                (
                    "tests/frontend/contract/"
                    "test_diagnostic_task_lifecycle_live_contract.py::"
                    "test_live_canceled_node_never_reaches_ordered_runner"
                ),
                (
                    "tests/frontend/contract/"
                    "test_diagnostic_task_lifecycle_live_contract.py::"
                    "test_live_completed_campaign_syncs_terminal_diagnostic_lifecycle"
                ),
                (
                    "tests/frontend/contract/"
                    "test_diagnostic_task_lifecycle_live_contract.py::"
                    "test_final_batch_pause_then_resume_reconciles_completed_campaign"
                ),
                (
                    "tests/frontend/contract/"
                    "test_diagnostic_task_lifecycle_live_contract.py::"
                    "test_live_cancel_target_cannot_reach_order_cancellation"
                ),
                (
                    "tests/frontend/contract/"
                    "test_diagnostic_task_failed_node_retry_live_contract.py::"
                    "test_live_failed_node_retry_failure_creates_a_new_failed_attempt"
                ),
                (
                    "tests/frontend/contract/"
                    "test_diagnostic_task_failed_node_retry_live_contract.py::"
                    "test_live_campaign_progress_after_retry_preserves_task_handle_binding"
                ),
                (
                    "tests/frontend/contract/"
                    "test_diagnostic_task_failed_node_retry_live_contract.py::"
                    "test_live_retry_completion_preserves_a_newer_public_campaign_pause"
                ),
            ),
        ),
        PersistedTracerCoverage(
            requirement="connection-generation-disposal-and-no-late-callback",
            pytest_targets=(
                (
                    "tests/frontend/contract/"
                    "test_diagnostic_tasks_live_fake_conformance.py::"
                    "test_live_and_fake_reject_before_acceptance_while_disconnected"
                    "[_live_recovery_harness]"
                ),
                (
                    "tests/frontend/contract/"
                    "test_diagnostic_tasks_live_fake_conformance.py::"
                    "test_live_diagnostic_tasks_reconnects_with_a_new_generation_only_after_reread"
                ),
                (
                    "tests/frontend/contract/"
                    "test_diagnostic_tasks_live_fake_conformance.py::"
                    "test_live_adapter_quarantines_an_authoritative_read_from_old_generation"
                ),
                (
                    "tests/frontend/contract/"
                    "test_diagnostic_tasks_live_fake_conformance.py::"
                    "test_live_adapter_close_drops_an_inflight_read_without_late_callback"
                ),
                (
                    "tests/frontend/contract/"
                    "test_diagnostic_tasks_live_fake_conformance.py::"
                    "test_live_adapter_ignores_old_generation_batches_but_rereads_current"
                ),
                (
                    "tests/frontend/contract/"
                    "test_diagnostic_tasks_live_fake_conformance.py::"
                    "test_disconnect_after_durable_acceptance_preserves_the_original_handle"
                ),
                (
                    "tests/frontend/contract/"
                    "test_diagnostic_tasks_live_fake_conformance.py::"
                    "test_old_generation_accepted_response_requires_authoritative_recovery"
                ),
            ),
        ),
    ),
)

_DIAGNOSTIC_CONFORMANCE_SOURCE = (
    "tests/frontend/contract/test_diagnostic_tasks_live_fake_conformance.py"
)
_TRACER_CONFORMANCE_TARGETS = tuple(
    target
    for category in PERSISTED_PRODUCT_TRACER.coverage
    for target in category.pytest_targets
    if target.startswith(f"{_DIAGNOSTIC_CONFORMANCE_SOURCE}::")
)
_TRACER_OTHER_CONTRACT_TARGETS = tuple(
    target
    for category in PERSISTED_PRODUCT_TRACER.coverage
    for target in category.pytest_targets
    if not target.startswith(f"{_DIAGNOSTIC_CONFORMANCE_SOURCE}::")
)


INTEGRATION_GATE_GROUPS: tuple[IntegrationGateGroup, ...] = (
    IntegrationGateGroup(
        "shared-feature-conformance",
        (
            (
                "tests/frontend/contract/"
                "test_diagnostic_tasks_feature_contract.py"
            ),
            (
                "tests/frontend/contract/"
                "test_strategy_library_feature_contract.py"
            ),
            (
                "tests/frontend/contract/"
                "test_strategy_library_application_live_contract.py"
            ),
            (
                "tests/frontend/contract/"
                "test_strategy_library_live_fake_conformance.py"
            ),
            (
                "tests/frontend/contract/"
                "test_scenario_lab_feature_contract.py"
            ),
            (
                "tests/frontend/contract/"
                "test_scenario_lab_application_live_contract.py"
            ),
            (
                "tests/frontend/contract/"
                "test_scenario_lab_live_fake_conformance.py"
            ),
            (
                "tests/frontend/contract/"
                "test_diagnostic_tasks_application_live_contract.py"
            ),
            (
                "tests/frontend/contract/"
                "test_diagnostic_tasks_live_fake_conformance.py"
            ),
            (
                "tests/frontend/contract/"
                "test_strategy_diagnostics_v1_feature_pair_conformance.py"
            ),
            (
                "tests/frontend/contract/"
                "test_strategy_diagnostics_v1_frontend_v2_integration_gate.py"
            ),
        ),
        pytest_args=tuple(
            f"--deselect={target}"
            for target in _TRACER_CONFORMANCE_TARGETS
        ),
    ),
    IntegrationGateGroup(
        "persisted-application-qml-tracer",
        PERSISTED_PRODUCT_TRACER.pytest_targets,
    ),
    IntegrationGateGroup(
        "strategy-diagnostics-v1-regression",
        ("tests/strategy_diagnostics",),
        pytest_args=(
            "-k",
            "not importing_root_package_keeps_persistence_lazy",
        ),
    ),
    IntegrationGateGroup(
        "strategy-diagnostics-v1-lazy-import-isolation",
        (
            (
                "tests/strategy_diagnostics/test_installation.py::"
                "test_importing_root_package_keeps_persistence_lazy"
            ),
        ),
        clean_python=True,
    ),
    IntegrationGateGroup(
        "frontend-v2-contract",
        ("tests/frontend/contract",),
        pytest_args=(
            (
                "--ignore=tests/frontend/contract/"
                "test_diagnostic_tasks_feature_contract.py"
            ),
            (
                "--ignore=tests/frontend/contract/"
                "test_strategy_library_feature_contract.py"
            ),
            (
                "--ignore=tests/frontend/contract/"
                "test_strategy_library_application_live_contract.py"
            ),
            (
                "--ignore=tests/frontend/contract/"
                "test_strategy_library_live_fake_conformance.py"
            ),
            (
                "--ignore=tests/frontend/contract/"
                "test_scenario_lab_feature_contract.py"
            ),
            (
                "--ignore=tests/frontend/contract/"
                "test_scenario_lab_application_live_contract.py"
            ),
            (
                "--ignore=tests/frontend/contract/"
                "test_scenario_lab_live_fake_conformance.py"
            ),
            (
                "--ignore=tests/frontend/contract/"
                "test_diagnostic_tasks_application_live_contract.py"
            ),
            (
                "--ignore=tests/frontend/contract/"
                "test_diagnostic_tasks_live_fake_conformance.py"
            ),
            (
                "--ignore=tests/frontend/contract/"
                "test_strategy_diagnostics_v1_feature_pair_conformance.py"
            ),
            (
                "--ignore=tests/frontend/contract/"
                "test_strategy_diagnostics_v1_frontend_v2_integration_gate.py"
            ),
            *tuple(
                f"--deselect={target}"
                for target in _TRACER_OTHER_CONTRACT_TARGETS
            ),
        ),
    ),
    IntegrationGateGroup(
        "frontend-v2-integration-e2e-accessibility",
        (
            "tests/frontend/integration",
            "tests/frontend/e2e",
        ),
        pytest_args=(
            f"--deselect={PERSISTED_PRODUCT_TRACER.pytest_target}",
        ),
    ),
    IntegrationGateGroup(
        "frontend-v2-unit",
        ("tests/frontend/unit",),
        pytest_args=("--ignore=tests/frontend/unit/test_event_bridge.py",),
        fresh_sqlite=True,
    ),
    IntegrationGateGroup(
        "frontend-v2-event-bridge",
        ("tests/frontend/unit/test_event_bridge.py",),
        fresh_sqlite=True,
    ),
    IntegrationGateGroup(
        "frontend-v2-safety",
        ("tests/frontend/safety",),
    ),
    IntegrationGateGroup(
        "frontend-v2-performance-packaging-contract",
        (
            "tests/frontend/performance",
            "tests/frontend/packaging",
        ),
    ),
)

REQUIRED_CONTRACT_DOCUMENTS: tuple[Path, ...] = (
    Path("docs/contracts/integration/strategy-diagnostics-v1-frontend-v2-contract.md"),
    Path("docs/testing/integration/strategy-diagnostics-v1-frontend-v2-runbook.md"),
)
REQUIRED_CONTRACT_MARKERS: dict[Path, tuple[str, ...]] = {
    REQUIRED_CONTRACT_DOCUMENTS[0]: (
        "# Strategy Diagnostics V1 + Frontend V2 Wave 3 contract",
        "`StrategyLibraryFeature` version 1.0",
        "`ScenarioLabFeature` version 1.0",
        "`DiagnosticTasksFeature` version 1.0",
        "`RunMonitoringFeature` version 1.2",
        "`EvidenceAndFindingsFeature` version 1.1",
        "`StrategyDiagnosticsV1DiagnosticTasksApplication` version 1.0",
        "`StrategyDiagnosticsV1StrategyLibraryApplication` version 1.0",
        "`StrategyDiagnosticsV1ScenarioLabApplication` version 1.0",
        "Issue #79 activates Scenario Lab read tracing",
        "Issue #84 activates `DiagnosticSetupSelectionContext`",
        "Issue #86 completes source-level T08/T09/T10 preflight",
        "Issue #87 freezes one immutable source candidate",
        "`identity-ledger.json`",
        "durable bookmark contains those immutable references",
        "Seam 1",
        "Seam 2",
        "Seam 3",
        "Wave 4 remain unimplemented",
        "Issue #88 owns the installed offline black-box certification",
    ),
    REQUIRED_CONTRACT_DOCUMENTS[1]: (
        "# Strategy Diagnostics V1 + Frontend V2 Wave 3 integration runbook",
        "`StrategyLibraryFeature` 1.0",
        "`ScenarioLabFeature` 1.0",
        "`DiagnosticTasksFeature` 1.0",
        "`RunMonitoringFeature` 1.2",
        "`EvidenceAndFindingsFeature` 1.1",
        "`StrategyDiagnosticsV1DiagnosticTasksApplication` 1.0",
        "`StrategyDiagnosticsV1StrategyLibraryApplication` 1.0",
        "`StrategyDiagnosticsV1ScenarioLabApplication` 1.0",
        "including Issues #77–#87",
        "--evidence-root",
        "identity-ledger.json",
        "durable bookmark reread",
        PERSISTED_PRODUCT_TRACER.function_name,
        "test_diagnostic_tasks_live_fake_conformance.py",
        "test_strategy_library_live_fake_conformance.py",
        "test_scenario_lab_live_fake_conformance.py",
        "test_live_exact_setup_selection_is_bound_through_approval",
        "Seam 3",
        "Issue #88",
        "source-level T08/T09/T10 preflight",
    ),
}

_SUPPORTING_READ_TRACER_SOURCES: tuple[Path, ...] = (
    Path("tests/frontend/integration/test_live_run_to_evidence_journey.py"),
    Path(
        "tests/frontend/contract/"
        "test_strategy_diagnostics_v1_evidence_and_findings_live_contract.py"
    ),
    Path("tests/frontend/unit/test_diagnostics_panel.py"),
)
_FORBIDDEN_TRACER_MARKERS = (
    "DictionaryFixtureApplicationReadModel",
    "_LiveJourneyQueries",
    "get_run_monitoring_snapshot",
    "get_evidence_and_findings_snapshot",
)


def validate_integration_gate(project_root: Path) -> IntegrationGateValidation:
    """Fail closed when the union manifest, docs, or tracer drift."""

    root = project_root.resolve()
    errors: list[str] = []
    expected_interfaces = (
        "StrategyLibraryFeature",
        "ScenarioLabFeature",
        "DiagnosticTasksFeature",
        "RunMonitoringFeature",
        "EvidenceAndFindingsFeature",
        "SystemHealthFeature",
    )
    actual_interfaces = tuple(
        interface.name.value for interface in ACTIVE_FEATURE_INTERFACES
    )
    if actual_interfaces != expected_interfaces:
        errors.append(
            "ACTIVE_FEATURE_INTERFACES drifted: "
            f"expected {expected_interfaces!r}, got {actual_interfaces!r}"
        )
    if DIAGNOSTIC_TASKS_APPLICATION_INTERFACE_VERSION.render() != "1.0":
        errors.append(
            "StrategyDiagnosticsV1DiagnosticTasksApplication drifted from 1.0"
        )
    if STRATEGY_LIBRARY_APPLICATION_INTERFACE_VERSION.render() != "1.0":
        errors.append(
            "StrategyDiagnosticsV1StrategyLibraryApplication drifted from 1.0"
        )
    if SCENARIO_LAB_APPLICATION_INTERFACE_VERSION.render() != "1.0":
        errors.append(
            "StrategyDiagnosticsV1ScenarioLabApplication drifted from 1.0"
        )
    expected_tracer_requirements = (
        "authoritative-strategy-library-slice",
        "authoritative-scenario-recipe-materialization-and-formal-set",
        "typed-diagnostic-setup-selection-handoff",
        "bounded-dependency-change-revalidation-and-reapproval",
        "quick-experiment-and-execution-assumption-run-facts",
        "authoritative-input-and-exact-revision",
        "terminal-evidence-finding-breakpoint-manifest-identities",
        "command-identity-idempotency-and-recovery",
        "lifecycle-retry-terminal-and-order-isolation",
        "connection-generation-disposal-and-no-late-callback",
    )
    actual_tracer_requirements = tuple(
        category.requirement
        for category in PERSISTED_PRODUCT_TRACER.coverage
    )
    if actual_tracer_requirements != expected_tracer_requirements:
        errors.append(
            "persisted product tracer coverage drifted: "
            f"expected {expected_tracer_requirements!r}, "
            f"got {actual_tracer_requirements!r}"
        )
    if len(PERSISTED_PRODUCT_TRACER.pytest_targets) != len(
        set(PERSISTED_PRODUCT_TRACER.pytest_targets)
    ):
        errors.append("persisted product tracer targets must be unique")

    names = tuple(group.name for group in INTEGRATION_GATE_GROUPS)
    if len(names) != len(set(names)):
        errors.append("integration gate group names must be unique")
    for group in INTEGRATION_GATE_GROUPS:
        if not group.pytest_targets:
            errors.append(f"{group.name}: no pytest targets")
        for target in group.pytest_targets:
            target_parts = target.split("::", maxsplit=1)
            target_path = root / target_parts[0]
            if not target_path.exists():
                errors.append(f"{group.name}: missing target {target}")
                continue
            if len(target_parts) == 2:
                function_name = target_parts[1].partition("[")[0]
                try:
                    _function_source(target_path, function_name)
                except (SyntaxError, ValueError) as error:
                    errors.append(f"{group.name}: {error}")

    for document in REQUIRED_CONTRACT_DOCUMENTS:
        document_path = root / document
        if not document_path.is_file():
            errors.append(f"missing required contract document {document}")
            continue
        document_source = document_path.read_text(encoding="utf-8")
        for marker in REQUIRED_CONTRACT_MARKERS[document]:
            if marker not in document_source:
                errors.append(
                    f"{document}: missing Wave 3 contract marker {marker!r}"
                )

    tracer_path = root / PERSISTED_PRODUCT_TRACER.source_path
    if not tracer_path.is_file():
        errors.append(
            "missing persisted product tracer source "
            f"{PERSISTED_PRODUCT_TRACER.source_path}"
        )
    else:
        try:
            tracer_source = _function_source(
                tracer_path,
                PERSISTED_PRODUCT_TRACER.function_name,
            )
        except (SyntaxError, ValueError) as error:
            errors.append(str(error))
        else:
            for marker in PERSISTED_PRODUCT_TRACER.required_markers:
                if marker not in tracer_source:
                    errors.append(
                        "persisted product tracer is missing "
                        f"{marker!r}"
                    )
            for marker in PERSISTED_PRODUCT_TRACER.forbidden_markers:
                if marker in tracer_source:
                    errors.append(
                        "persisted product tracer contains forbidden "
                        f"{marker!r}"
                    )

    for tracer_source_path in _SUPPORTING_READ_TRACER_SOURCES:
        tracer_path = root / tracer_source_path
        if not tracer_path.is_file():
            errors.append(f"missing persisted tracer source {tracer_source_path}")
            continue
        tracer_source = tracer_path.read_text(encoding="utf-8")
        for marker in _FORBIDDEN_TRACER_MARKERS:
            if marker in tracer_source:
                errors.append(
                    f"persisted tracer source {tracer_source_path} contains {marker}"
                )

    return IntegrationGateValidation(ok=not errors, errors=tuple(errors))


def _function_source(path: Path, function_name: str) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    function = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == function_name
        ),
        None,
    )
    if function is None:
        raise ValueError(
            f"{path}: missing persisted product tracer {function_name}"
        )
    segment = ast.get_source_segment(source, function)
    if segment is None:
        raise ValueError(
            f"{path}: cannot isolate persisted product tracer {function_name}"
        )
    return segment


_SOURCE_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
_WAVE3_MIGRATIONS = (
    "0019_scenario_recipe_dependency_bindings",
    "0020_scenario_lab_commands_and_materialization_handles",
    "0021_diagnostic_selection_dependency_invalidation",
)


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _evidence_relative_path(path: Path, evidence_root: Path) -> str:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(evidence_root.resolve())
    except ValueError as exc:
        raise ValueError(
            f"Source candidate evidence escapes its root: {resolved}"
        ) from exc
    return relative.as_posix()


def _junit_counts(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    suites = (
        (root,)
        if root.tag == "testsuite"
        else tuple(root.findall("testsuite"))
    )
    counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for suite in suites:
        for name in counts:
            counts[name] += int(suite.attrib.get(name, "0"))
    if counts["tests"] <= 0:
        raise ValueError(f"JUnit report executed no tests: {path}")
    if counts["failures"] or counts["errors"]:
        raise ValueError(f"JUnit report is not green: {path}")
    return counts


def _required_ledger_mapping(
    parent: Mapping[str, object],
    name: str,
) -> Mapping[str, object]:
    value = parent.get(name)
    if not isinstance(value, Mapping):
        raise ValueError(f"identity ledger section {name!r} is unavailable")
    return value


def _require_ledger_values(
    section_name: str,
    section: Mapping[str, object],
    names: Sequence[str],
) -> None:
    missing = tuple(
        name
        for name in names
        if name not in section
        or section[name] is None
        or section[name] == ""
        or section[name] == []
    )
    if missing:
        raise ValueError(
            f"identity ledger section {section_name!r} is incomplete: "
            f"{missing!r}"
        )


def _validate_identity_ledger(
    ledger: object,
    *,
    source_commit: str,
) -> Mapping[str, object]:
    if not isinstance(ledger, Mapping):
        raise ValueError("identity ledger must be a JSON object")
    if ledger.get("schema_version") != 1:
        raise ValueError("identity ledger schema_version must be 1")
    if ledger.get("candidate_source") != source_commit:
        raise ValueError("identity ledger is bound to a different candidate source")
    expected_registry = [
        "StrategyLibraryFeature/1.0",
        "ScenarioLabFeature/1.0",
        "DiagnosticTasksFeature/1.0",
        "RunMonitoringFeature/1.2",
        "EvidenceAndFindingsFeature/1.1",
        "SystemHealthFeature/1.0",
    ]
    if ledger.get("feature_interfaces") != expected_registry:
        raise ValueError(
            "identity ledger does not contain the exact six-Feature registry"
        )

    required_sections = {
        "strategy_library": (
            "selection_context_id",
            "entries",
        ),
        "scenario_lab": (
            "historical_segment",
            "recipe_draft",
            "recipe_validation",
            "approved_recipe",
            "materialization_task_handle",
            "materialized_case",
            "formal_scenario_set",
            "execution_resolution",
            "selection_context",
        ),
        "diagnostic_tasks": (
            "setup_context_id",
            "task_id",
            "configuration_content_id",
            "validation_id",
            "approval_id",
            "task_handle_ids",
        ),
        "campaign": (
            "campaign_id",
            "node_ids",
            "attempt_ids",
            "run_ids",
            "requested_effective_override",
        ),
        "evidence_and_findings": (
            "evidence_package_id",
            "evidence_record_ids",
            "finding_ids",
            "breakpoint_ids",
            "breakpoint_finding_edges",
            "reproduction_manifest_id",
        ),
        "recovery": (
            "durable_identity_graph",
        ),
    }
    sections: dict[str, Mapping[str, object]] = {}
    for section_name, names in required_sections.items():
        section = _required_ledger_mapping(ledger, section_name)
        _require_ledger_values(section_name, section, names)
        sections[section_name] = section

    strategy_entries = sections["strategy_library"]["entries"]
    if (
        not isinstance(strategy_entries, list)
        or len(strategy_entries) != 2
        or any(
            not isinstance(entry, list)
            or len(entry) != 5
            or any(not isinstance(value, str) or not value for value in entry)
            for entry in strategy_entries
        )
    ):
        raise ValueError(
            "identity ledger Strategy Library entries are not the exact "
            "two identity/version/manifest/Guardrail tuples"
        )

    scenario = sections["scenario_lab"]
    scenario_identity_fields = {
        "historical_segment": (
            "segmentId",
            "contentHash",
            "sourceSnapshotId",
        ),
        "recipe_draft": ("draftId", "payloadHash"),
        "recipe_validation": (
            "validationId",
            "draftId",
            "recipeContentHash",
        ),
        "approved_recipe": (
            "recipeVersionId",
            "approvalId",
            "contentHash",
        ),
        "materialization_task_handle": (
            "taskHandleId",
            "attemptId",
            "resultIdentity",
        ),
        "materialized_case": (
            "scenarioId",
            "pathId",
            "recipeVersionId",
        ),
        "formal_scenario_set": ("scenarioSetId", "caseIds"),
        "execution_resolution": ("resolutionId", "targets"),
        "selection_context": (
            "selectionContextId",
            "executionResolutionId",
        ),
    }
    for name, fields in scenario_identity_fields.items():
        projection = _required_ledger_mapping(scenario, name)
        _require_ledger_values(f"scenario_lab.{name}", projection, fields)

    run_facts = _required_ledger_mapping(
        sections["campaign"],
        "requested_effective_override",
    )
    _require_ledger_values(
        "campaign.requested_effective_override",
        run_facts,
        ("requested", "effective", "resolutions"),
    )
    evidence = sections["evidence_and_findings"]
    finding_ids = evidence["finding_ids"]
    breakpoint_ids = evidence["breakpoint_ids"]
    breakpoint_edges = evidence["breakpoint_finding_edges"]
    if (
        not isinstance(finding_ids, list)
        or not all(isinstance(value, str) and value for value in finding_ids)
        or not isinstance(breakpoint_ids, list)
        or not all(
            isinstance(value, str) and value for value in breakpoint_ids
        )
        or not isinstance(breakpoint_edges, list)
        or not breakpoint_edges
        or any(
            not isinstance(edge, list)
            or len(edge) != 2
            or edge[0] not in finding_ids
            or edge[1] not in breakpoint_ids
            for edge in breakpoint_edges
        )
    ):
        raise ValueError(
            "identity ledger does not contain exact Finding-to-Breakpoint "
            "provenance edges"
        )
    recovery = sections["recovery"]
    for name in (
        "remount_preserved_exact_identities",
        "application_reopen_preserved_exact_identities",
        "market_path_store_reopened_from_files",
        "old_generation_quarantined",
    ):
        if recovery.get(name) is not True:
            raise ValueError(
                f"identity ledger recovery proof {name!r} did not pass"
            )
    return ledger


def write_source_candidate_evidence(
    project_root: Path,
    *,
    evidence_root: Path,
    source_commit: str,
    executions: Sequence[IntegrationGateExecution],
) -> Path:
    """Seal the complete source-level Gate reports to one candidate SHA."""

    if _SOURCE_COMMIT_PATTERN.fullmatch(source_commit) is None:
        raise ValueError("candidate source must be one full lowercase Git SHA")
    root = project_root.resolve()
    candidate_root = evidence_root.resolve()
    candidate_root.mkdir(parents=True, exist_ok=True)
    expected_groups = tuple(group.name for group in INTEGRATION_GATE_GROUPS)
    actual_groups = tuple(item.group for item in executions)
    if actual_groups != expected_groups:
        raise ValueError(
            "candidate evidence requires the complete ordered Gate: "
            f"expected {expected_groups!r}, got {actual_groups!r}"
        )
    if any(item.returncode != 0 for item in executions):
        raise ValueError("candidate evidence requires every Gate group to pass")

    identity_ledger_path = candidate_root / "identity-ledger.json"
    if not identity_ledger_path.is_file():
        raise ValueError("persisted six-Feature identity ledger is unavailable")
    identity_ledger = _validate_identity_ledger(json.loads(
        identity_ledger_path.read_text(encoding="utf-8")
    ), source_commit=source_commit)

    group_evidence: list[dict[str, object]] = []
    for execution in executions:
        paths = (
            execution.junit_path,
            execution.stdout_path,
            execution.stderr_path,
        )
        if any(path is None for path in paths):
            raise ValueError(
                f"{execution.group}: JUnit and raw logs are required"
            )
        junit_path, stdout_path, stderr_path = paths
        assert junit_path is not None
        assert stdout_path is not None
        assert stderr_path is not None
        for path in (junit_path, stdout_path, stderr_path):
            _evidence_relative_path(path, candidate_root)
            if not path.is_file():
                raise ValueError(
                    f"{execution.group}: missing source Gate report {path}"
                )
        group_evidence.append(
            {
                "name": execution.group,
                "command": list(execution.command),
                "returncode": execution.returncode,
                "junit": {
                    "path": _evidence_relative_path(junit_path, candidate_root),
                    "sha256": _sha256_path(junit_path),
                    **_junit_counts(junit_path),
                },
                "stdout": {
                    "path": _evidence_relative_path(stdout_path, candidate_root),
                    "sha256": _sha256_path(stdout_path),
                },
                "stderr": {
                    "path": _evidence_relative_path(stderr_path, candidate_root),
                    "sha256": _sha256_path(stderr_path),
                },
            }
        )

    active_registry = [
        f"{item.name.value}/{item.version.render()}"
        for item in ACTIVE_FEATURE_INTERFACES
    ]
    summary = {
        "schema_version": 1,
        "candidate_source": source_commit,
        "candidate_kind": "immutable-wave3-source",
        "release_claim": False,
        "all_groups_passed": True,
        "groups": group_evidence,
        "persisted_tracer_coverage": [
            item.requirement for item in PERSISTED_PRODUCT_TRACER.coverage
        ],
        "identity_ledger": {
            "path": "identity-ledger.json",
            "sha256": _sha256_path(identity_ledger_path),
        },
        "active_feature_registry": active_registry,
        "application_interfaces": [
            "StrategyDiagnosticsV1StrategyLibraryApplication/"
            + STRATEGY_LIBRARY_APPLICATION_INTERFACE_VERSION.render(),
            "StrategyDiagnosticsV1ScenarioLabApplication/"
            + SCENARIO_LAB_APPLICATION_INTERFACE_VERSION.render(),
            "StrategyDiagnosticsV1DiagnosticTasksApplication/"
            + DIAGNOSTIC_TASKS_APPLICATION_INTERFACE_VERSION.render(),
        ],
        "migration_chain": "0001-through-0021",
        "migrations": list(_WAVE3_MIGRATIONS),
        "toolchain_lock": {
            "path": "stock_sim/release/frontend_v2_toolchain.lock.json",
            "sha256": _sha256_path(
                root
                / "stock_sim"
                / "release"
                / "frontend_v2_toolchain.lock.json"
            ),
        },
        "contract_documents": [
            {
                "path": path.as_posix(),
                "sha256": _sha256_path(root / path),
            }
            for path in REQUIRED_CONTRACT_DOCUMENTS
        ],
        "seams": {
            "seam_1_persisted_five_feature_tracer": "passed",
            "seam_2_shared_live_fake_conformance": "passed",
            "seam_3_installed_offline_certification": "pending-issue-88",
        },
        "wave4_started": False,
    }
    summary_path = candidate_root / "source-candidate-summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (candidate_root / "evidence-summary.md").write_text(
        "\n".join(
            (
                "# Wave 3 immutable source candidate evidence",
                "",
                f"Candidate source: `{source_commit}`",
                "",
                "All ten source integration Gate groups passed and are bound",
                "to the JUnit/raw reports and persisted six-Feature identity",
                "ledger in this directory.",
                "",
                "This is source-level evidence only. Issue #88 owns installed",
                "offline Windows certification and the GitHub Release. Wave 4",
                "has not started.",
                "",
            )
        ),
        encoding="utf-8",
    )
    checksum_entries = []
    for path in sorted(
        (
            item
            for item in candidate_root.rglob("*")
            if item.is_file() and item.name != "SHA256SUMS.txt"
        ),
        key=lambda item: item.relative_to(candidate_root).as_posix(),
    ):
        checksum_entries.append(
            _sha256_path(path).removeprefix("sha256:")
            + "  "
            + path.relative_to(candidate_root).as_posix()
        )
    (candidate_root / "SHA256SUMS.txt").write_text(
        "\n".join(checksum_entries) + "\n",
        encoding="utf-8",
    )
    return summary_path


def _verify_candidate_source(
    project_root: Path,
    source_commit: str,
    *,
    allowed_untracked_root: Path | None = None,
) -> None:
    if _SOURCE_COMMIT_PATTERN.fullmatch(source_commit) is None:
        raise ValueError("candidate source must be one full lowercase Git SHA")
    repository_root = Path(
        subprocess.run(
            ("git", "rev-parse", "--show-toplevel"),
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    ).resolve()
    if not project_root.resolve().is_relative_to(repository_root):
        raise ValueError("project root is outside the candidate Git worktree")
    head = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if head != source_commit:
        raise ValueError(
            "candidate source does not match HEAD: "
            f"expected {source_commit}, observed {head}"
        )
    tracked_status = subprocess.run(
        ("git", "status", "--porcelain", "--untracked-files=no"),
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if tracked_status:
        raise ValueError(
            "candidate source evidence requires a clean worktree before capture"
        )
    untracked = subprocess.run(
        ("git", "ls-files", "--others", "--exclude-standard", "-z"),
        cwd=repository_root,
        check=True,
        capture_output=True,
    ).stdout
    untracked_paths = tuple(
        (repository_root / os.fsdecode(item)).resolve()
        for item in untracked.split(b"\0")
        if item
    )
    allowed_root = (
        None
        if allowed_untracked_root is None
        else allowed_untracked_root.resolve()
    )
    if allowed_root is not None and not allowed_root.is_relative_to(
        repository_root
    ):
        raise ValueError(
            "candidate evidence root is outside the candidate Git worktree"
        )
    unexpected = tuple(
        path
        for path in untracked_paths
        if allowed_root is None or not path.is_relative_to(allowed_root)
    )
    if unexpected:
        raise ValueError(
            "candidate source evidence found unexpected untracked files: "
            + ", ".join(str(path) for path in unexpected)
        )


def run_integration_gate(
    project_root: Path,
    *,
    python_executable: str = sys.executable,
    group_names: Sequence[str] = (),
    temporary_parent: Path | None = None,
    evidence_root: Path | None = None,
    source_commit: str | None = None,
) -> tuple[IntegrationGateExecution, ...]:
    """Run the checked-in groups in isolation and stop on the first failure."""

    root = project_root.resolve()
    validation = validate_integration_gate(root)
    if not validation.ok:
        raise RuntimeError("; ".join(validation.errors))
    selected = set(group_names)
    unknown = selected.difference(group.name for group in INTEGRATION_GATE_GROUPS)
    if unknown:
        raise ValueError(f"unknown integration gate groups: {sorted(unknown)!r}")
    if (evidence_root is None) != (source_commit is None):
        raise ValueError(
            "evidence_root and source_commit must be provided together"
        )
    if evidence_root is not None and selected:
        raise ValueError("candidate evidence requires the complete Gate")

    candidate_evidence_root: Path | None = None
    if evidence_root is not None:
        assert source_commit is not None
        _verify_candidate_source(root, source_commit)
        candidate_evidence_root = evidence_root.resolve()
        if candidate_evidence_root.exists() and any(
            candidate_evidence_root.iterdir()
        ):
            raise ValueError(
                "candidate evidence root must be absent or empty before capture"
            )
        candidate_evidence_root.mkdir(parents=True, exist_ok=True)

    environment = os.environ.copy()
    environment.pop("PYTEST_ADDOPTS", None)
    environment.pop("PYTEST_PLUGINS", None)
    environment.pop("STOCKSIM_WAVE3_IDENTITY_LEDGER", None)
    environment.pop("STOCKSIM_WAVE3_CANDIDATE_SOURCE", None)
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    environment.setdefault("QT_QPA_PLATFORM", "offscreen")
    environment.setdefault("QT_QUICK_BACKEND", "software")
    resolved_temporary_parent = _integration_gate_temporary_parent(
        root,
        temporary_parent,
    )
    executions: list[IntegrationGateExecution] = []
    for group_index, group in enumerate(INTEGRATION_GATE_GROUPS, start=1):
        if selected and group.name not in selected:
            continue
        interpreter = _interpreter_command(
            python_executable,
            clean_python=group.clean_python,
        )
        # Native DuckDB Parquet writes still observe the traditional Windows
        # path limit. Keep every pytest and SQLite temporary path beside the
        # checkout instead of under the much deeper user TEMP hierarchy.
        with TemporaryDirectory(
            prefix=f"uti-g{group_index:02d}-",
            dir=resolved_temporary_parent,
        ) as temporary_root:
            group_root = Path(temporary_root).resolve()
            command = (
                *interpreter,
                "-m",
                "pytest",
                *group.pytest_targets,
                *group.pytest_args,
                *(
                    ()
                    if candidate_evidence_root is None
                    else (
                        "--junitxml="
                        + str(
                            candidate_evidence_root
                            / "groups"
                            / group.name
                            / "junit.xml"
                        ),
                    )
                ),
                f"--basetemp={group_root / 'pytest'}",
                "-o",
                "addopts=",
                "-p",
                "no:cacheprovider",
                "-q",
            )
            group_environment = environment.copy()
            if group.fresh_sqlite:
                database_path = group_root / "stock_sim_test.db"
                group_environment["STOCKSIM_DB_URL"] = (
                    f"sqlite:///{database_path.as_posix()}"
                )
            junit_path: Path | None = None
            stdout_path: Path | None = None
            stderr_path: Path | None = None
            completed: (
                subprocess.CompletedProcess[bytes]
                | subprocess.CompletedProcess[str]
            )
            if candidate_evidence_root is None:
                completed = subprocess.run(
                    command,
                    cwd=root,
                    env=group_environment,
                    check=False,
                )
            else:
                assert source_commit is not None
                group_evidence_root = (
                    candidate_evidence_root / "groups" / group.name
                )
                group_evidence_root.mkdir(parents=True, exist_ok=True)
                junit_path = group_evidence_root / "junit.xml"
                stdout_path = group_evidence_root / "stdout.log"
                stderr_path = group_evidence_root / "stderr.log"
                if group.name == "persisted-application-qml-tracer":
                    group_environment["STOCKSIM_WAVE3_IDENTITY_LEDGER"] = str(
                        candidate_evidence_root / "identity-ledger.json"
                    )
                    group_environment["STOCKSIM_WAVE3_CANDIDATE_SOURCE"] = (
                        source_commit
                    )
                with (
                    stdout_path.open("w", encoding="utf-8") as stdout_stream,
                    stderr_path.open("w", encoding="utf-8") as stderr_stream,
                ):
                    completed = subprocess.run(
                        command,
                        cwd=root,
                        env=group_environment,
                        check=False,
                        stdout=stdout_stream,
                        stderr=stderr_stream,
                        text=True,
                    )
        execution = IntegrationGateExecution(
            group=group.name,
            command=command,
            returncode=completed.returncode,
            junit_path=junit_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        executions.append(execution)
        if completed.returncode:
            break
    if candidate_evidence_root is not None and all(
        item.returncode == 0 for item in executions
    ):
        assert source_commit is not None
        _verify_candidate_source(
            root,
            source_commit,
            allowed_untracked_root=candidate_evidence_root,
        )
        write_source_candidate_evidence(
            root,
            evidence_root=candidate_evidence_root,
            source_commit=source_commit,
            executions=executions,
        )
    return tuple(executions)


def _worktree_sibling_temporary_parent(project_root: Path) -> Path:
    for candidate in (project_root, *project_root.parents):
        if (candidate / ".git").exists():
            return candidate.parent
    raise RuntimeError(
        "Cannot place integration-gate temporary files outside the Git "
        f"worktree containing {project_root}"
    )


def _integration_gate_temporary_parent(
    project_root: Path,
    configured: Path | None,
) -> Path:
    if configured is None:
        return _worktree_sibling_temporary_parent(project_root)
    candidate = configured.resolve()
    if not candidate.is_dir():
        raise ValueError(
            "integration-gate temporary parent must be an existing directory: "
            f"{candidate}"
        )
    return candidate


def _interpreter_command(
    python_executable: str,
    *,
    clean_python: bool,
) -> tuple[str, ...]:
    if not clean_python:
        return (python_executable,)
    if os.name == "nt":
        launcher = shutil.which("py")
        if launcher is not None:
            return (launcher, "-3.11")
    return (python_executable,)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate or run the Strategy Diagnostics V1 + Frontend V2 "
            "Wave 3 source integration quality gate."
        )
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
    )
    parser.add_argument(
        "--group",
        action="append",
        default=[],
        dest="groups",
    )
    parser.add_argument(
        "--temporary-parent",
        type=Path,
        help=(
            "Existing short directory in which isolated pytest roots are "
            "created; defaults to the worktree parent."
        ),
    )
    parser.add_argument(
        "--evidence-root",
        type=Path,
        help=(
            "Empty output directory for source-bound JUnit, raw logs, "
            "identity ledger, summary, and checksums. Requires "
            "--source-commit and the complete Gate."
        ),
    )
    parser.add_argument(
        "--source-commit",
        help="Full immutable candidate Git SHA bound to --evidence-root.",
    )
    arguments = parser.parse_args(argv)
    validation = validate_integration_gate(arguments.project_root)
    if not validation.ok:
        for error in validation.errors:
            print(f"ERROR: {error}")
        return 2
    if arguments.validate_only:
        print("Wave 3 source integration gate manifest: valid")
        return 0
    executions = run_integration_gate(
        arguments.project_root,
        group_names=arguments.groups,
        temporary_parent=arguments.temporary_parent,
        evidence_root=arguments.evidence_root,
        source_commit=arguments.source_commit,
    )
    for execution in executions:
        print(f"{execution.group}: exit {execution.returncode}")
    return 0 if executions and executions[-1].returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "INTEGRATION_GATE_GROUPS",
    "PERSISTED_PRODUCT_TRACER",
    "REQUIRED_CONTRACT_DOCUMENTS",
    "REQUIRED_CONTRACT_MARKERS",
    "IntegrationGateExecution",
    "IntegrationGateGroup",
    "IntegrationGateValidation",
    "PersistedProductTracer",
    "main",
    "run_integration_gate",
    "validate_integration_gate",
    "write_source_candidate_evidence",
]
