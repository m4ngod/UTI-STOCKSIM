from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_importing_root_package_keeps_persistence_lazy(tmp_path: Path) -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPOSITORY_ROOT.parent)

    imported = subprocess.run(
        [sys.executable, "-c", "import stock_sim; print(stock_sim.__version__)"],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert imported.stdout.splitlines()[-1] == "0.0.1"
    assert not (tmp_path / "stock_sim_test.db").exists()

    resolved = subprocess.run(
        [sys.executable, "-c", "from stock_sim import Account; print(Account.__name__)"],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert resolved.stdout.splitlines()[-1] == "Account"


def test_installed_package_starts_in_a_subprocess_outside_the_checkout(
    tmp_path: Path,
) -> None:
    install_root = tmp_path / "installed"
    caller_root = tmp_path / "caller"
    caller_root.mkdir()
    source_root = tmp_path / "source"
    shutil.copytree(
        REPOSITORY_ROOT,
        source_root,
        ignore=shutil.ignore_patterns(
            ".git",
            ".pytest_cache",
            "__pycache__",
            "build",
            "*.egg-info",
            "stock_sim_test.db*",
        ),
    )

    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--no-build-isolation",
            "--target",
            str(install_root),
            str(source_root),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(install_root)
    completed = subprocess.run(
        [sys.executable, "-m", "strategy_diagnostics", "--json"],
        cwd=caller_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == {
        "message": "Diagnostics workspace is ready.",
        "persistence_revision": None,
        "persistence_status": "not_initialized",
        "product": "Strategy Diagnostics Laboratory",
        "status": "ready",
        "supported_persistence_revision": "0008_ptrade_host_audit",
        "workspace": "Diagnostics",
    }

    quentx_probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import importlib; "
                "from strategy_diagnostics.ptrade_host import "
                "QUENTX_SCENARIO_NATIVE_STRATEGY_ID as i, "
                "QUENTX_SCENARIO_NATIVE_STRATEGY_VERSION as v, "
                "ptrade_manifest_for; "
                "m=ptrade_manifest_for(i,v); "
                "s=importlib.import_module(m.strategy_module); "
                "print(s.STRATEGY_LINEAGE)"
            ),
        ],
        cwd=caller_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert quentx_probe.stdout.strip() == (
        "QuentX5_2_3_retest_soft_promoted_v20260721"
    )

    live_minute_probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import importlib; "
                "from strategy_diagnostics.ptrade_host import "
                "LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID as i, "
                "LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_VERSION as v, "
                "ptrade_manifest_for; "
                "m=ptrade_manifest_for(i,v); "
                "s=importlib.import_module(m.strategy_module); "
                "print(s.STRATEGY_LINEAGE)"
            ),
        ],
        cwd=caller_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert live_minute_probe.stdout.strip() == "ptrade/live_minute_strategy.py"

    worker = subprocess.run(
        [sys.executable, "-m", "strategy_diagnostics.ptrade_host_worker"],
        input=json.dumps({"protocol_version": "unsupported"}),
        cwd=caller_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    worker_envelope = json.loads(worker.stdout)
    assert worker_envelope["ok"] is False
    assert worker_envelope["error_type"] == "PTradeCompatibilityError"
    assert worker_envelope["surface_version"] == "ptrade_surface.v1"
