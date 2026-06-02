from __future__ import annotations

import argparse
import fnmatch
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT.parent / "stock_sim.zip"

INCLUDE_DIRS = [
    "app",
    "core",
    "services",
    "persistence",
    "agents",
    "rl",
    "infra",
    "observability",
    "scripts",
    "tests",
    "docs",
    "configs",
    "stock_sim",
]

INCLUDE_FILES = [
    "pyproject.toml",
    "pytest.ini",
    "README.md",
    "PROJECT_BACKGROUND_AND_GOALS.md",
    "settings.py",
    "setup_frontend_entry.py",
    "sitecustomize.py",
    "__init__.py",
]

SKIP_DIR_NAMES = {
    ".git",
    ".idea",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "logs",
    "output",
    "tmp",
    "stock_sim.egg-info",
}

SKIP_FILE_PATTERNS = [
    "*.db",
    "*.db-shm",
    "*.db-wal",
    "*.pyc",
    "*.pyo",
    "*.zip",
    "export_snap-*.csv",
]

EVIDENCE_LATEST_FILES = [
    "latest_package.json",
    "evidence_manifest.json",
    "artifact_hashes.json",
    "run_readback_summary.json",
]


def should_skip(path: Path) -> bool:
    rel_parts = path.relative_to(REPO_ROOT).parts
    if any(part in SKIP_DIR_NAMES for part in rel_parts):
        return True
    return any(fnmatch.fnmatch(path.name, pattern) for pattern in SKIP_FILE_PATTERNS)


def iter_included_paths() -> list[Path]:
    paths: list[Path] = []
    for dirname in INCLUDE_DIRS:
        root = REPO_ROOT / dirname
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and not should_skip(path):
                paths.append(path)

    evidence_latest = REPO_ROOT / "evidence" / "latest"
    if evidence_latest.exists():
        for filename in EVIDENCE_LATEST_FILES:
            path = evidence_latest / filename
            if path.is_file():
                paths.append(path)

    for filename in INCLUDE_FILES:
        path = REPO_ROOT / filename
        if path.is_file() and not should_skip(path):
            paths.append(path)

    return sorted(set(paths), key=lambda item: item.relative_to(REPO_ROOT).as_posix())


def package(output: Path) -> tuple[int, int]:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    paths = iter_included_paths()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in paths:
            rel = path.relative_to(REPO_ROOT)
            zf.write(path, Path(REPO_ROOT.name) / rel)
    return len(paths), output.stat().st_size


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the clean StockSim submission zip.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    count, size = package(args.output)
    print(f"wrote {args.output.resolve()} with {count} files, {size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
