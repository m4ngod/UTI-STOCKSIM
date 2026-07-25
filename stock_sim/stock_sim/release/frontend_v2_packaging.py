"""Reproducible packaging contract for the Frontend V2 Journey Workspace."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import sys
from typing import Any, Sequence
import xml.etree.ElementTree as ET
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_QML_ROOT = PROJECT_ROOT / "app" / "ui" / "qml"
TOOLCHAIN_LOCK_PATH = Path(__file__).with_name(
    "frontend_v2_toolchain.lock.json"
)
MAX_QML_DELTA_BYTES = 50 * 1024 * 1024
_QML_IMPORT_PATTERN = re.compile(
    r"^\s*import\s+"
    r"(?P<module>[A-Za-z_][A-Za-z0-9_.]*)\s+"
    r"(?P<version>[0-9]+\.[0-9]+)"
    r"(?:\s+as\s+[A-Za-z_][A-Za-z0-9_]*)?\s*$"
)


@dataclass(frozen=True, slots=True)
class ToolchainVersions:
    python: str
    pyside6: str
    qt: str
    numpy: str
    nuitka: str


@dataclass(frozen=True, slots=True)
class LockedPlatform:
    operating_system: str
    architecture: str


@dataclass(frozen=True, slots=True)
class FrontendV2ToolchainLock:
    schema_version: int
    platform: LockedPlatform
    toolchain: ToolchainVersions
    invalidation_policy: str


@dataclass(frozen=True, slots=True)
class QmlDependency:
    module: str
    version: str
    source_files: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QmlDependencyManifest:
    scan_kind: str
    source_digest: str
    dependencies: tuple[QmlDependency, ...]


@dataclass(frozen=True, slots=True)
class ResolvedQmlDependency:
    name: str
    dependency_type: str
    relative_path: str | None
    plugin: str | None
    optional: bool


@dataclass(frozen=True, slots=True)
class QmlDependencyClosure:
    scanner: str
    raw_output_digest: str
    dependencies: tuple[ResolvedQmlDependency, ...]


class PackageKind(str, Enum):
    WIDGETS_ROLLBACK = "widgets-rollback"
    QML_JOURNEY = "qml-journey"


@dataclass(frozen=True, slots=True)
class PackageBuildPlan:
    kind: PackageKind
    source_commit: str
    entry_point: Path
    output_root: Path
    distribution_dir: Path
    executable_name: str
    nuitka_report: Path
    nuitka_command: tuple[str, ...]
    source_imports: QmlDependencyManifest | None
    resolved_qml_dependencies: QmlDependencyClosure | None


@dataclass(frozen=True, slots=True)
class QmlRuntimeDeployment:
    scanner: str
    qml_modules: tuple[str, ...]
    binary_dependencies: tuple[str, ...]
    deployed_files: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ArtifactChecksum:
    relative_path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class PackageInventory:
    kind: PackageKind
    source_commit: str
    file_count: int
    total_bytes: int
    tree_sha256: str
    files: tuple[ArtifactChecksum, ...]


@dataclass(frozen=True, slots=True)
class PackageEvidence:
    source_commit: str
    toolchain_identity: str
    widgets_rollback: PackageInventory
    qml_journey: PackageInventory
    qml_delta_bytes: int
    qml_delta_limit_bytes: int
    webengine_files: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RendererLaneEvidence:
    lane: str
    graphics_api: str
    states: tuple[str, ...]
    clean_exit: bool
    errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RendererGateEvidence:
    source_commit: str
    created_at: str
    environment_identity: str
    toolchain_identity: str
    hardware: RendererLaneEvidence
    software: RendererLaneEvidence


@dataclass(frozen=True, slots=True)
class ReleaseBuildResult:
    source_commit: str
    output_root: str
    packages: PackageEvidence
    renderers: RendererGateEvidence
    archives: tuple[ArtifactChecksum, ...]


@dataclass(frozen=True, slots=True)
class CleanRoomCertification:
    source_commit: str
    qml_archive_sha256: str
    clean_room_report_sha256: str
    operating_system: str
    architecture: str
    certified_at: str


EXPECTED_TOOLCHAIN = ToolchainVersions(
    python="3.11.9",
    pyside6="6.9.1",
    qt="6.9.1",
    numpy="2.3.1",
    nuitka="2.6.8",
)


def load_toolchain_lock(
    path: Path = TOOLCHAIN_LOCK_PATH,
) -> FrontendV2ToolchainLock:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    platform = payload["platform"]
    toolchain = payload["toolchain"]
    return FrontendV2ToolchainLock(
        schema_version=int(payload["schema_version"]),
        platform=LockedPlatform(
            operating_system=str(platform["operating_system"]),
            architecture=str(platform["architecture"]),
        ),
        toolchain=ToolchainVersions(
            python=str(toolchain["python"]),
            pyside6=str(toolchain["pyside6"]),
            qt=str(toolchain["qt"]),
            numpy=str(toolchain["numpy"]),
            nuitka=str(toolchain["nuitka"]),
        ),
        invalidation_policy=str(payload["invalidation_policy"]),
    )


def running_toolchain() -> ToolchainVersions:
    import numpy
    import PySide6
    from PySide6.QtCore import qVersion
    from nuitka.Version import getNuitkaVersion

    return ToolchainVersions(
        python=".".join(str(part) for part in sys.version_info[:3]),
        pyside6=PySide6.__version__,
        qt=qVersion(),
        numpy=numpy.__version__,
        nuitka=getNuitkaVersion(),
    )


def verify_running_toolchain(
    lock: FrontendV2ToolchainLock,
) -> tuple[str, ...]:
    running = running_toolchain()
    mismatches = []
    for field in fields(ToolchainVersions):
        field_name = field.name
        expected = getattr(lock.toolchain, field_name)
        actual = getattr(running, field_name)
        if actual != expected:
            mismatches.append(
                f"{field_name}: expected {expected}, observed {actual}"
            )
    observed_platform = running_platform()
    if (
        observed_platform.operating_system
        != lock.platform.operating_system
    ):
        mismatches.append(
            "operating_system: expected "
            f"{lock.platform.operating_system}, observed "
            f"{observed_platform.operating_system}"
        )
    if observed_platform.architecture != lock.platform.architecture:
        mismatches.append(
            "architecture: expected "
            f"{lock.platform.architecture}, observed "
            f"{observed_platform.architecture}"
        )
    return tuple(mismatches)


def running_platform() -> LockedPlatform:
    if sys.platform != "win32":
        operating_system = platform.system()
    else:
        windows_version = sys.getwindowsversion()
        operating_system = classify_windows_operating_system(
            build=windows_version.build,
            product_type=windows_version.product_type,
        )
    observed_architecture = platform.machine().casefold()
    architecture = (
        "x86_64"
        if observed_architecture in {"amd64", "x86_64"}
        else observed_architecture
    )
    return LockedPlatform(
        operating_system=operating_system,
        architecture=architecture,
    )


def classify_windows_operating_system(
    *,
    build: int,
    product_type: int,
) -> str:
    if product_type != 1:
        return "Windows Server"
    return "Windows 11" if build >= 22000 else "Windows 10"


def toolchain_evidence_identity(
    lock: FrontendV2ToolchainLock,
) -> str:
    canonical = json.dumps(
        {
            "schema_version": lock.schema_version,
            "platform": {
                "operating_system": lock.platform.operating_system,
                "architecture": lock.platform.architecture,
            },
            "toolchain": {
                "python": lock.toolchain.python,
                "pyside6": lock.toolchain.pyside6,
                "qt": lock.toolchain.qt,
                "numpy": lock.toolchain.numpy,
                "nuitka": lock.toolchain.nuitka,
            },
            "invalidation_policy": lock.invalidation_policy,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def scan_qml_dependencies(
    qml_root: Path,
) -> QmlDependencyManifest:
    qml_files = tuple(sorted(qml_root.rglob("*.qml")))
    if not qml_files:
        raise ValueError(f"No QML sources found under {qml_root}")

    sources_by_dependency: dict[tuple[str, str], set[str]] = {}
    source_hasher = hashlib.sha256()
    for qml_file in qml_files:
        relative_path = qml_file.relative_to(qml_root).as_posix()
        content = qml_file.read_text(encoding="utf-8")
        source_hasher.update(relative_path.encode("utf-8"))
        source_hasher.update(b"\0")
        source_hasher.update(content.encode("utf-8"))
        source_hasher.update(b"\0")
        for line in content.splitlines():
            match = _QML_IMPORT_PATTERN.match(line)
            if match is None:
                continue
            key = (match.group("module"), match.group("version"))
            sources_by_dependency.setdefault(key, set()).add(relative_path)

    dependencies = tuple(
        QmlDependency(
            module=module,
            version=version,
            source_files=tuple(sorted(source_files)),
        )
        for (module, version), source_files in sorted(
            sources_by_dependency.items()
        )
    )
    return QmlDependencyManifest(
        scan_kind="qml-source-import-scan",
        source_digest=f"sha256:{source_hasher.hexdigest()}",
        dependencies=dependencies,
    )


def resolve_qml_dependency_closure(
    qml_root: Path,
) -> QmlDependencyClosure:
    import PySide6

    pyside_root = Path(PySide6.__file__).resolve().parent
    scanner_path = pyside_root / "qmlimportscanner.exe"
    qml_import_path = pyside_root / "qml"
    if not scanner_path.is_file():
        raise FileNotFoundError(
            f"PySide6 qmlimportscanner is unavailable at {scanner_path}"
        )
    completed = subprocess.run(
        (
            str(scanner_path),
            "-rootPath",
            str(qml_root),
            "-importPath",
            str(qml_import_path),
        ),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    raw_dependencies: list[dict[str, Any]] = json.loads(completed.stdout)
    dependencies = tuple(
        sorted(
            (
                ResolvedQmlDependency(
                    name=str(item["name"]),
                    dependency_type=str(item["type"]),
                    relative_path=(
                        str(item["relativePath"])
                        if item.get("relativePath")
                        else None
                    ),
                    plugin=(
                        str(item["plugin"])
                        if item.get("plugin")
                        else None
                    ),
                    optional=bool(item.get("pluginIsOptional", False)),
                )
                for item in raw_dependencies
                if item.get("name") and item.get("type")
            ),
            key=lambda dependency: (
                dependency.name,
                dependency.relative_path or "",
            ),
        )
    )
    return QmlDependencyClosure(
        scanner="pyside6-qmlimportscanner",
        raw_output_digest=(
            f"sha256:{hashlib.sha256(completed.stdout.encode('utf-8')).hexdigest()}"
        ),
        dependencies=dependencies,
    )


def create_package_build_plans(
    *,
    output_root: Path,
    source_commit: str,
) -> tuple[PackageBuildPlan, PackageBuildPlan]:
    lock = load_toolchain_lock()
    mismatches = verify_running_toolchain(lock)
    if mismatches:
        raise RuntimeError(
            "Running toolchain does not match the Frontend V2 lock: "
            + "; ".join(mismatches)
        )
    source_imports = scan_qml_dependencies(PROJECT_QML_ROOT)
    resolved_dependencies = resolve_qml_dependency_closure(
        PROJECT_QML_ROOT
    )
    forbidden_dependencies = tuple(
        dependency.name
        for dependency in resolved_dependencies.dependencies
        if dependency.name.casefold().startswith(
            ("qtwebengine", "qtwebview")
        )
    )
    if forbidden_dependencies:
        raise RuntimeError(
            "Forbidden WebEngine/WebView QML dependencies discovered: "
            + ", ".join(forbidden_dependencies)
        )

    entry_root = Path(__file__).resolve().parent
    widgets_entry = entry_root / "frontend_widgets_rollback_entry.py"
    qml_entry = entry_root / "frontend_v2_package_entry.py"
    widgets_output = output_root / PackageKind.WIDGETS_ROLLBACK.value
    qml_output = output_root / PackageKind.QML_JOURNEY.value
    widgets_plan = _build_plan(
        kind=PackageKind.WIDGETS_ROLLBACK,
        source_commit=source_commit,
        entry_point=widgets_entry,
        output_root=widgets_output,
        executable_name="UTI-Widgets-Rollback.exe",
        source_imports=None,
        resolved_qml_dependencies=None,
        extra_arguments=(
            "--nofollow-import-to=app.panels",
            "--nofollow-import-to=app.app_context",
            "--nofollow-import-to=app.core_dto",
            "--nofollow-import-to=app.features",
            "--nofollow-import-to=app.runtime_gateway",
            "--nofollow-import-to=app.state",
            "--nofollow-import-to=app.ui.journey_workspace",
            "--nofollow-import-to=app.ui.ui_refresh",
            "--nofollow-import-to=app.controllers.trading_controller",
            "--nofollow-import-to=app.services.trading_service",
        ),
    )
    qml_plan = _build_plan(
        kind=PackageKind.QML_JOURNEY,
        source_commit=source_commit,
        entry_point=qml_entry,
        output_root=qml_output,
        executable_name="UTI-Frontend-V2.exe",
        source_imports=source_imports,
        resolved_qml_dependencies=resolved_dependencies,
        extra_arguments=(
            f"--include-data-dir={PROJECT_QML_ROOT}=app/ui/qml",
        ),
    )
    return widgets_plan, qml_plan


def _build_plan(
    *,
    kind: PackageKind,
    source_commit: str,
    entry_point: Path,
    output_root: Path,
    executable_name: str,
    source_imports: QmlDependencyManifest | None,
    resolved_qml_dependencies: QmlDependencyClosure | None,
    extra_arguments: tuple[str, ...],
) -> PackageBuildPlan:
    nuitka_report = output_root / "nuitka-report.xml"
    command = (
        sys.executable,
        "-m",
        "nuitka",
        str(entry_point),
        "--standalone",
        "--enable-plugin=pyside6",
        "--jobs=1",
        "--include-module=numpy._core._exceptions",
        "--assume-yes-for-downloads",
        "--noinclude-qt-translations",
        f"--output-dir={output_root}",
        f"--output-filename={executable_name}",
        f"--report={nuitka_report}",
        *extra_arguments,
    )
    return PackageBuildPlan(
        kind=kind,
        source_commit=source_commit,
        entry_point=entry_point,
        output_root=output_root,
        distribution_dir=output_root / f"{entry_point.stem}.dist",
        executable_name=executable_name,
        nuitka_report=nuitka_report,
        nuitka_command=command,
        source_imports=source_imports,
        resolved_qml_dependencies=resolved_qml_dependencies,
    )


def deploy_scanned_qml_runtime(
    plan: PackageBuildPlan,
) -> QmlRuntimeDeployment:
    if (
        plan.kind is not PackageKind.QML_JOURNEY
        or plan.resolved_qml_dependencies is None
    ):
        raise ValueError("QML runtime deployment requires a QML Journey plan")

    import PySide6

    pyside_root = Path(PySide6.__file__).resolve().parent
    qml_source_root = pyside_root / "qml"
    qml_target_root = plan.distribution_dir / "PySide6" / "qml"
    plan.distribution_dir.mkdir(parents=True, exist_ok=True)
    deployed_paths: set[Path] = set()
    plugin_binaries: list[Path] = []

    for dependency in plan.resolved_qml_dependencies.dependencies:
        if dependency.relative_path is None:
            continue
        source_dir = qml_source_root / dependency.relative_path
        if not source_dir.is_dir():
            raise FileNotFoundError(
                f"Resolved QML module is unavailable: {source_dir}"
            )
        target_dir = qml_target_root / dependency.relative_path
        target_dir.mkdir(parents=True, exist_ok=True)
        for source_file in sorted(source_dir.iterdir()):
            if not source_file.is_file():
                continue
            target_file = target_dir / source_file.name
            shutil.copy2(source_file, target_file)
            deployed_paths.add(target_file)
            if source_file.suffix.casefold() == ".dll":
                plugin_binaries.append(source_file)

    objdump_path = _find_objdump()
    pyside_binaries = {
        path.name.casefold(): path
        for path in pyside_root.iterdir()
        if path.is_file()
    }
    pending = list(plugin_binaries)
    inspected: set[Path] = set()
    binary_dependencies: set[str] = set()
    while pending:
        binary = pending.pop()
        if binary in inspected:
            continue
        inspected.add(binary)
        for imported_name in _inspect_binary_dependencies(
            binary,
            objdump_path,
        ):
            source_dependency = pyside_binaries.get(
                imported_name.casefold()
            )
            if source_dependency is None:
                continue
            binary_dependencies.add(source_dependency.name)
            target_dependency = (
                plan.distribution_dir / source_dependency.name
            )
            if not target_dependency.exists():
                shutil.copy2(source_dependency, target_dependency)
                deployed_paths.add(target_dependency)
            if source_dependency not in inspected:
                pending.append(source_dependency)

    relative_files = tuple(
        sorted(
            path.relative_to(plan.distribution_dir).as_posix()
            for path in deployed_paths
        )
    )
    forbidden_files = tuple(
        relative_path
        for relative_path in relative_files
        if "webengine" in relative_path.casefold()
        or "webview" in relative_path.casefold()
    )
    if forbidden_files:
        raise RuntimeError(
            "Forbidden WebEngine/WebView payload discovered: "
            + ", ".join(forbidden_files)
        )
    return QmlRuntimeDeployment(
        scanner=plan.resolved_qml_dependencies.scanner,
        qml_modules=tuple(
            dependency.name
            for dependency in plan.resolved_qml_dependencies.dependencies
        ),
        binary_dependencies=tuple(sorted(binary_dependencies)),
        deployed_files=relative_files,
    )


def _find_objdump() -> Path:
    from_path = shutil.which("objdump")
    if from_path:
        return Path(from_path).resolve()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise FileNotFoundError("LOCALAPPDATA is unavailable")
    cache_root = Path(local_app_data) / "Nuitka" / "Nuitka" / "Cache"
    candidates = tuple(
        sorted(
            cache_root.rglob("objdump.exe"),
            key=lambda path: (len(path.parts), str(path)),
        )
    )
    if not candidates:
        raise FileNotFoundError(
            "Nuitka compiler objdump is unavailable for PE dependency scanning"
        )
    return candidates[0]


def _inspect_binary_dependencies(
    binary: Path,
    objdump_path: Path,
) -> tuple[str, ...]:
    completed = subprocess.run(
        (str(objdump_path), "-p", str(binary)),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return tuple(
        match.group(1).strip()
        for line in completed.stdout.splitlines()
        if (match := re.search(r"DLL Name:\s*(.+)$", line))
    )


def write_package_evidence(
    *,
    plans: tuple[PackageBuildPlan, PackageBuildPlan],
    evidence_dir: Path,
) -> PackageEvidence:
    plans_by_kind = {plan.kind: plan for plan in plans}
    if set(plans_by_kind) != {
        PackageKind.WIDGETS_ROLLBACK,
        PackageKind.QML_JOURNEY,
    }:
        raise ValueError("Exactly one Widgets and one QML build plan is required")
    source_commits = {plan.source_commit for plan in plans}
    if len(source_commits) != 1:
        raise ValueError("Widgets and QML packages must use the same commit")
    source_commit = source_commits.pop()
    widgets_inventory = _inventory_package(
        plans_by_kind[PackageKind.WIDGETS_ROLLBACK]
    )
    qml_inventory = _inventory_package(
        plans_by_kind[PackageKind.QML_JOURNEY]
    )
    qml_delta_bytes = (
        qml_inventory.total_bytes - widgets_inventory.total_bytes
    )
    if qml_delta_bytes > MAX_QML_DELTA_BYTES:
        raise RuntimeError(
            "QML package delta exceeds 50 MiB: "
            f"{qml_delta_bytes} bytes"
        )
    webengine_files = tuple(
        checksum.relative_path
        for checksum in qml_inventory.files
        if "webengine" in checksum.relative_path.casefold()
        or "webview" in checksum.relative_path.casefold()
    )
    if webengine_files:
        raise RuntimeError(
            "QML package contains forbidden WebEngine/WebView payload: "
            + ", ".join(webengine_files)
        )
    lock = load_toolchain_lock()
    evidence = PackageEvidence(
        source_commit=source_commit,
        toolchain_identity=toolchain_evidence_identity(lock),
        widgets_rollback=widgets_inventory,
        qml_journey=qml_inventory,
        qml_delta_bytes=qml_delta_bytes,
        qml_delta_limit_bytes=MAX_QML_DELTA_BYTES,
        webengine_files=webengine_files,
    )
    evidence_dir.mkdir(parents=True, exist_ok=True)
    manifest_payload = {
        "schema_version": 1,
        "source_commit": source_commit,
        "toolchain_lock": asdict(lock),
        "toolchain_identity": evidence.toolchain_identity,
        "packages": {
            PackageKind.WIDGETS_ROLLBACK.value: asdict(
                widgets_inventory
            ),
            PackageKind.QML_JOURNEY.value: asdict(qml_inventory),
        },
        "qml_delta_bytes": qml_delta_bytes,
        "qml_delta_limit_bytes": MAX_QML_DELTA_BYTES,
        "webengine_files": webengine_files,
    }
    (evidence_dir / "dependency-manifest.json").write_text(
        json.dumps(
            manifest_payload,
            indent=2,
            sort_keys=True,
            default=_json_default,
        ),
        encoding="utf-8",
    )
    checksum_lines = []
    for inventory in (widgets_inventory, qml_inventory):
        for checksum in inventory.files:
            checksum_lines.append(
                f"{checksum.sha256.removeprefix('sha256:')}  "
                f"{inventory.kind.value}/{checksum.relative_path}"
            )
    (evidence_dir / "SHA256SUMS.txt").write_text(
        "\n".join(checksum_lines) + "\n",
        encoding="utf-8",
    )
    return evidence


def _inventory_package(plan: PackageBuildPlan) -> PackageInventory:
    executable = plan.distribution_dir / plan.executable_name
    if not executable.is_file():
        raise FileNotFoundError(
            f"Package executable is unavailable: {executable}"
        )
    files = tuple(
        _checksum_file(path, plan.distribution_dir)
        for path in sorted(
            (
                candidate
                for candidate in plan.distribution_dir.rglob("*")
                if candidate.is_file()
            ),
            key=lambda path: path.relative_to(
                plan.distribution_dir
            ).as_posix(),
        )
    )
    tree_hasher = hashlib.sha256()
    for checksum in files:
        tree_hasher.update(
            (
                f"{checksum.sha256} {checksum.size_bytes} "
                f"{checksum.relative_path}\n"
            ).encode("utf-8")
        )
    return PackageInventory(
        kind=plan.kind,
        source_commit=plan.source_commit,
        file_count=len(files),
        total_bytes=sum(checksum.size_bytes for checksum in files),
        tree_sha256=f"sha256:{tree_hasher.hexdigest()}",
        files=files,
    )


def _checksum_file(
    path: Path,
    package_root: Path,
) -> ArtifactChecksum:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return ArtifactChecksum(
        relative_path=path.relative_to(package_root).as_posix(),
        size_bytes=path.stat().st_size,
        sha256=f"sha256:{hasher.hexdigest()}",
    )


def _json_default(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def verify_clean_room_report(
    report_path: Path,
    *,
    expected_source_commit: str,
    expected_archive_sha256: str,
) -> tuple[str, ...]:
    payload: dict[str, Any] = json.loads(
        report_path.read_text(encoding="utf-8")
    )
    failures = []
    if payload.get("schema_version") != 2:
        failures.append("Unsupported clean-room report schema")
    if payload.get("source_commit") != expected_source_commit:
        failures.append("Clean-room source commit does not match")
    if payload.get("archive_sha256") != expected_archive_sha256:
        failures.append("Clean-room archive checksum does not match")
    if "windows 11" not in str(
        payload.get("operating_system", "")
    ).casefold():
        failures.append("Clean-room operating system is not Windows 11")
    if str(payload.get("architecture", "")).casefold() not in {
        "amd64",
        "x86_64",
    }:
        failures.append("Clean-room architecture is not x64")
    if payload.get("network_enumeration_succeeded") is not True:
        failures.append("Network adapter inventory was not established")
    if payload.get("network_adapters_up"):
        failures.append("Clean-room network is enabled")
    if payload.get("python_on_path") is not False:
        failures.append("Python is available on PATH")
    if payload.get("python_installations") != []:
        failures.append("Python is installed")
    if payload.get("compiler_on_path") is not False:
        failures.append("A compiler is available on PATH")
    if payload.get("compiler_installations") != []:
        failures.append("A compiler is installed")
    if payload.get("dependency_cache_present") is not False:
        failures.append("A dependency cache is present")
    if payload.get("dependency_cache_paths") != []:
        failures.append("Dependency cache paths are present")
    if payload.get("install_succeeded") is not True:
        failures.append("Package installation did not succeed")

    lanes = payload.get("renderer_lanes")
    if not isinstance(lanes, dict):
        failures.append("Renderer lane evidence is unavailable")
        return tuple(failures)
    expected_states = ["loading", "empty", "disconnected"]
    for lane_name, expected_api in (
        ("hardware", "Direct3D11"),
        ("software", "Software"),
    ):
        lane = lanes.get(lane_name)
        if not isinstance(lane, dict):
            failures.append(f"{lane_name} renderer lane is unavailable")
            continue
        if lane.get("exit_code") != 0:
            failures.append(f"{lane_name} renderer lane failed")
        if lane.get("graphics_api") != expected_api:
            failures.append(
                f"{lane_name} renderer used {lane.get('graphics_api')!r}"
            )
        if lane.get("states") != expected_states:
            failures.append(
                f"{lane_name} renderer did not show all required states"
            )
        if lane.get("clean_exit") is not True:
            failures.append(f"{lane_name} renderer did not exit cleanly")
        if lane.get("errors"):
            failures.append(f"{lane_name} renderer reported errors")
    return tuple(failures)


def write_renderer_evidence(
    *,
    hardware_report: Path,
    software_report: Path,
    source_commit: str,
    evidence_dir: Path,
) -> RendererGateEvidence:
    hardware = _load_renderer_lane(
        hardware_report,
        expected_lane="hardware",
        expected_graphics_api="Direct3D11",
    )
    software = _load_renderer_lane(
        software_report,
        expected_lane="software",
        expected_graphics_api="Software",
    )
    lock = load_toolchain_lock()
    evidence = RendererGateEvidence(
        source_commit=source_commit,
        created_at=datetime.now(timezone.utc).isoformat(),
        environment_identity=(
            f"{socket.gethostname()}|{platform.platform()}|"
            f"{platform.machine()}"
        ),
        toolchain_identity=toolchain_evidence_identity(lock),
        hardware=hardware,
        software=software,
    )
    source_imports = scan_qml_dependencies(PROJECT_QML_ROOT)
    dependency_closure = resolve_qml_dependency_closure(
        PROJECT_QML_ROOT
    )
    payload = {
        "schema_version": 1,
        **asdict(evidence),
        "toolchain_lock": asdict(lock),
        "qml_source_imports": asdict(source_imports),
        "qml_dependency_closure": asdict(dependency_closure),
    }
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "renderer-gate-report.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return evidence


def _load_renderer_lane(
    report_path: Path,
    *,
    expected_lane: str,
    expected_graphics_api: str,
) -> RendererLaneEvidence:
    payload: dict[str, Any] = json.loads(
        report_path.read_text(encoding="utf-8")
    )
    states = tuple(
        str(observation.get("state"))
        for observation in payload.get("observations", ())
    )
    errors = tuple(str(error) for error in payload.get("errors", ()))
    if payload.get("renderer_lane") != expected_lane:
        raise RuntimeError(
            f"Expected {expected_lane} renderer report at {report_path}"
        )
    if payload.get("graphics_api") != expected_graphics_api:
        raise RuntimeError(
            f"{expected_lane} used {payload.get('graphics_api')!r}"
        )
    if states != ("loading", "empty", "disconnected"):
        raise RuntimeError(
            f"{expected_lane} did not show all required states"
        )
    if errors or payload.get("clean_exit") is not True:
        raise RuntimeError(f"{expected_lane} renderer smoke failed")
    return RendererLaneEvidence(
        lane=expected_lane,
        graphics_api=expected_graphics_api,
        states=states,
        clean_exit=True,
        errors=(),
    )


def audit_nuitka_dependency_report(
    report_path: Path,
    *,
    package_kind: PackageKind,
) -> tuple[str, ...]:
    root = ET.parse(report_path).getroot()
    findings = []
    if root.attrib.get("mode") != "standalone":
        findings.append("Nuitka report is not a standalone build")
    if root.attrib.get("completion") != "yes":
        findings.append("Nuitka report did not complete successfully")
    module_names = tuple(
        element.attrib["name"]
        for element in root.findall(".//module")
        if element.attrib.get("name")
    )
    for module_name in module_names:
        folded = module_name.casefold()
        if folded.startswith(
            ("pyside6.qtwebengine", "pyside6.qtwebview")
        ):
            findings.append(
                f"Forbidden web module in dependency graph: {module_name}"
            )
        if package_kind is PackageKind.QML_JOURNEY and folded.startswith(
            "app."
        ):
            allowed = (
                folded.startswith("app.features")
                or folded == "app.ui"
                or folded == "app.ui.journey_workspace"
            )
            if not allowed:
                findings.append(
                    "Forbidden non-V2 application module in dependency graph: "
                    f"{module_name}"
                )
        if package_kind is PackageKind.WIDGETS_ROLLBACK and folded.startswith(
            (
                "app.app_context",
                "app.core_dto",
                "app.features",
                "app.runtime_gateway",
                "app.state",
                "app.controllers.trading",
                "app.services.trading",
                "app.panels",
                "app.ui.journey_workspace",
                "app.ui.ui_refresh",
                "app.ui.adapters.orders",
                "app.core_dto.trade",
            )
        ):
            findings.append(
                "Rollback baseline contains a transaction path: "
                f"{module_name}"
            )
    for element in root.iter():
        for value in element.attrib.values():
            folded = value.casefold()
            if "webengine" in folded or "qtwebview" in folded:
                findings.append(
                    f"Forbidden web payload in Nuitka report: {value}"
                )
    return tuple(dict.fromkeys(findings))


def audit_frontend_v2_surface() -> tuple[str, ...]:
    findings = []
    qml_sources = tuple(sorted(PROJECT_QML_ROOT.rglob("*.qml")))
    for source in qml_sources:
        content = source.read_text(encoding="utf-8")
        if re.search(
            r"^\s*(?:Button|Action|Shortcut)\s*\{",
            content,
            re.MULTILINE,
        ):
            findings.append(
                f"Interactive action surface found in {source.name}"
            )
        if re.search(r"^\s*import\s+QtWeb", content, re.MULTILINE):
            findings.append(f"Web QML import found in {source.name}")

    python_sources = (
        PROJECT_ROOT
        / "stock_sim"
        / "release"
        / "frontend_v2_package_entry.py",
        PROJECT_ROOT
        / "stock_sim"
        / "release"
        / "frontend_widgets_rollback_entry.py",
        PROJECT_ROOT / "app" / "features" / "run_monitoring.py",
        PROJECT_ROOT / "app" / "ui" / "journey_workspace.py",
    )
    forbidden_identifier = re.compile(
        r"\b(?:submit_order|cancel_order|replace_order|bulk_order|"
        r"place_order|buy|sell|dispatch)\b",
        re.IGNORECASE,
    )
    for source in python_sources:
        content = source.read_text(encoding="utf-8")
        match = forbidden_identifier.search(content)
        if match is not None:
            findings.append(
                f"Forbidden transaction identifier {match.group(0)!r} "
                f"found in {source.name}"
            )
    return tuple(findings)


def create_deterministic_package_archive(
    plan: PackageBuildPlan,
    *,
    archive_dir: Path,
) -> ArtifactChecksum:
    executable = plan.distribution_dir / plan.executable_name
    if not executable.is_file():
        raise FileNotFoundError(
            f"Package executable is unavailable: {executable}"
        )
    archive_dir.mkdir(parents=True, exist_ok=True)
    commit_fragment = re.sub(
        r"[^A-Za-z0-9_.-]",
        "-",
        plan.source_commit,
    )[:12]
    archive_path = (
        archive_dir / f"{plan.kind.value}-{commit_fragment}.zip"
    )
    package_files = tuple(
        sorted(
            (
                candidate
                for candidate in plan.distribution_dir.rglob("*")
                if candidate.is_file()
            ),
            key=lambda path: path.relative_to(
                plan.distribution_dir
            ).as_posix(),
        )
    )
    with zipfile.ZipFile(
        archive_path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for source_file in package_files:
            relative_path = source_file.relative_to(
                plan.distribution_dir
            ).as_posix()
            archive_name = f"{plan.kind.value}/{relative_path}"
            info = zipfile.ZipInfo(
                filename=archive_name,
                date_time=(1980, 1, 1, 0, 0, 0),
            )
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0o644 << 16
            archive.writestr(info, source_file.read_bytes())
    return _checksum_file(archive_path, archive_dir)


def build_frontend_v2_release(
    *,
    output_root: Path,
    source_commit: str,
) -> ReleaseBuildResult:
    """Build and verify the same-commit Widgets/QML release pair."""

    verify_release_source(
        source_root=PROJECT_ROOT,
        source_commit=source_commit,
    )
    if output_root.exists() and any(output_root.iterdir()):
        raise RuntimeError(
            f"Release output directory is not empty: {output_root}"
        )
    output_root.mkdir(parents=True, exist_ok=True)
    plans = create_package_build_plans(
        output_root=output_root / "packages",
        source_commit=source_commit,
    )
    surface_findings = audit_frontend_v2_surface()
    if surface_findings:
        raise RuntimeError(
            "Frontend V2 surface audit failed: "
            + "; ".join(surface_findings)
        )

    for plan in plans:
        subprocess.run(
            plan.nuitka_command,
            cwd=PROJECT_ROOT,
            check=True,
        )
        dependency_findings = audit_nuitka_dependency_report(
            plan.nuitka_report,
            package_kind=plan.kind,
        )
        if dependency_findings:
            raise RuntimeError(
                f"{plan.kind.value} dependency audit failed: "
                + "; ".join(dependency_findings)
            )

    qml_plan = next(
        plan for plan in plans if plan.kind is PackageKind.QML_JOURNEY
    )
    widgets_plan = next(
        plan
        for plan in plans
        if plan.kind is PackageKind.WIDGETS_ROLLBACK
    )
    deploy_scanned_qml_runtime(qml_plan)

    smoke_root = output_root / "evidence" / "smoke"
    _run_packaged_smoke(
        widgets_plan,
        ("--smoke-report-dir", str(smoke_root / "widgets")),
    )
    for lane in ("hardware", "software"):
        _run_packaged_smoke(
            qml_plan,
            (
                "--renderer-lane",
                lane,
                "--smoke-report-dir",
                str(smoke_root / lane),
            ),
        )

    evidence_dir = output_root / "evidence"
    package_evidence = write_package_evidence(
        plans=plans,
        evidence_dir=evidence_dir,
    )
    renderer_evidence = write_renderer_evidence(
        hardware_report=smoke_root / "hardware" / "smoke-report.json",
        software_report=smoke_root / "software" / "smoke-report.json",
        source_commit=source_commit,
        evidence_dir=evidence_dir,
    )
    archive_dir = output_root / "archives"
    archives = tuple(
        create_deterministic_package_archive(
            plan,
            archive_dir=archive_dir,
        )
        for plan in plans
    )
    result = ReleaseBuildResult(
        source_commit=source_commit,
        output_root=str(output_root.resolve()),
        packages=package_evidence,
        renderers=renderer_evidence,
        archives=archives,
    )
    (evidence_dir / "release-candidate-summary.json").write_text(
        json.dumps(
            asdict(result),
            indent=2,
            sort_keys=True,
            default=_json_default,
        ),
        encoding="utf-8",
    )
    return result


def verify_release_source(
    *,
    source_root: Path,
    source_commit: str,
) -> None:
    observed_commit = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    if observed_commit != source_commit:
        raise RuntimeError(
            "Release source commit does not match HEAD: "
            f"expected {source_commit}, observed {observed_commit}"
        )
    tracked_changes = subprocess.run(
        ("git", "status", "--porcelain", "--untracked-files=all"),
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    if tracked_changes:
        raise RuntimeError(
            "Release builds require a clean working tree; observed: "
            + tracked_changes.replace("\n", "; ")
        )
    tracked_result = subprocess.run(
        ("git", "ls-files", "--cached", "-z"),
        cwd=source_root,
        check=True,
        capture_output=True,
    )
    tracked_files = {
        raw_path.decode("utf-8", errors="surrogateescape").replace(
            "\\",
            "/",
        )
        for raw_path in tracked_result.stdout.split(b"\0")
        if raw_path
    }
    qml_root = source_root / "app" / "ui" / "qml"
    if qml_root.is_dir():
        non_commit_inputs = tuple(
            sorted(
                path.relative_to(source_root).as_posix()
                for path in qml_root.rglob("*")
                if path.is_file()
                and path.relative_to(source_root).as_posix()
                not in tracked_files
            )
        )
        if non_commit_inputs:
            raise RuntimeError(
                "Release build contains an ignored or untracked release "
                "input: " + ", ".join(non_commit_inputs)
            )


def certify_frontend_v2_release(
    *,
    output_root: Path,
    source_commit: str,
    clean_room_report: Path,
) -> CleanRoomCertification:
    evidence_dir = output_root / "evidence"
    candidate_path = evidence_dir / "release-candidate-summary.json"
    if not candidate_path.is_file():
        raise FileNotFoundError(
            f"Release candidate evidence is unavailable: {candidate_path}"
        )
    candidate: dict[str, Any] = json.loads(
        candidate_path.read_text(encoding="utf-8")
    )
    if candidate.get("source_commit") != source_commit:
        raise RuntimeError(
            "Release candidate source commit does not match certification"
        )
    retained_archives = candidate.get("archives", ())
    if not isinstance(retained_archives, list):
        raise RuntimeError("Release candidate archive inventory is invalid")
    archive_dir = (output_root / "archives").resolve()
    verified_archives: list[dict[str, Any]] = []
    for retained_archive in retained_archives:
        if not isinstance(retained_archive, dict):
            raise RuntimeError(
                "Release candidate archive inventory is invalid"
            )
        relative_path = str(
            retained_archive.get("relative_path", "")
        )
        archive_path = (archive_dir / relative_path).resolve()
        try:
            archive_path.relative_to(archive_dir)
        except ValueError as error:
            raise RuntimeError(
                f"Release archive escapes the archive root: {relative_path}"
            ) from error
        if not archive_path.is_file():
            raise FileNotFoundError(
                f"Release archive is unavailable: {archive_path}"
            )
        observed = _checksum_file(archive_path, archive_dir)
        if (
            observed.sha256 != retained_archive.get("sha256")
            or observed.size_bytes
            != retained_archive.get("size_bytes")
        ):
            raise RuntimeError(
                "Release archive checksum does not match candidate "
                f"evidence: {relative_path}"
            )
        verified_archives.append(asdict(observed))

    qml_archives = [
        archive
        for archive in verified_archives
        if str(archive["relative_path"]).startswith(
            f"{PackageKind.QML_JOURNEY.value}-"
        )
    ]
    widgets_archives = [
        archive
        for archive in verified_archives
        if str(archive["relative_path"]).startswith(
            f"{PackageKind.WIDGETS_ROLLBACK.value}-"
        )
    ]
    if len(qml_archives) != 1:
        raise RuntimeError(
            "Release candidate must retain exactly one QML archive"
        )
    if len(widgets_archives) != 1:
        raise RuntimeError(
            "Release candidate must retain exactly one Widgets archive"
        )
    qml_archive_sha256 = str(qml_archives[0].get("sha256", ""))
    failures = verify_clean_room_report(
        clean_room_report,
        expected_source_commit=source_commit,
        expected_archive_sha256=qml_archive_sha256,
    )
    if failures:
        raise RuntimeError(
            "Clean-room certification failed: " + "; ".join(failures)
        )

    report_payload: dict[str, Any] = json.loads(
        clean_room_report.read_text(encoding="utf-8")
    )
    report_checksum = _checksum_file(
        clean_room_report,
        clean_room_report.parent,
    )
    certification = CleanRoomCertification(
        source_commit=source_commit,
        qml_archive_sha256=qml_archive_sha256,
        clean_room_report_sha256=report_checksum.sha256,
        operating_system=str(report_payload["operating_system"]),
        architecture=str(report_payload["architecture"]),
        certified_at=datetime.now(timezone.utc).isoformat(),
    )
    retained_report_path = evidence_dir / "clean-room-report.json"
    if clean_room_report.resolve() != retained_report_path.resolve():
        shutil.copy2(clean_room_report, retained_report_path)
    final_payload = {
        "schema_version": 1,
        "status": "certified",
        "candidate": candidate,
        "verified_archives": verified_archives,
        "clean_room": asdict(certification),
        "clean_room_report": report_payload,
    }
    (evidence_dir / "release-summary.json").write_text(
        json.dumps(final_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return certification


def _run_packaged_smoke(
    plan: PackageBuildPlan,
    arguments: tuple[str, ...],
) -> None:
    executable = plan.distribution_dir / plan.executable_name
    completed = subprocess.run(
        (str(executable), *arguments),
        cwd=plan.distribution_dir,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"{plan.kind.value} packaged smoke failed with "
            f"exit code {completed.returncode}"
        )


def _serialize_build_plan(plan: PackageBuildPlan) -> dict[str, Any]:
    return {
        "kind": plan.kind.value,
        "source_commit": plan.source_commit,
        "entry_point": str(plan.entry_point),
        "output_root": str(plan.output_root),
        "distribution_dir": str(plan.distribution_dir),
        "executable_name": plan.executable_name,
        "nuitka_report": str(plan.nuitka_report),
        "nuitka_command": list(plan.nuitka_command),
        "source_imports": (
            asdict(plan.source_imports)
            if plan.source_imports is not None
            else None
        ),
        "resolved_qml_dependencies": (
            asdict(plan.resolved_qml_dependencies)
            if plan.resolved_qml_dependencies is not None
            else None
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the locked Frontend V2 release pair."
    )
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--certify-clean-room-report", type=Path)
    arguments = parser.parse_args(argv)
    if arguments.plan_only and arguments.certify_clean_room_report:
        parser.error(
            "--plan-only and --certify-clean-room-report are exclusive"
        )
    if arguments.plan_only:
        plans = create_package_build_plans(
            output_root=arguments.output_root / "packages",
            source_commit=arguments.source_commit,
        )
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "source_commit": arguments.source_commit,
                    "plans": [
                        _serialize_build_plan(plan) for plan in plans
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if arguments.certify_clean_room_report is not None:
        certification = certify_frontend_v2_release(
            output_root=arguments.output_root,
            source_commit=arguments.source_commit,
            clean_room_report=arguments.certify_clean_room_report,
        )
        print(
            json.dumps(
                asdict(certification),
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    result = build_frontend_v2_release(
        output_root=arguments.output_root,
        source_commit=arguments.source_commit,
    )
    print(
        json.dumps(
            asdict(result),
            indent=2,
            sort_keys=True,
            default=_json_default,
        )
    )
    return 0


__all__ = [
    "CleanRoomCertification",
    "FrontendV2ToolchainLock",
    "PackageEvidence",
    "RendererGateEvidence",
    "ReleaseBuildResult",
    "build_frontend_v2_release",
    "certify_frontend_v2_release",
    "load_toolchain_lock",
    "main",
    "toolchain_evidence_identity",
    "verify_clean_room_report",
    "verify_running_toolchain",
]


if __name__ == "__main__":
    raise SystemExit(main())
