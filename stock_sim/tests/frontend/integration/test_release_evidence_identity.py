from __future__ import annotations

import hashlib
import re
import subprocess

from stock_sim.release.frontend_v2_packaging import (
    PROJECT_ROOT,
    TOOLCHAIN_LOCK_PATH,
)


def test_release_evidence_records_verified_source_and_toolchain(
    record_testsuite_property,
):
    completed = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    source_commit = completed.stdout.strip()
    assert re.fullmatch(r"[0-9a-f]{40}", source_commit)
    record_testsuite_property(
        "frontend_v2_source_commit",
        source_commit,
    )
    record_testsuite_property(
        "frontend_v2_toolchain_lock_sha256",
        (
            "sha256:"
            + hashlib.sha256(TOOLCHAIN_LOCK_PATH.read_bytes()).hexdigest()
        ),
    )
