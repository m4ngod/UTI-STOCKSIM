"""Wave 1 Strategy Diagnostics V1 + Frontend V2 integration quality gate.

This gate is deliberately not a release-certification claim.  It keeps the
shared conformance, persisted tracer, backend regression, and existing
Frontend V2 gates executable from one fail-closed manifest.  Issue #53 owns
the separate release-certification evidence and artifacts.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from app.features import ACTIVE_FEATURE_INTERFACES


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


INTEGRATION_GATE_GROUPS: tuple[IntegrationGateGroup, ...] = (
    IntegrationGateGroup(
        "shared-feature-conformance",
        (
            (
                "tests/frontend/contract/"
                "test_strategy_diagnostics_v1_feature_pair_conformance.py"
            ),
            (
                "tests/frontend/contract/"
                "test_strategy_diagnostics_v1_frontend_v2_integration_gate.py"
            ),
        ),
    ),
    IntegrationGateGroup(
        "persisted-application-qml-tracer",
        ("tests/frontend/integration/test_live_run_to_evidence_journey.py",),
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
                "test_strategy_diagnostics_v1_feature_pair_conformance.py"
            ),
            (
                "--ignore=tests/frontend/contract/"
                "test_strategy_diagnostics_v1_frontend_v2_integration_gate.py"
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
            "--ignore=tests/frontend/integration/test_live_run_to_evidence_journey.py",
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

_CERTIFICATION_TRACER_SOURCES: tuple[Path, ...] = (
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

    names = tuple(group.name for group in INTEGRATION_GATE_GROUPS)
    if len(names) != len(set(names)):
        errors.append("integration gate group names must be unique")
    for group in INTEGRATION_GATE_GROUPS:
        if not group.pytest_targets:
            errors.append(f"{group.name}: no pytest targets")
        for target in group.pytest_targets:
            target_path = root / target.split("::", maxsplit=1)[0]
            if not target_path.exists():
                errors.append(f"{group.name}: missing target {target}")

    for document in REQUIRED_CONTRACT_DOCUMENTS:
        if not (root / document).is_file():
            errors.append(f"missing required contract document {document}")

    for tracer_source_path in _CERTIFICATION_TRACER_SOURCES:
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


def run_integration_gate(
    project_root: Path,
    *,
    python_executable: str = sys.executable,
    group_names: Sequence[str] = (),
) -> tuple[IntegrationGateExecution, ...]:
    """Run the checked-in groups in isolation and stop on the first failure."""

    validation = validate_integration_gate(project_root)
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
    executions: list[IntegrationGateExecution] = []
    for group in INTEGRATION_GATE_GROUPS:
        if selected and group.name not in selected:
            continue
        interpreter = _interpreter_command(
            python_executable,
            clean_python=group.clean_python,
        )
        command = (
            *interpreter,
            "-m",
            "pytest",
            *group.pytest_targets,
            *group.pytest_args,
            "-o",
            "addopts=",
            "-p",
            "no:cacheprovider",
            "-q",
        )
        temporary_database = (
            TemporaryDirectory(prefix="stocksim-integration-gate-")
            if group.fresh_sqlite
            else nullcontext(None)
        )
        with temporary_database as database_root:
            group_environment = environment.copy()
            if database_root is not None:
                database_path = Path(database_root).resolve() / "stock_sim_test.db"
                group_environment["STOCKSIM_DB_URL"] = (
                    f"sqlite:///{database_path.as_posix()}"
                )
            completed = subprocess.run(
                command,
                cwd=project_root,
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
            "Wave 1 integration quality gate."
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
    arguments = parser.parse_args(argv)
    validation = validate_integration_gate(arguments.project_root)
    if not validation.ok:
        for error in validation.errors:
            print(f"ERROR: {error}")
        return 2
    if arguments.validate_only:
        print("Wave 1 integration gate manifest: valid")
        return 0
    executions = run_integration_gate(
        arguments.project_root,
        group_names=arguments.groups,
    )
    for execution in executions:
        print(f"{execution.group}: exit {execution.returncode}")
    return 0 if executions and executions[-1].returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "INTEGRATION_GATE_GROUPS",
    "REQUIRED_CONTRACT_DOCUMENTS",
    "IntegrationGateExecution",
    "IntegrationGateGroup",
    "IntegrationGateValidation",
    "main",
    "run_integration_gate",
    "validate_integration_gate",
]
