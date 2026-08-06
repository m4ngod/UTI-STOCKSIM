from __future__ import annotations

import json
import inspect
import subprocess
from array import array
from collections import deque
from collections.abc import (
    Mapping,
    MutableMapping,
    MutableSequence,
    MutableSet,
)
from pathlib import Path
from typing import Any, TypeVar, get_args, get_origin, get_type_hints

import pytest

import stock_sim.release.strategy_diagnostics_v1_frontend_v2_gate as gate_module

from app.features import (
    DiagnosticTasksFeature,
    EvidenceAndFindingsFeature,
    RunMonitoringFeature,
    ScenarioLabFeature,
    StrategyLibraryFeature,
    StrategyDiagnosticsV1DiagnosticTasksApplication,
)
from app.features.strategy_library_application import (
    StrategyDiagnosticsV1StrategyLibraryApplication,
)
from app.features.scenario_lab_application import (
    StrategyDiagnosticsV1ScenarioLabApplication,
)
from stock_sim.release.strategy_diagnostics_v1_frontend_v2_gate import (
    INTEGRATION_GATE_GROUPS,
    PERSISTED_PRODUCT_TRACER,
    REQUIRED_CONTRACT_DOCUMENTS,
    REQUIRED_CONTRACT_MARKERS,
    IntegrationGateExecution,
    run_integration_gate,
    validate_integration_gate,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _transitive_interface_graph(*interfaces: type[object]) -> set[object]:
    pending: deque[object] = deque()
    for interface in interfaces:
        for name, member in inspect.getmembers(interface):
            if name.startswith("_"):
                continue
            if isinstance(member, property) and member.fget is not None:
                pending.extend(get_type_hints(member.fget).values())
            elif inspect.isfunction(member):
                pending.extend(get_type_hints(member).values())

    visited: set[object] = set()
    while pending:
        public_type = pending.popleft()
        try:
            hash(public_type)
        except TypeError:
            if isinstance(public_type, (list, tuple, set, frozenset)):
                pending.extend(public_type)
                continue
            raise
        if public_type in visited:
            continue
        visited.add(public_type)
        origin = get_origin(public_type)
        if origin is not None:
            pending.append(origin)
            pending.extend(get_args(public_type))
            continue
        if isinstance(public_type, TypeVar):
            if public_type.__bound__ is not None:
                pending.append(public_type.__bound__)
            pending.extend(public_type.__constraints__)
            continue
        if inspect.isclass(public_type) and getattr(
            public_type, "__module__", ""
        ).startswith("app.features"):
            pending.extend(get_type_hints(public_type).values())
    return visited


def _public_type_graph_violations(
    public_graph: set[object],
) -> tuple[str, ...]:
    violations: list[str] = []
    mutable_concrete_types = {
        list,
        set,
        dict,
        bytearray,
        deque,
        array,
    }
    mutable_abstract_types = (
        MutableMapping,
        MutableSequence,
        MutableSet,
    )
    for public_type in public_graph:
        candidate = get_origin(public_type) or public_type
        if candidate is Any:
            violations.append("Any")
            continue
        if candidate is Mapping:
            violations.append("Mapping")
            continue
        if candidate in mutable_concrete_types:
            violations.append(getattr(candidate, "__name__", repr(candidate)))
            continue
        if inspect.isclass(candidate) and any(
            issubclass(candidate, mutable_family)
            for mutable_family in mutable_abstract_types
        ):
            violations.append(
                f"mutable collection {candidate.__module__}.{candidate.__name__}"
            )
            continue
        module = getattr(candidate, "__module__", "")
        name = getattr(candidate, "__name__", "")
        if module.startswith(
            (
                "strategy_diagnostics",
                "sqlalchemy",
                "PySide6",
                "_thread",
                "asyncio",
                "concurrent",
                "multiprocessing",
                "queue",
                "threading",
            )
        ):
            violations.append(f"forbidden module {module}.{name}")
        if name in {"EventBridge", "RuntimeGateway"}:
            violations.append(name)
        if any(
            marker in name
            for marker in ("Repository", "Database", "ArtifactStore")
        ):
            violations.append(name)
    return tuple(violations)


def test_all_five_active_features_and_application_interfaces_have_clean_public_type_graphs():
    public_graph = _transitive_interface_graph(
        DiagnosticTasksFeature,
        RunMonitoringFeature,
        EvidenceAndFindingsFeature,
        StrategyLibraryFeature,
        ScenarioLabFeature,
        StrategyDiagnosticsV1DiagnosticTasksApplication,
        StrategyDiagnosticsV1StrategyLibraryApplication,
        StrategyDiagnosticsV1ScenarioLabApplication,
    )

    assert _public_type_graph_violations(public_graph) == ()


@pytest.mark.parametrize(
    "forbidden_type",
    (
        list[str],
        set[str],
        dict[str, str],
        bytearray,
        deque[str],
        array,
        MutableMapping[str, str],
        MutableSequence[str],
        MutableSet[str],
    ),
)
def test_public_type_graph_guard_rejects_every_mutable_collection_family(
    forbidden_type: object,
) -> None:
    assert _public_type_graph_violations({forbidden_type})


def test_integration_gate_is_complete_and_repository_valid():
    report = validate_integration_gate(PROJECT_ROOT)

    assert report.ok, report.errors
    assert tuple(group.name for group in INTEGRATION_GATE_GROUPS) == (
        "shared-feature-conformance",
        "persisted-application-qml-tracer",
        "strategy-diagnostics-v1-regression",
        "strategy-diagnostics-v1-lazy-import-isolation",
        "frontend-v2-contract",
        "frontend-v2-integration-e2e-accessibility",
        "frontend-v2-unit",
        "frontend-v2-event-bridge",
        "frontend-v2-safety",
        "frontend-v2-performance-packaging-contract",
    )
    assert all(group.pytest_targets for group in INTEGRATION_GATE_GROUPS)
    groups = {group.name: group for group in INTEGRATION_GATE_GROUPS}
    assert groups["strategy-diagnostics-v1-lazy-import-isolation"].clean_python
    assert groups["frontend-v2-unit"].fresh_sqlite
    assert groups["frontend-v2-event-bridge"].fresh_sqlite
    assert (
        groups["persisted-application-qml-tracer"].pytest_targets
        == PERSISTED_PRODUCT_TRACER.pytest_targets
    )
    assert (
        f"--deselect={PERSISTED_PRODUCT_TRACER.pytest_target}"
        in groups["frontend-v2-integration-e2e-accessibility"].pytest_args
    )
    assert all(
        f"--ignore={target}" in groups["frontend-v2-contract"].pytest_args
        for target in groups["shared-feature-conformance"].pytest_targets[:-1]
    )
    assert {
        Path(
            "docs/contracts/integration/strategy-diagnostics-v1-frontend-v2-contract.md"
        ),
        Path("docs/testing/integration/strategy-diagnostics-v1-frontend-v2-runbook.md"),
    } == set(REQUIRED_CONTRACT_DOCUMENTS)
    assert set(REQUIRED_CONTRACT_MARKERS) == set(REQUIRED_CONTRACT_DOCUMENTS)
    assert tuple(
        category.requirement
        for category in PERSISTED_PRODUCT_TRACER.coverage
    ) == (
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
    assert all(
        category.pytest_targets
        for category in PERSISTED_PRODUCT_TRACER.coverage
    )
    assert len(PERSISTED_PRODUCT_TRACER.pytest_targets) == len(
        set(PERSISTED_PRODUCT_TRACER.pytest_targets)
    )


def test_wave2_gate_freezes_the_complete_product_tracer_and_contract_language():
    assert PERSISTED_PRODUCT_TRACER.source_path == Path(
        "tests/frontend/integration/test_diagnostic_tasks_workspace_route.py"
    )
    assert PERSISTED_PRODUCT_TRACER.function_name == (
        "test_live_qml_tracer_recovers_retries_and_reopens_exact_evidence"
    )
    assert {
        "LiveStrategyLibraryAdapter",
        "LiveScenarioLabAdapter",
        "LiveDiagnosticTasksAdapter",
        "LiveRunMonitoringAdapter",
        "LiveEvidenceAndFindingsAdapter",
        "LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter",
        "LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter",
        "LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter",
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
    } <= set(PERSISTED_PRODUCT_TRACER.required_markers)
    assert {
        "DeterministicFakeStrategyLibraryAdapter",
        "DeterministicFakeScenarioLabAdapter",
        "DeterministicFakeDiagnosticTasksAdapter",
        "DeterministicFakeRunMonitoringAdapter",
        "DeterministicFakeEvidenceAndFindingsAdapter",
        "DictionaryFixtureApplicationReadModel",
        "_LiveJourneyQueries",
        "Repository",
        "session.execute",
    } <= set(PERSISTED_PRODUCT_TRACER.forbidden_markers)

    for document, markers in REQUIRED_CONTRACT_MARKERS.items():
        source = (PROJECT_ROOT / document).read_text(encoding="utf-8")
        assert all(marker in source for marker in markers)


def test_persisted_journey_certification_has_no_synthetic_dictionary_producer():
    sources = (
        (
            PROJECT_ROOT
            / "tests"
            / "frontend"
            / "integration"
            / "test_live_run_to_evidence_journey.py"
        ),
        (
            PROJECT_ROOT
            / "tests"
            / "frontend"
            / "contract"
            / "test_strategy_diagnostics_v1_evidence_and_findings_live_contract.py"
        ),
        (
            PROJECT_ROOT
            / "tests"
            / "frontend"
            / "unit"
            / "test_diagnostics_panel.py"
        ),
    )

    for source_path in sources:
        source = source_path.read_text(encoding="utf-8")
        for forbidden in (
            "DictionaryFixtureApplicationReadModel",
            "_LiveJourneyQueries",
            "get_run_monitoring_snapshot",
            "get_evidence_and_findings_snapshot",
        ):
            assert forbidden not in source


def test_gate_neutralizes_external_pytest_configuration(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def _completed(command, *, cwd, env, check):
        captured.update(command=command, cwd=cwd, env=env, check=check)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setenv("PYTEST_ADDOPTS", "--maxfail=1 -k hostile-selection")
    monkeypatch.setenv("PYTEST_PLUGINS", "hostile_external_plugin")
    monkeypatch.setenv(
        "STOCKSIM_WAVE3_IDENTITY_LEDGER",
        "hostile-external-ledger.json",
    )
    monkeypatch.setenv("STOCKSIM_WAVE3_CANDIDATE_SOURCE", "0" * 40)
    monkeypatch.delenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", raising=False)
    monkeypatch.setattr(subprocess, "run", _completed)

    executions = run_integration_gate(
        PROJECT_ROOT,
        group_names=("frontend-v2-event-bridge",),
    )

    assert len(executions) == 1
    command = captured["command"]
    assert isinstance(command, tuple)
    assert ("-o", "addopts=") == command[command.index("-o") : command.index("-o") + 2]
    assert ("-p", "no:cacheprovider") == command[
        command.index("-p") : command.index("-p") + 2
    ]
    basetemp_arguments = tuple(
        argument
        for argument in command
        if isinstance(argument, str)
        and argument.startswith("--basetemp=")
    )
    assert len(basetemp_arguments) == 1
    basetemp = Path(basetemp_arguments[0].split("=", maxsplit=1)[1])
    assert basetemp.parent.parent == PROJECT_ROOT.parent.parent
    environment = captured["env"]
    assert isinstance(environment, dict)
    assert "PYTEST_ADDOPTS" not in environment
    assert "PYTEST_PLUGINS" not in environment
    assert "STOCKSIM_WAVE3_IDENTITY_LEDGER" not in environment
    assert "STOCKSIM_WAVE3_CANDIDATE_SOURCE" not in environment
    assert environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"


def test_gate_uses_explicit_existing_short_temporary_parent(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    temporary_parent = tmp_path / "short-gate-temp"
    temporary_parent.mkdir()

    def _completed(command, *, cwd, env, check):
        captured.update(command=command, cwd=cwd, env=env, check=check)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", _completed)

    executions = run_integration_gate(
        PROJECT_ROOT,
        group_names=("frontend-v2-event-bridge",),
        temporary_parent=temporary_parent,
    )

    assert len(executions) == 1
    command = captured["command"]
    assert isinstance(command, tuple)
    basetemp_argument = next(
        argument
        for argument in command
        if isinstance(argument, str) and argument.startswith("--basetemp=")
    )
    basetemp = Path(basetemp_argument.split("=", maxsplit=1)[1])
    assert basetemp.parent.parent == temporary_parent.resolve()


def test_gate_rejects_missing_explicit_temporary_parent(tmp_path: Path) -> None:
    missing_parent = tmp_path / "missing-gate-temp"

    with pytest.raises(ValueError, match="temporary parent must be an existing"):
        run_integration_gate(
            PROJECT_ROOT,
            group_names=("frontend-v2-event-bridge",),
            temporary_parent=missing_parent,
        )


def _complete_identity_ledger(source_commit: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "candidate_source": source_commit,
        "feature_interfaces": [
            "StrategyLibraryFeature/1.0",
            "ScenarioLabFeature/1.0",
            "DiagnosticTasksFeature/1.0",
            "RunMonitoringFeature/1.2",
            "EvidenceAndFindingsFeature/1.1",
            "SystemHealthFeature/1.0",
        ],
        "strategy_library": {
            "selection_context_id": "strategy-selection-1",
            "entries": [
                ["strategy-1", "1", "manifest-1", "guardrail-1", "1"],
                ["strategy-2", "1", "manifest-2", "guardrail-2", "1"],
            ],
        },
        "scenario_lab": {
            "historical_segment": {
                "segmentId": "segment-1",
                "contentHash": "segment-hash-1",
                "sourceSnapshotId": "snapshot-1",
            },
            "recipe_draft": {
                "draftId": "draft-1",
                "payloadHash": "draft-hash-1",
            },
            "recipe_validation": {
                "validationId": "validation-1",
                "draftId": "draft-1",
                "recipeContentHash": "recipe-hash-1",
            },
            "approved_recipe": {
                "recipeVersionId": "recipe-version-1",
                "approvalId": "recipe-approval-1",
                "contentHash": "recipe-hash-1",
            },
            "materialization_task_handle": {
                "taskHandleId": "materialization-handle-1",
                "attemptId": "materialization-attempt-1",
                "resultIdentity": "market-path-1",
            },
            "materialized_case": {
                "scenarioId": "case-1",
                "pathId": "market-path-1",
                "recipeVersionId": "recipe-version-1",
            },
            "formal_scenario_set": {
                "scenarioSetId": "scenario-set-1",
                "caseIds": ["case-1"],
            },
            "execution_resolution": {
                "resolutionId": "resolution-1",
                "targets": ["target-1"],
            },
            "selection_context": {
                "selectionContextId": "scenario-selection-1",
                "executionResolutionId": "resolution-1",
            },
        },
        "diagnostic_tasks": {
            "setup_context_id": "setup-1",
            "task_id": "task-1",
            "configuration_content_id": "configuration-1",
            "validation_id": "task-validation-1",
            "approval_id": "task-approval-1",
            "task_handle_ids": ["task-handle-1"],
        },
        "campaign": {
            "campaign_id": "campaign-1",
            "node_ids": ["node-1"],
            "attempt_ids": ["attempt-1"],
            "run_ids": ["run-1"],
            "requested_effective_override": {
                "requested": {"slippage_bps": "100"},
                "effective": {"slippage_bps": "20"},
                "resolutions": [{"override_reason": "strategy-cap"}],
            },
        },
        "evidence_and_findings": {
            "evidence_package_id": "evidence-package-1",
            "evidence_record_ids": ["evidence-record-1"],
            "finding_ids": ["finding-1"],
            "breakpoint_ids": ["breakpoint-1"],
            "breakpoint_finding_edges": [
                ["finding-1", "breakpoint-1"]
            ],
            "reproduction_manifest_id": "reproduction-manifest-1",
        },
        "recovery": {
            "remount_preserved_exact_identities": True,
            "application_reopen_preserved_exact_identities": True,
            "market_path_store_reopened_from_files": True,
            "old_generation_quarantined": True,
            "durable_identity_graph": ["strategy-1", "run-1"],
        },
    }


def test_full_green_gate_writes_one_source_bound_candidate_evidence_set(
    tmp_path: Path,
) -> None:
    evidence_root = tmp_path / "candidate-evidence"
    evidence_root.mkdir()
    source_commit = "a" * 40
    identity_ledger_path = evidence_root / "identity-ledger.json"
    identity_ledger_path.write_text(
        json.dumps({"candidate_source": source_commit}),
        encoding="utf-8",
    )
    executions = []
    for group in INTEGRATION_GATE_GROUPS:
        group_root = evidence_root / "groups" / group.name
        group_root.mkdir(parents=True)
        junit_path = group_root / "junit.xml"
        stdout_path = group_root / "stdout.log"
        stderr_path = group_root / "stderr.log"
        junit_path.write_text(
            '<testsuite tests="1" failures="0" errors="0" skipped="0" />',
            encoding="utf-8",
        )
        stdout_path.write_text("one passing test\n", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        executions.append(
            IntegrationGateExecution(
                group=group.name,
                command=("python", "-m", "pytest", group.name),
                returncode=0,
                junit_path=junit_path,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )
        )

    with pytest.raises(ValueError, match="schema_version"):
        gate_module.write_source_candidate_evidence(
            PROJECT_ROOT,
            evidence_root=evidence_root,
            source_commit=source_commit,
            executions=executions,
        )

    incomplete_ledger = _complete_identity_ledger(source_commit)
    del incomplete_ledger["evidence_and_findings"][
        "breakpoint_finding_edges"
    ]
    identity_ledger_path.write_text(
        json.dumps(incomplete_ledger),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="breakpoint_finding_edges"):
        gate_module.write_source_candidate_evidence(
            PROJECT_ROOT,
            evidence_root=evidence_root,
            source_commit=source_commit,
            executions=executions,
        )

    identity_ledger_path.write_text(
        json.dumps(_complete_identity_ledger(source_commit)),
        encoding="utf-8",
    )
    summary_path = gate_module.write_source_candidate_evidence(
        PROJECT_ROOT,
        evidence_root=evidence_root,
        source_commit=source_commit,
        executions=executions,
    )

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["schema_version"] == 1
    assert summary["candidate_source"] == source_commit
    assert summary["candidate_kind"] == "immutable-wave3-source"
    assert summary["release_claim"] is False
    assert summary["all_groups_passed"] is True
    assert [item["name"] for item in summary["groups"]] == [
        item.name for item in INTEGRATION_GATE_GROUPS
    ]
    assert summary["active_feature_registry"] == [
        "StrategyLibraryFeature/1.0",
        "ScenarioLabFeature/1.0",
        "DiagnosticTasksFeature/1.0",
        "RunMonitoringFeature/1.2",
        "EvidenceAndFindingsFeature/1.1",
        "SystemHealthFeature/1.0",
    ]
    assert summary["application_interfaces"] == [
        "StrategyDiagnosticsV1StrategyLibraryApplication/1.0",
        "StrategyDiagnosticsV1ScenarioLabApplication/1.0",
        "StrategyDiagnosticsV1DiagnosticTasksApplication/1.0",
    ]
    assert summary["migrations"][-3:] == [
        "0019_scenario_recipe_dependency_bindings",
        "0020_scenario_lab_commands_and_materialization_handles",
        "0021_diagnostic_selection_dependency_invalidation",
    ]
    assert summary["seams"] == {
        "seam_1_persisted_five_feature_tracer": "passed",
        "seam_2_shared_live_fake_conformance": "passed",
        "seam_3_installed_offline_certification": "pending-issue-88",
    }
    assert summary["wave4_started"] is False
    assert (evidence_root / "evidence-summary.md").is_file()
    checksums = (evidence_root / "SHA256SUMS.txt").read_text(
        encoding="utf-8"
    )
    assert "source-candidate-summary.json" in checksums
    assert "identity-ledger.json" in checksums


def test_evidence_mode_captures_junit_raw_logs_and_tracer_ledger(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_commit = "b" * 40
    evidence_root = tmp_path / "evidence"
    group = gate_module.IntegrationGateGroup(
        "persisted-application-qml-tracer",
        ("tests/example.py",),
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(gate_module, "INTEGRATION_GATE_GROUPS", (group,))
    monkeypatch.setattr(
        gate_module,
        "validate_integration_gate",
        lambda _root: gate_module.IntegrationGateValidation(True, ()),
    )
    candidate_verifications: list[tuple[str, Path | None]] = []

    def _verify(_root, candidate, *, allowed_untracked_root=None):
        candidate_verifications.append((candidate, allowed_untracked_root))

    monkeypatch.setattr(gate_module, "_verify_candidate_source", _verify)

    def _completed(
        command,
        *,
        cwd,
        env,
        check,
        stdout,
        stderr,
        text,
    ):
        junit_argument = next(
            item for item in command if item.startswith("--junitxml=")
        )
        Path(junit_argument.split("=", maxsplit=1)[1]).write_text(
            '<testsuite tests="1" failures="0" errors="0" skipped="0" />',
            encoding="utf-8",
        )
        stdout.write("passed\n")
        stderr.write("")
        ledger_path = Path(env["STOCKSIM_WAVE3_IDENTITY_LEDGER"])
        ledger_path.write_text(
            json.dumps({"candidate_source": source_commit}),
            encoding="utf-8",
        )
        captured.update(command=command, env=env, text=text)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", _completed)

    def _write(_root, *, evidence_root, source_commit, executions):
        captured.update(
            evidence_root=evidence_root,
            source_commit=source_commit,
            executions=executions,
        )
        return evidence_root / "source-candidate-summary.json"

    monkeypatch.setattr(gate_module, "write_source_candidate_evidence", _write)

    executions = run_integration_gate(
        PROJECT_ROOT,
        temporary_parent=tmp_path,
        evidence_root=evidence_root,
        source_commit=source_commit,
    )

    assert candidate_verifications == [
        (source_commit, None),
        (source_commit, evidence_root.resolve()),
    ]
    assert captured["source_commit"] == source_commit
    assert captured["evidence_root"] == evidence_root.resolve()
    assert captured["text"] is True
    command = captured["command"]
    assert any(item.startswith("--junitxml=") for item in command)
    environment = captured["env"]
    assert environment["STOCKSIM_WAVE3_CANDIDATE_SOURCE"] == source_commit
    assert environment["STOCKSIM_WAVE3_IDENTITY_LEDGER"] == str(
        evidence_root.resolve() / "identity-ledger.json"
    )
    assert executions[0].junit_path is not None
    assert executions[0].stdout_path is not None
    assert executions[0].stderr_path is not None


def test_evidence_mode_rejects_source_drift_before_sealing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_commit = "e" * 40
    evidence_root = tmp_path / "evidence"
    group = gate_module.IntegrationGateGroup(
        "persisted-application-qml-tracer",
        ("tests/example.py",),
    )
    verification_count = 0
    sealed = False

    monkeypatch.setattr(gate_module, "INTEGRATION_GATE_GROUPS", (group,))
    monkeypatch.setattr(
        gate_module,
        "validate_integration_gate",
        lambda _root: gate_module.IntegrationGateValidation(True, ()),
    )

    def _verify(_root, _candidate, *, allowed_untracked_root=None):
        nonlocal verification_count
        verification_count += 1
        if allowed_untracked_root is not None:
            raise ValueError("candidate source changed while Gate was running")

    def _completed(
        command,
        *,
        cwd,
        env,
        check,
        stdout,
        stderr,
        text,
    ):
        junit_argument = next(
            item for item in command if item.startswith("--junitxml=")
        )
        Path(junit_argument.split("=", maxsplit=1)[1]).write_text(
            '<testsuite tests="1" failures="0" errors="0" skipped="0" />',
            encoding="utf-8",
        )
        stdout.write("passed\n")
        stderr.write("")
        return subprocess.CompletedProcess(command, 0)

    def _write(*args, **kwargs):
        nonlocal sealed
        sealed = True
        raise AssertionError("drifted source must not be sealed")

    monkeypatch.setattr(gate_module, "_verify_candidate_source", _verify)
    monkeypatch.setattr(subprocess, "run", _completed)
    monkeypatch.setattr(gate_module, "write_source_candidate_evidence", _write)

    with pytest.raises(ValueError, match="changed while Gate was running"):
        run_integration_gate(
            PROJECT_ROOT,
            temporary_parent=tmp_path,
            evidence_root=evidence_root,
            source_commit=source_commit,
        )

    assert verification_count == 2
    assert sealed is False


def test_candidate_source_verification_scans_the_git_toplevel(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    project_root = repository_root / "stock_sim"
    project_root.mkdir(parents=True)
    (project_root / "tracked.txt").write_text(
        "candidate source\n",
        encoding="utf-8",
    )
    for command in (
        ("git", "init", "--initial-branch=master"),
        ("git", "config", "user.email", "wave3@example.invalid"),
        ("git", "config", "user.name", "Wave 3 Gate"),
        ("git", "add", "."),
        ("git", "commit", "-m", "candidate"),
    ):
        subprocess.run(
            command,
            cwd=repository_root,
            check=True,
            capture_output=True,
        )
    source_commit = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    evidence_root = project_root / "docs" / "evidence" / source_commit
    evidence_root.mkdir(parents=True)
    (evidence_root / "junit.xml").write_text(
        "<testsuite />\n",
        encoding="utf-8",
    )

    gate_module._verify_candidate_source(
        project_root,
        source_commit,
        allowed_untracked_root=evidence_root,
    )

    sibling_untracked = repository_root / "Quent" / "untracked.txt"
    sibling_untracked.parent.mkdir()
    sibling_untracked.write_text("must be rejected\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected untracked files"):
        gate_module._verify_candidate_source(
            project_root,
            source_commit,
            allowed_untracked_root=evidence_root,
        )


def test_evidence_mode_requires_a_full_source_sha_and_complete_gate(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="provided together"):
        run_integration_gate(
            PROJECT_ROOT,
            temporary_parent=tmp_path,
            evidence_root=tmp_path / "evidence",
        )
    with pytest.raises(ValueError, match="complete Gate"):
        run_integration_gate(
            PROJECT_ROOT,
            temporary_parent=tmp_path,
            group_names=("frontend-v2-event-bridge",),
            evidence_root=tmp_path / "evidence",
            source_commit="c" * 40,
        )


def test_cli_routes_candidate_source_and_evidence_root_to_the_gate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    source_commit = "d" * 40
    evidence_root = tmp_path / "evidence"
    monkeypatch.setattr(
        gate_module,
        "validate_integration_gate",
        lambda _root: gate_module.IntegrationGateValidation(True, ()),
    )

    def _run(project_root, **kwargs):
        captured.update(project_root=project_root, **kwargs)
        return (
            gate_module.IntegrationGateExecution(
                group="complete",
                command=("pytest",),
                returncode=0,
            ),
        )

    monkeypatch.setattr(gate_module, "run_integration_gate", _run)

    assert gate_module.main(
        (
            "--project-root",
            str(PROJECT_ROOT),
            "--temporary-parent",
            str(tmp_path),
            "--evidence-root",
            str(evidence_root),
            "--source-commit",
            source_commit,
        )
    ) == 0
    assert captured["evidence_root"] == evidence_root
    assert captured["source_commit"] == source_commit
