"""Agent batch-creation modal logic."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.panels.agents.panel import AgentsPanel
from app.services.agent_service import BATCH_ALLOWED_TYPES

MAX_COUNT = 500

__all__ = ["AgentCreationModal", "MAX_COUNT"]


class AgentCreationModal:
    def __init__(self, agents_panel: AgentsPanel):
        self._panel = agents_panel
        self._agent_type: Optional[str] = None
        self._count: Optional[int] = None
        self._name_prefix: Optional[str] = None
        self._strategies: Optional[List[str]] = None
        self._initial_cash: Optional[float] = None
        self._error: Optional[str] = None
        self._submitted = False
        self._progress_cache: Optional[Dict[str, Any]] = None

    def open(self):
        self._agent_type = None
        self._count = None
        self._name_prefix = None
        self._strategies = None
        self._initial_cash = None
        self._error = None
        self._submitted = False
        self._progress_cache = None

    def submit(
        self,
        *,
        agent_type: str,
        count: int,
        name_prefix: str | None = None,
        strategies: Optional[List[str]] = None,
        initial_cash: Optional[float] = None,
    ) -> bool:
        self._agent_type = agent_type
        self._count = count
        self._name_prefix = None
        clean_strategies = self._clean_strategies(strategies)
        if agent_type == "Retail" and clean_strategies:
            clean_strategies = clean_strategies[:1]
        self._strategies = clean_strategies
        self._initial_cash = float(initial_cash) if initial_cash is not None else None
        self._error = None
        self._submitted = False
        self._progress_cache = None

        if count <= 0:
            self._error = "INVALID_COUNT"
            return False
        if count > MAX_COUNT:
            self._error = "COUNT_TOO_LARGE"
            return False
        if agent_type not in BATCH_ALLOWED_TYPES:
            self._error = "AGENT_BATCH_UNSUPPORTED"
            return False
        if agent_type == "MultiStrategyRetail" and not clean_strategies:
            self._error = "EMPTY_STRATEGIES"
            return False
        if self._initial_cash is not None and self._initial_cash < 0:
            self._error = "INVALID_INITIAL_CASH"
            return False

        try:
            ok = self._panel.start_batch_create(
                count=count,
                agent_type=agent_type,
                name_prefix=name_prefix or "agent",
                strategies=self._strategies,
                initial_cash=self._initial_cash,
            )
            if not ok:
                self._error = "BATCH_IN_PROGRESS"
                return False
            self._submitted = True
            self.refresh_progress()
            return True
        except Exception as exc:  # noqa: BLE001
            self._error = getattr(exc, "code", "UNKNOWN") or "UNKNOWN"
            return False

    def refresh_progress(self):
        try:
            view = self._panel.get_view()
            self._progress_cache = view.get("batch")
        except Exception:
            pass

    def get_view(self) -> Dict[str, Any]:
        return {
            "input": {
                "agent_type": self._agent_type,
                "count": self._count,
                "name_prefix": self._name_prefix,
                "strategies": list(self._strategies) if self._strategies else (None if self._strategies is None else []),
                "initial_cash": self._initial_cash,
            },
            "error": self._error,
            "submitted": self._submitted,
            "progress": self._progress_cache,
        }

    def _clean_strategies(self, strategies: Optional[List[str]]) -> Optional[List[str]]:
        if strategies is None:
            return None
        clean: List[str] = []
        seen: set[str] = set()
        for strategy in strategies:
            value = (strategy or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            clean.append(value)
        return clean
