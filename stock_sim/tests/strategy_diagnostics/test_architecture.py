from __future__ import annotations

import ast
from pathlib import Path

import pytest


DIAGNOSTIC_PACKAGE = Path(__file__).resolve().parents[2] / "strategy_diagnostics"
FORBIDDEN_IMPORT_PREFIXES = (
    "PySide6",
    "agents.retail_calibration",
    "agents.retail_calibration_report",
    "agents.retail_persona",
    "agents.retail_strategy",
    "agents.retail_trader",
    "app.panels.arena",
    "app.services.arena_experiment_runner",
    "app.services.long_arena_dry_run",
    "app.services.model_population_service",
    "app.services.runtime_model_agent",
    "app.services.runtime_retail_agent",
    "app.services.training_arena_service",
    "app.ui",
    "core.matching_engine",
    "persistence.models_training",
    "services.engine_registry",
    "services.ipo_retail_distribution",
    "services.training_episode_service",
    "stock_sim.agents.retail_calibration",
    "stock_sim.agents.retail_calibration_report",
    "stock_sim.agents.retail_persona",
    "stock_sim.agents.retail_strategy",
    "stock_sim.agents.retail_trader",
    "stock_sim.core.matching_engine",
    "stock_sim.persistence.models_training",
    "stock_sim.services.engine_registry",
    "stock_sim.services.ipo_retail_distribution",
    "stock_sim.services.training_episode_service",
)


def _is_forbidden(module_name: str) -> bool:
    return any(
        module_name == prefix or module_name.startswith(f"{prefix}.")
        for prefix in FORBIDDEN_IMPORT_PREFIXES
    )


def _forbidden_imports(root: Path) -> list[str]:
    violations: list[str] = []
    for source_path in sorted(root.rglob("*.py")):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), source_path.as_posix())
        for node in ast.walk(tree):
            candidates: list[str] = []
            if isinstance(node, ast.Import):
                candidates.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                candidates.append(node.module)
                candidates.extend(f"{node.module}.{alias.name}" for alias in node.names)
            for candidate in candidates:
                if _is_forbidden(candidate):
                    relative_path = source_path.relative_to(root).as_posix()
                    violations.append(f"{relative_path}:{node.lineno}:{candidate}")
    return violations


@pytest.mark.parametrize(
    ("source_text", "forbidden_module"),
    [
        ("from app.panels import arena\n", "app.panels.arena"),
        (
            "from app.services import model_population_service\n",
            "app.services.model_population_service",
        ),
        ("from agents import retail_trader\n", "agents.retail_trader"),
        ("from core import matching_engine\n", "core.matching_engine"),
        ("from PySide6 import QtWidgets\n", "PySide6.QtWidgets"),
    ],
)
def test_architecture_rule_rejects_each_forbidden_family(
    tmp_path: Path,
    source_text: str,
    forbidden_module: str,
) -> None:
    source = tmp_path / "bad_boundary.py"
    source.write_text(source_text, encoding="utf-8")

    assert f"bad_boundary.py:1:{forbidden_module}" in _forbidden_imports(tmp_path)


def test_diagnostic_domain_is_isolated_from_legacy_runtime_and_qt() -> None:
    assert _forbidden_imports(DIAGNOSTIC_PACKAGE) == []
