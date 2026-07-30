"""Mandatory Frontend V2 no-manual-trading release gate.

The gate is deliberately stricter than a text search. It reflects the two
active Feature Interfaces, parses QML Adapter slots and Journey source,
inspects live/fake Adapter surfaces and runtime calls, and records immutable
evidence that packaging certification can require.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import asdict, dataclass
from functools import lru_cache
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence
import xml.etree.ElementTree as ET


POLICY_VERSION = "frontend-v2-no-manual-trading-v1"

ACTIVE_FEATURE_INTERFACE_ALLOWLIST: Mapping[str, frozenset[str]] = (
    MappingProxyType(
        {
            "DiagnosticTasksFeature": frozenset(
                {
                    "interface_version",
                    "snapshot",
                    "subscribe",
                    "create_diagnostic_task",
                    "revise_configuration",
                    "validate_configuration",
                    "approve_configuration",
                    "start_formal_diagnostic_campaign",
                    "pause_diagnostic_target",
                    "resume_diagnostic_target",
                    "cancel_diagnostic_target",
                    "retry_failed_campaign_node",
                    "close",
                }
            ),
            "RunMonitoringFeature": frozenset(
                {
                    "interface_version",
                    "snapshot",
                    "subscribe",
                    "pause_diagnostic_task",
                    "resume_diagnostic_task",
                    "cancel_diagnostic_task",
                    "close",
                }
            ),
            "EvidenceAndFindingsFeature": frozenset(
                {
                    "interface_version",
                    "snapshot",
                    "subscribe",
                    "close",
                }
            ),
        }
    )
)

QML_ADAPTER_SLOT_ALLOWLIST: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "DiagnosticTasksQtAdapter": frozenset({"refresh"}),
        "RunMonitoringQtAdapter": frozenset(
            {
                "refresh",
                "pauseDiagnosticTask",
                "resumeDiagnosticTask",
                "cancelDiagnosticTask",
            }
        ),
        "EvidenceAndFindingsQtAdapter": frozenset(
            {
                "selectCandidate",
                "selectFinding",
                "selectChartPointAtRatio",
                "stepChartPoint",
                "selectChartOverlay",
                "selectChartBreakpoint",
                "setEvidenceFilter",
                "setSortOrder",
                "setActiveTab",
                "setViewportIntent",
            }
        ),
    }
)

JOURNEY_ROUTE_ALLOWLIST = frozenset(
    {
        "diagnostic_tasks",
        "run_monitoring",
        "evidence_and_findings",
    }
)
JOURNEY_SHORTCUT_KEY_ALLOWLIST = frozenset(
    {
        "Return",
        "Enter",
        "Space",
        "Left",
        "Right",
        "Home",
        "End",
    }
)

# Wave 1 has no telemetry command registry. Presentation telemetry may be
# introduced later only through this inert event-name allowlist; it may never
# contain callables or runtime dispatch targets.
TELEMETRY_EVENT_ALLOWLIST: frozenset[str] = frozenset()

RUNTIME_GATEWAY_CALL_ALLOWLIST: Mapping[str, frozenset[str]] = (
    MappingProxyType(
        {
            # Diagnostic Tasks consumes only its typed in-process Application
            # Interface; RuntimeGateway is never an approved authority.
            "LiveDiagnosticTasksAdapter": frozenset(),
            # Issue #50 moved Run Monitoring to the typed in-process
            # Strategy Diagnostics V1 read model. Any RuntimeGateway call is
            # now unapproved for this adapter.
            "LiveRunMonitoringAdapter": frozenset(),
            # Issue #51 moved Evidence & Findings onto the same typed
            # read-model boundary. The legacy dictionary RuntimeGateway is no
            # longer an approved authority for this adapter either.
            "LiveEvidenceAndFindingsAdapter": frozenset(),
        }
    )
)

DIAGNOSTIC_TASK_CONTROLLER_ALLOWLIST: Mapping[str, str] = MappingProxyType(
    {
        "pause": "pause_arena",
        "resume": "resume_arena",
        "cancel": "cancel_diagnostic_task",
    }
)

REQUIRED_GATE_SURFACES = (
    "feature_interfaces",
    "qml_adapter_slots",
    "qml_object_tree",
    "journey_navigation",
    "shortcut_allowlist",
    "telemetry_registry",
    "runtime_dispatch_live",
    "runtime_dispatch_deterministic_fake",
    "read_only_diagnostic_context",
    "release_blocking",
)

RUNTIME_NEGATIVE_TEST_CASE_ALLOWLIST = frozenset(
    {
        (
            "test_qml_object_tree_navigation_and_runtime_surface_are_safe"
            "[deterministic_fake]"
        ),
        (
            "test_qml_object_tree_navigation_and_runtime_surface_are_safe"
            "[live]"
        ),
        (
            "test_order_and_fill_evidence_renders_only_as_non_editable_"
            "context[deterministic_fake]"
        ),
        (
            "test_order_and_fill_evidence_renders_only_as_non_editable_"
            "context[live]"
        ),
        "test_live_cancel_diagnostic_task_cannot_reach_order_cancellation",
    }
)

_FORBIDDEN_RUNTIME_MEMBERS = frozenset(
    {
        "submit_order",
        "place_order",
        "cancel_order",
        "replace_order",
        "bulk_order",
        "buy",
        "sell",
        "dispatch",
    }
)
_FORBIDDEN_BACKEND_IMPORT_PREFIXES = (
    "services",
    "stock_sim.services",
    "persistence",
    "stock_sim.persistence",
    "app.runtime_gateway",
    "app.app_context",
    "app.controllers",
    "app.panels",
    "app.services",
    "app.ui.adapters",
    "core.order",
    "stock_sim.core.order",
)
_FORBIDDEN_QML_PATTERNS = (
    re.compile(
        r"\b(?:submit_order|place_order|cancel_order|replace_order|"
        r"bulk_order|order_entry)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b[A-Za-z0-9_]*(?:(?:submit|place|cancel|replace|bulk)Order|"
        r"Order(?:Entry|Submit|Place|Cancel|Replace|Bulk))[A-Za-z0-9_]*\b",
    ),
    re.compile(r"\b(?:buy|sell)\b", re.IGNORECASE),
    re.compile(r"\bdispatch\b", re.IGNORECASE),
    re.compile(
        r"\b(?:submit|place|cancel|replace|bulk)[ -]order\b",
        re.IGNORECASE,
    ),
    re.compile(r"\border[ -]entry\b", re.IGNORECASE),
)
_ROUTE_PATTERN = re.compile(r'openRoute\(\s*"([^"]+)"')
_DEFAULT_ROUTE_PATTERN = re.compile(
    r'property\s+string\s+activeRoute\s*:\s*"([^"]+)"'
)
_SHORTCUT_KEY_PATTERN = re.compile(r"\bQt\.Key_([A-Za-z0-9_]+)")
_KEY_HANDLER_PATTERN = re.compile(
    r"\bKeys\.on([A-Za-z0-9_]+)Pressed\b"
)
_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class NoManualTradingGateReport:
    schema_version: int
    policy_version: str
    source_commit: str
    status: str
    source_digest: str
    checked_surfaces: tuple[str, ...]
    adapter_modes: tuple[str, ...]
    feature_members: tuple[tuple[str, tuple[str, ...]], ...]
    qml_adapter_slots: tuple[tuple[str, tuple[str, ...]], ...]
    routes: tuple[str, ...]
    shortcut_keys: tuple[str, ...]
    telemetry_events: tuple[str, ...]
    runtime_gateway_calls: tuple[tuple[str, tuple[str, ...]], ...]
    runtime_test_file_digest: str
    runtime_test_exit_code: int
    runtime_test_cases: tuple[str, ...]
    findings: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return self.status == "passed" and not self.findings


def qml_source_inventory(qml_root: Path) -> tuple[Path, ...]:
    """Return the exact recursive QML inventory used by audit and packaging."""

    return tuple(
        sorted(
            qml_root.rglob("*.qml"),
            key=lambda path: path.relative_to(qml_root).as_posix(),
        )
    )


def _public_members(interface: type[Any]) -> frozenset[str]:
    return frozenset(
        name
        for name in vars(interface)
        if not name.startswith("_")
    )


def audit_feature_interface(
    interface_name: str,
    interface: type[Any],
    allowed_members: Iterable[str],
) -> tuple[str, ...]:
    expected = frozenset(allowed_members)
    observed = _public_members(interface)
    findings: list[str] = []
    for member in sorted(observed - expected):
        findings.append(
            f"{interface_name} exposes unapproved member {member!r}"
        )
    for member in sorted(expected - observed):
        findings.append(
            f"{interface_name} is missing approved member {member!r}"
        )
    for member in sorted(observed & _FORBIDDEN_RUNTIME_MEMBERS):
        findings.append(
            f"{interface_name} exposes forbidden transaction member "
            f"{member!r}"
        )
    return tuple(dict.fromkeys(findings))


def audit_qml_text(source_name: str, content: str) -> tuple[str, ...]:
    findings: list[str] = []
    for pattern in _FORBIDDEN_QML_PATTERNS:
        for match in pattern.finditer(content):
            findings.append(
                f"{source_name} exposes forbidden QML action "
                f"{match.group(0)!r}"
            )
    return tuple(dict.fromkeys(findings))


def audit_python_text(source_name: str, content: str) -> tuple[str, ...]:
    tree = ast.parse(content)
    findings: list[str] = []
    for node in ast.walk(tree):
        candidate: str | None = None
        if isinstance(node, ast.Attribute):
            candidate = node.attr
        elif isinstance(node, ast.Name):
            candidate = node.id
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
        ):
            candidate = node.value.strip()
        if candidate is None:
            continue
        normalized = re.sub(
            r"(?<!^)(?=[A-Z])",
            "_",
            candidate,
        ).casefold()
        if normalized not in _FORBIDDEN_RUNTIME_MEMBERS:
            continue
        findings.append(
            f"{source_name} references forbidden runtime operation "
            f"{candidate!r}"
        )
    return tuple(dict.fromkeys(findings))


def _is_forbidden_backend_module(module_name: str) -> bool:
    folded = module_name.casefold()
    return any(
        folded == prefix or folded.startswith(prefix + ".")
        for prefix in _FORBIDDEN_BACKEND_IMPORT_PREFIXES
    )


def audit_python_imports(
    source_name: str,
    content: str,
    *,
    package_name: str | None = None,
    allowed_backend_imports: Iterable[str] = (),
) -> tuple[str, ...]:
    tree = ast.parse(content)
    findings: list[str] = []
    allowed_imports = frozenset(allowed_backend_imports)
    for node in ast.walk(tree):
        dynamic_loader: str | None = None
        if isinstance(node, ast.Import) and any(
            alias.name in {"builtins", "importlib"}
            or alias.name.startswith(("builtins.", "importlib."))
            for alias in node.names
        ):
            dynamic_loader = "builtins/importlib"
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and (
                node.module in {"builtins", "importlib"}
                or node.module.startswith(("builtins.", "importlib."))
            )
        ):
            dynamic_loader = node.module
        elif isinstance(node, ast.ImportFrom) and any(
            alias.name == "__import__" for alias in node.names
        ):
            dynamic_loader = "__import__"
        elif isinstance(node, ast.Name) and node.id == "__import__":
            dynamic_loader = "__import__"
        elif (
            isinstance(node, ast.Attribute)
            and node.attr in {"import_module", "__import__"}
        ):
            dynamic_loader = node.attr
        if dynamic_loader is not None:
            findings.append(
                f"{source_name}:{getattr(node, 'lineno', 0)} uses "
                f"forbidden dynamic import loader {dynamic_loader!r}"
            )

        dynamic_execution: str | None = None
        if (
            isinstance(node, ast.Name)
            and node.id in {"compile", "eval", "exec"}
        ):
            dynamic_execution = node.id
        elif isinstance(node, ast.ImportFrom) and any(
            alias.name in {"compile", "eval", "exec"}
            for alias in node.names
        ):
            dynamic_execution = "builtins dynamic execution alias"
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value in {"compile", "eval", "exec"}
        ):
            dynamic_execution = node.value
        elif (
            isinstance(node, ast.Attribute)
            and node.attr in {"compile", "eval", "exec"}
            and isinstance(node.value, ast.Name)
            and node.value.id in {"builtins", "__builtins__"}
        ):
            dynamic_execution = f"{node.value.id}.{node.attr}"
        if dynamic_execution is not None:
            findings.append(
                f"{source_name}:{getattr(node, 'lineno', 0)} uses "
                f"forbidden dynamic execution {dynamic_execution!r}"
            )

        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
        ):
            if node.value in {"__import__", "import_module"}:
                findings.append(
                    f"{source_name}:{node.lineno} uses forbidden dynamic "
                    f"import reflection {node.value!r}"
                )
            if _is_forbidden_backend_module(node.value):
                findings.append(
                    f"{source_name}:{node.lineno} references forbidden "
                    f"backend module {node.value!r}"
                )

        imported_modules: tuple[str, ...] = ()
        if isinstance(node, ast.Import):
            imported_modules = tuple(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                if package_name is None:
                    findings.append(
                        f"{source_name}:{node.lineno} has an unauditable "
                        "relative import"
                    )
                    continue
                try:
                    base_module = importlib.util.resolve_name(
                        "." * node.level + (node.module or ""),
                        package_name,
                    )
                except ImportError:
                    findings.append(
                        f"{source_name}:{node.lineno} has an invalid "
                        "relative import"
                    )
                    continue
            else:
                base_module = node.module or ""
            imported_modules = tuple(
                (
                    f"{base_module}.{alias.name}"
                    if base_module and alias.name != "*"
                    else base_module
                )
                for alias in node.names
            )
        elif isinstance(node, ast.Call) and (
            (
                isinstance(node.func, ast.Name)
                and node.func.id == "__import__"
            )
            or (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "import_module"
            )
        ):
            if (
                node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                imported_modules = (node.args[0].value,)
            else:
                findings.append(
                    f"{source_name}:{node.lineno} uses an unauditable "
                    "dynamic import"
                )
        for module_name in imported_modules:
            if module_name in allowed_imports:
                continue
            if not _is_forbidden_backend_module(module_name):
                continue
            findings.append(
                f"{source_name}:{getattr(node, 'lineno', 0)} imports "
                "forbidden backend "
                f"module {module_name!r}"
            )
    return tuple(dict.fromkeys(findings))


def _source_package_name(
    project_root: Path,
    source_path: Path,
) -> str:
    relative = source_path.relative_to(project_root)
    parts = list(relative.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    elif parts:
        parts.pop()
    return ".".join(parts)


def _is_slot_decorator(decorator: ast.expr) -> bool:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(target, ast.Name):
        return target.id == "Slot"
    return isinstance(target, ast.Attribute) and target.attr == "Slot"


def _qml_adapter_slots(
    source_path: Path,
    class_name: str,
) -> frozenset[str]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return frozenset(
                member.name
                for member in node.body
                if isinstance(
                    member,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                )
                and not member.name.startswith("_")
                and any(
                    _is_slot_decorator(decorator)
                    for decorator in member.decorator_list
                )
            )
    return frozenset()


def _attribute_chain(node: ast.expr) -> tuple[str, ...]:
    names: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        names.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        names.append(current.id)
    return tuple(reversed(names))


def audit_runtime_gateway_text(
    source_name: str,
    content: str,
    *,
    class_name: str,
    allowed_calls: Iterable[str],
) -> tuple[frozenset[str], tuple[str, ...]]:
    """Require every RuntimeGateway load to be an approved direct call."""

    tree = ast.parse(content)
    class_node = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == class_name
        ),
        None,
    )
    if class_node is None:
        return (
            frozenset(),
            (f"{source_name} is missing runtime adapter {class_name!r}",),
        )
    parents: dict[ast.AST, ast.AST] = {
        child: parent
        for parent in ast.walk(class_node)
        for child in ast.iter_child_nodes(parent)
    }
    calls: set[str] = set()
    findings: list[str] = []
    for node in ast.walk(class_node):
        if (
            not isinstance(node, ast.Attribute)
            or _attribute_chain(node) != ("self", "_runtime_gateway")
        ):
            continue
        if isinstance(node.ctx, ast.Store):
            owner = parents.get(node)
            while owner is not None and not isinstance(
                owner,
                (ast.FunctionDef, ast.AsyncFunctionDef),
            ):
                owner = parents.get(owner)
            if owner is None or owner.name != "__init__":
                findings.append(
                    f"{source_name}:{node.lineno} rebinds RuntimeGateway "
                    "outside __init__"
                )
            continue
        member_node = parents.get(node)
        call = (
            parents.get(member_node)
            if member_node is not None
            else None
        )
        if (
            isinstance(member_node, ast.Attribute)
            and member_node.value is node
            and isinstance(call, ast.Call)
            and call.func is member_node
        ):
            calls.add(member_node.attr)
            continue
        findings.append(
            f"{source_name}:{node.lineno} uses indirect RuntimeGateway "
            "access; only approved direct calls are allowed"
        )

    expected = frozenset(allowed_calls)
    for member_name in sorted(calls - expected):
        findings.append(
            f"{class_name} makes unapproved RuntimeGateway call "
            f"{member_name!r}"
        )
    for member_name in sorted(expected - calls):
        findings.append(
            f"{class_name} is missing approved RuntimeGateway call "
            f"{member_name!r}"
        )
    return frozenset(calls), tuple(dict.fromkeys(findings))


def _runtime_gateway_calls(
    source_path: Path,
    class_name: str,
    allowed_calls: Iterable[str],
) -> tuple[frozenset[str], tuple[str, ...]]:
    return audit_runtime_gateway_text(
        source_path.name,
        source_path.read_text(encoding="utf-8"),
        class_name=class_name,
        allowed_calls=allowed_calls,
    )


def _telemetry_events(source_paths: Iterable[Path]) -> frozenset[str]:
    events: set[str] = set()
    for source_path in source_paths:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                not isinstance(node, ast.Call)
                or not isinstance(node.func, ast.Attribute)
                or node.func.attr not in {"inc", "gauge", "timeit"}
                or not node.args
                or not isinstance(node.args[0], ast.Constant)
                or not isinstance(node.args[0].value, str)
            ):
                continue
            events.add(node.args[0].value)
    return frozenset(events)


def _digest_sources(
    project_root: Path,
    source_paths: Iterable[Path],
) -> str:
    digest = hashlib.sha256()
    for source_path in sorted(
        set(source_paths),
        key=lambda path: path.relative_to(project_root).as_posix(),
    ):
        relative_path = source_path.relative_to(project_root).as_posix()
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(source_path.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _named_calls(node: ast.AST, name: str) -> tuple[ast.Call, ...]:
    return tuple(
        candidate
        for candidate in ast.walk(node)
        if isinstance(candidate, ast.Call)
        and isinstance(candidate.func, ast.Name)
        and candidate.func.id == name
    )


def audit_release_blocking_text(
    source_name: str,
    content: str,
) -> tuple[str, ...]:
    """Verify package planning is gated by one retained audit report."""

    tree = ast.parse(content)
    build = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "build_frontend_v2_release"
        ),
        None,
    )
    if build is None:
        return (
            f"{source_name} is missing build_frontend_v2_release",
        )

    findings: list[str] = []
    gate_calls = _named_calls(build, "audit_no_manual_trading_gate")
    if len(gate_calls) != 1:
        findings.append(
            f"{source_name} must run the no-manual-trading gate exactly "
            f"once before packaging; observed {len(gate_calls)} calls"
        )
        return tuple(findings)
    gate_call = gate_calls[0]
    assignment = next(
        (
            node
            for node in ast.walk(build)
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            and (
                (
                    isinstance(node, ast.Assign)
                    and node.value is gate_call
                    and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == "safety_evidence"
                )
                or (
                    isinstance(node, ast.AnnAssign)
                    and node.value is gate_call
                    and isinstance(node.target, ast.Name)
                    and node.target.id == "safety_evidence"
                )
            )
        ),
        None,
    )
    if assignment is None:
        findings.append(
            f"{source_name} does not retain the gate result as "
            "safety_evidence"
        )
        return tuple(findings)

    surface_calls = _named_calls(build, "audit_frontend_v2_surface")
    if (
        len(surface_calls) != 1
        or len(surface_calls[0].args) != 1
        or not isinstance(surface_calls[0].args[0], ast.Name)
        or surface_calls[0].args[0].id != "safety_evidence"
    ):
        findings.append(
            f"{source_name} does not pass the retained safety_evidence "
            "into the final surface audit"
        )

    plan_calls = _named_calls(build, "create_package_build_plans")
    if len(plan_calls) != 1 or plan_calls[0].lineno <= gate_call.lineno:
        findings.append(
            f"{source_name} does not defer package planning until after "
            "the safety gate"
        )
    blocking_checks = tuple(
        node
        for node in ast.walk(build)
        if isinstance(node, ast.If)
        and gate_call.lineno < node.lineno
        and (not plan_calls or node.lineno < plan_calls[0].lineno)
        and any(isinstance(child, ast.Raise) for child in ast.walk(node))
        and any(
            isinstance(child, ast.Name)
            and child.id == "safety_evidence"
            for child in ast.walk(node.test)
        )
    )
    if len(blocking_checks) != 1:
        findings.append(
            f"{source_name} does not block before package planning on "
            "the retained safety_evidence"
        )

    retained = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "ReleaseBuildResult"
        and any(
            keyword.arg == "safety"
            and isinstance(keyword.value, ast.Name)
            and keyword.value.id == "safety_evidence"
            for keyword in node.keywords
        )
        for node in ast.walk(build)
    )
    if not retained:
        findings.append(
            f"{source_name} does not retain the exact blocked report in "
            "release evidence"
        )
    return tuple(dict.fromkeys(findings))


@lru_cache(maxsize=8)
def _execute_runtime_negative_tests(
    project_root_text: str,
    source_digest: str,
) -> tuple[int, tuple[str, ...], str]:
    del source_digest
    project_root = Path(project_root_text)
    runtime_test = (
        project_root
        / "tests"
        / "frontend"
        / "safety"
        / "test_no_manual_trading_runtime_gate.py"
    )
    environment = os.environ.copy()
    environment.pop("PYTEST_ADDOPTS", None)
    environment.pop("PYTEST_PLUGINS", None)
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    environment.setdefault("QT_QPA_PLATFORM", "offscreen")
    environment.setdefault("QT_QUICK_BACKEND", "software")
    with tempfile.TemporaryDirectory(
        prefix="frontend-v2-safety-",
    ) as temporary_directory:
        junit_report = Path(temporary_directory) / "runtime-tests.xml"
        try:
            completed = subprocess.run(
                (
                    sys.executable,
                    "-m",
                    "pytest",
                    str(runtime_test.relative_to(project_root)),
                    "-q",
                    "-o",
                    "addopts=",
                    "-p",
                    "no:cacheprovider",
                    f"--junitxml={junit_report}",
                ),
                cwd=project_root,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return -1, (), str(error)
        test_cases: tuple[str, ...] = ()
        if junit_report.is_file():
            try:
                test_cases = passed_junit_test_cases(junit_report)
            except (ET.ParseError, OSError) as error:
                test_cases = ()
                parse_error = str(error)
            else:
                parse_error = ""
        else:
            parse_error = "JUnit runtime-test report was not created"
    output = "\n".join(
        part.strip()
        for part in (completed.stdout, completed.stderr, parse_error)
        if part.strip()
    )
    return completed.returncode, test_cases, output


def passed_junit_test_cases(report_path: Path) -> tuple[str, ...]:
    """Return only executed JUnit cases with no skip/failure/error outcome."""

    root = ET.parse(report_path).getroot()
    failed_outcomes = {"skipped", "failure", "error"}
    return tuple(
        sorted(
            str(case.attrib["name"])
            for case in root.iter("testcase")
            if case.attrib.get("name")
            and not any(
                child.tag.rsplit("}", 1)[-1] in failed_outcomes
                for child in case
            )
        )
    )


def _is_frozen_dataclass(candidate: type[Any]) -> bool:
    parameters = getattr(candidate, "__dataclass_params__", None)
    return bool(parameters is not None and parameters.frozen)


def _format_member_observations(
    values: Mapping[str, Iterable[str]],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple(
        (name, tuple(sorted(members)))
        for name, members in sorted(values.items())
    )


def audit_no_manual_trading_gate(
    project_root: Path,
    *,
    source_commit: str = "working-tree",
) -> NoManualTradingGateReport:
    project_root = project_root.resolve()
    loaded_project_root = Path(__file__).resolve().parents[2]
    if project_root != loaded_project_root:
        raise ValueError(
            "The safety gate must audit the same source tree that supplied "
            "the loaded release module"
        )
    qml_root = project_root / "app" / "ui" / "qml"
    qml_sources = qml_source_inventory(qml_root)
    journey_source = qml_root / "JourneyWorkspace.qml"
    qt_adapter_source = project_root / "app" / "ui" / "journey_workspace.py"
    evidence_chart_source = project_root / "app" / "ui" / "evidence_chart.py"
    accessibility_source = project_root / "app" / "ui" / "accessibility.py"
    feature_sources = tuple(
        sorted(
            (project_root / "app" / "features").rglob("*.py"),
            key=lambda path: path.relative_to(project_root).as_posix(),
        )
    )
    packaging_source = (
        project_root
        / "stock_sim"
        / "release"
        / "frontend_v2_packaging.py"
    )
    runtime_test_source = (
        project_root
        / "tests"
        / "frontend"
        / "safety"
        / "test_no_manual_trading_runtime_gate.py"
    )
    live_sources = {
        "LiveDiagnosticTasksAdapter": (
            project_root / "app" / "features" / "live_diagnostic_tasks.py"
        ),
        "LiveRunMonitoringAdapter": (
            project_root / "app" / "features" / "live_run_monitoring.py"
        ),
        "LiveEvidenceAndFindingsAdapter": (
            project_root
            / "app"
            / "features"
            / "live_evidence_and_findings.py"
        ),
    }
    telemetry_sources = (
        qt_adapter_source,
        *live_sources.values(),
        evidence_chart_source,
    )

    from app.features import (
        DeterministicFakeDiagnosticTasksAdapter,
        DeterministicFakeEvidenceAndFindingsAdapter,
        DeterministicFakeRunMonitoringAdapter,
        DiagnosticTasksFeature,
        EvidenceAndFindingsFeature,
        FillEvidenceTrace,
        LiveDiagnosticTasksAdapter,
        LiveEvidenceAndFindingsAdapter,
        LiveRunMonitoringAdapter,
        OrderEvidenceTrace,
        ReadOnlyDiagnosticContext,
        ReadOnlyEvidenceContext,
        RunMonitoringFeature,
    )
    from app.features.run_monitoring import _diagnostic_task_transition

    interfaces: Mapping[str, type[Any]] = {
        "DiagnosticTasksFeature": DiagnosticTasksFeature,
        "RunMonitoringFeature": RunMonitoringFeature,
        "EvidenceAndFindingsFeature": EvidenceAndFindingsFeature,
    }
    findings: list[str] = []
    feature_members = {
        name: _public_members(interface)
        for name, interface in interfaces.items()
    }
    for name, interface in interfaces.items():
        findings.extend(
            audit_feature_interface(
                name,
                interface,
                ACTIVE_FEATURE_INTERFACE_ALLOWLIST[name],
            )
        )

    qml_adapter_slots = {
        class_name: _qml_adapter_slots(qt_adapter_source, class_name)
        for class_name in QML_ADAPTER_SLOT_ALLOWLIST
    }
    for class_name, expected in QML_ADAPTER_SLOT_ALLOWLIST.items():
        observed = qml_adapter_slots[class_name]
        for member in sorted(observed - expected):
            findings.append(
                f"{class_name} exposes unapproved QML Slot {member!r}"
            )
        for member in sorted(expected - observed):
            findings.append(
                f"{class_name} is missing approved QML Slot {member!r}"
            )

    qml_content = {
        source.relative_to(qml_root).as_posix(): source.read_text(
            encoding="utf-8"
        )
        for source in qml_sources
    }
    for source_name, content in qml_content.items():
        findings.extend(audit_qml_text(source_name, content))
    active_python_sources = (
        *feature_sources,
        qt_adapter_source,
        evidence_chart_source,
        accessibility_source,
        project_root
        / "stock_sim"
        / "release"
        / "frontend_v2_package_entry.py",
    )
    for source_path in active_python_sources:
        findings.extend(
            audit_python_text(
                source_path.name,
                source_path.read_text(encoding="utf-8"),
            )
        )
        findings.extend(
            audit_python_imports(
                source_path.name,
                source_path.read_text(encoding="utf-8"),
                package_name=_source_package_name(
                    project_root,
                    source_path,
                ),
                allowed_backend_imports=(
                    ("app.app_context.build_app_context",)
                    if source_path.name == "frontend_v2_package_entry.py"
                    else ()
                ),
            )
        )
    journey_content = journey_source.read_text(encoding="utf-8")
    routes = frozenset(
        route
        for content in qml_content.values()
        for route in _ROUTE_PATTERN.findall(content)
    )
    default_routes = frozenset(
        _DEFAULT_ROUTE_PATTERN.findall(journey_content)
    )
    if routes != JOURNEY_ROUTE_ALLOWLIST:
        findings.append(
            "Journey route allowlist mismatch: "
            f"expected {sorted(JOURNEY_ROUTE_ALLOWLIST)!r}, "
            f"observed {sorted(routes)!r}"
        )
    if not default_routes or not default_routes <= JOURNEY_ROUTE_ALLOWLIST:
        findings.append(
            "Journey default route is not in the approved route allowlist"
        )
    shortcut_keys = frozenset(
        key
        for content in qml_content.values()
        for key in (
            *_SHORTCUT_KEY_PATTERN.findall(content),
            *_KEY_HANDLER_PATTERN.findall(content),
        )
    )
    if shortcut_keys != JOURNEY_SHORTCUT_KEY_ALLOWLIST:
        findings.append(
            "Journey shortcut key allowlist mismatch: "
            f"expected {sorted(JOURNEY_SHORTCUT_KEY_ALLOWLIST)!r}, "
            f"observed {sorted(shortcut_keys)!r}"
        )

    telemetry_events = _telemetry_events(telemetry_sources)
    if telemetry_events != TELEMETRY_EVENT_ALLOWLIST:
        findings.append(
            "Frontend V2 telemetry event allowlist mismatch: "
            f"expected {sorted(TELEMETRY_EVENT_ALLOWLIST)!r}, "
            f"observed {sorted(telemetry_events)!r}"
        )

    adapter_types = (
        DeterministicFakeDiagnosticTasksAdapter,
        LiveDiagnosticTasksAdapter,
        DeterministicFakeRunMonitoringAdapter,
        LiveRunMonitoringAdapter,
        DeterministicFakeEvidenceAndFindingsAdapter,
        LiveEvidenceAndFindingsAdapter,
    )
    for adapter_type in adapter_types:
        for member in sorted(_FORBIDDEN_RUNTIME_MEMBERS):
            if hasattr(adapter_type, member):
                findings.append(
                    f"{adapter_type.__name__} exposes forbidden runtime "
                    f"member {member!r}"
                )

    runtime_gateway_calls: dict[str, frozenset[str]] = {}
    for class_name, expected in RUNTIME_GATEWAY_CALL_ALLOWLIST.items():
        observed, gateway_findings = _runtime_gateway_calls(
            live_sources[class_name],
            class_name,
            expected,
        )
        runtime_gateway_calls[class_name] = observed
        findings.extend(gateway_findings)

    for action, controller_method in (
        DIAGNOSTIC_TASK_CONTROLLER_ALLOWLIST.items()
    ):
        transition = _diagnostic_task_transition(action)
        if transition.controller_method != controller_method:
            findings.append(
                f"Diagnostic task {action!r} routes to unapproved "
                f"controller method {transition.controller_method!r}"
            )

    read_only_types = (
        ReadOnlyDiagnosticContext,
        ReadOnlyEvidenceContext,
        OrderEvidenceTrace,
        FillEvidenceTrace,
    )
    for context_type in read_only_types:
        if not _is_frozen_dataclass(context_type):
            findings.append(
                f"{context_type.__name__} is not an immutable read-only "
                "diagnostic value"
            )
    findings.extend(
        audit_release_blocking_text(
            packaging_source.name,
            packaging_source.read_text(encoding="utf-8"),
        )
    )

    audited_sources = (
        *feature_sources,
        qt_adapter_source,
        evidence_chart_source,
        accessibility_source,
        project_root / "app" / "ui" / "main_window.py",
        *qml_sources,
        project_root / "pyproject.toml",
        project_root
        / "stock_sim"
        / "release"
        / "frontend_v2_package_entry.py",
        packaging_source,
        project_root
        / "docs"
        / "frontend-v2"
        / "no-manual-trading-release-gate.md",
        runtime_test_source,
        Path(__file__).resolve(),
    )
    source_digest = _digest_sources(project_root, audited_sources)
    (
        runtime_test_exit_code,
        runtime_test_cases,
        runtime_test_output,
    ) = (
        _execute_runtime_negative_tests(
            str(project_root),
            source_digest,
        )
    )
    if runtime_test_exit_code != 0:
        details = runtime_test_output[-2000:] or "no test output"
        findings.append(
            "Runtime no-manual-trading negative tests failed with "
            f"exit code {runtime_test_exit_code}: {details}"
        )
    if (
        frozenset(runtime_test_cases)
        != RUNTIME_NEGATIVE_TEST_CASE_ALLOWLIST
    ):
        findings.append(
            "Runtime no-manual-trading negative test sentinel mismatch: "
            f"expected {sorted(RUNTIME_NEGATIVE_TEST_CASE_ALLOWLIST)!r}, "
            f"observed {sorted(runtime_test_cases)!r}"
        )
    observed_after_runtime = _digest_sources(project_root, audited_sources)
    if observed_after_runtime != source_digest:
        findings.append(
            "Audited release sources changed while the safety gate ran"
        )
        source_digest = observed_after_runtime

    unique_findings = tuple(dict.fromkeys(findings))
    runtime_verified = (
        runtime_test_exit_code == 0
        and frozenset(runtime_test_cases)
        == RUNTIME_NEGATIVE_TEST_CASE_ALLOWLIST
    )
    checked_surfaces: tuple[str, ...] = REQUIRED_GATE_SURFACES
    if not runtime_verified:
        checked_surfaces = tuple(
            surface
            for surface in REQUIRED_GATE_SURFACES
            if surface
            not in {
                "qml_object_tree",
                "runtime_dispatch_live",
                "runtime_dispatch_deterministic_fake",
            }
        )
    return NoManualTradingGateReport(
        schema_version=1,
        policy_version=POLICY_VERSION,
        source_commit=source_commit,
        status="passed" if not unique_findings else "failed",
        source_digest=source_digest,
        checked_surfaces=checked_surfaces,
        adapter_modes=tuple(
            mode
            for mode in ("deterministic_fake", "live")
            if any(f"[{mode}]" in case for case in runtime_test_cases)
        ),
        feature_members=_format_member_observations(feature_members),
        qml_adapter_slots=_format_member_observations(qml_adapter_slots),
        routes=tuple(sorted(routes)),
        shortcut_keys=tuple(sorted(shortcut_keys)),
        telemetry_events=tuple(sorted(telemetry_events)),
        runtime_gateway_calls=_format_member_observations(
            runtime_gateway_calls
        ),
        runtime_test_file_digest=(
            "sha256:"
            + hashlib.sha256(runtime_test_source.read_bytes()).hexdigest()
        ),
        runtime_test_exit_code=runtime_test_exit_code,
        runtime_test_cases=runtime_test_cases,
        findings=unique_findings,
    )


def verify_safety_gate_payload(
    candidate: Mapping[str, Any],
    *,
    expected_source_commit: str,
    expected_source_digest: str | None = None,
) -> tuple[str, ...]:
    safety = candidate.get("safety")
    if not isinstance(safety, Mapping):
        return ("Safety gate evidence is unavailable",)
    findings: list[str] = []
    if safety.get("schema_version") != 1:
        findings.append("Safety gate schema version is unsupported")
    if safety.get("policy_version") != POLICY_VERSION:
        findings.append("Safety gate policy version does not match")
    if safety.get("source_commit") != expected_source_commit:
        findings.append("Safety gate source commit does not match")
    if safety.get("status") != "passed":
        findings.append("Safety gate status is not passed")
    recorded_findings = safety.get("findings")
    if not isinstance(recorded_findings, list) or recorded_findings:
        findings.append("Safety gate contains findings")
    if set(safety.get("adapter_modes") or ()) != {
        "deterministic_fake",
        "live",
    }:
        findings.append("Safety gate did not cover live and fake modes")
    if set(safety.get("checked_surfaces") or ()) != set(
        REQUIRED_GATE_SURFACES
    ):
        findings.append("Safety gate surface coverage is incomplete")
    if not _SHA256_PATTERN.fullmatch(
        str(safety.get("source_digest") or "")
    ):
        findings.append("Safety gate source digest is invalid")
    elif (
        expected_source_digest is not None
        and safety.get("source_digest") != expected_source_digest
    ):
        findings.append(
            "Safety gate source digest does not match audited source"
        )
    if safety.get("runtime_test_exit_code") != 0:
        findings.append(
            "Safety gate runtime negative tests did not pass"
        )
    if set(safety.get("runtime_test_cases") or ()) != set(
        RUNTIME_NEGATIVE_TEST_CASE_ALLOWLIST
    ):
        findings.append(
            "Safety gate runtime negative test sentinels are incomplete"
        )
    if not _SHA256_PATTERN.fullmatch(
        str(safety.get("runtime_test_file_digest") or "")
    ):
        findings.append(
            "Safety gate runtime test file digest is invalid"
        )
    return tuple(findings)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Enforce the Frontend V2 no-manual-trading release gate."
        )
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument("--source-commit", default="working-tree")
    arguments = parser.parse_args(argv)
    report = audit_no_manual_trading_gate(
        arguments.project_root,
        source_commit=arguments.source_commit,
    )
    print(json.dumps(asdict(report), indent=2, sort_keys=True))
    return 0 if report.passed else 1


__all__ = [
    "ACTIVE_FEATURE_INTERFACE_ALLOWLIST",
    "DIAGNOSTIC_TASK_CONTROLLER_ALLOWLIST",
    "JOURNEY_ROUTE_ALLOWLIST",
    "JOURNEY_SHORTCUT_KEY_ALLOWLIST",
    "NoManualTradingGateReport",
    "POLICY_VERSION",
    "QML_ADAPTER_SLOT_ALLOWLIST",
    "REQUIRED_GATE_SURFACES",
    "RUNTIME_NEGATIVE_TEST_CASE_ALLOWLIST",
    "RUNTIME_GATEWAY_CALL_ALLOWLIST",
    "TELEMETRY_EVENT_ALLOWLIST",
    "audit_feature_interface",
    "audit_no_manual_trading_gate",
    "audit_python_imports",
    "audit_python_text",
    "audit_qml_text",
    "audit_release_blocking_text",
    "audit_runtime_gateway_text",
    "main",
    "passed_junit_test_cases",
    "qml_source_inventory",
    "verify_safety_gate_payload",
]


if __name__ == "__main__":
    raise SystemExit(main())
