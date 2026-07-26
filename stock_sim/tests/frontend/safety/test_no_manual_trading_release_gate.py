from __future__ import annotations

from dataclasses import FrozenInstanceError, asdict, replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib

import pytest

from app.features import (
    CancelDiagnosticTask,
    DeterministicFakeEvidenceAndFindingsAdapter,
    DeterministicFakeRunMonitoringAdapter,
    DiagnosticTaskId,
    EvidenceAndFindingsFeature,
    FillEvidenceTrace,
    LiveEvidenceAndFindingsAdapter,
    LiveRunMonitoringAdapter,
    OrderEvidenceTrace,
    ReadOnlyDiagnosticContext,
    ReadOnlyEvidenceContext,
    RunMonitoringFeature,
)
from stock_sim.release.no_manual_trading_gate import (
    ACTIVE_FEATURE_INTERFACE_ALLOWLIST,
    JOURNEY_ROUTE_ALLOWLIST,
    JOURNEY_SHORTCUT_KEY_ALLOWLIST,
    QML_ADAPTER_SLOT_ALLOWLIST,
    REQUIRED_GATE_SURFACES,
    TELEMETRY_EVENT_ALLOWLIST,
    audit_feature_interface,
    audit_no_manual_trading_gate,
    audit_python_imports,
    audit_python_text,
    audit_qml_text,
    audit_runtime_gateway_text,
    main as safety_gate_main,
    passed_junit_test_cases,
    qml_source_inventory,
)
from stock_sim.release import frontend_v2_packaging


PROJECT_ROOT = Path(__file__).resolve().parents[3]
FORBIDDEN_RUNTIME_MEMBERS = (
    "submit_order",
    "place_order",
    "cancel_order",
    "replace_order",
    "bulk_order",
    "buy",
    "sell",
    "dispatch",
)


