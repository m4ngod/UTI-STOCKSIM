"""Immutable source bindings for registered formal PTrade strategies."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Mapping


@dataclass(frozen=True, slots=True)
class FormalStrategySourceBinding:
    """Bind one registered strategy to its source and retained package copy."""

    source_relative_path: str
    packaged_relative_path: str
    normalized_sha256: str


FORMAL_STRATEGY_SOURCE_BINDINGS: Final[
    Mapping[str, FormalStrategySourceBinding]
] = MappingProxyType(
    {
        "strategy_diagnostics.quentx_scenario_native_strategy": (
            FormalStrategySourceBinding(
                source_relative_path=(
                    "strategy_diagnostics/"
                    "quentx_scenario_native_strategy.py"
                ),
                packaged_relative_path=(
                    "strategy_diagnostics/formal_sources/"
                    "quentx_scenario_native_strategy.py.txt"
                ),
                normalized_sha256=(
                    "6a3c17569f58765e2980e622db0eb09a4a8243e8450eb600"
                    "56148f9267a4de03"
                ),
            )
        ),
        "strategy_diagnostics.live_minute_scenario_native_strategy": (
            FormalStrategySourceBinding(
                source_relative_path=(
                    "strategy_diagnostics/"
                    "live_minute_scenario_native_strategy.py"
                ),
                packaged_relative_path=(
                    "strategy_diagnostics/formal_sources/"
                    "live_minute_scenario_native_strategy.py.txt"
                ),
                normalized_sha256=(
                    "0e4eee382acbe0c4034885afc5b400991018559fa25d6f948"
                    "1f393bd696cae00"
                ),
            )
        ),
    }
)


__all__ = [
    "FORMAL_STRATEGY_SOURCE_BINDINGS",
    "FormalStrategySourceBinding",
]
