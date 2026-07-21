"""Public product interface for the Strategy Diagnostics Laboratory."""

from .application import (
    DIAGNOSTIC_SCHEMA_REVISION,
    DiagnosticsApplication,
    DiagnosticsApplicationState,
    create_diagnostics_application,
)
from .baostock_source import BaoStockHistoricalSource, BaoStockSourceLayout
from .historical_segments import (
    AdmissionCheck,
    HistoricalMarketSegment,
    HistoricalSegmentRecommendation,
    HistoricalSegmentSelection,
    HistoricalSourceInspection,
    InMemoryHistoricalSource,
    SegmentAdmissionReport,
    SourceArtifact,
    SourceProvenance,
    SourceSnapshot,
)

__all__ = [
    "DIAGNOSTIC_SCHEMA_REVISION",
    "DiagnosticsApplication",
    "DiagnosticsApplicationState",
    "BaoStockHistoricalSource",
    "BaoStockSourceLayout",
    "AdmissionCheck",
    "HistoricalMarketSegment",
    "HistoricalSegmentRecommendation",
    "HistoricalSegmentSelection",
    "HistoricalSourceInspection",
    "InMemoryHistoricalSource",
    "SegmentAdmissionReport",
    "SourceArtifact",
    "SourceProvenance",
    "SourceSnapshot",
    "create_diagnostics_application",
]