def test_current_wave1_slice_passes_every_mandatory_safety_surface():
    report = audit_no_manual_trading_gate(
        PROJECT_ROOT,
        source_commit="issue-44-test",
    )

    assert report.passed is True
    assert report.status == "passed"
    assert report.findings == ()
    assert set(report.checked_surfaces) == set(REQUIRED_GATE_SURFACES)
    assert set(report.adapter_modes) == {"deterministic_fake", "live"}
    assert dict(report.feature_members) == {
        name: tuple(sorted(members))
        for name, members in ACTIVE_FEATURE_INTERFACE_ALLOWLIST.items()
    }
    assert dict(report.qml_adapter_slots) == {
        name: tuple(sorted(members))
        for name, members in QML_ADAPTER_SLOT_ALLOWLIST.items()
    }
    assert report.routes == tuple(sorted(JOURNEY_ROUTE_ALLOWLIST))
    assert report.shortcut_keys == tuple(
        sorted(JOURNEY_SHORTCUT_KEY_ALLOWLIST)
    )
    assert report.telemetry_events == tuple(
        sorted(TELEMETRY_EVENT_ALLOWLIST)
    )
    assert report.source_digest.startswith("sha256:")
    assert report.runtime_test_exit_code == 0
    assert set(report.runtime_test_cases) == {
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
    runtime_test = (
        PROJECT_ROOT
        / "tests"
        / "frontend"
        / "safety"
        / "test_no_manual_trading_runtime_gate.py"
    )
    assert report.runtime_test_file_digest == (
        "sha256:" + hashlib.sha256(runtime_test.read_bytes()).hexdigest()
    )


def test_gate_refuses_to_mix_a_target_tree_with_imports_from_another_tree(
    tmp_path,
):
    with pytest.raises(ValueError, match="same source tree"):
        audit_no_manual_trading_gate(tmp_path)


def test_public_feature_reflection_is_exact_and_generic_dispatch_is_rejected():
    assert audit_feature_interface(
        "RunMonitoringFeature",
        RunMonitoringFeature,
        ACTIVE_FEATURE_INTERFACE_ALLOWLIST["RunMonitoringFeature"],
    ) == ()
    assert audit_feature_interface(
        "EvidenceAndFindingsFeature",
        EvidenceAndFindingsFeature,
        ACTIVE_FEATURE_INTERFACE_ALLOWLIST[
            "EvidenceAndFindingsFeature"
        ],
    ) == ()

    class CompromisedRunMonitoringFeature:
        interface_version = "1.0"

        def snapshot(self):
            return None

        def subscribe(self):
            return None

        def pause_diagnostic_task(self):
            return None

        def resume_diagnostic_task(self):
            return None

        def cancel_diagnostic_task(self):
            return None

        def close(self):
            return None

        def dispatch(self, payload):
            return payload

    findings = audit_feature_interface(
        "RunMonitoringFeature",
        CompromisedRunMonitoringFeature,
        ACTIVE_FEATURE_INTERFACE_ALLOWLIST["RunMonitoringFeature"],
    )

    assert any("dispatch" in finding for finding in findings)


def test_every_live_and_fake_adapter_denies_manual_runtime_members():
    adapter_types = (
        DeterministicFakeRunMonitoringAdapter,
        LiveRunMonitoringAdapter,
        DeterministicFakeEvidenceAndFindingsAdapter,
        LiveEvidenceAndFindingsAdapter,
    )

    for adapter_type in adapter_types:
        for member in FORBIDDEN_RUNTIME_MEMBERS:
            assert not hasattr(adapter_type, member), (
                f"{adapter_type.__name__}.{member} must remain unavailable"
            )


def test_diagnostic_task_cancel_has_a_distinct_typed_identity():
    command = CancelDiagnosticTask(
        target_id=DiagnosticTaskId("TASK-SAFETY-44"),
        expected_revision=1,
    )

    assert type(command) is CancelDiagnosticTask
    assert command.target_id == DiagnosticTaskId("TASK-SAFETY-44")
    assert not hasattr(command, "order_id")


def test_market_account_position_order_and_fill_context_is_immutable():
    run_context = ReadOnlyDiagnosticContext(
        market=("600519.SH",),
        account=("MODEL-B17",),
        positions=("600519.SH +100",),
        orders=("ORD-001 filled",),
        fills=("FILL-001 100 @ 1500",),
    )
    evidence_context = ReadOnlyEvidenceContext(
        market=("600519.SH",),
        account=("MODEL-B17",),
        positions=("600519.SH +100",),
        orders=(
            OrderEvidenceTrace(
                identity="ORD-001",
                instrument="600519.SH",
                status="filled",
                diagnostic_note="Read-only trace.",
            ),
        ),
        fills=(
            FillEvidenceTrace(
                identity="FILL-001",
                order_identity="ORD-001",
                instrument="600519.SH",
                quantity=100,
                price="1500",
            ),
        ),
    )

    with pytest.raises(FrozenInstanceError):
        run_context.orders = ("ORD-COMPROMISED",)
    with pytest.raises(FrozenInstanceError):
        evidence_context.fills = ()
    assert isinstance(run_context.orders, tuple)
    assert isinstance(evidence_context.orders, tuple)
    assert isinstance(evidence_context.fills, tuple)


def test_qml_gate_allows_diagnostic_cancel_and_rejects_transaction_actions():
    safe_qml = """
    DiagnosticCommandButton {
        objectName: "cancelDiagnosticTask"
        text: "Cancel diagnostic task"
        onInvoked: runMonitoring.cancelDiagnosticTask()
    }
    """
    compromised_qml = """
    Rectangle {
        objectName: "hiddenOrderEntry"
        Accessible.role: Accessible.Button
        Accessible.name: "Buy"
        property string secondaryAction: "sell"
        property string transactionKind: "order-entry"
        Keys.onReturnPressed: dispatch("submit_order")
    }
    """

    assert audit_qml_text("Safe.qml", safe_qml) == ()
    findings = audit_qml_text("Compromised.qml", compromised_qml)
    assert any("hiddenOrderEntry" in finding for finding in findings)
    assert any("Buy" in finding for finding in findings)
    assert any("'sell'" in finding for finding in findings)
    assert any("order-entry" in finding for finding in findings)
    assert any("submit_order" in finding for finding in findings)


def test_python_gate_rejects_direct_dynamic_and_camel_case_order_dispatch():
    safe_python = (
        "def cancel_diagnostic_task(controller, task_id):\n"
        "    return controller.cancel_diagnostic_task(task_id)\n"
    )
    compromised_python = (
        "def compromised(gateway, order_id, payload):\n"
        "    gateway.cancelOrder(order_id)\n"
        "    getattr(gateway, 'submit_order')(payload)\n"
        "    return gateway.dispatch(payload)\n"
    )

    assert audit_python_text("safe.py", safe_python) == ()
    findings = audit_python_text("compromised.py", compromised_python)
    assert any("cancelOrder" in finding for finding in findings)
    assert any("submit_order" in finding for finding in findings)
    assert any("dispatch" in finding for finding in findings)


def test_python_import_gate_rejects_backend_transaction_dependencies():
    safe_python = (
        "from app.features.run_monitoring import RunMonitoringFeature\n"
    )
    compromised_python = (
        "from services.order_service import OrderService\n"
        "from stock_sim.persistence.models_order import OrderORM\n"
        "from app import runtime_gateway\n"
        "from stock_sim import services\n"
        "from app.services.trading_service import TradingService\n"
        "from .. import runtime_gateway as parent_gateway\n"
    )

    assert audit_python_imports("safe.py", safe_python) == ()
    findings = audit_python_imports(
        "compromised.py",
        compromised_python,
        package_name="app.features",
    )
    assert any("services.order_service" in item for item in findings)
    assert any(
        "stock_sim.persistence.models_order" in item
        for item in findings
    )
    assert any("app.runtime_gateway" in item for item in findings)
    assert any("stock_sim.services" in item for item in findings)
    assert any(
        "app.services.trading_service" in item
        for item in findings
    )


@pytest.mark.parametrize(
    ("source", "expected_finding"),
    (
        (
            "from importlib import import_module as load\n"
            "load('services.order_service')\n",
            "dynamic import loader 'importlib'",
        ),
        (
            "loader = __import__\n"
            "loader('stock_sim.persistence.models_order')\n",
            "dynamic import loader '__import__'",
        ),
        (
            "loader = getattr(__builtins__, '__import__')\n"
            "loader('services.order_service')\n",
            "dynamic import reflection '__import__'",
        ),
        (
            "exec('from services.order_service import OrderService')\n",
            "dynamic execution 'exec'",
        ),
        (
            "runner = __builtins__.exec\n"
            "runner('from services.order_service import OrderService')\n",
            "dynamic execution '__builtins__.exec'",
        ),
    ),
)
def test_python_import_gate_rejects_each_dynamic_loader_independently(
    source,
    expected_finding,
):
    findings = audit_python_imports(
        "dynamic_probe.py",
        source,
        package_name="app.features",
    )

    assert any(expected_finding in item for item in findings)


def test_runtime_junit_sentinel_counts_only_executed_passing_cases(tmp_path):
    report = tmp_path / "runtime-tests.xml"
    report.write_text(
        """
        <testsuites>
          <testsuite tests="3" failures="0" errors="0" skipped="2">
            <testcase name="passed" />
            <testcase name="skipped"><skipped /></testcase>
            <testcase name="xfail"><skipped type="pytest.xfail" /></testcase>
          </testsuite>
        </testsuites>
        """,
        encoding="utf-8",
    )

    assert passed_junit_test_cases(report) == ("passed",)


def test_qml_inventory_recurses_into_every_packaged_component(tmp_path):
    qml_root = tmp_path / "qml"
    nested = qml_root / "controls" / "HiddenOrderEntry.qml"
    nested.parent.mkdir(parents=True)
    nested.write_text("Item {}", encoding="utf-8")
    root = qml_root / "JourneyWorkspace.qml"
    root.write_text("Item {}", encoding="utf-8")

    assert tuple(
        path.relative_to(qml_root).as_posix()
        for path in qml_source_inventory(qml_root)
    ) == (
        "JourneyWorkspace.qml",
        "controls/HiddenOrderEntry.qml",
    )


def test_runtime_gateway_gate_rejects_alias_and_helper_delegation():
    safe = """
class LiveAdapter:
    def __init__(self, runtime_gateway):
        self._runtime_gateway = runtime_gateway

    def read(self):
        return self._runtime_gateway.get_snapshot()
"""
    compromised = """
class LiveAdapter:
    def __init__(self, runtime_gateway):
        self._runtime_gateway = runtime_gateway

    def read(self, helper):
        gateway = self._runtime_gateway
        helper(self._runtime_gateway)
        return gateway.cancel_order("ORD-44")
"""

    observed, findings = audit_runtime_gateway_text(
        "safe.py",
        safe,
        class_name="LiveAdapter",
        allowed_calls=frozenset({"get_snapshot"}),
    )
    assert observed == frozenset({"get_snapshot"})
    assert findings == ()

    observed, findings = audit_runtime_gateway_text(
        "compromised.py",
        compromised,
        class_name="LiveAdapter",
        allowed_calls=frozenset({"get_snapshot"}),
    )
    assert observed == frozenset()
    assert any("indirect RuntimeGateway access" in item for item in findings)


def test_packaging_surface_audit_delegates_to_the_mandatory_gate():
    assert frontend_v2_packaging.audit_frontend_v2_surface() == ()


def test_release_gate_has_a_source_tree_module_cli(capsys):
    metadata = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert (
        "frontend-v2-no-manual-trading-gate"
        not in metadata["project"]["scripts"]
    )
    assert safety_gate_main(
        (
            "--project-root",
            str(PROJECT_ROOT),
            "--source-commit",
            "issue-44-test",
        )
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "passed"
    assert payload["adapter_modes"] == ["deterministic_fake", "live"]


def test_release_gate_cannot_be_switched_to_collect_only_by_environment():
    environment = os.environ.copy()
    environment["PYTEST_ADDOPTS"] = "--collect-only"
    completed = subprocess.run(
        (
            sys.executable,
            "-m",
            "stock_sim.release.no_manual_trading_gate",
            "--project-root",
            str(PROJECT_ROOT),
            "--source-commit",
            "issue-44-hostile-environment",
        ),
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        timeout=180,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["runtime_test_exit_code"] == 0
    assert len(payload["runtime_test_cases"]) == 5
    assert payload["status"] == "passed"


def test_safety_failure_blocks_release_before_any_package_build(
    tmp_path,
    monkeypatch,
):
    package_build_started = False

    def record_package_build(**_kwargs):
        nonlocal package_build_started
        package_build_started = True
        return ()

    monkeypatch.setattr(
        frontend_v2_packaging,
        "verify_release_source",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        frontend_v2_packaging,
        "create_package_build_plans",
        record_package_build,
    )
    audited = audit_no_manual_trading_gate(
        PROJECT_ROOT,
        source_commit="compromised",
    )
    failed_report = replace(
        audited,
        status="failed",
        findings=("manual order command exposed",),
    )
    gate_calls = 0

    def run_gate(*_args, **_kwargs):
        nonlocal gate_calls
        gate_calls += 1
        return failed_report

    def inspect_same_report(report):
        assert report is failed_report
        return report.findings

    monkeypatch.setattr(
        frontend_v2_packaging,
        "audit_no_manual_trading_gate",
        run_gate,
    )
    monkeypatch.setattr(
        frontend_v2_packaging,
        "audit_frontend_v2_surface",
        inspect_same_report,
    )

    with pytest.raises(
        RuntimeError,
        match="Frontend V2 safety gate failed",
    ):
        frontend_v2_packaging.build_frontend_v2_release(
            output_root=tmp_path / "release",
            source_commit="compromised",
        )

    assert package_build_started is False
    assert gate_calls == 1
    assert not (tmp_path / "release" / "packages").exists()


def test_clean_room_certification_rejects_missing_or_failed_safety_evidence(
    tmp_path,
):
    candidate_path = tmp_path / "release-candidate-summary.json"
    candidate_path.write_text(
        json.dumps({"source_commit": "abc123"}),
        encoding="utf-8",
    )

    missing = frontend_v2_packaging.verify_safety_gate_evidence(
        json.loads(candidate_path.read_text(encoding="utf-8")),
        expected_source_commit="abc123",
    )
    assert "Safety gate evidence is unavailable" in missing

    failed = frontend_v2_packaging.verify_safety_gate_evidence(
        {
            "source_commit": "abc123",
            "safety": {
                "source_commit": "abc123",
                "status": "failed",
                "adapter_modes": ["deterministic_fake", "live"],
                "checked_surfaces": list(REQUIRED_GATE_SURFACES),
                "findings": ["manual order command exposed"],
                "source_digest": "sha256:" + "0" * 64,
            },
        },
        expected_source_commit="abc123",
    )
    assert "Safety gate status is not passed" in failed
    assert "Safety gate contains findings" in failed


def test_clean_room_certification_rejects_fabricated_source_digest():
    safety = json.loads(
        json.dumps(
            asdict(
                audit_no_manual_trading_gate(
                    PROJECT_ROOT,
                    source_commit="abc123",
                )
            )
        )
    )
    safety["source_digest"] = "sha256:" + "0" * 64

    failures = frontend_v2_packaging.verify_safety_gate_evidence(
        {
            "source_commit": "abc123",
            "safety": safety,
        },
        expected_source_commit="abc123",
    )

    assert "Safety gate source digest does not match audited source" in (
        failures
    )


def test_future_manual_trading_is_denied_by_default_in_product_policy():
    policy = (
        PROJECT_ROOT
        / "docs"
        / "frontend-v2"
        / "no-manual-trading-release-gate.md"
    ).read_text(encoding="utf-8")
    normalized = policy.casefold()

    assert "denied by default" in normalized
    assert "separate product decision" in normalized
    assert "cancel diagnostic task" in normalized
    assert "cancel order" in normalized
