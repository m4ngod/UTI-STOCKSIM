"""Headless logic panel for the Diagnostics workspace."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from strategy_diagnostics import HistoricalSegmentSelection


class _DiagnosticsState(Protocol):
    def to_dict(self) -> dict[str, object]: ...


class DiagnosticsApplicationPort(Protocol):
    def start(self) -> _DiagnosticsState: ...

    def status(self) -> _DiagnosticsState: ...

    def historical_segment_catalog_view(self) -> dict[str, object]: ...

    def admit_historical_segment(
        self, selection: HistoricalSegmentSelection
    ) -> _DiagnosticsState: ...

    def recommend_historical_segments(
        self,
        intent: str = "",
        limit: int = 3,
    ) -> tuple[_DiagnosticsState, ...]: ...


class DiagnosticsPanel:
    def __init__(self, application: DiagnosticsApplicationPort) -> None:
        self._application = application
        self._recommendations: list[dict[str, object]] = []
        self._application.start()

    def get_view(self) -> dict[str, object]:
        view = self._application.status().to_dict()
        catalog = dict(self._application.historical_segment_catalog_view())
        catalog["recommendations"] = list(self._recommendations)
        view["historical_segment_catalog"] = catalog
        return view

    def admit_historical_segment(
        self,
        *,
        market: str,
        start_date: str,
        end_date: str,
    ) -> dict[str, object]:
        report = self._application.admit_historical_segment(
            HistoricalSegmentSelection(
                market=market,
                start_date=date.fromisoformat(start_date),
                end_date=date.fromisoformat(end_date),
            )
        )
        return report.to_dict()

    def recommend_historical_segments(
        self,
        *,
        intent: str = "",
        limit: int = 3,
    ) -> list[dict[str, object]]:
        recommendations = self._application.recommend_historical_segments(
            intent=intent,
            limit=limit,
        )
        self._recommendations = [item.to_dict() for item in recommendations]
        return list(self._recommendations)


__all__ = ["DiagnosticsApplicationPort", "DiagnosticsPanel"]
