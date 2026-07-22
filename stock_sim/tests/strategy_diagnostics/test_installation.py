from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_installed_package_starts_in_a_subprocess_outside_the_checkout(
    tmp_path: Path,
) -> None:
    install_root = tmp_path / "installed"
    caller_root = tmp_path / "caller"
    caller_root.mkdir()

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
            str(REPOSITORY_ROOT),
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
        "supported_persistence_revision": "0005_strategy_runs",
        "workspace": "Diagnostics",
    }
