"""Reproducible packaging contract for the Frontend V2 Journey Workspace."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from enum import Enum
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from typing import Any, Mapping, Sequence
from urllib.parse import unquote, urlparse
import xml.etree.ElementTree as ET
import zipfile

from strategy_diagnostics.formal_strategy_sources import (
    FORMAL_STRATEGY_SOURCE_BINDINGS,
)
from stock_sim.release.no_manual_trading_gate import (
    NoManualTradingGateReport,
    audit_no_manual_trading_gate,
    qml_source_inventory,
    verify_safety_gate_payload,
)
from stock_sim.release.strategy_diagnostics_v1_release_fixture import (
    FORMAL_V1_RELEASE_FIXTURE_ARCHIVE,
    FORMAL_V1_RELEASE_FIXTURE_DIRNAME,
    WAVE3_RELEASE_INPUT_FIXTURE_ARCHIVE,
    WAVE3_RELEASE_INPUT_FIXTURE_DIRNAME,
    SealedFormalV1ReleaseFixtureManifest,
    SealedWave2ReleaseInputFixtureManifest,
    create_sealed_formal_v1_release_fixture,
    create_sealed_wave2_release_input_fixture,
    extract_sealed_formal_v1_release_fixture_archive,
    extract_sealed_wave2_release_input_fixture_archive,
    write_sealed_formal_v1_release_fixture_archive,
    write_sealed_wave2_release_input_fixture_archive,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_QML_ROOT = PROJECT_ROOT / "app" / "ui" / "qml"
TOOLCHAIN_LOCK_PATH = Path(__file__).with_name(
    "frontend_v2_toolchain.lock.json"
)
_FORMAL_STRATEGY_SOURCE_DATA_FILES = (
    *(
        (
            PROJECT_ROOT / binding.source_relative_path,
            binding.packaged_relative_path,
        )
        for binding in FORMAL_STRATEGY_SOURCE_BINDINGS.values()
    ),
)
_REQUIRED_FORMAL_STRATEGY_SOURCE_DATA_FILES = frozenset(
    destination
    for _source, destination in _FORMAL_STRATEGY_SOURCE_DATA_FILES
)
MAX_QML_DELTA_BYTES = 50 * 1024 * 1024
CLEAN_ROOM_REPORT_SCHEMA_VERSION = 8
PACKAGE_SMOKE_REPORT_SCHEMA_VERSION = 4
RENDERER_GATE_REPORT_SCHEMA_VERSION = 2
_QML_IMPORT_PATTERN = re.compile(
    r"^\s*import\s+"
    r"(?P<module>[A-Za-z_][A-Za-z0-9_.]*)\s+"
    r"(?P<version>[0-9]+\.[0-9]+)"
    r"(?:\s+as\s+[A-Za-z_][A-Za-z0-9_]*)?\s*$"
)
_SHA256_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_REQUIRED_PROJECT_DEPENDENCY_MODULES = frozenset(
    {
        "_duckdb",
        "app.features.live_strategy_library",
        "app.features.live_scenario_lab",
        "app.features.live_strategy_diagnostics_v1_application",
        "app.features.strategy_library_application",
        "app.features.scenario_lab_application",
        "duckdb",
        "persistence.models_training",
        "sqlalchemy.dialects.sqlite.pysqlite",
        "stock_sim.release.strategy_diagnostics_v1_release_fixture",
        "strategy_diagnostics.application",
        "strategy_diagnostics.diagnostic_evidence_storage",
        "strategy_diagnostics.live_minute_scenario_native_strategy",
        "strategy_diagnostics.market_paths",
        "strategy_diagnostics.persistence",
        "strategy_diagnostics.quentx_scenario_native_strategy",
        "strategy_diagnostics.strategy_inventory",
    }
)
_QML_FORBIDDEN_BACKEND_MODULE_PREFIXES = (
    "app.runtime_gateway",
    "app.controllers.trading_controller",
    "app.panels.market.trade_dialog",
    "app.services.trading_service",
    "core.order",
    "services.order_service",
    "services.runtime_command_service",
    "stock_sim.core.order",
    "stock_sim.services.order_service",
    "stock_sim.services.runtime_command_service",
    "strategy_diagnostics.ptrade_host_worker",
)
_FORBIDDEN_NETWORK_MODULE_PREFIXES = (
    "aiohttp",
    "app.services.redis_subscriber",
    "http.server",
    "httpx",
    "pydoc",
    "redis",
    "requests",
    "socketserver",
    "urllib3",
    "websockets",
    "wsgiref.simple_server",
    "xmlrpc.server",
)
_WIDGETS_FORBIDDEN_SEAM_MODULE_PREFIXES = (
    "app.app_context",
    "app.event_bridge",
    "app.features",
)
_QML_NUITKA_EXCLUDED_MODULE_PREFIXES = (
    "app.legacy_panel_context",
    "app.controllers",
    "app.panels",
    "app.runtime_gateway",
    "app.services",
    "app.ui.adapters",
    *_FORBIDDEN_NETWORK_MODULE_PREFIXES,
    "core.order",
    "services.order_service",
    "services.runtime_command_service",
    "stock_sim.core.order",
    "stock_sim.services.order_service",
    "stock_sim.services.runtime_command_service",
)
_QML_ALLOWED_APP_MODULE_PREFIXES = (
    "app.app_context",
    "app.core_dto",
    "app.diagnostics_runtime_gateway",
    "app.event_bridge",
    "app.features",
    "app.i18n",
    "app.journey_recovery",
    "app.state",
    "app.ui.accessibility",
    "app.ui.docking",
    "app.ui.evidence_chart",
    "app.ui.journey_workspace",
    "app.ui.main_window",
    "app.ui.ui_refresh",
)
_PRODUCTION_JOURNEY_PATH = (
    "DiagnosticsApplication",
    "FileBackedV1Persistence",
    "LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter",
    "LiveStrategyLibraryAdapter",
    "LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter",
    "LiveScenarioLabAdapter",
    "LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter",
    "LiveDiagnosticTasksAdapter",
    "LiveStrategyDiagnosticsV1ApplicationAdapter",
    "EventBridge",
    "LiveRunMonitoringAdapter",
    "LiveEvidenceAndFindingsAdapter",
    "LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter",
    "LiveSystemHealthAdapter",
    "JourneyWorkspaceHost",
)
_ACTIVE_JOURNEY_ROUTES = (
    "strategy_library",
    "scenario_lab",
    "diagnostic_tasks",
    "run_monitoring",
    "evidence_and_findings",
    "system_health",
)
_UIA_CHECKPOINT_BINDINGS = {
    "loading": ("runMonitoringRouteNavigation", "loading"),
    "empty": ("diagnosticTasksRouteNavigation", "empty"),
    "failed": ("failedCampaignNodeAttemptHistory", "failed"),
    "recovering": ("diagnosticTaskRecoveryProgressStatus", "recover"),
    "partial": ("systemHealthAccessibleStatus", "partial"),
    "disconnected": ("systemHealthAccessibleStatus", "disconnected"),
    "stale": ("systemHealthAccessibleStatus", "stale"),
    "completed": ("runMonitoringRouteNavigation", "terminal"),
}
_RUNTIME_SAFETY_STAGES = ("running", "reopened_terminal")
_RUNTIME_SAFETY_COVERAGE = frozenset(
    {
        "qml_object_tree",
        "accessible_interface",
        "action_interface",
        "selection_interface",
        "value_interface",
        "shortcut_properties",
        "qt_signal_surface",
        "command_binding_properties",
        "context_menu_roles",
        "hidden_automation_peers",
    }
)
_WAVE2_RELEASE_FIXTURE_KIND = "authoritative_writable_wave3_inputs"
_WAVE3_ACCEPTED_SETUP_COMMAND_KINDS = (
    "compare_formal_strategy_set",
    "select_formal_strategy_set",
    "create_recipe_draft",
    "validate_recipe_draft",
    "approve_recipe",
    "materialize_reference_path",
    "compose_formal_scenario_set",
    "resolve_execution_assumptions",
    "select_formal_scenario_set",
)
_WAVE2_ACCEPTED_COMMAND_KINDS = (
    "create_diagnostic_task",
    "revise_configuration",
    "validate_configuration",
    "approve_configuration",
    "start_formal_diagnostic_campaign",
)
_EXPECTED_CLEAN_ROOM_JOURNEY = (
    (
        "launched_terminal_run",
        "run_monitoring",
        "terminal",
        "ready",
        "fresh",
        "fresh",
    ),
    (
        "terminal_evidence",
        "evidence_and_findings",
        "terminal",
        "ready",
        "fresh",
        "fresh",
    ),
    (
        "disconnected_run",
        "run_monitoring",
        "terminal",
        "ready",
        "disconnected",
        "fresh",
    ),
    (
        "disconnected_evidence",
        "evidence_and_findings",
        "terminal",
        "ready",
        "disconnected",
        "disconnected",
    ),
    (
        "reconnected_pending_run",
        "run_monitoring",
        "terminal",
        "ready",
        "stale",
        "stale",
    ),
    (
        "reconnected_pending_evidence",
        "evidence_and_findings",
        "terminal",
        "ready",
        "stale",
        "stale",
    ),
    (
        "reconnected_terminal_run",
        "run_monitoring",
        "terminal",
        "ready",
        "fresh",
        "stale",
    ),
    (
        "reconnected_evidence",
        "evidence_and_findings",
        "terminal",
        "ready",
        "fresh",
        "fresh",
    ),
    (
        "remounted_terminal_run",
        "run_monitoring",
        "terminal",
        "ready",
        "fresh",
        "fresh",
    ),
    (
        "remounted_terminal_evidence",
        "evidence_and_findings",
        "terminal",
        "ready",
        "fresh",
        "fresh",
    ),
)
_EXPECTED_CONNECTION_TRANSITIONS = (
    "connected",
    "disconnected",
    "reconnected",
    "remounted",
    "closed",
)
_EXPECTED_APPLICATION_READ_MODEL_INTERFACE = (
    "StrategyDiagnosticsV1ApplicationReadModel/1.0"
)
_EXPECTED_ACTIVE_FEATURE_INTERFACES = (
    "StrategyLibraryFeature/1.0",
    "ScenarioLabFeature/1.0",
    "DiagnosticTasksFeature/1.0",
    "RunMonitoringFeature/1.2",
    "EvidenceAndFindingsFeature/1.1",
    "SystemHealthFeature/1.0",
)
REAL_V1_IDENTITY_FIELDS = (
    "campaign_identity",
    "case_identity",
    "run_identity",
    "strategy_identity",
    "approved_recipe_identity",
    "evidence_package_identity",
    "reproduction_manifest_identity",
)
_CROSS_LANE_STABLE_FIELDS = (
    "fixture_kind",
    "strategy_selection_created_after_install",
    "recipe_draft_created_after_install",
    "recipe_validation_created_after_install",
    "recipe_approval_created_after_install",
    "reference_path_materialized_after_install",
    "scenario_set_created_after_install",
    "scenario_selection_created_after_install",
    "terminal_case_manifest_binding_verified",
    "terminal_campaign_node_lifecycle",
    "installed_setup_ledger_reopened",
    "installed_setup_command_kinds",
    "task_created_after_install",
    "campaign_created_after_install",
    "accepted_command_kinds",
    "writable_persistence_verified",
    "application_reopened",
    "background_continuation_verified",
    "task_cancel_order_isolation_verified",
    "persistence_kind",
    "persistence_reopened",
    "application_read_model_interface",
    "active_feature_interfaces",
    "campaign_status",
    "run_status",
    "evidence_status",
    "keyboard_navigation_verified",
    "accessibility_preferences_verified",
    "old_generation_rejected",
    "authoritative_reconnect_verified",
    "routes_rendered",
    "production_path",
    "connection_transitions",
    "manual_trading_action_count",
    "read_only_context_visible",
    "clean_exit",
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
class LockedBuildArtifact:
    filename: str
    url: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class LockedExecutable:
    relative_path: str
    version: str
    version_line: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class LockedNativeToolchain:
    compiler_family: str
    compiler_distribution: str
    nuitka_install_tree_file_count: int
    nuitka_install_tree_total_bytes: int
    nuitka_install_tree_sha256: str
    compiler_tree_file_count: int
    compiler_tree_total_bytes: int
    compiler_tree_sha256: str
    nuitka_source: LockedBuildArtifact
    compiler_archive: LockedBuildArtifact
    compiler: LockedExecutable
    binary_inspector: LockedExecutable


@dataclass(frozen=True, slots=True)
class FrontendV2ToolchainLock:
    schema_version: int
    platform: LockedPlatform
    toolchain: ToolchainVersions
    native_toolchain: LockedNativeToolchain
    invalidation_policy: str
    production_dependencies: dict[str, str] = field(default_factory=dict)
    build_dependencies: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LockedNativeToolchainPaths:
    nuitka_source: Path
    compiler_archive: Path
    compiler: Path
    binary_inspector: Path


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
    native_toolchain_attestation: Path
    isolated_pycache_root: Path
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
    dependency_reports: tuple[ArtifactChecksum, ...]
    native_toolchain_attestations: tuple[ArtifactChecksum, ...]
    formal_strategy_sources: tuple[ArtifactChecksum, ...]


@dataclass(frozen=True, slots=True)
class RendererLaneEvidence:
    lane: str
    certification_scope: str
    graphics_api: str
    journey_stages: tuple[str, ...]
    routes_rendered: tuple[str, ...]
    production_path: tuple[str, ...]
    fixture_kind: str
    strategy_selection_created_after_install: bool
    recipe_draft_created_after_install: bool
    recipe_validation_created_after_install: bool
    recipe_approval_created_after_install: bool
    reference_path_materialized_after_install: bool
    scenario_set_created_after_install: bool
    scenario_selection_created_after_install: bool
    strategy_selection_context_identity: str
    recipe_draft_identity: str
    recipe_validation_identity: str
    materialization_task_handle_identity: str
    materialized_path_identity: str
    materialized_scenario_identity: str
    terminal_campaign_case_identity: str
    terminal_selected_campaign_case_identity: str
    terminal_node_market_scenario_identity: str
    terminal_campaign_node_lifecycle: str
    terminal_case_manifest_binding_verified: bool
    installed_setup_ledger_reopened: bool
    reopened_installed_setup_ledger: dict[str, tuple[str, ...]]
    formal_scenario_set_identity: str
    scenario_selection_context_identity: str
    setup_selection_context_identity: str
    installed_setup_command_kinds: tuple[str, ...]
    installed_recipe_draft_identities: tuple[str, ...]
    installed_recipe_validation_identities: tuple[str, ...]
    installed_approved_recipe_identities: tuple[str, ...]
    installed_materialization_task_handle_identities: tuple[str, ...]
    installed_materialized_path_identities: tuple[str, ...]
    installed_materialized_scenario_identities: tuple[str, ...]
    task_created_after_install: bool
    campaign_created_after_install: bool
    diagnostic_task_identity: str
    accepted_command_kinds: tuple[str, ...]
    task_handle_identities: tuple[str, ...]
    writable_persistence_verified: bool
    application_reopened: bool
    background_continuation_verified: bool
    task_cancel_order_isolation_verified: bool
    campaign_identity: str
    case_identity: str
    run_identity: str
    strategy_identity: str
    approved_recipe_identity: str
    evidence_package_identity: str
    reproduction_manifest_identity: str
    artifact_hashes: tuple[str, ...]
    persistence_kind: str
    persistence_reopened: bool
    application_read_model_interface: str
    active_feature_interfaces: tuple[str, ...]
    campaign_status: str
    run_status: str
    evidence_status: str
    expected_identity_graph: tuple[str, ...]
    feature_identity_graph: tuple[str, ...]
    qml_identity_graph_checkpoints: dict[str, tuple[str, ...]]
    evidence_identity_sets: dict[str, tuple[str, ...]]
    persisted_manifest_identities: tuple[str, ...]
    persisted_run_identities: tuple[str, ...]
    raw_artifact_hashes: tuple[str, ...]
    keyboard_navigation_verified: bool
    accessibility_preferences_verified: bool
    accessibility_announcements: tuple[str, ...]
    old_generation_rejected: bool
    authoritative_reconnect_verified: bool
    queued_state_observed: bool
    running_state_observed: bool
    partial_state_observed: bool
    controlled_failure_observed: bool
    safe_failure_reason_verified: bool
    retry_idempotency_verified: bool
    duplicate_work_count: int
    terminal_completion_observed: bool
    system_health_context_verified: bool
    system_health_identity_graph: tuple[str, ...]
    system_health_accessibility_verified: bool
    focus_restoration_verified: bool
    connection_transitions: tuple[str, ...]
    manual_trading_action_count: int
    read_only_context_visible: bool
    clean_exit: bool
    errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RendererGateEvidence:
    source_commit: str
    certification_scope: str
    created_at: str
    environment_identity: str
    toolchain_identity: str
    hardware: RendererLaneEvidence
    software: RendererLaneEvidence


@dataclass(frozen=True, slots=True)
class ReleaseBuildResult:
    source_commit: str
    output_root: str
    safety: NoManualTradingGateReport
    packages: PackageEvidence
    renderers: RendererGateEvidence
    renderer_gate_report: ArtifactChecksum
    archives: tuple[ArtifactChecksum, ...]


@dataclass(frozen=True, slots=True)
class CleanRoomCertification:
    source_commit: str
    qml_archive_sha256: str
    widgets_archive_sha256: str
    clean_room_report_sha256: str
    mandatory_release_gates_sha256: str
    operating_system: str
    architecture: str
    certified_at: str


@dataclass(frozen=True, slots=True)
class AccessibilityGateEvidence:
    issue_number: int
    issue_url: str
    source_commit: str
    status: str
    test_count: int
    junit_sha256: str


@dataclass(frozen=True, slots=True)
class SafetyGateEvidence:
    issue_number: int
    issue_url: str
    source_commit: str
    status: str
    report_sha256: str


@dataclass(frozen=True, slots=True)
class PerformanceGateEvidence:
    issue_number: int
    issue_url: str
    source_commit: str
    status: str
    fixture_archive_sha256: str
    certification_sha256: str
    hardware_report_sha256: str
    software_report_sha256: str
    safety_report_sha256: str


@dataclass(frozen=True, slots=True)
class MandatoryReleaseGateEvidence:
    source_commit: str
    toolchain_identity: str
    accessibility: AccessibilityGateEvidence
    safety: SafetyGateEvidence
    performance: PerformanceGateEvidence


@dataclass(frozen=True, slots=True)
class _CleanRoomScreenshotArtifact:
    state: str
    relative_path: str
    sha256: str
    source_path: Path


_REQUIRED_ACCESSIBILITY_TESTS = frozenset(
    (
        (
            "test_narrator_sees_named_state_progress_commands_and_"
            "no_trading_actions"
        ),
        (
            "test_keyboard_route_actions_restore_meaningful_visible_"
            "focus_immediately"
        ),
        (
            "test_evidence_semantics_keep_chart_narrative_and_table_"
            "on_one_revision"
        ),
        (
            "test_state_changes_remain_distinguishable_and_repair_"
            "focus_without_color"
        ),
        (
            "test_remount_reestablishes_meaningful_keyboard_focus_"
            "without_state_mutation"
        ),
        (
            "test_200_percent_text_scale_scrolls_focused_content_and_"
            "reduces_motion"
        ),
        (
            "test_shared_default_and_high_contrast_tokens_meet_wcag_"
            "aa_ratios"
        ),
        (
            "test_accessible_journey_renders_at_200_percent_in_"
            "supported_lanes[software-Software]"
        ),
        (
            "test_accessible_journey_renders_at_200_percent_in_"
            "supported_lanes[hardware-Direct3D11]"
        ),
        (
            "test_file_backed_formal_campaign_reopens_and_traces_exact_"
            "ids_through_qml"
        ),
        (
            "test_release_evidence_records_verified_source_and_"
            "toolchain"
        ),
    )
)


EXPECTED_TOOLCHAIN = ToolchainVersions(
    python="3.11.9",
    pyside6="6.9.1",
    qt="6.9.1",
    numpy="2.3.1",
    nuitka="4.1.3",
)

EXPECTED_PRODUCTION_DEPENDENCIES = {
    "PySide6": "6.9.1",
    "PySide6-Addons": "6.9.1",
    "PySide6-Essentials": "6.9.1",
    "SQLAlchemy": "2.0.49",
    "asn1crypto": "1.5.1",
    "duckdb": "1.5.4",
    "greenlet": "3.4.0",
    "numpy": "2.3.1",
    "pg8000": "1.31.5",
    "psycopg": "3.2.9",
    "psycopg-binary": "3.2.9",
    "pydantic": "1.10.26",
    "pyqtgraph": "0.13.7",
    "python-dateutil": "2.9.0.post0",
    "redis": "7.4.0",
    "scramp": "1.4.8",
    "shiboken6": "6.9.1",
    "six": "1.17.0",
    "typing-extensions": "4.15.0",
    "tzdata": "2025.2",
}
EXPECTED_BUILD_DEPENDENCIES = {
    "Nuitka": "4.1.3",
    "ordered-set": "4.1.0",
    "zstandard": "0.25.0",
}


def load_toolchain_lock(
    path: Path = TOOLCHAIN_LOCK_PATH,
) -> FrontendV2ToolchainLock:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    platform = payload["platform"]
    toolchain = payload["toolchain"]
    native_toolchain = payload["native_toolchain"]

    def locked_artifact(value: Mapping[str, Any]) -> LockedBuildArtifact:
        return LockedBuildArtifact(
            filename=str(value["filename"]),
            url=str(value["url"]),
            sha256=str(value["sha256"]),
            size_bytes=int(value["size_bytes"]),
        )

    def locked_executable(value: Mapping[str, Any]) -> LockedExecutable:
        return LockedExecutable(
            relative_path=str(value["relative_path"]),
            version=str(value["version"]),
            version_line=str(value["version_line"]),
            sha256=str(value["sha256"]),
            size_bytes=int(value["size_bytes"]),
        )

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
        native_toolchain=LockedNativeToolchain(
            compiler_family=str(native_toolchain["compiler_family"]),
            compiler_distribution=str(
                native_toolchain["compiler_distribution"]
            ),
            nuitka_install_tree_file_count=int(
                native_toolchain["nuitka_install_tree_file_count"]
            ),
            nuitka_install_tree_total_bytes=int(
                native_toolchain["nuitka_install_tree_total_bytes"]
            ),
            nuitka_install_tree_sha256=str(
                native_toolchain["nuitka_install_tree_sha256"]
            ),
            compiler_tree_file_count=int(
                native_toolchain["compiler_tree_file_count"]
            ),
            compiler_tree_total_bytes=int(
                native_toolchain["compiler_tree_total_bytes"]
            ),
            compiler_tree_sha256=str(
                native_toolchain["compiler_tree_sha256"]
            ),
            nuitka_source=locked_artifact(
                native_toolchain["nuitka_source"]
            ),
            compiler_archive=locked_artifact(
                native_toolchain["compiler_archive"]
            ),
            compiler=locked_executable(native_toolchain["compiler"]),
            binary_inspector=locked_executable(
                native_toolchain["binary_inspector"]
            ),
        ),
        invalidation_policy=str(payload["invalidation_policy"]),
        production_dependencies={
            str(name): str(version)
            for name, version in payload.get(
                "production_dependencies",
                {},
            ).items()
        },
        build_dependencies={
            str(name): str(version)
            for name, version in payload.get(
                "build_dependencies",
                {},
            ).items()
        },
    )


def running_locked_dependencies(
    lock: FrontendV2ToolchainLock,
) -> tuple[dict[str, str], dict[str, str]]:
    def observed(locked: dict[str, str]) -> dict[str, str]:
        return {
            name: importlib.metadata.version(name)
            for name in sorted(locked)
        }

    return (
        observed(lock.production_dependencies),
        observed(lock.build_dependencies),
    )


def running_toolchain() -> ToolchainVersions:
    import numpy
    import PySide6
    from PySide6.QtCore import qVersion

    return ToolchainVersions(
        python=".".join(str(part) for part in sys.version_info[:3]),
        pyside6=PySide6.__version__,
        qt=qVersion(),
        numpy=numpy.__version__,
        nuitka=importlib.metadata.version("Nuitka"),
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
    observed_production, observed_build = running_locked_dependencies(lock)
    for dependency_kind, expected_dependencies, actual_dependencies in (
        (
            "production_dependency",
            lock.production_dependencies,
            observed_production,
        ),
        (
            "build_dependency",
            lock.build_dependencies,
            observed_build,
        ),
    ):
        for name, expected in sorted(expected_dependencies.items()):
            actual = actual_dependencies.get(name)
            if actual != expected:
                mismatches.append(
                    f"{dependency_kind}[{name}]: expected {expected}, "
                    f"observed {actual}"
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
            "native_toolchain": asdict(lock.native_toolchain),
            "production_dependencies": dict(
                sorted(lock.production_dependencies.items())
            ),
            "build_dependencies": dict(
                sorted(lock.build_dependencies.items())
            ),
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
    qml_files = qml_source_inventory(qml_root)
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
            (
                f"--include-data-files={TOOLCHAIN_LOCK_PATH}="
                "stock_sim/release/frontend_v2_toolchain.lock.json"
            ),
            "--include-package=psycopg",
            "--include-package=psycopg_binary",
            *(
                f"--nofollow-import-to={module_prefix}"
                for module_prefix in (
                    *_WIDGETS_FORBIDDEN_SEAM_MODULE_PREFIXES,
                    *_FORBIDDEN_NETWORK_MODULE_PREFIXES,
                )
            ),
            "--nofollow-import-to=app.runtime_gateway",
            "--nofollow-import-to=app.ui.journey_workspace",
            "--nofollow-import-to=app.ui.ui_refresh",
            "--nofollow-import-to=app.controllers.trading_controller",
            "--nofollow-import-to=app.services.trading_service",
            "--nofollow-import-to=app.panels.market.trade_dialog",
            "--nofollow-import-to=core.order",
            "--nofollow-import-to=services.order_service",
            "--nofollow-import-to=services.runtime_command_service",
            "--nofollow-import-to=stock_sim.core.order",
            "--nofollow-import-to=stock_sim.services.order_service",
            "--nofollow-import-to=stock_sim.services.runtime_command_service",
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
            (
                f"--include-data-files={TOOLCHAIN_LOCK_PATH}="
                "stock_sim/release/frontend_v2_toolchain.lock.json"
            ),
            (
                "--include-data-files="
                f"{PROJECT_ROOT / 'stock_sim/release/wave4_daily_observation_ledger.schema.json'}="
                "stock_sim/release/wave4_daily_observation_ledger.schema.json"
            ),
            "--include-module=stock_sim.release.frontend_v2_performance_runtime",
            "--include-module=stock_sim.release.wave4_rollback_probe",
            "--include-module=stock_sim.release.wave4_legacy_inventory",
            "--include-module=stock_sim.release.wave4_observation_ledger",
            (
                "--include-module=stock_sim.release."
                "strategy_diagnostics_v1_release_fixture"
            ),
            "--include-module=app.features.live_strategy_diagnostics_v1_application",
            "--include-module=app.features.live_strategy_library",
            "--include-module=app.features.live_scenario_lab",
            "--include-module=app.features.strategy_library_application",
            "--include-module=app.features.scenario_lab_application",
            "--include-module=strategy_diagnostics.application",
            "--include-module=strategy_diagnostics.persistence",
            "--include-module=strategy_diagnostics.market_paths",
            "--include-module=strategy_diagnostics.diagnostic_evidence_storage",
            "--include-module=strategy_diagnostics.quentx_scenario_native_strategy",
            "--include-module=strategy_diagnostics.live_minute_scenario_native_strategy",
            "--include-module=strategy_diagnostics.strategy_inventory",
            *(
                f"--include-data-files={source}={destination}"
                for source, destination
                in _FORMAL_STRATEGY_SOURCE_DATA_FILES
            ),
            "--include-module=sqlalchemy.dialects.sqlite.pysqlite",
            "--include-package=duckdb",
            "--include-module=_duckdb",
            *(
                f"--nofollow-import-to={module_prefix}"
                for module_prefix in _QML_NUITKA_EXCLUDED_MODULE_PREFIXES
            ),
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
    entry_point = entry_point.resolve()
    output_root = output_root.resolve()
    nuitka_report = output_root / "nuitka-report.xml"
    isolated_pycache_root = output_root / "python-pycache"
    command = (
        sys.executable,
        "-I",
        "-B",
        "-X",
        f"pycache_prefix={isolated_pycache_root}",
        "-m",
        "nuitka",
        str(entry_point),
        "--standalone",
        "--mingw64",
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
        native_toolchain_attestation=(
            output_root / "native-toolchain-attestation.json"
        ),
        isolated_pycache_root=isolated_pycache_root,
        nuitka_command=command,
        source_imports=source_imports,
        resolved_qml_dependencies=resolved_qml_dependencies,
    )


def deploy_scanned_qml_runtime(
    plan: PackageBuildPlan,
    *,
    objdump_path: Path | None = None,
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

    if objdump_path is None:
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


def _nuitka_downloads_cache_root() -> Path:
    downloads_cache = os.environ.get("NUITKA_CACHE_DIR_DOWNLOADS")
    nuitka_cache = os.environ.get("NUITKA_CACHE_DIR")
    if downloads_cache:
        cache_root = Path(downloads_cache)
    elif nuitka_cache:
        cache_root = Path(nuitka_cache) / "downloads"
    else:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            raise FileNotFoundError(
                "Nuitka cache root and LOCALAPPDATA are unavailable"
            )
        cache_root = (
            Path(local_app_data)
            / "Nuitka"
            / "Nuitka"
            / "Cache"
            / "downloads"
        )
    return cache_root.resolve()


def _resolve_locked_native_toolchain_paths(
    lock: FrontendV2ToolchainLock,
) -> LockedNativeToolchainPaths:
    nuitka_source_value = os.environ.get(
        "FRONTEND_V2_NUITKA_SOURCE_ARCHIVE"
    )
    if not nuitka_source_value:
        raise FileNotFoundError(
            "FRONTEND_V2_NUITKA_SOURCE_ARCHIVE is required for a locked "
            "production build"
        )
    native = lock.native_toolchain
    distribution_root = (
        _nuitka_downloads_cache_root()
        / "gcc"
        / lock.platform.architecture
        / native.compiler_distribution
    )
    return LockedNativeToolchainPaths(
        nuitka_source=Path(nuitka_source_value).resolve(),
        compiler_archive=(
            distribution_root / native.compiler_archive.filename
        ).resolve(),
        compiler=(
            distribution_root / Path(native.compiler.relative_path)
        ).resolve(),
        binary_inspector=(
            distribution_root
            / Path(native.binary_inspector.relative_path)
        ).resolve(),
    )


def _verify_locked_file(
    *,
    path: Path,
    filename: str | None,
    size_bytes: int,
    sha256: str,
    label: str,
) -> None:
    if filename is not None and path.name != filename:
        raise RuntimeError(
            f"Locked {label} filename mismatch: expected {filename}, "
            f"observed {path.name}"
        )
    if not path.is_file():
        raise FileNotFoundError(f"Locked {label} is unavailable: {path}")
    observed_size = path.stat().st_size
    if observed_size != size_bytes:
        raise RuntimeError(
            f"Locked {label} size mismatch: expected {size_bytes}, "
            f"observed {observed_size}"
        )
    observed_sha256 = _sha256_path(path)
    if observed_sha256 != sha256:
        raise RuntimeError(
            f"Locked {label} SHA-256 mismatch: expected {sha256}, "
            f"observed {observed_sha256}"
        )


def _verify_locked_executable(
    *,
    path: Path,
    locked: LockedExecutable,
    label: str,
) -> None:
    _verify_locked_file(
        path=path,
        filename=Path(locked.relative_path).name,
        size_bytes=locked.size_bytes,
        sha256=locked.sha256,
        label=label,
    )
    completed = subprocess.run(
        (str(path), "--version"),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    version_lines = completed.stdout.splitlines()
    if not version_lines:
        raise RuntimeError(f"Locked {label} did not report a version")
    first_line = version_lines[0].strip()
    if first_line != locked.version_line or locked.version not in first_line:
        raise RuntimeError(
            f"Locked {label} version mismatch: expected "
            f"{locked.version_line!r}, observed {first_line!r}"
        )


def _compiler_tree_identity(root: Path) -> tuple[int, int, str]:
    files = tuple(
        sorted(
            (path for path in root.rglob("*") if path.is_file()),
            key=lambda path: path.relative_to(root).as_posix(),
        )
    )
    tree_hasher = hashlib.sha256()
    total_bytes = 0
    for path in files:
        relative_path = path.relative_to(root).as_posix()
        size_bytes = path.stat().st_size
        total_bytes += size_bytes
        tree_hasher.update(
            (
                f"{_sha256_path(path)} {size_bytes} {relative_path}\n"
            ).encode("utf-8")
        )
    return len(files), total_bytes, f"sha256:{tree_hasher.hexdigest()}"


def _running_nuitka_installation_identity(
) -> tuple[int, int, str, str, str]:
    distribution = importlib.metadata.distribution("Nuitka")
    package_root = Path(distribution.locate_file("nuitka")).resolve()
    package_files = tuple(
        sorted(
            (
                path
                for path in package_root.rglob("*")
                if path.is_file()
                and "__pycache__" not in path.parts
                and path.suffix.casefold() not in {".pyc", ".pyo"}
            ),
            key=lambda path: path.relative_to(package_root).as_posix(),
        )
    )
    tree_hasher = hashlib.sha256()
    total_bytes = 0
    for path in package_files:
        relative_path = path.relative_to(package_root).as_posix()
        size_bytes = path.stat().st_size
        total_bytes += size_bytes
        tree_hasher.update(
            (
                f"{_sha256_path(path)} {size_bytes} {relative_path}\n"
            ).encode("utf-8")
        )

    direct_url_text = distribution.read_text("direct_url.json")
    if direct_url_text is None:
        raise RuntimeError(
            "Locked Nuitka installation has no direct_url archive identity"
        )
    direct_url = json.loads(direct_url_text)
    archive_hashes = direct_url.get("archive_info", {}).get("hashes", {})
    source_sha256 = str(archive_hashes.get("sha256", ""))
    source_filename = Path(
        unquote(urlparse(str(direct_url.get("url", ""))).path)
    ).name
    return (
        len(package_files),
        total_bytes,
        f"sha256:{tree_hasher.hexdigest()}",
        source_filename,
        f"sha256:{source_sha256}",
    )


def verify_locked_native_toolchain(
    lock: FrontendV2ToolchainLock,
) -> LockedNativeToolchainPaths:
    native = lock.native_toolchain
    if native.compiler_family != "MinGW64":
        raise RuntimeError(
            "Frontend V2 production compiler family must be MinGW64"
        )
    paths = _resolve_locked_native_toolchain_paths(lock)
    observed_nuitka_identity = _running_nuitka_installation_identity()
    expected_nuitka_identity = (
        native.nuitka_install_tree_file_count,
        native.nuitka_install_tree_total_bytes,
        native.nuitka_install_tree_sha256,
        native.nuitka_source.filename,
        native.nuitka_source.sha256,
    )
    if observed_nuitka_identity != expected_nuitka_identity:
        raise RuntimeError(
            "Locked Nuitka installation identity mismatch: expected "
            f"{expected_nuitka_identity!r}, observed "
            f"{observed_nuitka_identity!r}"
        )
    for path, artifact, label in (
        (paths.nuitka_source, native.nuitka_source, "Nuitka source archive"),
        (
            paths.compiler_archive,
            native.compiler_archive,
            "compiler archive",
        ),
    ):
        _verify_locked_file(
            path=path,
            filename=artifact.filename,
            size_bytes=artifact.size_bytes,
            sha256=artifact.sha256,
            label=label,
        )
    _verify_locked_executable(
        path=paths.compiler,
        locked=native.compiler,
        label="compiler",
    )
    _verify_locked_executable(
        path=paths.binary_inspector,
        locked=native.binary_inspector,
        label="binary inspector",
    )
    compiler_tree_root = paths.compiler.parent.parent
    observed_tree_identity = _compiler_tree_identity(compiler_tree_root)
    expected_tree_identity = (
        native.compiler_tree_file_count,
        native.compiler_tree_total_bytes,
        native.compiler_tree_sha256,
    )
    if observed_tree_identity != expected_tree_identity:
        raise RuntimeError(
            "Locked compiler tree identity mismatch: expected "
            f"{expected_tree_identity!r}, observed {observed_tree_identity!r}"
        )
    return paths


def _find_objdump(
    lock: FrontendV2ToolchainLock | None = None,
) -> Path:
    retained_lock = lock or load_toolchain_lock()
    paths = _resolve_locked_native_toolchain_paths(retained_lock)
    _verify_locked_executable(
        path=paths.binary_inspector,
        locked=retained_lock.native_toolchain.binary_inspector,
        label="binary inspector",
    )
    return paths.binary_inspector


def _expected_native_toolchain_attestation_payload(
    *,
    package_kind: PackageKind,
    source_commit: str,
    report_checksum: ArtifactChecksum,
    distribution_identity: Mapping[str, Any],
    archive_checksum: ArtifactChecksum,
    lock: FrontendV2ToolchainLock,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "package_kind": package_kind.value,
        "source_commit": source_commit,
        "toolchain_identity": toolchain_evidence_identity(lock),
        "nuitka_report": asdict(report_checksum),
        "distribution": dict(distribution_identity),
        "archive": asdict(archive_checksum),
        "native_toolchain": asdict(lock.native_toolchain),
    }


def _write_native_toolchain_attestation(
    *,
    plan: PackageBuildPlan,
    archive_checksum: ArtifactChecksum,
    lock: FrontendV2ToolchainLock,
) -> None:
    verify_locked_native_toolchain(lock)
    report_checksum = _checksum_file(plan.nuitka_report, plan.output_root)
    inventory = _inventory_package(plan)
    payload = _expected_native_toolchain_attestation_payload(
        package_kind=plan.kind,
        source_commit=plan.source_commit,
        report_checksum=report_checksum,
        distribution_identity={
            "file_count": inventory.file_count,
            "total_bytes": inventory.total_bytes,
            "tree_sha256": inventory.tree_sha256,
        },
        archive_checksum=archive_checksum,
        lock=lock,
    )
    plan.native_toolchain_attestation.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _verify_isolated_pycache_root(plan: PackageBuildPlan) -> None:
    plan.isolated_pycache_root.mkdir(parents=True, exist_ok=True)
    retained_files = tuple(
        sorted(
            (
                path
                for path in plan.isolated_pycache_root.rglob("*")
                if path.is_file()
            ),
            key=lambda path: path.relative_to(
                plan.isolated_pycache_root
            ).as_posix(),
        )
    )
    if retained_files:
        raise RuntimeError(
            "Nuitka isolated Python bytecode cache is not empty: "
            + ", ".join(
                path.relative_to(plan.isolated_pycache_root).as_posix()
                for path in retained_files
            )
        )


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
    archives: tuple[ArtifactChecksum, ArtifactChecksum],
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
    archives_by_kind: dict[PackageKind, ArtifactChecksum] = {}
    for kind in PackageKind:
        matches = tuple(
            archive
            for archive in archives
            if archive.relative_path.startswith(f"{kind.value}-")
            and archive.relative_path.endswith(".zip")
        )
        if len(matches) != 1:
            raise ValueError(
                f"Exactly one {kind.value} archive checksum is required"
            )
        archives_by_kind[kind] = matches[0]
    package_roots = {
        plan.output_root.parent.resolve()
        for plan in plans
    }
    if len(package_roots) != 1:
        raise ValueError("Package plans must share one package root")
    packages_root = package_roots.pop()
    dependency_reports = tuple(
        _checksum_file(plan.nuitka_report, packages_root)
        for plan in sorted(plans, key=lambda item: item.kind.value)
    )
    for plan in plans:
        inventory = (
            widgets_inventory
            if plan.kind is PackageKind.WIDGETS_ROLLBACK
            else qml_inventory
        )
        expected_attestation = _expected_native_toolchain_attestation_payload(
            package_kind=plan.kind,
            source_commit=plan.source_commit,
            report_checksum=_checksum_file(
                plan.nuitka_report,
                plan.output_root,
            ),
            distribution_identity={
                "file_count": inventory.file_count,
                "total_bytes": inventory.total_bytes,
                "tree_sha256": inventory.tree_sha256,
            },
            archive_checksum=archives_by_kind[plan.kind],
            lock=lock,
        )
        observed_attestation = _load_json_mapping(
            plan.native_toolchain_attestation
        )
        if observed_attestation != expected_attestation:
            raise RuntimeError(
                "Native toolchain attestation does not match the "
                f"production lock/report: {plan.kind.value}"
            )
    native_toolchain_attestations = tuple(
        _checksum_file(plan.native_toolchain_attestation, packages_root)
        for plan in sorted(plans, key=lambda item: item.kind.value)
    )
    qml_distribution = plans_by_kind[
        PackageKind.QML_JOURNEY
    ].distribution_dir
    formal_strategy_sources = tuple(
        _checksum_file(
            qml_distribution / binding.packaged_relative_path,
            packages_root,
        )
        for binding in FORMAL_STRATEGY_SOURCE_BINDINGS.values()
    )
    evidence = PackageEvidence(
        source_commit=source_commit,
        toolchain_identity=toolchain_evidence_identity(lock),
        widgets_rollback=widgets_inventory,
        qml_journey=qml_inventory,
        qml_delta_bytes=qml_delta_bytes,
        qml_delta_limit_bytes=MAX_QML_DELTA_BYTES,
        webengine_files=webengine_files,
        dependency_reports=dependency_reports,
        native_toolchain_attestations=native_toolchain_attestations,
        formal_strategy_sources=formal_strategy_sources,
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
        "dependency_reports": tuple(
            asdict(report) for report in dependency_reports
        ),
        "native_toolchain_attestations": tuple(
            asdict(attestation)
            for attestation in native_toolchain_attestations
        ),
        "formal_strategy_sources": tuple(
            asdict(source) for source in formal_strategy_sources
        ),
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


def _inventory_distribution(
    *,
    kind: PackageKind,
    source_commit: str,
    distribution_dir: Path,
) -> PackageInventory:
    files = tuple(
        _checksum_file(path, distribution_dir)
        for path in sorted(
            (
                candidate
                for candidate in distribution_dir.rglob("*")
                if candidate.is_file()
            ),
            key=lambda path: path.relative_to(distribution_dir).as_posix(),
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
        kind=kind,
        source_commit=source_commit,
        file_count=len(files),
        total_bytes=sum(checksum.size_bytes for checksum in files),
        tree_sha256=f"sha256:{tree_hasher.hexdigest()}",
        files=files,
    )


def _inventory_package(plan: PackageBuildPlan) -> PackageInventory:
    executable = plan.distribution_dir / plan.executable_name
    if not executable.is_file():
        raise FileNotFoundError(
            f"Package executable is unavailable: {executable}"
        )
    return _inventory_distribution(
        kind=plan.kind,
        source_commit=plan.source_commit,
        distribution_dir=plan.distribution_dir,
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


def _json_projection(value: Any) -> Any:
    return json.loads(
        json.dumps(value, sort_keys=True, default=_json_default)
    )


_REOPENED_SETUP_LEDGER_KEYS = (
    "recipe_drafts",
    "recipe_validations",
    "approved_recipes",
    "materialization_task_handles",
    "materialized_paths",
    "materialized_scenarios",
    "draft_validation_approval_bindings",
    "materialization_bindings",
    "campaign_case_bindings",
    "formal_scenario_sets",
    "scenario_selection_contexts",
    "scenario_selection_set_bindings",
    "strategy_selection_contexts",
    "setup_selection_contexts",
    "task_scenario_selection_contexts",
)


def _canonical_reopened_setup_ledger(
    value: object,
) -> dict[str, tuple[str, ...]] | None:
    if not isinstance(value, Mapping) or set(value) != set(
        _REOPENED_SETUP_LEDGER_KEYS
    ):
        return None
    ledger: dict[str, tuple[str, ...]] = {}
    for key in _REOPENED_SETUP_LEDGER_KEYS:
        entries = value.get(key)
        if not isinstance(entries, (list, tuple)) or any(
            not isinstance(entry, str) or not entry.strip()
            for entry in entries
        ):
            return None
        ledger[key] = tuple(entries)
    return ledger


def _expected_reopened_setup_ledger(
    payload: Mapping[str, Any],
) -> dict[str, tuple[str, ...]] | None:
    family_fields = (
        "installed_recipe_draft_identities",
        "installed_recipe_validation_identities",
        "installed_approved_recipe_identities",
        "installed_materialization_task_handle_identities",
        "installed_materialized_path_identities",
        "installed_materialized_scenario_identities",
    )
    family: dict[str, tuple[str, ...]] = {}
    for field_name in family_fields:
        values = payload.get(field_name)
        if (
            not isinstance(values, (list, tuple))
            or len(values) != 14
            or any(
                not isinstance(value, str) or not value.strip()
                for value in values
            )
        ):
            return None
        family[field_name] = tuple(values)
    singular_fields = (
        "formal_scenario_set_identity",
        "scenario_selection_context_identity",
        "strategy_selection_context_identity",
        "setup_selection_context_identity",
    )
    if any(
        not isinstance(payload.get(field_name), str)
        or not str(payload[field_name]).strip()
        for field_name in singular_fields
    ):
        return None
    drafts = family["installed_recipe_draft_identities"]
    validations = family["installed_recipe_validation_identities"]
    recipes = family["installed_approved_recipe_identities"]
    handles = family[
        "installed_materialization_task_handle_identities"
    ]
    paths = family["installed_materialized_path_identities"]
    cases = family["installed_materialized_scenario_identities"]
    formal_set = str(payload["formal_scenario_set_identity"])
    scenario_selection = str(
        payload["scenario_selection_context_identity"]
    )
    return {
        "recipe_drafts": tuple(sorted(drafts)),
        "recipe_validations": tuple(sorted(validations)),
        "approved_recipes": tuple(sorted(recipes)),
        "materialization_task_handles": tuple(sorted(handles)),
        "materialized_paths": tuple(sorted(paths)),
        "materialized_scenarios": tuple(sorted(cases)),
        "draft_validation_approval_bindings": tuple(
            sorted(
                "|".join(values)
                for values in zip(
                    drafts,
                    validations,
                    recipes,
                    strict=True,
                )
            )
        ),
        "materialization_bindings": tuple(
            sorted(
                "|".join(values)
                for values in zip(recipes, handles, paths, strict=True)
            )
        ),
        "campaign_case_bindings": tuple(
            sorted(
                "|".join(values)
                for values in zip(recipes, paths, cases, strict=True)
            )
        ),
        "formal_scenario_sets": (formal_set,),
        "scenario_selection_contexts": (scenario_selection,),
        "scenario_selection_set_bindings": (
            f"{scenario_selection}|{formal_set}",
        ),
        "strategy_selection_contexts": (
            str(payload["strategy_selection_context_identity"]),
        ),
        "setup_selection_contexts": (
            str(payload["setup_selection_context_identity"]),
        ),
        "task_scenario_selection_contexts": (scenario_selection,),
    }


def _installed_wave2_smoke_failures(
    payload: Mapping[str, Any],
    *,
    require_installed_window_scale: bool = True,
) -> tuple[str, ...]:
    failures: list[str] = []
    if payload.get("fixture_kind") != _WAVE2_RELEASE_FIXTURE_KIND:
        failures.append(
            "did not use the authoritative writable Wave 3 input fixture"
        )
    for field_name, message in (
        (
            "strategy_selection_created_after_install",
            "did not select the formal Strategy set after install",
        ),
        (
            "recipe_draft_created_after_install",
            "did not create a Scenario Recipe Draft after install",
        ),
        (
            "recipe_validation_created_after_install",
            "did not validate the Scenario Recipe Draft after install",
        ),
        (
            "recipe_approval_created_after_install",
            "did not approve the Scenario Recipe after install",
        ),
        (
            "reference_path_materialized_after_install",
            "did not materialize a Reference Market Path after install",
        ),
        (
            "scenario_set_created_after_install",
            "did not compose a Formal Scenario Set after install",
        ),
        (
            "scenario_selection_created_after_install",
            "did not select a Formal Scenario Set after install",
        ),
        (
            "task_created_after_install",
            "did not create a Diagnostic Task after install",
        ),
        (
            "campaign_created_after_install",
            "did not create a Formal Diagnostic Campaign after install",
        ),
        (
            "writable_persistence_verified",
            "did not verify writable persistence",
        ),
        (
            "application_reopened",
            "did not reopen the Application over persisted state",
        ),
        (
            "background_continuation_verified",
            "did not keep the Campaign nonterminal through route, "
            "disconnect, and Application-reopen recovery",
        ),
        (
            "task_cancel_order_isolation_verified",
            "did not verify Diagnostic Task cancel/order isolation",
        ),
    ):
        if payload.get(field_name) is not True:
            failures.append(message)
    setup_identity_messages = {
        "strategy_selection_context_identity": (
            "formal Strategy selection identity is unavailable"
        ),
        "recipe_draft_identity": "Scenario Recipe Draft identity is unavailable",
        "recipe_validation_identity": (
            "Scenario Recipe validation identity is unavailable"
        ),
        "approved_recipe_identity": (
            "approved Scenario Recipe identity is unavailable"
        ),
        "materialization_task_handle_identity": (
            "materialization TaskHandle identity is unavailable"
        ),
        "materialized_path_identity": (
            "materialized Reference Market Path identity is unavailable"
        ),
        "materialized_scenario_identity": (
            "materialized Scenario identity is unavailable"
        ),
        "formal_scenario_set_identity": (
            "Formal Scenario Set identity is unavailable"
        ),
        "scenario_selection_context_identity": (
            "formal Scenario selection identity is unavailable"
        ),
        "setup_selection_context_identity": (
            "Diagnostic setup selection identity is unavailable"
        ),
    }
    for field_name, message in setup_identity_messages.items():
        value = payload.get(field_name)
        if not isinstance(value, str) or not value.strip():
            failures.append(message)
    if tuple(payload.get("installed_setup_command_kinds", ())) != (
        _WAVE3_ACCEPTED_SETUP_COMMAND_KINDS
    ):
        failures.append(
            "did not accept the exact Strategy/Recipe/Path/Scenario setup "
            "command journey"
        )
    installed_identity_fields = (
        "installed_recipe_draft_identities",
        "installed_recipe_validation_identities",
        "installed_approved_recipe_identities",
        "installed_materialization_task_handle_identities",
        "installed_materialized_path_identities",
        "installed_materialized_scenario_identities",
    )
    installed_identities: dict[str, tuple[Any, ...]] = {}
    for field_name in installed_identity_fields:
        values = payload.get(field_name)
        if (
            not isinstance(values, (list, tuple))
            or len(values) != 14
            or any(not isinstance(value, str) or not value for value in values)
            or len(set(values)) != 14
        ):
            failures.append(
                f"{field_name} does not contain the complete 14-case "
                "installed formal Recipe family"
            )
            continue
        installed_identities[field_name] = tuple(values)
    for singular_field, collection_field in (
        ("recipe_draft_identity", "installed_recipe_draft_identities"),
        (
            "recipe_validation_identity",
            "installed_recipe_validation_identities",
        ),
        (
            "approved_recipe_identity",
            "installed_approved_recipe_identities",
        ),
        (
            "materialization_task_handle_identity",
            "installed_materialization_task_handle_identities",
        ),
        (
            "materialized_path_identity",
            "installed_materialized_path_identities",
        ),
        (
            "materialized_scenario_identity",
            "installed_materialized_scenario_identities",
        ),
    ):
        if payload.get(singular_field) not in installed_identities.get(
            collection_field,
            (),
        ):
            failures.append(
                f"{singular_field} is not bound to the installed formal "
                "Recipe family"
            )
    installed_recipe_ids = installed_identities.get(
        "installed_approved_recipe_identities",
        (),
    )
    approved_recipe_identity = payload.get("approved_recipe_identity")
    if approved_recipe_identity in installed_recipe_ids:
        selected_index = installed_recipe_ids.index(approved_recipe_identity)
        for singular_field, collection_field in (
            ("recipe_draft_identity", "installed_recipe_draft_identities"),
            (
                "recipe_validation_identity",
                "installed_recipe_validation_identities",
            ),
            (
                "materialization_task_handle_identity",
                "installed_materialization_task_handle_identities",
            ),
            (
                "materialized_path_identity",
                "installed_materialized_path_identities",
            ),
            (
                "materialized_scenario_identity",
                "installed_materialized_scenario_identities",
            ),
        ):
            values = installed_identities.get(collection_field, ())
            if (
                len(values) != 14
                or payload.get(singular_field) != values[selected_index]
            ):
                failures.append(
                    f"{singular_field} is not bound to the terminal "
                    "installed Recipe identity"
                )
    terminal_campaign_case_identity = payload.get(
        "terminal_campaign_case_identity"
    )
    terminal_selected_campaign_case_identity = payload.get(
        "terminal_selected_campaign_case_identity"
    )
    if (
        not isinstance(terminal_campaign_case_identity, str)
        or not terminal_campaign_case_identity.strip()
        or terminal_campaign_case_identity != payload.get("case_identity")
    ):
        failures.append(
            "terminal Manifest execution Case identity is not bound to "
            "the completed Campaign node"
        )
    if (
        not isinstance(terminal_selected_campaign_case_identity, str)
        or not terminal_selected_campaign_case_identity.strip()
        or terminal_selected_campaign_case_identity
        != payload.get("materialized_scenario_identity")
    ):
        failures.append(
            "terminal execution Case is not bound to the selected installed "
            "Campaign Case identity"
        )
    terminal_node_market_scenario_identity = payload.get(
        "terminal_node_market_scenario_identity"
    )
    if (
        not isinstance(terminal_node_market_scenario_identity, str)
        or not terminal_node_market_scenario_identity.strip()
        or terminal_node_market_scenario_identity
        != payload.get("materialized_path_identity")
    ):
        failures.append(
            "terminal Campaign node is not bound to the selected installed "
            "Reference Market Path identity"
        )
    if payload.get("terminal_campaign_node_lifecycle") != "completed":
        failures.append("terminal Campaign node is not completed")
    if payload.get("terminal_case_manifest_binding_verified") is not True:
        failures.append(
            "terminal Campaign Case to execution Case/Manifest binding was "
            "not verified"
        )
    reopened_setup_ledger = _canonical_reopened_setup_ledger(
        payload.get("reopened_installed_setup_ledger")
    )
    expected_setup_ledger = _expected_reopened_setup_ledger(payload)
    if (
        payload.get("installed_setup_ledger_reopened") is not True
        or reopened_setup_ledger is None
        or expected_setup_ledger is None
        or reopened_setup_ledger != expected_setup_ledger
    ):
        failures.append(
            "installed setup ledger was not authoritatively re-read after "
            "Application reopen"
        )
    raw_artifact_hashes = payload.get("raw_artifact_hashes")
    if (
        not isinstance(raw_artifact_hashes, (list, tuple))
        or not set(
            installed_identities.get(
                "installed_materialized_path_identities",
                (),
            )
        ).issubset(raw_artifact_hashes)
    ):
        failures.append(
            "installed materialized Reference Market Paths did not reach "
            "the persisted raw artifact inventory"
        )
    diagnostic_task_identity = payload.get("diagnostic_task_identity")
    if (
        not isinstance(diagnostic_task_identity, str)
        or not diagnostic_task_identity.strip()
    ):
        failures.append("Diagnostic Task identity is unavailable")
    if tuple(payload.get("accepted_command_kinds", ())) != (
        _WAVE2_ACCEPTED_COMMAND_KINDS
    ):
        failures.append(
            "did not accept the exact create/revise/validate/approve/start "
            "command journey"
        )
    task_handle_identities = payload.get("task_handle_identities")
    if (
        not isinstance(task_handle_identities, (list, tuple))
        or len(task_handle_identities) < 3
        or any(
            not isinstance(identity, str) or not identity.strip()
            for identity in task_handle_identities
        )
        or len(set(task_handle_identities)) != len(task_handle_identities)
    ):
        failures.append(
            "persistent TaskHandle identities are incomplete or invalid"
        )
    for field_name, label in (
        ("queued_state_observed", "queued task state"),
        ("running_state_observed", "running task state"),
        ("partial_state_observed", "partial task state"),
        ("controlled_failure_observed", "controlled task failure"),
        ("safe_failure_reason_verified", "safe failure reason"),
        ("retry_idempotency_verified", "idempotent task retry"),
        ("terminal_completion_observed", "terminal task completion"),
        ("system_health_context_verified", "System Health context"),
        (
            "system_health_accessibility_verified",
            "System Health accessibility",
        ),
        ("focus_restoration_verified", "route focus restoration"),
    ):
        if payload.get(field_name) is not True:
            failures.append(f"{label} was not verified")
    if payload.get("duplicate_work_count") != 0:
        failures.append("Diagnostic Task retry produced duplicate work")
    if require_installed_window_scale:
        accessibility_checkpoints = payload.get("accessibility_checkpoints")
        if (
            not isinstance(accessibility_checkpoints, (list, tuple))
            or len(accessibility_checkpoints) < 8
            or any(
                not isinstance(checkpoint, Mapping)
                or not isinstance(
                    checkpoint.get("window_device_pixel_ratio"),
                    (int, float),
                )
                or not math.isfinite(
                    float(checkpoint.get("window_device_pixel_ratio", 0))
                )
                or float(checkpoint.get("window_device_pixel_ratio", 0))
                != 2.0
                for checkpoint in accessibility_checkpoints
            )
        ):
            failures.append(
                "installed accessibility checkpoints did not prove 200 "
                "percent Qt window scaling"
            )
    expected_health_graph = (
        diagnostic_task_identity,
        payload.get("campaign_identity"),
        payload.get("run_identity"),
        payload.get("evidence_package_identity"),
        payload.get("reproduction_manifest_identity"),
    )
    if tuple(payload.get("system_health_identity_graph", ())) != (
        expected_health_graph
    ):
        failures.append(
            "System Health did not retain the exact Task/Run/Evidence/Manifest graph"
        )
    return tuple(failures)


def _real_v1_smoke_failures(
    payload: Mapping[str, Any],
) -> tuple[str, ...]:
    failures: list[str] = []
    for field_name in REAL_V1_IDENTITY_FIELDS:
        value = payload.get(field_name)
        if not isinstance(value, str) or not value.strip():
            failures.append(
                f"real V1 {field_name.replace('_', ' ')} is unavailable"
            )
    artifact_hashes = payload.get("artifact_hashes")
    if (
        not isinstance(artifact_hashes, (list, tuple))
        or not artifact_hashes
        or any(
            not isinstance(value, str)
            or _SHA256_DIGEST_PATTERN.fullmatch(value) is None
            for value in artifact_hashes
        )
    ):
        failures.append("real V1 artifact hashes are invalid")
    if payload.get("persistence_kind") != "sqlite+json+parquet":
        failures.append("real V1 persistence kind is invalid")
    if payload.get("persistence_reopened") is not True:
        failures.append("real V1 persistence was not reopened")
    if (
        payload.get("application_read_model_interface")
        != _EXPECTED_APPLICATION_READ_MODEL_INTERFACE
    ):
        failures.append("real V1 Application read-model interface changed")
    if tuple(payload.get("active_feature_interfaces", ())) != (
        _EXPECTED_ACTIVE_FEATURE_INTERFACES
    ):
        failures.append("active Frontend V2 Feature Interfaces changed")
    if payload.get("campaign_status") != "completed":
        failures.append("Formal Diagnostic Campaign is not completed")
    if payload.get("run_status") != "completed":
        failures.append("selected real V1 Strategy Run is not completed")
    if payload.get("evidence_status") != "sealed":
        failures.append("real V1 Diagnostic Evidence is not sealed")
    expected_graph = payload.get("expected_identity_graph")
    feature_graph = payload.get("feature_identity_graph")
    if (
        not isinstance(expected_graph, (list, tuple))
        or not expected_graph
        or any(
            not isinstance(identity, str) or not identity.strip()
            for identity in expected_graph
        )
    ):
        failures.append("real V1 expected identity graph is invalid")
        expected_graph = ()
    if tuple(feature_graph or ()) != tuple(expected_graph):
        failures.append(
            "typed Feature identity graph changed from the real V1 graph"
        )
    identity_sets = payload.get("evidence_identity_sets")
    required_identity_sets = {
        "candidates",
        "metrics",
        "comparisons",
        "curves",
        "breakpoints",
        "findings",
    }
    if (
        not isinstance(identity_sets, dict)
        or set(identity_sets) != required_identity_sets
        or any(
            not isinstance(values, (list, tuple))
            or any(
                not isinstance(identity, str) or not identity.strip()
                for identity in values
            )
            for values in identity_sets.values()
        )
        or any(
            not identity_sets.get(name)
            for name in required_identity_sets - {"breakpoints"}
        )
    ):
        failures.append("real V1 evidence identity sets are invalid")
    else:
        persisted_manifest_identities = payload.get(
            "persisted_manifest_identities"
        )
        persisted_run_identities = payload.get(
            "persisted_run_identities"
        )
        raw_artifact_hashes = payload.get("raw_artifact_hashes")
        persisted_identity_sets_valid = bool(
            isinstance(persisted_manifest_identities, (list, tuple))
            and persisted_manifest_identities
            and isinstance(persisted_run_identities, (list, tuple))
            and persisted_run_identities
            and isinstance(raw_artifact_hashes, (list, tuple))
            and raw_artifact_hashes
            and all(
                isinstance(identity, str) and identity.strip()
                for identity in (
                    *persisted_manifest_identities,
                    *persisted_run_identities,
                )
            )
            and all(
                isinstance(identity, str)
                and len(identity) == 64
                and all(
                    character in "0123456789abcdef"
                    for character in identity
                )
                for identity in raw_artifact_hashes
            )
        )
        if not persisted_identity_sets_valid:
            failures.append(
                "real V1 persisted manifest, run, or raw artifact "
                "identities are invalid"
            )
        flattened_identity_graph = {
            str(payload[field_name])
            for field_name in REAL_V1_IDENTITY_FIELDS
        } | {
            str(identity)
            for identities in identity_sets.values()
            for identity in identities
        }
        if payload.get("fixture_kind") == _WAVE2_RELEASE_FIXTURE_KIND:
            diagnostic_task_identity = payload.get(
                "diagnostic_task_identity"
            )
            task_handle_identities = payload.get(
                "task_handle_identities"
            )
            if isinstance(diagnostic_task_identity, str):
                flattened_identity_graph.add(diagnostic_task_identity)
            if isinstance(task_handle_identities, (list, tuple)):
                flattened_identity_graph.update(
                    str(identity)
                    for identity in task_handle_identities
                )
        if persisted_identity_sets_valid:
            flattened_identity_graph.update(
                str(identity)
                for identity in (
                    tuple(persisted_manifest_identities or ())
                    + tuple(persisted_run_identities or ())
                    + tuple(raw_artifact_hashes or ())
                )
            )
        if (
            persisted_identity_sets_valid
            and flattened_identity_graph != set(expected_graph)
        ):
            failures.append(
                "real V1 evidence identity sets do not form the expected graph"
            )
    checkpoints = payload.get("qml_identity_graph_checkpoints")
    expected_stages = {
        stage for stage, *_ in _EXPECTED_CLEAN_ROOM_JOURNEY
    }
    if (
        not isinstance(checkpoints, dict)
        or set(checkpoints) != expected_stages
        or any(
            tuple(checkpoint) != tuple(expected_graph)
            for checkpoint in checkpoints.values()
            if isinstance(checkpoint, (list, tuple))
        )
        or any(
            not isinstance(checkpoint, (list, tuple))
            for checkpoint in checkpoints.values()
        )
    ):
        failures.append(
            "QML/QAccessible identity graph checkpoints are incomplete"
        )
    for field_name, label in (
        ("keyboard_navigation_verified", "keyboard navigation"),
        (
            "accessibility_preferences_verified",
            "200 percent/reduced-motion/high-contrast preferences",
        ),
        ("old_generation_rejected", "old EventBridge generation rejection"),
        (
            "authoritative_reconnect_verified",
            "authoritative reconnect",
        ),
    ):
        if payload.get(field_name) is not True:
            failures.append(f"{label} was not verified")
    announcements = payload.get("accessibility_announcements")
    announcement_text = " ".join(
        str(value) for value in announcements or ()
    ).casefold()
    if (
        not isinstance(announcements, (list, tuple))
        or "disconnected" not in announcement_text
        or "fresh" not in announcement_text
    ):
        failures.append(
            "accessible disconnect and fresh announcements are incomplete"
        )
    return tuple(failures)


def verify_clean_room_report(
    report_path: Path,
    *,
    expected_source_commit: str,
    expected_archive_sha256: str,
    expected_widgets_archive_sha256: str | None = None,
) -> tuple[str, ...]:
    payload: dict[str, Any] = json.loads(
        report_path.read_text(encoding="utf-8-sig")
    )
    failures = []
    if payload.get("schema_version") != CLEAN_ROOM_REPORT_SCHEMA_VERSION:
        failures.append("Unsupported clean-room report schema")
    if payload.get("source_commit") != expected_source_commit:
        failures.append("Clean-room source commit does not match")
    if payload.get("archive_sha256") != expected_archive_sha256:
        failures.append("Clean-room archive checksum does not match")
    if (
        expected_widgets_archive_sha256 is not None
        and payload.get("widgets_archive_sha256")
        != expected_widgets_archive_sha256
    ):
        failures.append(
            "Clean-room Widgets archive checksum does not match"
        )
    if "windows 11" not in str(
        payload.get("operating_system", "")
    ).casefold():
        failures.append("Clean-room operating system is not Windows 11")
    if str(payload.get("architecture", "")).casefold() not in {
        "amd64",
        "x86_64",
    }:
        failures.append("Clean-room architecture is not x64")
    certification_environment = payload.get("certification_environment")
    if not isinstance(certification_environment, Mapping):
        failures.append("Clean-room certification environment is unavailable")
    elif certification_environment.get("schema_version") != 1:
        failures.append("Unsupported clean-room environment schema")
    else:
        environment_kind = certification_environment.get("kind")
        accessible_filesystem_drive_count = certification_environment.get(
            "accessible_filesystem_drive_count"
        )
        common_environment_verified = (
            certification_environment.get("system_drive") == "C:"
            and isinstance(accessible_filesystem_drive_count, int)
            and not isinstance(accessible_filesystem_drive_count, bool)
            and accessible_filesystem_drive_count == 1
            and certification_environment.get(
                "unexpected_accessible_filesystem_drives"
            )
            == []
        )
        environment_verified = (
            environment_kind == "windows-sandbox"
            and payload.get("is_windows_sandbox") is True
            and payload.get("user_name") == "WDAGUtilityAccount"
            and certification_environment.get("windows_sandbox") is True
            and certification_environment.get("native_boot_vhdx") is False
            and common_environment_verified
        )
        if not environment_verified:
            failures.append("Clean-room certification environment is invalid")
    if payload.get("network_enumeration_succeeded") is not True:
        failures.append("Network adapter inventory was not established")
    if payload.get("network_adapters_up") != []:
        failures.append("Clean-room network is enabled")
    if payload.get("network_adapters_enabled") != []:
        failures.append("Clean-room network adapters remain enabled")
    network_default_route_count = payload.get("network_default_route_count")
    if (
        not isinstance(network_default_route_count, int)
        or isinstance(network_default_route_count, bool)
        or network_default_route_count != 0
    ):
        failures.append("Clean-room network has a default route")
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
    if payload.get("source_checkout_absent") is not True:
        failures.append("A source checkout is available in the clean room")
    if payload.get("source_checkout_markers") != []:
        failures.append("Source-checkout markers are present")
    package_installation = payload.get("package_installation")
    if not isinstance(package_installation, dict):
        failures.append("Guest-local package installation evidence is unavailable")
    else:
        if package_installation.get("storage_kind") != "guest_local_filesystem":
            failures.append("Package installation storage is not guest-local")
        if package_installation.get("candidate_guest_local") is not True:
            failures.append("QML candidate did not run from guest-local storage")
        if package_installation.get("widgets_guest_local") is not True:
            failures.append("Widgets rollback did not run from guest-local storage")
        if (
            package_installation.get("execution_from_mapped_evidence")
            is not False
        ):
            failures.append("A package executed from mapped evidence storage")
        if package_installation.get("verified") is not True:
            failures.append("Guest-local package installation was not verified")
    accessibility_environment = payload.get("accessibility_environment")
    if not isinstance(accessibility_environment, dict):
        failures.append("OS accessibility environment evidence is unavailable")
    else:
        if (
            accessibility_environment.get(
                "text_scale_configured_before_launch"
            )
            is not True
        ):
            failures.append("OS text scaling was not configured before launch")
        if accessibility_environment.get("text_scale_registry_percent") != 200:
            failures.append("OS text scaling was not configured to 200 percent")
        if accessibility_environment.get("guest_dpi_override_applied") is not False:
            failures.append("Guest DPI override evidence is not explicitly false")
        if (
            accessibility_environment.get("native_dpi_evidence_source")
            != "GetDpiForWindow"
        ):
            failures.append("Native window DPI evidence source is unsupported")
        if accessibility_environment.get("errors") not in ([], ()):
            failures.append("OS accessibility configuration reported errors")
    if payload.get("install_succeeded") is not True:
        failures.append("QML package installation did not succeed")
    if (
        expected_widgets_archive_sha256 is not None
        and payload.get("widgets_install_succeeded") is not True
    ):
        failures.append("Widgets rollback installation did not succeed")

    dpi_preflight = payload.get("installed_dpi_preflight")
    if not isinstance(dpi_preflight, dict):
        failures.append("Installed DPI preflight evidence is unavailable")
    else:
        dpi_ratio = dpi_preflight.get("qt_window_device_pixel_ratio")
        expected_snapshot_identity = (
            f"uia:{dpi_preflight.get('checkpoint_sequence')}:"
            f"{dpi_preflight.get('checkpoint')}:"
            f"{dpi_preflight.get('route')}:"
            f"{dpi_preflight.get('run_revision')}:"
            f"{dpi_preflight.get('evidence_revision')}:"
            f"{dpi_preflight.get('status_object_name')}:"
            f"{dpi_preflight.get('status_semantic_term')}:"
            f"scale{dpi_preflight.get('window_scale_percent')}"
        )
        if (
            dpi_preflight.get("schema_version") != 1
            or dpi_preflight.get("stage") != "installed-dpi-preflight"
            or dpi_preflight.get("source_commit") != expected_source_commit
            or dpi_preflight.get("renderer_lane") != "hardware"
            or dpi_preflight.get("certification_scope")
            != "installed-dpi-preflight"
            or dpi_preflight.get("production_path")
            != list(_PRODUCTION_JOURNEY_PATH)
            or dpi_preflight.get("production_path_matches") is not True
            or dpi_preflight.get("checkpoint") != "loading"
            or dpi_preflight.get("checkpoint_sequence") != 1
            or dpi_preflight.get("route") != "run_monitoring"
            or re.fullmatch(
                r"r\d+", str(dpi_preflight.get("run_revision", ""))
            )
            is None
            or re.fullmatch(
                r"r\d+", str(dpi_preflight.get("evidence_revision", ""))
            )
            is None
            or dpi_preflight.get("status_object_name")
            != "runMonitoringRouteNavigation"
            or dpi_preflight.get("status_semantic_term") != "loading"
            or dpi_preflight.get("window_scale_percent") != 200
            or dpi_preflight.get("snapshot_identity")
            != expected_snapshot_identity
            or dpi_preflight.get("snapshot_identity_matches") is not True
            or not isinstance(dpi_ratio, (int, float))
            or not math.isfinite(float(dpi_ratio))
            or float(dpi_ratio) != 2.0
            or dpi_preflight.get("native_window_dpi") != 192
            or dpi_preflight.get("candidate_exit_code") != 0
            or dpi_preflight.get("candidate_external_uia_acknowledged")
            is not True
            or dpi_preflight.get("candidate_clean_exit") is not True
            or dpi_preflight.get("passed") is not True
            or dpi_preflight.get("errors") not in ([], ())
        ):
            failures.append("Installed DPI preflight did not pass")

    installed_performance = payload.get("installed_performance")
    if not isinstance(installed_performance, dict):
        failures.append("Installed performance evidence is unavailable")
    else:
        from .frontend_v2_performance import validate_performance_lane

        toolchain_digest = _sha256_path(TOOLCHAIN_LOCK_PATH)
        for lane_name in ("hardware", "software"):
            lane_report = installed_performance.get(lane_name)
            if not isinstance(lane_report, dict):
                failures.append(
                    f"{lane_name} installed performance evidence is unavailable"
                )
                continue
            if lane_report.get("schema_version") != 4:
                failures.append(
                    f"{lane_name} installed performance schema must be 4"
                )
                continue
            failures.extend(
                f"{lane_name} installed performance {failure}"
                for failure in validate_performance_lane(
                    lane_report,
                    expected_lane=lane_name,
                    expected_source_commit=expected_source_commit,
                    expected_toolchain_digest=toolchain_digest,
                )
            )

    for block_name, required_true_fields in (
        (
            "fresh_install_migration",
            (
                "passed",
                "schema_migration_verified",
                "bookmark_migration_verified",
                "deterministic",
                "idempotent",
                "identity_retention_verified",
                "reopen_verified",
            ),
        ),
        (
            "copied_wave3_migration",
            (
                "passed",
                "schema_migration_verified",
                "bookmark_migration_verified",
                "deterministic",
                "idempotent",
                "identity_retention_verified",
                "reopen_verified",
            ),
        ),
        (
            "candidate_widgets_candidate_rollback",
            (
                "passed",
                "same_source_commit",
                "same_dependency_lock",
                "identity_retention_verified",
                "reopen_verified",
            ),
        ),
        (
            "observation_ledger_readiness",
            (
                "passed",
                "legacy_inventory_available",
                "observation_ledger_configuration_available",
            ),
        ),
    ):
        block = payload.get(block_name)
        if not isinstance(block, dict):
            failures.append(
                f"{block_name.replace('_', ' ')} evidence is unavailable"
            )
            continue
        if block.get("source_commit") != expected_source_commit:
            failures.append(
                f"{block_name.replace('_', ' ')} source commit does not match"
            )
        for field_name in required_true_fields:
            if block.get(field_name) is not True:
                failures.append(
                    f"{block_name.replace('_', ' ')} {field_name.replace('_', ' ')} "
                    "was not verified"
                )
        if block.get("destructive_migration") is not False:
            failures.append(
                f"{block_name.replace('_', ' ')} did not prove a non-destructive migration"
            )
    ledger = payload.get("observation_ledger_readiness")
    if isinstance(ledger, dict):
        legacy_route_count = ledger.get("legacy_route_count")
        if (
            not isinstance(legacy_route_count, int)
            or isinstance(legacy_route_count, bool)
            or legacy_route_count < 1
        ):
            failures.append("Observation ledger legacy route count is unavailable")
        if ledger.get("observation_window_started") is not False:
            failures.append(
                "Issue #118 must not start the formal observation window"
            )
    rollback = payload.get("candidate_widgets_candidate_rollback")
    if isinstance(rollback, dict):
        rollback_lanes = rollback.get("renderer_lanes")
        if not isinstance(rollback_lanes, dict):
            failures.append(
                "Candidate-to-Widgets rollback renderer lanes are unavailable"
            )
        else:
            for lane_name in ("hardware", "software"):
                lane_rollback = rollback_lanes.get(lane_name)
                if not isinstance(lane_rollback, dict):
                    failures.append(
                        f"{lane_name} candidate-to-Widgets rollback is unavailable"
                    )
                    continue
                if lane_rollback.get("lane") != lane_name:
                    failures.append(
                        f"{lane_name} candidate-to-Widgets rollback lane does not match"
                    )
                if lane_rollback.get("source_commit") != expected_source_commit:
                    failures.append(
                        f"{lane_name} candidate-to-Widgets rollback source does not match"
                    )
                for field_name in (
                    "passed",
                    "same_source_commit",
                    "same_dependency_lock",
                    "identity_retention_verified",
                    "task_handle_continuity_verified",
                    "order_state_continuity_verified",
                    "reopen_verified",
                ):
                    if lane_rollback.get(field_name) is not True:
                        failures.append(
                            f"{lane_name} candidate-to-Widgets rollback "
                            f"{field_name.replace('_', ' ')} was not verified"
                        )
                if lane_rollback.get("destructive_migration") is not False:
                    failures.append(
                        f"{lane_name} candidate-to-Widgets rollback did not prove "
                        "a non-destructive migration"
                    )

    lanes = payload.get("renderer_lanes")
    if not isinstance(lanes, dict):
        failures.append("Renderer lane evidence is unavailable")
        return tuple(failures)
    expected_stages = tuple(
        stage for stage, *_ in _EXPECTED_CLEAN_ROOM_JOURNEY
    )
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
        if lane.get("schema_version") != PACKAGE_SMOKE_REPORT_SCHEMA_VERSION:
            failures.append(
                f"{lane_name} renderer smoke report schema is unsupported"
            )
        if lane.get("certification_scope") != "installed":
            failures.append(
                f"{lane_name} renderer report is not installed certification"
            )
        if lane.get("graphics_api") != expected_api:
            failures.append(
                f"{lane_name} renderer used {lane.get('graphics_api')!r}"
            )
        if tuple(lane.get("production_path", ())) != (
            _PRODUCTION_JOURNEY_PATH
        ):
            failures.append(
                f"{lane_name} renderer did not use the real V1 "
                "Application-to-Feature path"
            )
        failures.extend(
            f"{lane_name} renderer {failure}"
            for failure in _real_v1_smoke_failures(lane)
        )
        failures.extend(
            f"{lane_name} renderer {failure}"
            for failure in _installed_wave2_smoke_failures(lane)
        )
        if lane.get("source_commit") != expected_source_commit:
            failures.append(
                f"{lane_name} renderer source commit does not match"
            )
        if tuple(lane.get("connection_transitions", ())) != (
            _EXPECTED_CONNECTION_TRANSITIONS
        ):
            failures.append(
                f"{lane_name} renderer did not complete the connection, "
                "remount, and close journey"
            )
        if tuple(lane.get("routes_rendered", ())) != _ACTIVE_JOURNEY_ROUTES:
            failures.append(
                f"{lane_name} renderer did not render all six active routes"
            )
        observations = lane.get("observations")
        observed_journey = (
            tuple(
                (
                    observation.get("stage"),
                    observation.get("route"),
                    observation.get("run_state"),
                    observation.get("evidence_state"),
                    observation.get("run_freshness"),
                    observation.get("evidence_freshness"),
                )
                for observation in observations
                if isinstance(observation, dict)
            )
            if isinstance(observations, list)
            else ()
        )
        if observed_journey != _EXPECTED_CLEAN_ROOM_JOURNEY:
            failures.append(
                f"{lane_name} renderer did not show the complete "
                "release-candidate journey"
            )
        _, screenshot_failures = _inspect_clean_room_screenshots(
            report_path=report_path,
            lane_name=lane_name,
            lane=lane,
            expected_states=expected_stages,
        )
        failures.extend(screenshot_failures)
        if lane.get("manual_trading_action_count") != 0:
            failures.append(
                f"{lane_name} renderer exposed an unapproved action"
            )
        runtime_safety_audits = lane.get("manual_trading_route_audits")
        if not isinstance(runtime_safety_audits, list):
            failures.append(
                f"{lane_name} renderer runtime safety audits are unavailable"
            )
        else:
            observed_route_stages: set[tuple[str, str]] = set()
            for audit in runtime_safety_audits:
                if not isinstance(audit, dict):
                    failures.append(
                        f"{lane_name} renderer runtime safety audit is invalid"
                    )
                    continue
                observed_route_stages.add(
                    (str(audit.get("stage", "")), str(audit.get("route", "")))
                )
                if set(audit.get("coverage") or ()) != _RUNTIME_SAFETY_COVERAGE:
                    failures.append(
                        f"{lane_name} renderer runtime safety coverage is incomplete"
                    )
                if audit.get("object_count", 0) <= 0 or audit.get(
                    "accessible_object_count", 0
                ) <= 0:
                    failures.append(
                        f"{lane_name} renderer runtime object tree was not scanned"
                    )
                if audit.get("forbidden_action_count") != 0 or audit.get(
                    "forbidden_actions"
                ) not in ([], ()):
                    failures.append(
                        f"{lane_name} renderer exposed a manual-trading capability"
                    )
            expected_route_stages = {
                (stage, route)
                for stage in _RUNTIME_SAFETY_STAGES
                for route in _ACTIVE_JOURNEY_ROUTES
            }
            if (
                len(runtime_safety_audits) != len(expected_route_stages)
                or observed_route_stages != expected_route_stages
            ):
                failures.append(
                    f"{lane_name} renderer runtime safety route coverage is incomplete"
                )
        uia_accessibility = lane.get("uia_accessibility")
        if not isinstance(uia_accessibility, dict):
            failures.append(
                f"{lane_name} renderer UIA accessibility evidence is unavailable"
            )
        else:
            required_semantics = {
                "loading",
                "empty",
                "stale",
                "disconnected",
                "partial",
                "failed",
                "recovering",
                "completed",
                "progress",
                "error",
                "health",
                "fresh",
                "recovery",
            }
            observed_semantics = uia_accessibility.get("semantic_terms")
            semantics_valid = bool(
                isinstance(observed_semantics, dict)
                and set(observed_semantics) == required_semantics
                and all(observed_semantics.values())
            )
            narrator_checkpoints = uia_accessibility.get(
                "narrator_checkpoint_evidence"
            )
            narrator_checkpoint_mappings_valid = bool(
                isinstance(narrator_checkpoints, list)
                and all(
                    isinstance(checkpoint, Mapping)
                    for checkpoint in narrator_checkpoints
                )
            )
            required_narrator_checkpoints = (
                "loading",
                "empty",
                "failed",
                "recovering",
                "partial",
                "disconnected",
                "stale",
                "completed",
            )
            checkpoint_timestamps: list[datetime] = []
            if narrator_checkpoint_mappings_valid:
                for checkpoint in narrator_checkpoints:
                    try:
                        captured_at = datetime.fromisoformat(
                            str(checkpoint.get("captured_at_utc", ""))
                        )
                    except (AttributeError, TypeError, ValueError):
                        checkpoint_timestamps = []
                        break
                    if captured_at.tzinfo is None:
                        checkpoint_timestamps = []
                        break
                    checkpoint_timestamps.append(captured_at)
            checkpoint_identities = (
                tuple(
                    str(checkpoint.get("snapshot_identity", ""))
                    for checkpoint in narrator_checkpoints
                )
                if narrator_checkpoint_mappings_valid
                else ()
            )
            checkpoint_scan_sequences = (
                tuple(
                    checkpoint.get("scan_sequence")
                    for checkpoint in narrator_checkpoints
                )
                if narrator_checkpoint_mappings_valid
                else ()
            )
            narrator_checkpoints_valid = bool(
                narrator_checkpoint_mappings_valid
                and len(narrator_checkpoints)
                == len(required_narrator_checkpoints)
                and tuple(
                    str(checkpoint.get("checkpoint", ""))
                    for checkpoint in narrator_checkpoints
                )
                == required_narrator_checkpoints
                and tuple(
                    checkpoint.get("sequence")
                    for checkpoint in narrator_checkpoints
                )
                == tuple(range(1, len(required_narrator_checkpoints) + 1))
                and all(checkpoint_identities)
                and len(set(checkpoint_identities))
                == len(checkpoint_identities)
                and all(
                    isinstance(sequence, int)
                    for sequence in checkpoint_scan_sequences
                )
                and all(
                    later > earlier
                    for earlier, later in zip(
                        checkpoint_scan_sequences,
                        checkpoint_scan_sequences[1:],
                    )
                )
                and len(checkpoint_timestamps)
                == len(required_narrator_checkpoints)
                and all(
                    later > earlier
                    for earlier, later in zip(
                        checkpoint_timestamps,
                        checkpoint_timestamps[1:],
                    )
                )
                and all(
                    isinstance(checkpoint, Mapping)
                    and checkpoint.get("route") in _ACTIVE_JOURNEY_ROUTES
                    and (
                        checkpoint.get("status_object_name"),
                        checkpoint.get("status_semantic_term"),
                    )
                    == _UIA_CHECKPOINT_BINDINGS[
                        str(checkpoint.get("checkpoint", ""))
                    ]
                    and checkpoint.get("snapshot_identity")
                    == (
                        f"uia:{checkpoint.get('sequence')}:"
                        f"{checkpoint.get('checkpoint')}:"
                        f"{checkpoint.get('route')}:"
                        f"{checkpoint.get('run_revision')}:"
                        f"{checkpoint.get('evidence_revision')}:"
                        f"{checkpoint.get('status_object_name')}:"
                        f"{checkpoint.get('status_semantic_term')}:"
                        f"scale{checkpoint.get('window_scale_percent')}"
                    )
                    and re.fullmatch(
                        r"r\d+",
                        str(checkpoint.get("run_revision", "")),
                    )
                    is not None
                    and re.fullmatch(
                        r"r\d+",
                        str(checkpoint.get("evidence_revision", "")),
                    )
                    is not None
                    and checkpoint.get("lifecycle_state_observed") is True
                    and checkpoint.get("narrator_running") is True
                    and checkpoint.get("focus_traversal_observed") is True
                    and isinstance(
                        checkpoint.get("window_scale_percent"),
                        (int, float),
                    )
                    and math.isfinite(
                        float(checkpoint.get("window_scale_percent", 0))
                    )
                    and checkpoint.get("window_scale_percent") == 200
                    and checkpoint.get("native_window_dpi") == 192
                    and checkpoint.get("complete_snapshot") is True
                    and checkpoint.get("named_element_count", 0) > 0
                    and bool(checkpoint.get("control_types"))
                    and checkpoint.get("passed") is True
                    for checkpoint in narrator_checkpoints
                )
            )
            discovered_count = uia_accessibility.get(
                "discovered_element_count",
                -1,
            )
            readable_count = uia_accessibility.get(
                "readable_element_count",
                -1,
            )
            unreadable_count = uia_accessibility.get(
                "unreadable_element_count",
                -1,
            )
            snapshot_accounting_valid = bool(
                isinstance(discovered_count, int)
                and isinstance(readable_count, int)
                and isinstance(unreadable_count, int)
                and discovered_count > 0
                and readable_count > 0
                and unreadable_count >= 0
                and readable_count + unreadable_count == discovered_count
                and uia_accessibility.get("complete_snapshot_count", 0) >= 8
            )
            if (
                uia_accessibility.get("passed") is not True
                or uia_accessibility.get("provider_available") is not True
                or uia_accessibility.get("scan_count", 0) <= 0
                or uia_accessibility.get("named_element_count", 0) <= 0
                or uia_accessibility.get("focusable_element_count", 0) <= 0
                or uia_accessibility.get("focus_observed") is not True
                or not uia_accessibility.get("control_types")
                or not uia_accessibility.get("action_patterns")
                or uia_accessibility.get("narrator_started") is not True
                or uia_accessibility.get("narrator_running_during_probe")
                is not True
                or uia_accessibility.get("focus_traversal_observed") is not True
                or not narrator_checkpoints_valid
                or not snapshot_accounting_valid
                or uia_accessibility.get("observed_window_dpi_x") != 192
                or uia_accessibility.get("observed_window_dpi_y") != 192
                or uia_accessibility.get("observed_scale_percent") != 200
                or uia_accessibility.get(
                    "observed_qt_window_scale_percent",
                    0,
                ) != 200
                or uia_accessibility.get("forbidden_action_count") != 0
                or uia_accessibility.get("forbidden_actions") not in ([], ())
                or not semantics_valid
                or uia_accessibility.get("errors") not in ([], ())
            ):
                failures.append(
                    f"{lane_name} renderer UIA/Narrator/200-percent gate failed"
                )
        if lane.get("read_only_context_visible") is not True:
            failures.append(
                f"{lane_name} renderer did not retain read-only "
                "orders and fills"
            )
        if lane.get("clean_exit") is not True:
            failures.append(f"{lane_name} renderer did not exit cleanly")
        if lane.get("errors"):
            failures.append(f"{lane_name} renderer reported errors")
    hardware_lane = lanes.get("hardware")
    software_lane = lanes.get("software")
    if isinstance(hardware_lane, dict) and isinstance(
        software_lane,
        dict,
    ):
        for field_name in _CROSS_LANE_STABLE_FIELDS:
            if hardware_lane.get(field_name) != software_lane.get(
                field_name
            ):
                failures.append(
                    "Renderer lanes did not certify the same real V1 "
                    f"{field_name.replace('_', ' ')}"
                )
    if expected_widgets_archive_sha256 is not None:
        widgets = payload.get("widgets_rollback")
        if not isinstance(widgets, dict):
            failures.append("Widgets rollback smoke evidence is unavailable")
        else:
            if widgets.get("exit_code") != 0:
                failures.append("Widgets rollback smoke failed")
            if widgets.get("source_commit") != expected_source_commit:
                failures.append(
                    "Widgets rollback source commit does not match"
                )
            if widgets.get("mode") != "read-only":
                failures.append("Widgets rollback is not read-only")
            if widgets.get("manual_trading_action_count") != 0:
                failures.append(
                    "Widgets rollback exposed a manual trading action"
                )
            if widgets.get("real_panel_count", 0) < 3:
                failures.append(
                    "Widgets rollback did not mount its real read-only panels"
                )
            if widgets.get("placeholder_panels") not in ([], ()):
                failures.append(
                    "Widgets rollback retained placeholder panels"
                )
            opened = set(widgets.get("opened_panels", ()))
            if not {"diagnostics", "market", "orders"}.issubset(opened):
                failures.append(
                    "Widgets rollback did not open all required panels"
                )
            if widgets.get("clean_exit") is not True:
                failures.append(
                    "Widgets rollback did not exit cleanly"
                )
            if widgets.get("errors"):
                failures.append("Widgets rollback reported errors")
    return tuple(failures)


def _inspect_clean_room_screenshots(
    *,
    report_path: Path,
    lane_name: str,
    lane: dict[str, Any],
    expected_states: tuple[str, ...],
) -> tuple[
    tuple[_CleanRoomScreenshotArtifact, ...],
    tuple[str, ...],
]:
    screenshots = lane.get("screenshots")
    if (
        not isinstance(screenshots, list)
        or len(screenshots) != len(expected_states)
    ):
        return (), (
            f"{lane_name} renderer screenshot evidence is incomplete",
        )

    report_root = report_path.parent.resolve()
    lane_root = (report_root / lane_name).resolve()
    artifacts: list[_CleanRoomScreenshotArtifact] = []
    failures: list[str] = []

    def fail(message: str) -> None:
        if message not in failures:
            failures.append(message)

    for expected_state, screenshot in zip(
        expected_states,
        screenshots,
        strict=True,
    ):
        if not isinstance(screenshot, dict) or screenshot.get(
            "stage"
        ) != expected_state:
            fail(f"{lane_name} renderer screenshot evidence is incomplete")
            continue

        relative_path = screenshot.get("relative_path")
        if not isinstance(relative_path, str) or not relative_path:
            fail(f"{lane_name} renderer screenshot path is unsafe")
            continue
        candidate = (report_root / relative_path).resolve()
        try:
            candidate.relative_to(lane_root)
        except ValueError:
            fail(f"{lane_name} renderer screenshot path is unsafe")
            continue
        if candidate.suffix.casefold() != ".png":
            fail(f"{lane_name} renderer screenshot path is unsafe")
            continue

        declared_sha256 = screenshot.get("sha256")
        if (
            not isinstance(declared_sha256, str)
            or _SHA256_DIGEST_PATTERN.fullmatch(declared_sha256) is None
        ):
            fail(f"{lane_name} renderer screenshot digest is invalid")
            continue
        if not candidate.is_file():
            fail(f"{lane_name} renderer screenshot is missing")
            continue

        observed = _checksum_file(candidate, report_root)
        if observed.sha256 != declared_sha256:
            fail(
                f"{lane_name} renderer screenshot checksum does not match"
            )
            continue
        artifacts.append(
            _CleanRoomScreenshotArtifact(
                state=expected_state,
                relative_path=relative_path,
                sha256=declared_sha256,
                source_path=candidate,
            )
        )

    artifact_digests = {
        artifact.state: artifact.sha256 for artifact in artifacts
    }
    route_state_groups = (
        (
            "launched_terminal_run",
            "disconnected_run",
        ),
        (
            "terminal_evidence",
            "disconnected_evidence",
        ),
    )
    major_states_are_distinct = all(
        len(
            {
                artifact_digests.get(stage)
                for stage in stage_group
            }
        )
        == len(stage_group)
        for stage_group in route_state_groups
    )
    if (
        lane.get("screenshots_distinct") is not True
        or len(artifacts) != len(expected_states)
        or not major_states_are_distinct
    ):
        fail(f"{lane_name} renderer screenshots are not distinct")
    return tuple(artifacts), tuple(failures)


def _retain_clean_room_screenshots(
    *,
    report_path: Path,
    report_payload: dict[str, Any],
    evidence_dir: Path,
) -> None:
    lanes = report_payload.get("renderer_lanes")
    if not isinstance(lanes, dict):
        raise RuntimeError("Renderer lane evidence is unavailable")

    target_root = evidence_dir.resolve()
    expected_states = tuple(
        stage for stage, *_ in _EXPECTED_CLEAN_ROOM_JOURNEY
    )
    artifacts: list[_CleanRoomScreenshotArtifact] = []
    for lane_name in ("hardware", "software"):
        lane = lanes.get(lane_name)
        if not isinstance(lane, dict):
            raise RuntimeError(
                f"{lane_name} renderer lane is unavailable"
            )
        lane_artifacts, failures = _inspect_clean_room_screenshots(
            report_path=report_path,
            lane_name=lane_name,
            lane=lane,
            expected_states=expected_states,
        )
        if failures:
            raise RuntimeError(
                "Clean-room screenshot evidence changed after verification: "
                + "; ".join(failures)
            )
        artifacts.extend(lane_artifacts)

    for artifact in artifacts:
        target_path = (target_root / artifact.relative_path).resolve()
        try:
            target_path.relative_to(target_root)
        except ValueError as error:
            raise RuntimeError(
                "Clean-room screenshot escapes the evidence root: "
                f"{artifact.relative_path}"
            ) from error
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if artifact.source_path.resolve() != target_path:
            shutil.copy2(artifact.source_path, target_path)
        retained = _checksum_file(target_path, target_root)
        if retained.sha256 != artifact.sha256:
            raise RuntimeError(
                "Retained clean-room screenshot checksum does not match: "
                f"{artifact.relative_path}"
            )


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
        expected_source_commit=source_commit,
    )
    software = _load_renderer_lane(
        software_report,
        expected_lane="software",
        expected_graphics_api="Software",
        expected_source_commit=source_commit,
    )
    for field_name in _CROSS_LANE_STABLE_FIELDS:
        if getattr(hardware, field_name) != getattr(
            software,
            field_name,
        ):
            raise RuntimeError(
                "Renderer lanes did not certify the same real V1 "
                f"{field_name.replace('_', ' ')}"
            )
    lock = load_toolchain_lock()
    evidence = RendererGateEvidence(
        source_commit=source_commit,
        certification_scope="package-assembly",
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
        "schema_version": RENDERER_GATE_REPORT_SCHEMA_VERSION,
        **asdict(evidence),
        "toolchain_lock": asdict(lock),
        "qml_source_imports": asdict(source_imports),
        "qml_dependency_closure": asdict(dependency_closure),
    }
    evidence_dir.mkdir(parents=True, exist_ok=True)
    report_path = evidence_dir / "renderer-gate-report.json"
    report_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    report_failures = verify_renderer_gate_report(
        report_path,
        expected_source_commit=source_commit,
        expected_candidate_renderers=asdict(evidence),
    )
    if report_failures:
        raise RuntimeError(
            "Renderer gate report verification failed: "
            + "; ".join(report_failures)
        )
    return evidence


def verify_renderer_gate_report(
    report_path: Path,
    *,
    expected_source_commit: str,
    expected_candidate_renderers: Mapping[str, Any] | None = None,
) -> tuple[str, ...]:
    payload = _load_json_mapping(report_path)
    failures: list[str] = []
    if payload.get("schema_version") != RENDERER_GATE_REPORT_SCHEMA_VERSION:
        failures.append("Renderer gate report schema is unsupported")
    if payload.get("source_commit") != expected_source_commit:
        failures.append("Renderer gate source commit does not match")
    if payload.get("certification_scope") != "package-assembly":
        failures.append("Renderer gate scope is not package-assembly")
    lock = load_toolchain_lock()
    if payload.get("toolchain_identity") != toolchain_evidence_identity(lock):
        failures.append("Renderer gate toolchain identity does not match")
    if payload.get("toolchain_lock") != _json_projection(asdict(lock)):
        failures.append("Renderer gate toolchain lock does not match")
    if payload.get("qml_source_imports") != _json_projection(
        asdict(scan_qml_dependencies(PROJECT_QML_ROOT))
    ):
        failures.append("Renderer gate QML source imports do not match")
    if payload.get("qml_dependency_closure") != _json_projection(
        asdict(resolve_qml_dependency_closure(PROJECT_QML_ROOT))
    ):
        failures.append("Renderer gate QML dependency closure does not match")
    projection: dict[str, Any] = {}
    for evidence_field in fields(RendererGateEvidence):
        if evidence_field.name not in payload:
            failures.append(
                f"Renderer gate {evidence_field.name} is unavailable"
            )
            continue
        projection[evidence_field.name] = payload[evidence_field.name]
    if (
        expected_candidate_renderers is not None
        and projection
        != _json_projection(dict(expected_candidate_renderers))
    ):
        failures.append(
            "Renderer gate projection does not match candidate evidence"
        )
    for lane_name, expected_graphics_api in (
        ("hardware", "Direct3D11"),
        ("software", "Software"),
    ):
        lane = payload.get(lane_name)
        if not isinstance(lane, Mapping):
            failures.append(f"Renderer gate {lane_name} lane is unavailable")
            continue
        for lane_field in fields(RendererLaneEvidence):
            if lane_field.name not in lane:
                failures.append(
                    f"Renderer gate {lane_name} {lane_field.name} is unavailable"
                )
        if lane.get("certification_scope") != "package-assembly":
            failures.append(
                f"Renderer gate {lane_name} scope is not package-assembly"
            )
        if lane.get("lane") != lane_name:
            failures.append(f"Renderer gate {lane_name} identity does not match")
        if lane.get("graphics_api") != expected_graphics_api:
            failures.append(
                f"Renderer gate {lane_name} graphics API does not match"
            )
        if tuple(lane.get("production_path", ())) != _PRODUCTION_JOURNEY_PATH:
            failures.append(
                f"Renderer gate {lane_name} production path does not match"
            )
        if tuple(lane.get("journey_stages", ())) != tuple(
            stage for stage, *_ in _EXPECTED_CLEAN_ROOM_JOURNEY
        ):
            failures.append(
                f"Renderer gate {lane_name} journey stages do not match"
            )
        if (
            lane.get("clean_exit") is not True
            or lane.get("errors") not in ([], ())
        ):
            failures.append(
                f"Renderer gate {lane_name} lifecycle did not pass"
            )
    return tuple(failures)


def _load_renderer_lane(
    report_path: Path,
    *,
    expected_lane: str,
    expected_graphics_api: str,
    expected_source_commit: str,
) -> RendererLaneEvidence:
    payload: dict[str, Any] = json.loads(
        report_path.read_text(encoding="utf-8")
    )
    observations = tuple(
        (
            str(observation.get("stage")),
            str(observation.get("route")),
            str(observation.get("run_state")),
            str(observation.get("evidence_state")),
            str(observation.get("run_freshness")),
            str(observation.get("evidence_freshness")),
        )
        for observation in payload.get("observations", ())
        if isinstance(observation, dict)
    )
    errors = tuple(str(error) for error in payload.get("errors", ()))
    if payload.get("schema_version") != PACKAGE_SMOKE_REPORT_SCHEMA_VERSION:
        raise RuntimeError(
            f"{expected_lane} renderer smoke report schema is unsupported"
        )
    if payload.get("renderer_lane") != expected_lane:
        raise RuntimeError(
            f"Expected {expected_lane} renderer report at {report_path}"
        )
    if payload.get("certification_scope") != "package-assembly":
        raise RuntimeError(
            f"{expected_lane} renderer report is not package-assembly smoke"
        )
    if payload.get("graphics_api") != expected_graphics_api:
        raise RuntimeError(
            f"{expected_lane} used {payload.get('graphics_api')!r}"
        )
    if payload.get("source_commit") != expected_source_commit:
        raise RuntimeError(
            f"{expected_lane} smoke source commit does not match"
        )
    if observations != _EXPECTED_CLEAN_ROOM_JOURNEY:
        raise RuntimeError(
            f"{expected_lane} did not show the complete production journey"
        )
    routes_rendered = tuple(payload.get("routes_rendered", ()))
    production_path = tuple(payload.get("production_path", ()))
    connection_transitions = tuple(
        payload.get("connection_transitions", ())
    )
    real_v1_failures = _real_v1_smoke_failures(payload)
    installed_wave2_failures = _installed_wave2_smoke_failures(
        payload,
        require_installed_window_scale=False,
    )
    if (
        routes_rendered != _ACTIVE_JOURNEY_ROUTES
        or production_path != _PRODUCTION_JOURNEY_PATH
        or connection_transitions
        != _EXPECTED_CONNECTION_TRANSITIONS
        or real_v1_failures
        or installed_wave2_failures
        or payload.get("manual_trading_action_count") != 0
        or payload.get("read_only_context_visible") is not True
        or errors
        or payload.get("clean_exit") is not True
    ):
        detail = (
            ": "
            + "; ".join((*real_v1_failures, *installed_wave2_failures))
            if real_v1_failures or installed_wave2_failures
            else ""
        )
        raise RuntimeError(
            f"{expected_lane} renderer smoke failed{detail}"
        )
    return RendererLaneEvidence(
        lane=expected_lane,
        certification_scope="package-assembly",
        graphics_api=expected_graphics_api,
        journey_stages=tuple(
            stage for stage, *_ in _EXPECTED_CLEAN_ROOM_JOURNEY
        ),
        routes_rendered=routes_rendered,
        production_path=production_path,
        fixture_kind=str(payload["fixture_kind"]),
        strategy_selection_created_after_install=True,
        recipe_draft_created_after_install=True,
        recipe_validation_created_after_install=True,
        recipe_approval_created_after_install=True,
        reference_path_materialized_after_install=True,
        scenario_set_created_after_install=True,
        scenario_selection_created_after_install=True,
        strategy_selection_context_identity=str(
            payload["strategy_selection_context_identity"]
        ),
        recipe_draft_identity=str(payload["recipe_draft_identity"]),
        recipe_validation_identity=str(
            payload["recipe_validation_identity"]
        ),
        materialization_task_handle_identity=str(
            payload["materialization_task_handle_identity"]
        ),
        materialized_path_identity=str(
            payload["materialized_path_identity"]
        ),
        materialized_scenario_identity=str(
            payload["materialized_scenario_identity"]
        ),
        terminal_campaign_case_identity=str(
            payload["terminal_campaign_case_identity"]
        ),
        terminal_selected_campaign_case_identity=str(
            payload["terminal_selected_campaign_case_identity"]
        ),
        terminal_node_market_scenario_identity=str(
            payload["terminal_node_market_scenario_identity"]
        ),
        terminal_campaign_node_lifecycle=str(
            payload["terminal_campaign_node_lifecycle"]
        ),
        terminal_case_manifest_binding_verified=True,
        installed_setup_ledger_reopened=True,
        reopened_installed_setup_ledger=(
            _canonical_reopened_setup_ledger(
                payload["reopened_installed_setup_ledger"]
            )
            or {}
        ),
        formal_scenario_set_identity=str(
            payload["formal_scenario_set_identity"]
        ),
        scenario_selection_context_identity=str(
            payload["scenario_selection_context_identity"]
        ),
        setup_selection_context_identity=str(
            payload["setup_selection_context_identity"]
        ),
        installed_setup_command_kinds=tuple(
            str(value)
            for value in payload["installed_setup_command_kinds"]
        ),
        installed_recipe_draft_identities=tuple(
            str(value)
            for value in payload["installed_recipe_draft_identities"]
        ),
        installed_recipe_validation_identities=tuple(
            str(value)
            for value in payload[
                "installed_recipe_validation_identities"
            ]
        ),
        installed_approved_recipe_identities=tuple(
            str(value)
            for value in payload["installed_approved_recipe_identities"]
        ),
        installed_materialization_task_handle_identities=tuple(
            str(value)
            for value in payload[
                "installed_materialization_task_handle_identities"
            ]
        ),
        installed_materialized_path_identities=tuple(
            str(value)
            for value in payload["installed_materialized_path_identities"]
        ),
        installed_materialized_scenario_identities=tuple(
            str(value)
            for value in payload[
                "installed_materialized_scenario_identities"
            ]
        ),
        task_created_after_install=True,
        campaign_created_after_install=True,
        diagnostic_task_identity=str(payload["diagnostic_task_identity"]),
        accepted_command_kinds=tuple(
            str(value) for value in payload["accepted_command_kinds"]
        ),
        task_handle_identities=tuple(
            str(value) for value in payload["task_handle_identities"]
        ),
        writable_persistence_verified=True,
        application_reopened=True,
        background_continuation_verified=True,
        task_cancel_order_isolation_verified=True,
        campaign_identity=str(payload["campaign_identity"]),
        case_identity=str(payload["case_identity"]),
        run_identity=str(payload["run_identity"]),
        strategy_identity=str(payload["strategy_identity"]),
        approved_recipe_identity=str(
            payload["approved_recipe_identity"]
        ),
        evidence_package_identity=str(
            payload["evidence_package_identity"]
        ),
        reproduction_manifest_identity=str(
            payload["reproduction_manifest_identity"]
        ),
        artifact_hashes=tuple(
            str(value) for value in payload["artifact_hashes"]
        ),
        persistence_kind=str(payload["persistence_kind"]),
        persistence_reopened=True,
        application_read_model_interface=str(
            payload["application_read_model_interface"]
        ),
        active_feature_interfaces=tuple(
            str(value)
            for value in payload["active_feature_interfaces"]
        ),
        campaign_status=str(payload["campaign_status"]),
        run_status=str(payload["run_status"]),
        evidence_status=str(payload["evidence_status"]),
        expected_identity_graph=tuple(
            str(value) for value in payload["expected_identity_graph"]
        ),
        feature_identity_graph=tuple(
            str(value) for value in payload["feature_identity_graph"]
        ),
        qml_identity_graph_checkpoints={
            str(stage): tuple(str(value) for value in values)
            for stage, values in payload[
                "qml_identity_graph_checkpoints"
            ].items()
        },
        evidence_identity_sets={
            str(name): tuple(str(value) for value in values)
            for name, values in payload["evidence_identity_sets"].items()
        },
        persisted_manifest_identities=tuple(
            str(value)
            for value in payload["persisted_manifest_identities"]
        ),
        persisted_run_identities=tuple(
            str(value)
            for value in payload["persisted_run_identities"]
        ),
        raw_artifact_hashes=tuple(
            str(value) for value in payload["raw_artifact_hashes"]
        ),
        keyboard_navigation_verified=True,
        accessibility_preferences_verified=True,
        accessibility_announcements=tuple(
            str(value)
            for value in payload["accessibility_announcements"]
        ),
        old_generation_rejected=True,
        authoritative_reconnect_verified=True,
        queued_state_observed=True,
        running_state_observed=True,
        partial_state_observed=True,
        controlled_failure_observed=True,
        safe_failure_reason_verified=True,
        retry_idempotency_verified=True,
        duplicate_work_count=0,
        terminal_completion_observed=True,
        system_health_context_verified=True,
        system_health_identity_graph=tuple(
            str(value) for value in payload["system_health_identity_graph"]
        ),
        system_health_accessibility_verified=True,
        focus_restoration_verified=True,
        connection_transitions=connection_transitions,
        manual_trading_action_count=0,
        read_only_context_visible=True,
        clean_exit=True,
        errors=(),
    )


def audit_nuitka_dependency_report(
    report_path: Path,
    *,
    package_kind: PackageKind,
) -> tuple[str, ...]:
    root = _parse_nuitka_dependency_report(report_path)
    findings = []
    lock = load_toolchain_lock()
    if root.attrib.get("nuitka_version") != lock.toolchain.nuitka:
        findings.append(
            "Nuitka version does not match the production lock: expected "
            f"{lock.toolchain.nuitka}, observed "
            f"{root.attrib.get('nuitka_version')!r}"
        )
    scons_environment = root.find("./scons_environment")
    expected_compiler_identity = {
        "c_compiler": lock.native_toolchain.compiler_family,
        "the_cc_name": "gcc",
        "the_compiler": "gcc",
    }
    if scons_environment is None or any(
        scons_environment.attrib.get(name) != expected
        for name, expected in expected_compiler_identity.items()
    ):
        observed_compiler_identity = (
            None
            if scons_environment is None
            else {
                name: scons_environment.attrib.get(name)
                for name in expected_compiler_identity
            }
        )
        findings.append(
            "Nuitka native compiler identity does not match the production "
            f"lock: expected {expected_compiler_identity!r}, observed "
            f"{observed_compiler_identity!r}"
        )
    if root.attrib.get("mode") != "standalone":
        findings.append("Nuitka report is not a standalone build")
    if root.attrib.get("completion") != "yes":
        findings.append("Nuitka report did not complete successfully")
    module_names = tuple(
        element.attrib["name"]
        for element in root.findall(".//module")
        if element.attrib.get("name")
    )
    if package_kind is PackageKind.QML_JOURNEY:
        observed_modules = {name.casefold() for name in module_names}
        for module_name in sorted(_REQUIRED_PROJECT_DEPENDENCY_MODULES):
            if module_name.casefold() not in observed_modules:
                findings.append(
                    "Required real V1 module is absent from the QML "
                    f"dependency closure: {module_name}"
                )
        observed_data_files = {
            element.attrib["name"].replace("\\", "/").casefold()
            for element in root.findall(".//data_file")
            if element.attrib.get("name")
        }
        for source_path in sorted(
            _REQUIRED_FORMAL_STRATEGY_SOURCE_DATA_FILES
        ):
            if source_path.casefold() not in observed_data_files:
                findings.append(
                    "Required audited formal strategy source is absent from "
                    f"the QML package: {source_path}"
                )
    for usage in root.findall(".//module_usage"):
        module_name = usage.attrib.get("name", "")
        if (
            usage.attrib.get("finding") == "not-found"
            and module_name.casefold()
            in _REQUIRED_PROJECT_DEPENDENCY_MODULES
        ):
            findings.append(
                f"Missing project module in dependency graph: {module_name}"
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
            allowed = folded == "app.ui" or any(
                folded == prefix or folded.startswith(prefix + ".")
                for prefix in _QML_ALLOWED_APP_MODULE_PREFIXES
            )
            if not allowed:
                findings.append(
                    "Forbidden non-V2 application module in dependency graph: "
                    f"{module_name}"
                )
        if any(
            folded == prefix or folded.startswith(prefix + ".")
            for prefix in _FORBIDDEN_NETWORK_MODULE_PREFIXES
        ):
            findings.append(
                "Forbidden network module in dependency graph: "
                f"{module_name}"
            )
        if (
            package_kind is PackageKind.QML_JOURNEY
            and any(
                folded == prefix or folded.startswith(prefix + ".")
                for prefix in _QML_FORBIDDEN_BACKEND_MODULE_PREFIXES
            )
        ):
            findings.append(
                "Forbidden backend transaction module in QML dependency "
                f"graph: {module_name}"
            )
        if (
            package_kind is PackageKind.WIDGETS_ROLLBACK
            and any(
                folded == prefix or folded.startswith(prefix + ".")
                for prefix in _WIDGETS_FORBIDDEN_SEAM_MODULE_PREFIXES
            )
        ):
            findings.append(
                "Rollback baseline is coupled to the Frontend V2/V1 Seam: "
                f"{module_name}"
            )
        if package_kind is PackageKind.WIDGETS_ROLLBACK and folded.startswith(
            (
                "app.runtime_gateway",
                "app.controllers.trading",
                "app.services.trading",
                "app.panels.market.trade_dialog",
                "app.ui.journey_workspace",
                "app.ui.ui_refresh",
                "core.order",
                "services.order_service",
                "services.runtime_command_service",
                "stock_sim.core.order",
                "stock_sim.services.order_service",
                "stock_sim.services.runtime_command_service",
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


def _parse_nuitka_dependency_report(report_path: Path) -> ET.Element:
    payload = report_path.read_bytes()
    declaration = payload[:128]
    for alias, standard in (
        (b"encoding='utf8'", b"encoding='utf-8'"),
        (b'encoding="utf8"', b'encoding="utf-8"'),
    ):
        if alias in declaration:
            payload = payload.replace(alias, standard, 1)
            break
    return ET.fromstring(payload)


def audit_frontend_v2_surface(
    report: NoManualTradingGateReport | None = None,
) -> tuple[str, ...]:
    if report is None:
        report = audit_no_manual_trading_gate(PROJECT_ROOT)
    findings = list(report.findings)
    for source in qml_source_inventory(PROJECT_QML_ROOT):
        content = source.read_text(encoding="utf-8")
        if re.search(r"^\s*import\s+QtWeb", content, re.MULTILINE):
            findings.append(f"Web QML import found in {source.name}")
    return tuple(dict.fromkeys(findings))


def audit_packaged_formal_strategy_sources(
    distribution_dir: Path,
    *,
    source_root: Path = PROJECT_ROOT,
) -> tuple[str, ...]:
    """Verify retained strategy text against immutable compiled digests."""

    findings: list[str] = []
    for module_name, binding in FORMAL_STRATEGY_SOURCE_BINDINGS.items():
        paths = (
            (
                "source",
                source_root / binding.source_relative_path,
            ),
            (
                "packaged",
                distribution_dir / binding.packaged_relative_path,
            ),
        )
        for location, path in paths:
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                findings.append(
                    f"{location.capitalize()} audited formal strategy "
                    f"source is unavailable: {module_name}"
                )
                continue
            observed = hashlib.sha256(
                content.encode("utf-8")
            ).hexdigest()
            if observed != binding.normalized_sha256:
                findings.append(
                    f"{location.capitalize()} audited formal strategy "
                    f"source digest does not match: {module_name}"
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
    safety_evidence = audit_no_manual_trading_gate(
        PROJECT_ROOT,
        source_commit=source_commit,
    )
    surface_findings = audit_frontend_v2_surface(safety_evidence)
    if not safety_evidence.passed or surface_findings:
        raise RuntimeError(
            "Frontend V2 safety gate failed: "
            + "; ".join(surface_findings)
        )
    lock = load_toolchain_lock()
    native_toolchain_paths = verify_locked_native_toolchain(lock)
    plans = create_package_build_plans(
        output_root=output_root / "packages",
        source_commit=source_commit,
    )

    for plan in plans:
        _verify_isolated_pycache_root(plan)
        subprocess.run(
            plan.nuitka_command,
            cwd=PROJECT_ROOT,
            check=True,
        )
        _verify_isolated_pycache_root(plan)
        dependency_findings = audit_nuitka_dependency_report(
            plan.nuitka_report,
            package_kind=plan.kind,
        )
        if dependency_findings:
            raise RuntimeError(
                f"{plan.kind.value} dependency audit failed: "
                + "; ".join(dependency_findings)
            )
        if plan.kind is PackageKind.QML_JOURNEY:
            source_findings = audit_packaged_formal_strategy_sources(
                plan.distribution_dir
            )
            if source_findings:
                raise RuntimeError(
                    "qml-journey formal strategy source audit failed: "
                    + "; ".join(source_findings)
                )

    qml_plan = next(
        plan for plan in plans if plan.kind is PackageKind.QML_JOURNEY
    )
    widgets_plan = next(
        plan
        for plan in plans
        if plan.kind is PackageKind.WIDGETS_ROLLBACK
    )
    deploy_scanned_qml_runtime(
        qml_plan,
        objdump_path=native_toolchain_paths.binary_inspector,
    )
    stage_packaged_formal_v1_release_fixture(qml_plan)
    stage_packaged_wave2_release_input_fixture(qml_plan)

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
                "--package-assembly-smoke-report-dir",
                str(smoke_root / lane),
            ),
        )

    archive_dir = output_root / "archives"
    archives = tuple(
        create_deterministic_package_archive(
            plan,
            archive_dir=archive_dir,
        )
        for plan in plans
    )
    for plan in plans:
        archive_matches = tuple(
            archive
            for archive in archives
            if archive.relative_path.startswith(f"{plan.kind.value}-")
        )
        if len(archive_matches) != 1:
            raise RuntimeError(
                f"Final {plan.kind.value} archive identity is ambiguous"
            )
        _write_native_toolchain_attestation(
            plan=plan,
            archive_checksum=archive_matches[0],
            lock=lock,
        )

    evidence_dir = output_root / "evidence"
    package_evidence = write_package_evidence(
        plans=plans,
        archives=archives,
        evidence_dir=evidence_dir,
    )
    renderer_evidence = write_renderer_evidence(
        hardware_report=smoke_root / "hardware" / "smoke-report.json",
        software_report=smoke_root / "software" / "smoke-report.json",
        source_commit=source_commit,
        evidence_dir=evidence_dir,
    )
    renderer_gate_report = _checksum_file(
        evidence_dir / "renderer-gate-report.json",
        evidence_dir,
    )
    result = ReleaseBuildResult(
        source_commit=source_commit,
        output_root=str(output_root.resolve()),
        safety=safety_evidence,
        packages=package_evidence,
        renderers=renderer_evidence,
        renderer_gate_report=renderer_gate_report,
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


def stage_packaged_formal_v1_release_fixture(
    plan: PackageBuildPlan,
) -> SealedFormalV1ReleaseFixtureManifest:
    """Create the immutable real V1 state consumed by packaged QML smoke."""

    if plan.kind is not PackageKind.QML_JOURNEY:
        raise ValueError(
            "A sealed Strategy Diagnostics V1 fixture belongs only "
            "to the QML journey package"
        )
    destination = (
        plan.distribution_dir / FORMAL_V1_RELEASE_FIXTURE_ARCHIVE
    )
    if destination.exists():
        raise RuntimeError(
            f"Packaged V1 release fixture already exists: {destination}"
        )
    # DuckDB's Windows native writer still observes the traditional path
    # limit.  Build the immutable fixture beside the checkout, where the
    # staging path is short, then copy and re-verify the relative file seal.
    with tempfile.TemporaryDirectory(
        prefix="uti-v1-release-",
        dir=PROJECT_ROOT.parent,
    ) as temporary_root:
        staged = (
            Path(temporary_root) / FORMAL_V1_RELEASE_FIXTURE_DIRNAME
        )
        manifest = create_sealed_formal_v1_release_fixture(
            bundle_root=staged,
            source_commit=plan.source_commit,
        )
        write_sealed_formal_v1_release_fixture_archive(
            bundle_root=staged,
            archive_path=destination,
        )
        verified = extract_sealed_formal_v1_release_fixture_archive(
            archive_path=destination,
            bundle_root=Path(temporary_root) / "verified",
        )
        if verified != manifest:
            raise RuntimeError(
                "Packaged V1 release fixture changed during archive staging"
            )
    return verified


def stage_packaged_wave2_release_input_fixture(
    plan: PackageBuildPlan,
) -> SealedWave2ReleaseInputFixtureManifest:
    """Stage source-bound inputs; installed commands create all task state."""

    if plan.kind is not PackageKind.QML_JOURNEY:
        raise ValueError(
            "Wave 2 authoritative inputs belong only to the QML journey "
            "package"
        )
    destination = (
        plan.distribution_dir / WAVE3_RELEASE_INPUT_FIXTURE_ARCHIVE
    )
    if destination.exists():
        raise RuntimeError(
            "Packaged Wave 3 authoritative input fixture already exists: "
            f"{destination}"
        )
    with tempfile.TemporaryDirectory(
        prefix="uti-wave3-inputs-",
        dir=PROJECT_ROOT.parent,
    ) as temporary_root:
        staged = (
            Path(temporary_root) / WAVE3_RELEASE_INPUT_FIXTURE_DIRNAME
        )
        manifest = create_sealed_wave2_release_input_fixture(
            bundle_root=staged,
            source_commit=plan.source_commit,
        )
        write_sealed_wave2_release_input_fixture_archive(
            bundle_root=staged,
            archive_path=destination,
        )
        verified = extract_sealed_wave2_release_input_fixture_archive(
            archive_path=destination,
            bundle_root=Path(temporary_root) / "verified",
        )
        if verified != manifest:
            raise RuntimeError(
                "Packaged Wave 3 authoritative input fixture changed during staging"
            )
    return verified


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


def verify_packaged_dependency_evidence(
    candidate: dict[str, Any],
    *,
    output_root: Path,
) -> tuple[str, ...]:
    packages = candidate.get("packages")
    if not isinstance(packages, dict):
        return ("Packaged dependency evidence is unavailable",)
    retained_reports = packages.get("dependency_reports")
    if not isinstance(retained_reports, list):
        return ("Packaged dependency report inventory is unavailable",)

    expected_paths = {
        f"{kind.value}/nuitka-report.xml"
        for kind in PackageKind
    }
    packages_root = (output_root / "packages").resolve()
    observed_paths: set[str] = set()
    findings: list[str] = []
    for retained_report in retained_reports:
        if not isinstance(retained_report, dict):
            findings.append(
                "Packaged dependency report inventory is invalid"
            )
            continue
        relative_path = str(retained_report.get("relative_path", ""))
        observed_paths.add(relative_path)
        report_path = (packages_root / relative_path).resolve()
        try:
            report_path.relative_to(packages_root)
        except ValueError:
            findings.append(
                f"Dependency report escapes package root: {relative_path}"
            )
            continue
        if not report_path.is_file():
            findings.append(
                f"Dependency report is unavailable: {relative_path}"
            )
            continue
        observed = _checksum_file(report_path, packages_root)
        if (
            observed.sha256 != retained_report.get("sha256")
            or observed.size_bytes
            != retained_report.get("size_bytes")
        ):
            findings.append(
                "dependency report checksum does not match candidate "
                f"evidence: {relative_path}"
            )
            continue
        try:
            package_kind = PackageKind(relative_path.split("/", 1)[0])
        except ValueError:
            findings.append(
                f"Dependency report package kind is invalid: {relative_path}"
            )
            continue
        dependency_findings = audit_nuitka_dependency_report(
            report_path,
            package_kind=package_kind,
        )
        findings.extend(
            f"{package_kind.value}: {finding}"
            for finding in dependency_findings
        )
    if observed_paths != expected_paths:
        findings.append(
            "Packaged dependency report inventory does not match the "
            f"release pair: expected {sorted(expected_paths)!r}, "
            f"observed {sorted(observed_paths)!r}"
        )
    retained_attestations = packages.get("native_toolchain_attestations")
    expected_attestation_paths = {
        f"{kind.value}/native-toolchain-attestation.json"
        for kind in PackageKind
    }
    observed_attestation_paths: set[str] = set()
    lock = load_toolchain_lock()
    retained_archives = candidate.get("archives")
    archive_checksums_by_kind: dict[PackageKind, ArtifactChecksum] = {}
    if not isinstance(retained_archives, list):
        findings.append("Candidate archive inventory is unavailable")
    else:
        archives_root = (output_root / "archives").resolve()
        for kind in PackageKind:
            matches = tuple(
                archive
                for archive in retained_archives
                if isinstance(archive, dict)
                and str(archive.get("relative_path", "")).startswith(
                    f"{kind.value}-"
                )
                and str(archive.get("relative_path", "")).endswith(".zip")
            )
            if len(matches) != 1:
                findings.append(
                    f"Candidate {kind.value} archive identity is ambiguous"
                )
                continue
            retained_archive = matches[0]
            archive_path = (
                archives_root / str(retained_archive["relative_path"])
            ).resolve()
            try:
                archive_path.relative_to(archives_root)
            except ValueError:
                findings.append(
                    f"Candidate {kind.value} archive escapes archive root"
                )
                continue
            if not archive_path.is_file():
                findings.append(
                    f"Candidate {kind.value} archive is unavailable"
                )
                continue
            observed_archive = _checksum_file(
                archive_path,
                archives_root,
            )
            if (
                observed_archive.sha256 != retained_archive.get("sha256")
                or observed_archive.size_bytes
                != retained_archive.get("size_bytes")
            ):
                findings.append(
                    f"Candidate {kind.value} archive checksum does not match"
                )
                continue
            archive_checksums_by_kind[kind] = observed_archive
    if not isinstance(retained_attestations, list):
        findings.append(
            "Native toolchain attestation inventory is unavailable"
        )
    else:
        for retained_attestation in retained_attestations:
            if not isinstance(retained_attestation, dict):
                findings.append(
                    "Native toolchain attestation inventory is invalid"
                )
                continue
            relative_path = str(
                retained_attestation.get("relative_path", "")
            )
            observed_attestation_paths.add(relative_path)
            attestation_path = (packages_root / relative_path).resolve()
            try:
                attestation_path.relative_to(packages_root)
            except ValueError:
                findings.append(
                    "Native toolchain attestation escapes package root: "
                    f"{relative_path}"
                )
                continue
            if not attestation_path.is_file():
                findings.append(
                    "Native toolchain attestation is unavailable: "
                    f"{relative_path}"
                )
                continue
            observed_attestation = _checksum_file(
                attestation_path,
                packages_root,
            )
            if (
                observed_attestation.sha256
                != retained_attestation.get("sha256")
                or observed_attestation.size_bytes
                != retained_attestation.get("size_bytes")
            ):
                findings.append(
                    "Native toolchain attestation checksum does not match "
                    f"candidate evidence: {relative_path}"
                )
                continue
            try:
                package_kind = PackageKind(relative_path.split("/", 1)[0])
            except ValueError:
                findings.append(
                    "Native toolchain attestation package kind is invalid: "
                    f"{relative_path}"
                )
                continue
            report_path = packages_root / package_kind.value / "nuitka-report.xml"
            if not report_path.is_file():
                findings.append(
                    "Native toolchain attestation report is unavailable: "
                    f"{package_kind.value}"
                )
                continue
            archive_checksum = archive_checksums_by_kind.get(package_kind)
            if archive_checksum is None:
                continue
            distribution_dir = packages_root / package_kind.value / (
                "frontend_widgets_rollback_entry.dist"
                if package_kind is PackageKind.WIDGETS_ROLLBACK
                else "frontend_v2_package_entry.dist"
            )
            if not distribution_dir.is_dir():
                findings.append(
                    "Native toolchain attestation distribution is "
                    f"unavailable: {package_kind.value}"
                )
                continue
            distribution_inventory = _inventory_distribution(
                kind=package_kind,
                source_commit=str(candidate.get("source_commit", "")),
                distribution_dir=distribution_dir,
            )
            expected_payload = _expected_native_toolchain_attestation_payload(
                package_kind=package_kind,
                source_commit=str(candidate.get("source_commit", "")),
                report_checksum=_checksum_file(
                    report_path,
                    packages_root / package_kind.value,
                ),
                distribution_identity={
                    "file_count": distribution_inventory.file_count,
                    "total_bytes": distribution_inventory.total_bytes,
                    "tree_sha256": distribution_inventory.tree_sha256,
                },
                archive_checksum=archive_checksum,
                lock=lock,
            )
            try:
                observed_payload = _load_json_mapping(attestation_path)
            except (OSError, ValueError, json.JSONDecodeError) as error:
                findings.append(
                    "Native toolchain attestation is unreadable: "
                    f"{package_kind.value}: {type(error).__name__}"
                )
                continue
            if observed_payload != expected_payload:
                findings.append(
                    "Native toolchain attestation does not match the "
                    f"production lock/report: {package_kind.value}"
                )
        if observed_attestation_paths != expected_attestation_paths:
            findings.append(
                "Native toolchain attestation inventory does not match the "
                f"release pair: expected "
                f"{sorted(expected_attestation_paths)!r}, observed "
                f"{sorted(observed_attestation_paths)!r}"
            )
    retained_sources = packages.get("formal_strategy_sources")
    expected_source_paths = {
        (
            "qml-journey/frontend_v2_package_entry.dist/"
            + binding.packaged_relative_path
        )
        for binding in FORMAL_STRATEGY_SOURCE_BINDINGS.values()
    }
    observed_source_paths: set[str] = set()
    if not isinstance(retained_sources, list):
        findings.append(
            "Packaged formal strategy source inventory is unavailable"
        )
    else:
        for retained_source in retained_sources:
            if not isinstance(retained_source, dict):
                findings.append(
                    "Packaged formal strategy source inventory is invalid"
                )
                continue
            relative_path = str(
                retained_source.get("relative_path", "")
            )
            observed_source_paths.add(relative_path)
            source_path = (packages_root / relative_path).resolve()
            try:
                source_path.relative_to(packages_root)
            except ValueError:
                findings.append(
                    "Packaged formal strategy source escapes package root: "
                    f"{relative_path}"
                )
                continue
            if not source_path.is_file():
                findings.append(
                    "Packaged formal strategy source is unavailable: "
                    f"{relative_path}"
                )
                continue
            observed = _checksum_file(source_path, packages_root)
            if (
                observed.sha256 != retained_source.get("sha256")
                or observed.size_bytes
                != retained_source.get("size_bytes")
            ):
                findings.append(
                    "Packaged formal strategy source checksum does not "
                    f"match candidate evidence: {relative_path}"
                )
        if observed_source_paths != expected_source_paths:
            findings.append(
                "Packaged formal strategy source inventory does not match "
                f"the registered bindings: expected "
                f"{sorted(expected_source_paths)!r}, observed "
                f"{sorted(observed_source_paths)!r}"
            )
    findings.extend(
        audit_packaged_formal_strategy_sources(
            packages_root
            / "qml-journey"
            / "frontend_v2_package_entry.dist"
        )
    )
    return tuple(dict.fromkeys(findings))


def certify_frontend_v2_release(
    *,
    output_root: Path,
    source_commit: str,
    clean_room_report: Path,
    accessibility_junit: Path | None = None,
    performance_evidence_dir: Path | None = None,
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
    renderer_gate_path = evidence_dir / "renderer-gate-report.json"
    if not renderer_gate_path.is_file():
        raise FileNotFoundError(
            "Release candidate renderer gate evidence is unavailable: "
            f"{renderer_gate_path}"
        )
    retained_renderer_gate_report = candidate.get("renderer_gate_report")
    if not isinstance(retained_renderer_gate_report, Mapping):
        raise RuntimeError(
            "Release candidate renderer gate checksum is unavailable"
        )
    observed_renderer_gate_report = _checksum_file(
        renderer_gate_path,
        evidence_dir,
    )
    if asdict(observed_renderer_gate_report) != dict(
        retained_renderer_gate_report
    ):
        raise RuntimeError(
            "Release candidate renderer gate checksum does not match"
        )
    candidate_renderers = candidate.get("renderers")
    if not isinstance(candidate_renderers, Mapping):
        raise RuntimeError(
            "Release candidate renderer projection is unavailable"
        )
    renderer_gate_failures = verify_renderer_gate_report(
        renderer_gate_path,
        expected_source_commit=source_commit,
        expected_candidate_renderers=candidate_renderers,
    )
    if renderer_gate_failures:
        raise RuntimeError(
            "Renderer gate candidate verification failed: "
            + "; ".join(renderer_gate_failures)
        )
    safety_failures = verify_safety_gate_evidence(
        candidate,
        expected_source_commit=source_commit,
    )
    if safety_failures:
        raise RuntimeError(
            "Safety gate certification failed: "
            + "; ".join(safety_failures)
        )
    dependency_failures = verify_packaged_dependency_evidence(
        candidate,
        output_root=output_root,
    )
    if dependency_failures:
        raise RuntimeError(
            "Dependency audit certification failed: "
            + "; ".join(dependency_failures)
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
    widgets_archive_sha256 = str(
        widgets_archives[0].get("sha256", "")
    )
    failures = verify_clean_room_report(
        clean_room_report,
        expected_source_commit=source_commit,
        expected_archive_sha256=qml_archive_sha256,
        expected_widgets_archive_sha256=widgets_archive_sha256,
    )
    if failures:
        raise RuntimeError(
            "Clean-room certification failed: " + "; ".join(failures)
        )
    if accessibility_junit is None or performance_evidence_dir is None:
        raise RuntimeError(
            "T08 accessibility and T10 performance evidence are mandatory "
            "release inputs"
        )
    mandatory_gates = write_mandatory_release_gate_evidence(
        accessibility_junit=accessibility_junit,
        performance_evidence_dir=performance_evidence_dir,
        candidate=candidate,
        source_commit=source_commit,
        evidence_dir=evidence_dir,
    )
    mandatory_gates_sha256 = _sha256_path(
        evidence_dir / "mandatory-release-gates.json"
    )

    report_payload: dict[str, Any] = json.loads(
        clean_room_report.read_text(encoding="utf-8-sig")
    )
    _retain_clean_room_screenshots(
        report_path=clean_room_report,
        report_payload=report_payload,
        evidence_dir=evidence_dir,
    )
    report_checksum = _checksum_file(
        clean_room_report,
        clean_room_report.parent,
    )
    certification = CleanRoomCertification(
        source_commit=source_commit,
        qml_archive_sha256=qml_archive_sha256,
        widgets_archive_sha256=widgets_archive_sha256,
        clean_room_report_sha256=report_checksum.sha256,
        mandatory_release_gates_sha256=mandatory_gates_sha256,
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
        "mandatory_release_gates": asdict(mandatory_gates),
        "clean_room": asdict(certification),
        "clean_room_report": report_payload,
    }
    (evidence_dir / "release-summary.json").write_text(
        json.dumps(final_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return certification


def verify_safety_gate_evidence(
    candidate: dict[str, Any],
    *,
    expected_source_commit: str,
) -> tuple[str, ...]:
    findings = list(
        verify_safety_gate_payload(
            candidate,
            expected_source_commit=expected_source_commit,
        )
    )
    if findings:
        return tuple(findings)
    observed = audit_no_manual_trading_gate(
        PROJECT_ROOT,
        source_commit=expected_source_commit,
    )
    findings.extend(
        verify_safety_gate_payload(
            candidate,
            expected_source_commit=expected_source_commit,
            expected_source_digest=observed.source_digest,
        )
    )
    safety = candidate.get("safety")
    expected_payload = json.loads(json.dumps(asdict(observed)))
    if safety != expected_payload:
        findings.append(
            "Safety gate evidence does not match the freshly audited report"
        )
    return tuple(dict.fromkeys(findings))


def write_mandatory_release_gate_evidence(
    *,
    accessibility_junit: Path,
    performance_evidence_dir: Path,
    candidate: Mapping[str, Any],
    source_commit: str,
    evidence_dir: Path,
) -> MandatoryReleaseGateEvidence:
    """Recompute and retain the exact-build T08, T09, and T10 inputs."""

    accessibility_tree = ET.parse(accessibility_junit)
    accessibility_root = accessibility_tree.getroot()
    test_cases = tuple(accessibility_root.iter("testcase"))
    accessibility_properties: dict[str, set[str]] = {}
    for property_element in accessibility_root.iter("property"):
        property_name = str(property_element.attrib.get("name", ""))
        property_value = str(property_element.attrib.get("value", ""))
        if property_name:
            accessibility_properties.setdefault(
                property_name,
                set(),
            ).add(property_value)
    source_identities = accessibility_properties.get(
        "frontend_v2_source_commit",
        set(),
    )
    if source_identities != {source_commit}:
        raise RuntimeError(
            "T08 accessibility source identity does not match the "
            "release build"
        )
    toolchain_lock_digest = _sha256_path(TOOLCHAIN_LOCK_PATH)
    toolchain_identities = accessibility_properties.get(
        "frontend_v2_toolchain_lock_sha256",
        set(),
    )
    if toolchain_identities != {toolchain_lock_digest}:
        raise RuntimeError(
            "T08 accessibility toolchain identity does not match the "
            "release build"
        )
    observed_test_names: set[str] = set()
    for test_case in test_cases:
        test_name = str(test_case.attrib.get("name", ""))
        observed_test_names.add(test_name)
        observed_test_names.add(test_name.partition("[")[0])
    missing_tests = sorted(
        _REQUIRED_ACCESSIBILITY_TESTS - observed_test_names
    )
    if missing_tests:
        raise RuntimeError(
            "T08 accessibility coverage is incomplete: "
            + ", ".join(missing_tests)
        )
    failed_tests = tuple(
        str(test_case.attrib.get("name", "unnamed"))
        for test_case in test_cases
        if any(
            test_case.find(outcome) is not None
            for outcome in ("failure", "error", "skipped")
        )
    )
    if failed_tests:
        raise RuntimeError(
            "T08 accessibility gate is not fully green: "
            + ", ".join(failed_tests)
        )

    performance_paths = {
        name: performance_evidence_dir / name
        for name in (
            "hardware.json",
            "software.json",
            "no-manual-trading.json",
            "certification.json",
            FORMAL_V1_RELEASE_FIXTURE_ARCHIVE,
        )
    }
    missing_performance_files = tuple(
        name
        for name, path in performance_paths.items()
        if not path.is_file()
    )
    if missing_performance_files:
        raise FileNotFoundError(
            "T10 performance evidence is incomplete: "
            + ", ".join(missing_performance_files)
        )
    hardware = _load_json_mapping(performance_paths["hardware.json"])
    software = _load_json_mapping(performance_paths["software.json"])
    safety = _load_json_mapping(
        performance_paths["no-manual-trading.json"]
    )
    stored_performance = _load_json_mapping(
        performance_paths["certification.json"]
    )
    fixture_archive_sha256 = _sha256_path(
        performance_paths[FORMAL_V1_RELEASE_FIXTURE_ARCHIVE]
    )
    for lane_name, lane_report in (
        ("hardware", hardware),
        ("software", software),
    ):
        probe = lane_report.get("integrated_v1_probe")
        observed_digest = (
            probe.get("fixture_archive_digest")
            if isinstance(probe, Mapping)
            else None
        )
        if observed_digest != fixture_archive_sha256:
            raise RuntimeError(
                f"T10 {lane_name} report does not match the retained "
                "fixture archive checksum"
            )
    candidate_safety = candidate.get("safety")
    if not isinstance(candidate_safety, Mapping):
        raise RuntimeError("T09 candidate safety evidence is unavailable")
    normalized_candidate_safety = json.loads(
        json.dumps(candidate_safety, sort_keys=True)
    )
    normalized_safety = json.loads(json.dumps(safety, sort_keys=True))
    if normalized_candidate_safety != normalized_safety:
        raise RuntimeError(
            "T09 safety evidence does not match the release candidate"
        )
    safety_failures = verify_safety_gate_payload(
        {"safety": normalized_safety},
        expected_source_commit=source_commit,
    )
    if safety_failures:
        raise RuntimeError(
            "T09 safety gate is not green for the release build: "
            + "; ".join(safety_failures)
        )

    from stock_sim.release.frontend_v2_performance import (
        certify_performance_evidence,
    )

    recomputed_performance = certify_performance_evidence(
        hardware,
        software,
        normalized_safety,
        expected_source_commit=source_commit,
        expected_toolchain_digest=toolchain_lock_digest,
        expected_fixture_archive_digest=fixture_archive_sha256,
    )
    recomputed_payload = json.loads(
        json.dumps(asdict(recomputed_performance), sort_keys=True)
    )
    normalized_stored_performance = json.loads(
        json.dumps(stored_performance, sort_keys=True)
    )
    if normalized_stored_performance != recomputed_payload:
        raise RuntimeError(
            "T10 performance aggregate does not match raw evidence"
        )
    if recomputed_performance.status != "certified":
        raise RuntimeError(
            "T10 performance gate is not green for the release build: "
            + "; ".join(recomputed_performance.failures)
        )

    gates_root = evidence_dir / "gates"
    accessibility_target = gates_root / "accessibility" / "junit.xml"
    safety_target = gates_root / "safety" / "no-manual-trading.json"
    performance_targets = {
        name: gates_root / "performance" / name
        for name in (
            "hardware.json",
            "software.json",
            "certification.json",
            FORMAL_V1_RELEASE_FIXTURE_ARCHIVE,
        )
    }
    accessibility_target.parent.mkdir(parents=True, exist_ok=True)
    safety_target.parent.mkdir(parents=True, exist_ok=True)
    next(iter(performance_targets.values())).parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    shutil.copy2(accessibility_junit, accessibility_target)
    shutil.copy2(
        performance_paths["no-manual-trading.json"],
        safety_target,
    )
    for name, target in performance_targets.items():
        shutil.copy2(performance_paths[name], target)

    accessibility = AccessibilityGateEvidence(
        issue_number=43,
        issue_url="https://github.com/m4ngod/UTI-STOCKSIM/issues/43",
        source_commit=source_commit,
        status="passed",
        test_count=len(test_cases),
        junit_sha256=_sha256_path(accessibility_target),
    )
    safety_evidence = SafetyGateEvidence(
        issue_number=44,
        issue_url="https://github.com/m4ngod/UTI-STOCKSIM/issues/44",
        source_commit=source_commit,
        status="passed",
        report_sha256=_sha256_path(safety_target),
    )
    performance_evidence = PerformanceGateEvidence(
        issue_number=45,
        issue_url="https://github.com/m4ngod/UTI-STOCKSIM/issues/45",
        source_commit=source_commit,
        status="certified",
        fixture_archive_sha256=_sha256_path(
            performance_targets[FORMAL_V1_RELEASE_FIXTURE_ARCHIVE]
        ),
        certification_sha256=_sha256_path(
            performance_targets["certification.json"]
        ),
        hardware_report_sha256=_sha256_path(
            performance_targets["hardware.json"]
        ),
        software_report_sha256=_sha256_path(
            performance_targets["software.json"]
        ),
        safety_report_sha256=_sha256_path(safety_target),
    )
    evidence = MandatoryReleaseGateEvidence(
        source_commit=source_commit,
        toolchain_identity=toolchain_evidence_identity(
            load_toolchain_lock()
        ),
        accessibility=accessibility,
        safety=safety_evidence,
        performance=performance_evidence,
    )
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "mandatory-release-gates.json").write_text(
        json.dumps(asdict(evidence), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return evidence


def _load_json_mapping(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _sha256_path(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return f"sha256:{hasher.hexdigest()}"


def _run_packaged_smoke(
    plan: PackageBuildPlan,
    arguments: tuple[str, ...],
) -> None:
    executable = plan.distribution_dir / plan.executable_name
    completed = subprocess.run(
        (
            str(executable),
            f"--source-commit={plan.source_commit}",
            *arguments,
        ),
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
    parser.add_argument("--accessibility-junit", type=Path)
    parser.add_argument("--performance-evidence-dir", type=Path)
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
        if (
            arguments.accessibility_junit is None
            or arguments.performance_evidence_dir is None
        ):
            parser.error(
                "--accessibility-junit and --performance-evidence-dir "
                "are required for certification"
            )
        certification = certify_frontend_v2_release(
            output_root=arguments.output_root,
            source_commit=arguments.source_commit,
            clean_room_report=arguments.certify_clean_room_report,
            accessibility_junit=arguments.accessibility_junit,
            performance_evidence_dir=arguments.performance_evidence_dir,
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
    "AccessibilityGateEvidence",
    "CleanRoomCertification",
    "FrontendV2ToolchainLock",
    "LockedBuildArtifact",
    "LockedExecutable",
    "LockedNativeToolchain",
    "LockedNativeToolchainPaths",
    "MandatoryReleaseGateEvidence",
    "PackageEvidence",
    "PerformanceGateEvidence",
    "RendererGateEvidence",
    "ReleaseBuildResult",
    "SafetyGateEvidence",
    "audit_packaged_formal_strategy_sources",
    "build_frontend_v2_release",
    "certify_frontend_v2_release",
    "load_toolchain_lock",
    "main",
    "stage_packaged_formal_v1_release_fixture",
    "stage_packaged_wave2_release_input_fixture",
    "toolchain_evidence_identity",
    "verify_safety_gate_evidence",
    "verify_clean_room_report",
    "verify_running_toolchain",
    "verify_locked_native_toolchain",
    "verify_renderer_gate_report",
    "write_mandatory_release_gate_evidence",
]


if __name__ == "__main__":
    raise SystemExit(main())
