from __future__ import annotations

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

from app.features import (
    DiagnosticTasksFeature,
    EvidenceAndFindingsFeature,
    RunMonitoringFeature,
    StrategyLibraryFeature,
    StrategyDiagnosticsV1DiagnosticTasksApplication,
)
from app.features.strategy_library_application import (
    StrategyDiagnosticsV1StrategyLibraryApplication,
)
from stock_sim.release.strategy_diagnostics_v1_frontend_v2_gate import (
    INTEGRATION_GATE_GROUPS,
    PERSISTED_PRODUCT_TRACER,
    REQUIRED_CONTRACT_DOCUMENTS,
    REQUIRED_CONTRACT_MARKERS,
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


def test_all_four_active_features_and_application_interfaces_have_clean_public_type_graphs():
    public_graph = _transitive_interface_graph(
        DiagnosticTasksFeature,
        RunMonitoringFeature,
        EvidenceAndFindingsFeature,
        StrategyLibraryFeature,
        StrategyDiagnosticsV1DiagnosticTasksApplication,
        StrategyDiagnosticsV1StrategyLibraryApplication,
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
        "authoritative-input-and-exact-revision",
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
        "LiveDiagnosticTasksAdapter",
        "LiveRunMonitoringAdapter",
        "LiveEvidenceAndFindingsAdapter",
        "LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter",
        "JourneyWorkspaceHost",
        "create_diagnostics_application",
        "create_engine",
        "engine.dispose()",
        "restarted_engine",
    } <= set(PERSISTED_PRODUCT_TRACER.required_markers)
    assert {
        "DeterministicFakeDiagnosticTasksAdapter",
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
