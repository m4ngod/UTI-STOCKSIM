from __future__ import annotations

import inspect
import subprocess
from collections import deque
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TypeVar, get_args, get_origin, get_type_hints

from app.features import EvidenceAndFindingsFeature, RunMonitoringFeature
from stock_sim.release.strategy_diagnostics_v1_frontend_v2_gate import (
    INTEGRATION_GATE_GROUPS,
    REQUIRED_CONTRACT_DOCUMENTS,
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


def test_only_the_two_wave_1_feature_interfaces_have_clean_public_type_graphs():
    public_graph = _transitive_interface_graph(
        RunMonitoringFeature,
        EvidenceAndFindingsFeature,
    )

    assert Any not in public_graph
    assert dict not in public_graph
    assert Mapping not in public_graph
    for public_type in public_graph:
        module = getattr(public_type, "__module__", "")
        name = getattr(public_type, "__name__", "")
        assert not module.startswith(
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
        )
        assert name != "EventBridge"
        assert "Repository" not in name


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
    assert {
        Path(
            "docs/contracts/integration/strategy-diagnostics-v1-frontend-v2-contract.md"
        ),
        Path("docs/testing/integration/strategy-diagnostics-v1-frontend-v2-runbook.md"),
    } == set(REQUIRED_CONTRACT_DOCUMENTS)


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
    environment = captured["env"]
    assert isinstance(environment, dict)
    assert "PYTEST_ADDOPTS" not in environment
    assert "PYTEST_PLUGINS" not in environment
    assert environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
