"""Wave 3 Strategy Diagnostics V1 + Frontend V2 source integration gate.

This gate is deliberately not a release-certification claim.  It keeps the
shared conformance, persisted tracer, backend regression, and existing
Frontend V2 gates executable from one fail-closed manifest.  Issue #88 owns
the Wave 3 installed-offline release certification, evidence, and artifacts.
"""

from __future__ import annotations

import argparse
import ast
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from app.features import (
    ACTIVE_FEATURE_INTERFACES,
    DIAGNOSTIC_TASKS_APPLICATION_INTERFACE_VERSION,
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
        "LiveDiagnosticTasksAdapter",
        "LiveRunMonitoringAdapter",
        "LiveEvidenceAndFindingsAdapter",
        "LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter",
        "JourneyWorkspaceHost",
        "create_diagnostics_application",
        "create_engine",
        "engine.dispose()",
        "restarted_engine",
        "durable_identity_graph",
        "expected_durable_identity_graph",
    ),
    forbidden_markers=(
        "DeterministicFakeDiagnosticTasksAdapter",
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
        "`DiagnosticTasksFeature` version 1.0",
        "`RunMonitoringFeature` version 1.2",
        "`EvidenceAndFindingsFeature` version 1.1",
        "`StrategyDiagnosticsV1DiagnosticTasksApplication` version 1.0",
        "`StrategyDiagnosticsV1StrategyLibraryApplication` version 1.0",
        "Issues #77 and #78 activate Strategy Library browse",
        "durable bookmark contains those immutable references",
        "Seam 1",
        "Seam 2",
        "Seam 3",
        "Wave 4 remain unimplemented",
        "Issue #88 owns Wave 3 installed offline release certification",
    ),
    REQUIRED_CONTRACT_DOCUMENTS[1]: (
        "# Strategy Diagnostics V1 + Frontend V2 Wave 3 integration runbook",
        "`StrategyLibraryFeature` 1.0",
        "`DiagnosticTasksFeature` 1.0",
        "`RunMonitoringFeature` 1.2",
        "`EvidenceAndFindingsFeature` 1.1",
        "`StrategyDiagnosticsV1DiagnosticTasksApplication` 1.0",
        "`StrategyDiagnosticsV1StrategyLibraryApplication` 1.0",
        "including Issues #77 and #78",
        "durable bookmark reread",
        PERSISTED_PRODUCT_TRACER.function_name,
        "test_diagnostic_tasks_live_fake_conformance.py",
        "test_strategy_library_live_fake_conformance.py",
        "Seam 3",
        "Issue #88",
        "does not claim T08, T09, or T10",
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
        "DiagnosticTasksFeature",
        "RunMonitoringFeature",
        "EvidenceAndFindingsFeature",
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
    expected_tracer_requirements = (
        "authoritative-strategy-library-slice",
        "authoritative-input-and-exact-revision",
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


def run_integration_gate(
    project_root: Path,
    *,
    python_executable: str = sys.executable,
    group_names: Sequence[str] = (),
    temporary_parent: Path | None = None,
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

    environment = os.environ.copy()
    environment.pop("PYTEST_ADDOPTS", None)
    environment.pop("PYTEST_PLUGINS", None)
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
            completed = subprocess.run(
                command,
                cwd=root,
                env=group_environment,
                check=False,
            )
        execution = IntegrationGateExecution(
            group=group.name,
            command=command,
            returncode=completed.returncode,
        )
        executions.append(execution)
        if completed.returncode:
            break
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
]
