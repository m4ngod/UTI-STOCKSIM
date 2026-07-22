"""Production historical-source adapter for local BaoStock A-share assets."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Sequence

from .historical_segments import (
    AdmissionCheck,
    HistoricalMarketSegment,
    HistoricalSegmentSelection,
    HistoricalSourceInspection,
    SourceArtifact,
    SourceProvenance,
    SourceSnapshot,
)
from .market_paths import (
    FiveMinuteBar,
    InstrumentState,
    ScenarioDataWorldInput,
    SessionPriceLimitReference,
)


_REQUIRED_DAILY_FIELDS = frozenset(
    {
        "date",
        "code",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "adjustflag",
        "tradestatus",
        "isST",
    }
)
_REQUIRED_MINUTE_FIELDS = frozenset(
    {
        "date",
        "time",
        "code",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "adjustflag",
    }
)
_QUALITY_CODES = (
    "bar_continuity",
    "instrument_coverage",
    "eligible_universe",
    "trading_status",
    "st_status",
    "suspension_state",
    "industry_as_of",
    "adjustment_consistency",
    "causal_availability",
    "required_fields",
    "missing_data",
    "duplicates",
    "timestamps",
)


@dataclass(frozen=True, slots=True)
class BaoStockSourceLayout:
    """Infrastructure configuration kept behind the historical-source port."""

    root: Path
    industry_snapshot_paths: tuple[Path, ...] = ()
    trading_calendar_path: Path | None = None

    @classmethod
    def from_environment(cls) -> "BaoStockSourceLayout":
        root = Path(os.environ.get("STOCK_SIM_BAOSTOCK_ROOT", r"L:\BaoStock_Data"))
        configured = os.environ.get("STOCK_SIM_INDUSTRY_SNAPSHOTS", "")
        paths = tuple(
            Path(value)
            for value in configured.split(os.pathsep)
            if value.strip()
        )
        if not paths:
            snapshot_dir = root / "metadata" / "industry_snapshots"
            paths = tuple(sorted(snapshot_dir.glob("*.csv")))
        if not paths:
            quentx_root = Path(os.environ.get("QUENTX_ROOT", r"T:\文档\QuentX"))
            versions = quentx_root / "ptrade" / "versions"
            paths = tuple(
                sorted(versions.glob("*/quentx_industry_snapshots_*.csv"))
            )
        calendar_value = os.environ.get("STOCK_SIM_TRADING_CALENDAR", "").strip()
        return cls(
            root=root,
            industry_snapshot_paths=paths,
            trading_calendar_path=(Path(calendar_value) if calendar_value else None),
        )

    @property
    def daily_unadjusted_metadata(self) -> Path:
        return self.root / "metadata" / "a_stock_daily_unadjusted"

    @property
    def daily_front_adjusted_metadata(self) -> Path:
        return self.root / "metadata" / "a_stock_daily_front_adjusted"

    @property
    def minute_metadata(self) -> Path:
        return self.root / "metadata" / "a_stock_5min_front_adjusted"

    @property
    def resolved_trading_calendar_path(self) -> Path:
        return self.trading_calendar_path or (
            self.root
            / "index_data"
            / "01_composite_index"
            / "sh_000001.csv"
        )


@dataclass(frozen=True, slots=True)
class _Instrument:
    code: str
    ipo_date: date
    out_date: date | None

    def active_on(self, trading_date: date) -> bool:
        return self.ipo_date <= trading_date and (
            self.out_date is None or trading_date <= self.out_date
        )


@dataclass(frozen=True, slots=True)
class _DailyRows:
    rows: Mapping[tuple[str, date], Mapping[str, str]]
    duplicate_count: int
    missing_files: tuple[str, ...]
    header_fields: frozenset[str]
    content_hash: str


@dataclass(frozen=True, slots=True)
class _InstrumentCatalog:
    instruments: tuple[_Instrument, ...]
    artifact: SourceArtifact


@dataclass(frozen=True, slots=True)
class _TradingCalendar:
    dates: tuple[date, ...]
    artifact: SourceArtifact


@dataclass(frozen=True, slots=True)
class _MinuteSummary:
    counts: Mapping[tuple[str, date], int]
    daily_aggregates: Mapping[tuple[str, date], tuple[float, ...]]
    row_count: int
    duplicate_count: int
    invalid_timestamp_count: int
    invalid_value_count: int
    unexpected_code_count: int
    adjustment_flags: frozenset[str]
    content_hash: str


@dataclass(frozen=True, slots=True)
class _LoadedFiveMinuteBars:
    bars: tuple[FiveMinuteBar, ...]
    source_artifact: SourceArtifact


@dataclass(frozen=True, slots=True)
class _IndustrySnapshot:
    by_snapshot_and_code: Mapping[tuple[date, str], tuple[date, str]]
    snapshot_dates: tuple[date, ...]
    row_count: int
    future_row_count: int
    content_hash: str


class BaoStockHistoricalSource:
    """Inspect local BaoStock files and emit admission evidence.

    The adapter reads configuration internally and returns only provenance and
    content identities.  Filesystem paths and DuckDB controls never cross the
    domain interface or reach the Diagnostics workspace.
    """

    def __init__(self, layout: BaoStockSourceLayout | None = None) -> None:
        self._layout = layout or BaoStockSourceLayout.from_environment()

    def inspect(
        self, selection: HistoricalSegmentSelection
    ) -> HistoricalSourceInspection | None:
        if selection.market != "mainland-a-share":
            return None

        manifests, manifest_errors = self._load_manifests()
        manifest_artifact = _artifact_from_payload(
            "source-manifests",
            manifests,
            sum(bool(item) for item in manifests.values()),
        )
        observed_at = _manifest_observed_at(manifests.values())
        version = f"baostock-{manifest_artifact.content_hash[:16]}"
        provenance = SourceProvenance(
            provider="BaoStock",
            dataset="local-mainland-a-share-history",
            version=version,
            observed_at=observed_at,
        )

        required_fields_ok = not manifest_errors and self._manifest_fields_ok(manifests)
        static_failures: dict[str, str] = {}
        if manifest_errors:
            static_failures["required_fields"] = "; ".join(manifest_errors)
        elif not required_fields_ok:
            static_failures["required_fields"] = (
                "Source manifests do not declare every required daily and 5-minute "
                "field; rebuild the local BaoStock datasets."
            )

        instrument_artifact: SourceArtifact | None = None
        try:
            instrument_catalog = self._load_instruments()
            instruments = instrument_catalog.instruments
            instrument_artifact = instrument_catalog.artifact
        except OSError as exc:
            instruments = ()
            static_failures["eligible_universe"] = (
                "The A-share instrument catalog is unavailable "
                f"({type(exc).__name__}); restore it and retry."
            )
        except ValueError as exc:
            instruments = ()
            static_failures["eligible_universe"] = (
                f"The A-share instrument catalog contains malformed data: {exc}"
            )
        eligible = tuple(
            instrument
            for instrument in instruments
            if instrument.ipo_date <= selection.end_date
            and (
                instrument.out_date is None
                or instrument.out_date >= selection.start_date
            )
        )
        eligible_codes = frozenset(item.code for item in eligible)
        if not eligible_codes:
            static_failures.setdefault(
                "eligible_universe",
                "No A-share instrument is active inside the selected IPO/delisting boundaries.",
            )

        calendar: _TradingCalendar | None = None
        calendar_error: str | None = None
        try:
            calendar = self._load_trading_calendar(selection)
        except OSError as exc:
            calendar_error = (
                "The independent A-share trading calendar is unavailable "
                f"({type(exc).__name__}); restore it and retry."
            )
        except ValueError as exc:
            calendar_error = (
                f"The independent A-share trading calendar is invalid: {exc}"
            )

        raw_rows = self._load_daily_rows(
            self._layout.daily_unadjusted_metadata
            / "a_stock_daily_download_summary.csv",
            eligible_codes,
            selection,
        )
        front_rows = self._load_daily_rows(
            self._layout.daily_front_adjusted_metadata
            / "a_stock_daily_download_summary.csv",
            eligible_codes,
            selection,
        )
        if (
            not _REQUIRED_DAILY_FIELDS <= raw_rows.header_fields
            or not _REQUIRED_DAILY_FIELDS <= front_rows.header_fields
        ):
            static_failures["required_fields"] = (
                "Selected daily CSV files do not contain every required raw/adjusted "
                "field; rebuild the affected source files."
            )
        industry = self._load_industry_snapshots()
        minute, minute_error = self._load_minute_summary(selection, eligible_codes)

        raw_dates = {item[1] for item in raw_rows.rows}
        trading_dates = (
            calendar.dates if calendar is not None else tuple(sorted(raw_dates))
        )
        missing_market_days = set(trading_dates) - raw_dates
        undeclared_market_days = raw_dates - set(trading_dates)
        active_pairs = {
            (instrument.code, trading_date)
            for trading_date in trading_dates
            for instrument in eligible
            if instrument.active_on(trading_date)
        }
        raw_pairs = set(raw_rows.rows)
        front_pairs = set(front_rows.rows)
        missing_daily_pairs = active_pairs - raw_pairs
        missing_front_pairs = active_pairs - front_pairs
        trading_pairs = {
            pair
            for pair, row in raw_rows.rows.items()
            if pair in active_pairs and row.get("tradestatus", "").strip() == "1"
        }
        suspended_pairs = {
            pair
            for pair, row in raw_rows.rows.items()
            if pair in active_pairs and row.get("tradestatus", "").strip() == "0"
        }
        minute_counts = minute.counts if minute is not None else {}
        incomplete_bars = {
            pair: minute_counts.get(pair, 0)
            for pair in trading_pairs
            if minute_counts.get(pair, 0) != 48
        }
        suspended_with_bars = {
            pair for pair in suspended_pairs if minute_counts.get(pair, 0) != 0
        }
        unknown_status = {
            pair
            for pair, row in raw_rows.rows.items()
            if pair in active_pairs
            and row.get("tradestatus", "").strip() not in {"0", "1"}
        }
        missing_st = {
            pair
            for pair, row in raw_rows.rows.items()
            if pair in active_pairs and row.get("isST", "").strip() not in {"0", "1"}
        }
        industry_missing, industry_future = _industry_quality(
            industry,
            active_pairs,
        )
        raw_adjustments = {
            row.get("adjustflag", "").strip() for row in raw_rows.rows.values()
        }
        front_adjustments = {
            row.get("adjustflag", "").strip() for row in front_rows.rows.values()
        }
        minute_adjustments = (
            set(minute.adjustment_flags) if minute is not None else set()
        )
        economic_adjustment_issues = (
            _economic_adjustment_issue_count(
                raw_rows.rows,
                front_rows.rows,
                minute.daily_aggregates,
                trading_pairs,
            )
            if minute is not None
            else 0
        )
        invalid_daily_values = _invalid_daily_value_count(raw_rows.rows.values())

        failures = dict(static_failures)
        if calendar_error:
            failures["bar_continuity"] = calendar_error
            failures["instrument_coverage"] = calendar_error
        elif missing_market_days:
            failures["bar_continuity"] = _count_reason(
                len(missing_market_days),
                "expected trading day(s) are entirely absent from the daily market source",
                "repair the daily datasets using the independent calendar and retry",
            )
        elif undeclared_market_days:
            failures["bar_continuity"] = _count_reason(
                len(undeclared_market_days),
                "daily market day(s) are not declared by the independent calendar",
                "repair the trading calendar and retry",
            )
        if minute_error:
            failures["bar_continuity"] = minute_error
            failures["instrument_coverage"] = minute_error
            failures["timestamps"] = minute_error
            failures.setdefault("required_fields", minute_error)
        elif incomplete_bars:
            failures["bar_continuity"] = _count_reason(
                len(incomplete_bars),
                "trading instrument-day(s) do not contain exactly 48 five-minute bars",
                "repair or re-download their Parquet partitions",
            )
        if raw_rows.missing_files or front_rows.missing_files:
            failures["instrument_coverage"] = _count_reason(
                len(raw_rows.missing_files) + len(front_rows.missing_files),
                "catalogued daily source file(s) are missing",
                "restore the listed dataset files and retry",
            )
        elif missing_daily_pairs or missing_front_pairs:
            failures["instrument_coverage"] = _count_reason(
                len(missing_daily_pairs | missing_front_pairs),
                "active instrument-day(s) lack raw or adjusted daily coverage",
                "repair the daily datasets and retry",
            )
        if missing_daily_pairs or unknown_status:
            failures["trading_status"] = _count_reason(
                len(missing_daily_pairs | unknown_status),
                "active instrument-day(s) lack a valid point-in-time trading status",
                "repair tradestatus coverage and retry",
            )
        if missing_daily_pairs or missing_st:
            failures["st_status"] = _count_reason(
                len(missing_daily_pairs | missing_st),
                "active instrument-day(s) lack a valid point-in-time ST state",
                "repair isST coverage and retry",
            )
        if suspended_with_bars:
            failures["suspension_state"] = _count_reason(
                len(suspended_with_bars),
                "suspended instrument-day(s) unexpectedly contain intraday bars",
                "reconcile suspension state with the intraday source",
            )
        if industry is None:
            failures["industry_as_of"] = (
                "No point-in-time industry snapshot is configured; set the internal "
                "industry snapshot source and retry."
            )
        elif industry_missing:
            failures["industry_as_of"] = _count_reason(
                len(industry_missing),
                "active instrument-day(s) lack an industry snapshot available as of that date",
                "add an earlier BaoStock industry snapshot and retry",
            )
        if industry_future or (industry is not None and industry.future_row_count):
            failures["causal_availability"] = _count_reason(
                len(industry_future) + (industry.future_row_count if industry else 0),
                "industry membership row(s) become available after their snapshot/use date",
                "remove future-dated rows and rebuild the snapshot",
            )
        if (
            raw_adjustments - {"3"}
            or front_adjustments - {"2"}
            or minute_adjustments - {"2"}
            or economic_adjustment_issues
        ):
            failures["adjustment_consistency"] = (
                "Selected rows do not consistently use daily raw=3, daily front=2, "
                "and five-minute front=2, or their OHLCV/amount economics do not "
                "reconcile; reconcile adjustments and retry."
            )
        if invalid_daily_values or (minute is not None and minute.invalid_value_count):
            failures["missing_data"] = _count_reason(
                invalid_daily_values
                + (minute.invalid_value_count if minute is not None else 0),
                "bar row(s) have missing/invalid OHLCV or amount values",
                "repair the source rows and retry",
            )
        duplicate_count = (
            raw_rows.duplicate_count
            + front_rows.duplicate_count
            + (minute.duplicate_count if minute is not None else 0)
        )
        if duplicate_count:
            failures["duplicates"] = _count_reason(
                duplicate_count,
                "duplicate bar row(s) were found",
                "deduplicate by instrument and timestamp and retry",
            )
        if minute is not None and minute.invalid_timestamp_count:
            failures["timestamps"] = _count_reason(
                minute.invalid_timestamp_count,
                "five-minute row(s) lie outside the A-share session grid",
                "repair timestamps and retry",
            )
        if minute is not None and minute.unexpected_code_count:
            failures.setdefault("eligible_universe", _count_reason(
                minute.unexpected_code_count,
                "intraday row(s) reference instruments outside the point-in-time catalog",
                "repair the catalog or remove the rows and retry",
            ))
        if not trading_dates:
            failures.setdefault(
                "bar_continuity",
                "The selected interval contains no recorded trading day.",
            )

        summaries = {
            "bar_continuity": (
                f"All {len(trading_pairs)} trading instrument-day(s) contain 48 five-minute bars."
            ),
            "instrument_coverage": (
                f"Raw, adjusted, and intraday coverage is complete for {len(active_pairs)} active instrument-day(s)."
            ),
            "eligible_universe": (
                f"Eligible Universe contains {len(eligible_codes)} instrument(s) using IPO and delisting boundaries."
            ),
            "trading_status": "Every active instrument-day has point-in-time trading status.",
            "st_status": "Every active instrument-day has point-in-time ST state.",
            "suspension_state": (
                f"{len(suspended_pairs)} suspended instrument-day(s) are consistent with intraday coverage."
            ),
            "industry_as_of": "Industry membership is available as of every active trading date.",
            "adjustment_consistency": (
                "Daily raw/front adjustment ratios and front-adjusted daily/five-minute "
                "OHLCV and amount economics reconcile."
            ),
            "causal_availability": "No industry or market row uses future-available information.",
            "required_fields": "All required daily and five-minute source fields are declared.",
            "missing_data": "Selected OHLCV and amount values are complete and valid.",
            "duplicates": "No duplicate instrument/timestamp rows were found.",
            "timestamps": "All intraday timestamps lie on the declared A-share five-minute grid.",
        }
        checks = tuple(
            AdmissionCheck(
                code=code,
                passed=code not in failures,
                summary=failures.get(code, summaries[code]),
            )
            for code in _QUALITY_CODES
        )
        artifacts = [manifest_artifact]
        if instrument_artifact is not None:
            artifacts.append(instrument_artifact)
        if calendar is not None:
            artifacts.append(calendar.artifact)
        artifacts.extend(
            (
                SourceArtifact(
                    "daily-unadjusted-selection",
                    raw_rows.content_hash,
                    len(raw_rows.rows),
                ),
                SourceArtifact(
                    "daily-front-adjusted-selection",
                    front_rows.content_hash,
                    len(front_rows.rows),
                ),
            )
        )
        if minute is not None:
            artifacts.append(
                SourceArtifact(
                    "five-minute-front-adjusted-selection",
                    minute.content_hash,
                    minute.row_count,
                )
            )
        if industry is not None:
            artifacts.append(
                SourceArtifact(
                    "industry-as-of-selection",
                    industry.content_hash,
                    industry.row_count,
                )
            )

        return HistoricalSourceInspection(
            selection=selection,
            label=(
                f"Mainland A-share {selection.start_date.isoformat()} to "
                f"{selection.end_date.isoformat()}"
            ),
            provenance=provenance,
            artifacts=tuple(artifacts),
            eligible_instrument_count=len(eligible_codes),
            trading_day_count=len(trading_dates),
            bar_count=minute.row_count if minute is not None else 0,
            checks=checks,
            recommendation_tags=(
                "baostock",
                "mainland-a-share",
                f"{len(trading_dates)}-trading-day",
            ),
        )

    def load_scenario_data_world(
        self,
        segment: HistoricalMarketSegment,
    ) -> ScenarioDataWorldInput:
        """Load and normalize the exact admitted source snapshot for materialization."""

        inspection = self.inspect(segment.selection)
        if inspection is None:
            raise ValueError("The admitted segment is not available from this source")
        failed_checks = tuple(check.code for check in inspection.checks if not check.passed)
        if failed_checks:
            raise ValueError(
                "The historical source no longer passes admission checks: "
                + ", ".join(failed_checks)
            )
        snapshot = SourceSnapshot.from_inspection(inspection)
        if snapshot.snapshot_id != segment.source_snapshot_id:
            raise ValueError(
                "The historical source changed after admission; admit a new segment before materialization"
            )

        manifests, manifest_errors = self._load_manifests()
        if manifest_errors:
            raise ValueError(
                "The historical source manifests changed after admission"
            )
        manifest_artifact = _artifact_from_payload(
            "source-manifests",
            manifests,
            sum(bool(item) for item in manifests.values()),
        )
        catalog = self._load_instruments()
        eligible = tuple(
            instrument
            for instrument in catalog.instruments
            if instrument.ipo_date <= segment.selection.end_date
            and (
                instrument.out_date is None
                or instrument.out_date >= segment.selection.start_date
            )
        )
        eligible_codes = frozenset(item.code for item in eligible)
        calendar = self._load_trading_calendar(segment.selection)
        raw_rows = self._load_daily_rows(
            self._layout.daily_unadjusted_metadata
            / "a_stock_daily_download_summary.csv",
            eligible_codes,
            segment.selection,
        )
        front_rows = self._load_daily_rows(
            self._layout.daily_front_adjusted_metadata
            / "a_stock_daily_download_summary.csv",
            eligible_codes,
            segment.selection,
        )
        industry = self._load_industry_snapshots()
        if industry is None:
            raise ValueError("Point-in-time industry data is unavailable")

        factor_by_pair: dict[tuple[str, date], Decimal | None] = {}
        states: list[InstrumentState] = []
        price_limit_references: list[SessionPriceLimitReference] = []
        for trading_date in calendar.dates:
            for instrument in eligible:
                if not instrument.active_on(trading_date):
                    states.append(
                        InstrumentState(
                            instrument=instrument.code,
                            effective_at=datetime.combine(
                                trading_date,
                                time(9, 30),
                            ),
                            eligible=False,
                            trading_status="inactive",
                            is_st=False,
                            industry=(
                                _industry_as_of_value(
                                    industry,
                                    instrument.code,
                                    trading_date,
                                )
                                or "not-applicable"
                            ),
                            decision_adjustment_factor=None,
                            decision_adjustment_provenance=(
                                "not-applicable-outside-listing"
                            ),
                        )
                    )
                    continue
                pair = (instrument.code, trading_date)
                raw = raw_rows.rows.get(pair)
                front = front_rows.rows.get(pair)
                if raw is None or front is None:
                    raise ValueError(
                        "Admitted daily market data is no longer complete"
                    )
                trading_status = raw.get("tradestatus", "").strip()
                factor = (
                    _daily_adjustment_factor(raw, front)
                    if trading_status == "1"
                    else None
                )
                factor_by_pair[pair] = factor
                try:
                    previous_close = Decimal(raw["preclose"])
                except (KeyError, InvalidOperation) as exc:
                    raise ValueError(
                        "Admitted previous-close reference data is no longer complete"
                    ) from exc
                if previous_close <= 0:
                    raise ValueError(
                        "Admitted previous-close reference data must be positive"
                    )
                price_limit_references.append(
                    SessionPriceLimitReference(
                        instrument=instrument.code,
                        session_date=trading_date,
                        previous_close=previous_close,
                        effective_at=datetime.combine(trading_date, time(9, 30)),
                        provenance="baostock-daily-unadjusted-preclose-v1",
                    )
                )
                industry_name = _industry_as_of_value(
                    industry,
                    instrument.code,
                    trading_date,
                )
                if industry_name is None:
                    raise ValueError(
                        "Admitted point-in-time industry data is no longer complete"
                    )
                states.append(
                    InstrumentState(
                        instrument=instrument.code,
                        effective_at=datetime.combine(trading_date, time(9, 30)),
                        eligible=True,
                        trading_status=(
                            "trading" if trading_status == "1" else "suspended"
                        ),
                        is_st=raw.get("isST", "").strip() == "1",
                        industry=industry_name,
                        decision_adjustment_factor=Decimal("1"),
                        decision_adjustment_provenance=(
                            "canonical-unadjusted-decision-view-v1"
                        ),
                    )
                )

        loaded_bars = self._load_normalized_five_minute_bars(
            segment.selection,
            factor_by_pair,
        )
        if len(loaded_bars.bars) != segment.bar_count:
            raise ValueError(
                "The admitted five-minute row count changed before materialization"
            )
        actual_artifacts = tuple(
            sorted(
                (
                    manifest_artifact,
                    catalog.artifact,
                    calendar.artifact,
                    SourceArtifact(
                        "daily-unadjusted-selection",
                        raw_rows.content_hash,
                        len(raw_rows.rows),
                    ),
                    SourceArtifact(
                        "daily-front-adjusted-selection",
                        front_rows.content_hash,
                        len(front_rows.rows),
                    ),
                    loaded_bars.source_artifact,
                    SourceArtifact(
                        "industry-as-of-selection",
                        industry.content_hash,
                        industry.row_count,
                    ),
                ),
                key=lambda item: item.name,
            )
        )
        if actual_artifacts != snapshot.artifacts:
            raise ValueError(
                "The historical source changed after admission; admit a new segment before materialization"
            )
        return ScenarioDataWorldInput(
            segment_id=segment.segment_id,
            segment_content_hash=segment.content_hash,
            source_snapshot_id=segment.source_snapshot_id,
            bars=loaded_bars.bars,
            instrument_states=tuple(states),
            price_limit_references=tuple(price_limit_references),
            normalization_provenance="front-5m-to-unadjusted-daily-ratio-v1",
        )

    def _load_normalized_five_minute_bars(
        self,
        selection: HistoricalSegmentSelection,
        factor_by_pair: Mapping[tuple[str, date], Decimal | None],
    ) -> _LoadedFiveMinuteBars:
        try:
            import duckdb
        except ImportError as exc:
            raise RuntimeError(
                "DuckDB is required to materialize the admitted five-minute data"
            ) from exc
        database = self._layout.minute_metadata / "market_data.duckdb"
        bars: list[FiveMinuteBar] = []
        digest = hashlib.sha256()
        row_count = 0
        with duckdb.connect(str(database), read_only=True) as connection:
            cursor = connection.execute(
                "SELECT code, date, time, open, high, low, close, volume, amount, "
                "adjustflag "
                "FROM minute_5_bars WHERE date >= ? AND date <= ? "
                "ORDER BY code, date, time",
                [selection.start_date.isoformat(), selection.end_date.isoformat()],
            )
            while True:
                batch = cursor.fetchmany(10_000)
                if not batch:
                    break
                for values in batch:
                    digest.update(_canonical_row(values))
                    row_count += 1
                    instrument = str(values[0]).strip().lower()
                    trading_date = _parse_date(str(values[1]))
                    if trading_date is None:
                        raise ValueError("A five-minute row has an invalid trading date")
                    factor = factor_by_pair.get((instrument, trading_date))
                    if factor is None:
                        raise ValueError(
                            "A five-minute row lacks a canonical unadjusted factor"
                        )
                    end_time = _parse_minute_end_time(str(values[2]))
                    if end_time is None or end_time.date() != trading_date:
                        raise ValueError("A five-minute row has an invalid Simulation Time")
                    prices = tuple(
                        (Decimal(str(value)) * factor).quantize(
                            Decimal("0.000001")
                        )
                        for value in values[3:7]
                    )
                    bars.append(
                        FiveMinuteBar(
                            instrument=instrument,
                            end_time=end_time,
                            open=prices[0],
                            high=prices[1],
                            low=prices[2],
                            close=prices[3],
                            volume=int(Decimal(str(values[7]))),
                            amount=Decimal(str(values[8])),
                        )
                    )
        return _LoadedFiveMinuteBars(
            bars=tuple(bars),
            source_artifact=SourceArtifact(
                "five-minute-front-adjusted-selection",
                digest.hexdigest(),
                row_count,
            ),
        )

    def _load_manifests(
        self,
    ) -> tuple[dict[str, Mapping[str, object]], tuple[str, ...]]:
        paths = {
            "daily_unadjusted": self._layout.daily_unadjusted_metadata
            / "manifest.json",
            "daily_front_adjusted": self._layout.daily_front_adjusted_metadata
            / "manifest.json",
            "minute_5_front_adjusted": self._layout.minute_metadata
            / "manifest.json",
        }
        manifests: dict[str, Mapping[str, object]] = {}
        errors: list[str] = []
        for name, path in paths.items():
            try:
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
                if not isinstance(payload, dict):
                    raise ValueError("manifest root must be an object")
                manifests[name] = payload
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                manifests[name] = {}
                errors.append(
                    f"{name} manifest unavailable or invalid ({type(exc).__name__}); "
                    "restore or rebuild it and retry"
                )
        return manifests, tuple(errors)

    @staticmethod
    def _manifest_fields_ok(manifests: Mapping[str, Mapping[str, object]]) -> bool:
        raw_fields = _string_set(
            manifests.get("daily_unadjusted", {}).get("fields", ())
        )
        front_fields = _string_set(
            manifests.get("daily_front_adjusted", {}).get("fields", ())
        )
        minute_fields = _string_set(
            manifests.get("minute_5_front_adjusted", {}).get("fields", ())
        )
        return (
            _REQUIRED_DAILY_FIELDS <= raw_fields
            and _REQUIRED_DAILY_FIELDS <= front_fields
            and _REQUIRED_MINUTE_FIELDS <= minute_fields
        )

    def _load_instruments(self) -> _InstrumentCatalog:
        path = self._layout.daily_unadjusted_metadata / "a_stock_daily_catalog.csv"
        instruments: list[_Instrument] = []
        malformed: list[str] = []
        seen_codes: set[str] = set()
        row_count = 0
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("type", "1").strip() != "1":
                    continue
                row_count += 1
                code = row.get("code", "").strip().lower()
                ipo_date = _parse_date(row.get("ipoDate", ""))
                raw_out_date = row.get("outDate", "").strip()
                out_date = _parse_date(raw_out_date)
                if not code or ipo_date is None:
                    malformed.append(f"row {row_count} has no valid code/IPO date")
                    continue
                if raw_out_date and out_date is None:
                    malformed.append(f"row {row_count} has an invalid delisting date")
                    continue
                if code in seen_codes:
                    malformed.append(f"row {row_count} duplicates instrument {code}")
                    continue
                seen_codes.add(code)
                instruments.append(
                    _Instrument(
                        code=code,
                        ipo_date=ipo_date,
                        out_date=out_date,
                    )
                )
        if malformed:
            raise ValueError(
                f"{len(malformed)} malformed catalog row(s); {malformed[0]}; repair the catalog and retry"
            )
        return _InstrumentCatalog(
            instruments=tuple(sorted(instruments, key=lambda item: item.code)),
            artifact=_artifact_from_file("instrument-catalog", path, row_count),
        )

    def _load_trading_calendar(
        self,
        selection: HistoricalSegmentSelection,
    ) -> _TradingCalendar:
        path = self._layout.resolved_trading_calendar_path
        _, rows = _read_csv_date_window(
            path,
            selection.start_date,
            selection.end_date,
        )
        parsed_dates = tuple(
            sorted(
                {
                    parsed
                    for row in rows
                    if (parsed := _parse_date(row.get("date", ""))) is not None
                }
            )
        )
        if not parsed_dates:
            raise ValueError(
                "the selected interval contains no declared trading day; verify the range and calendar"
            )
        return _TradingCalendar(
            dates=parsed_dates,
            artifact=_artifact_from_payload(
                "trading-calendar-selection",
                rows,
                len(parsed_dates),
            ),
        )

    def _load_daily_rows(
        self,
        summary_path: Path,
        eligible_codes: frozenset[str],
        selection: HistoricalSegmentSelection,
    ) -> _DailyRows:
        files: dict[str, Path] = {}
        missing_files: list[str] = []
        try:
            with summary_path.open("r", encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    code = row.get("code", "").strip().lower()
                    if code in eligible_codes:
                        file_value = row.get("file", "").strip()
                        if file_value:
                            files[code] = Path(file_value)
        except OSError:
            return _DailyRows(
                rows={},
                duplicate_count=0,
                missing_files=(summary_path.name,),
                header_fields=frozenset(),
                content_hash=hashlib.sha256(b"").hexdigest(),
            )

        missing_files = [
            code
            for code in sorted(eligible_codes)
            if code not in files or not files[code].is_file()
        ]
        rows: dict[tuple[str, date], Mapping[str, str]] = {}
        duplicate_count = 0
        header_fields: set[str] = set()
        digest = hashlib.sha256()
        for code in sorted(eligible_codes):
            path = files.get(code)
            if path is None or not path.is_file():
                continue
            fieldnames, selected_rows = _read_csv_date_window(
                path,
                selection.start_date,
                selection.end_date,
            )
            header_fields.update(fieldnames)
            for row in selected_rows:
                row_date = _parse_date(row.get("date", ""))
                if row_date is None:
                    continue
                normalized_code = row.get("code", code).strip().lower() or code
                key = (normalized_code, row_date)
                if key in rows:
                    duplicate_count += 1
                rows[key] = dict(row)
                digest.update(_canonical_row(row))
        return _DailyRows(
            rows=rows,
            duplicate_count=duplicate_count,
            missing_files=tuple(missing_files),
            header_fields=frozenset(header_fields),
            content_hash=digest.hexdigest(),
        )

    def _load_minute_summary(
        self,
        selection: HistoricalSegmentSelection,
        eligible_codes: frozenset[str],
    ) -> tuple[_MinuteSummary | None, str | None]:
        try:
            import duckdb
        except ImportError:
            return None, (
                "DuckDB is unavailable, so five-minute continuity cannot be proven; "
                "install the declared duckdb dependency and retry."
            )

        database = self._layout.minute_metadata / "market_data.duckdb"
        if not database.is_file():
            return None, (
                "The BaoStock five-minute DuckDB catalog is missing; rebuild it and retry."
            )
        counts: dict[tuple[str, date], int] = {}
        aggregate_values: dict[tuple[str, date], list[float]] = {}
        row_count = 0
        duplicate_count = 0
        invalid_timestamp_count = 0
        invalid_value_count = 0
        unexpected_code_count = 0
        flags: set[str] = set()
        seen: set[tuple[str, date, str]] = set()
        digest = hashlib.sha256()
        try:
            with duckdb.connect(str(database), read_only=True) as connection:
                cursor = connection.execute(
                    "SELECT code, date, time, open, high, low, close, volume, "
                    "amount, adjustflag FROM minute_5_bars "
                    "WHERE date >= ? AND date <= ? ORDER BY code, date, time",
                    [selection.start_date.isoformat(), selection.end_date.isoformat()],
                )
                while True:
                    batch = cursor.fetchmany(10_000)
                    if not batch:
                        break
                    for values in batch:
                        code = str(values[0]).strip().lower()
                        row_date = _parse_date(str(values[1]))
                        timestamp = str(values[2]).strip()
                        if row_date is None:
                            invalid_timestamp_count += 1
                            continue
                        if code not in eligible_codes:
                            unexpected_code_count += 1
                            continue
                        key = (code, row_date, timestamp)
                        if key in seen:
                            duplicate_count += 1
                        seen.add(key)
                        pair = (code, row_date)
                        counts[pair] = counts.get(pair, 0) + 1
                        if not _valid_five_minute_timestamp(timestamp):
                            invalid_timestamp_count += 1
                        if not _valid_ohlcv(values[3:9]):
                            invalid_value_count += 1
                        else:
                            numeric_values = [float(str(value)) for value in values[3:9]]
                            aggregate = aggregate_values.get(pair)
                            if aggregate is None:
                                aggregate_values[pair] = numeric_values
                            else:
                                aggregate[1] = max(aggregate[1], numeric_values[1])
                                aggregate[2] = min(aggregate[2], numeric_values[2])
                                aggregate[3] = numeric_values[3]
                                aggregate[4] += numeric_values[4]
                                aggregate[5] += numeric_values[5]
                        flags.add(str(values[9]).strip())
                        digest.update(_canonical_row(values))
                        row_count += 1
        except Exception as exc:
            return None, (
                "The five-minute DuckDB view could not be inspected: "
                f"{type(exc).__name__}; rebuild the local intraday catalog and retry."
            )
        return (
            _MinuteSummary(
                counts=counts,
                daily_aggregates={
                    pair: tuple(values) for pair, values in aggregate_values.items()
                },
                row_count=row_count,
                duplicate_count=duplicate_count,
                invalid_timestamp_count=invalid_timestamp_count,
                invalid_value_count=invalid_value_count,
                unexpected_code_count=unexpected_code_count,
                adjustment_flags=frozenset(flags),
                content_hash=digest.hexdigest(),
            ),
            None,
        )

    def _load_industry_snapshots(self) -> _IndustrySnapshot | None:
        paths = tuple(path for path in self._layout.industry_snapshot_paths if path.is_file())
        if not paths:
            return None
        rows: dict[tuple[date, str], tuple[date, str]] = {}
        future_rows = 0
        digest = hashlib.sha256()
        row_count = 0
        for path in sorted(paths):
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    snapshot_date = _parse_date(row.get("snapshot_date", ""))
                    update_date = _parse_date(row.get("update_date", ""))
                    code = row.get("code", "").strip().lower()
                    industry = row.get("industry", "").strip()
                    if not snapshot_date or not update_date or not code or not industry:
                        continue
                    if update_date > snapshot_date:
                        future_rows += 1
                    rows[(snapshot_date, code)] = (update_date, industry)
                    digest.update(_canonical_row(row))
                    row_count += 1
        return _IndustrySnapshot(
            by_snapshot_and_code=rows,
            snapshot_dates=tuple(sorted({key[0] for key in rows})),
            row_count=row_count,
            future_row_count=future_rows,
            content_hash=digest.hexdigest(),
        )


def _manifest_observed_at(manifests: Iterable[Mapping[str, object]]) -> datetime:
    observed: list[datetime] = []
    for manifest in manifests:
        value = manifest.get("generated_at")
        if not value:
            continue
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        observed.append(parsed)
    return max(observed, default=datetime(1970, 1, 1, tzinfo=timezone.utc))


def _parse_date(value: str) -> date | None:
    value = str(value).strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _parse_minute_end_time(value: str) -> datetime | None:
    digits = "".join(character for character in value if character.isdigit())
    if len(digits) < 14:
        return None
    try:
        return datetime.strptime(digits[:14], "%Y%m%d%H%M%S")
    except ValueError:
        return None


def _daily_adjustment_factor(
    raw: Mapping[str, str],
    front: Mapping[str, str],
) -> Decimal:
    try:
        raw_close = Decimal(raw["close"])
        front_close = Decimal(front["close"])
        if raw_close <= 0 or front_close <= 0:
            raise ValueError
        return (raw_close / front_close).quantize(Decimal("0.00000001"))
    except (KeyError, InvalidOperation, ValueError, ZeroDivisionError) as exc:
        raise ValueError(
            "Daily raw/front adjustment values cannot be normalized"
        ) from exc


def _industry_as_of_value(
    industry: _IndustrySnapshot,
    instrument: str,
    trading_date: date,
) -> str | None:
    candidates = tuple(
        snapshot_date
        for snapshot_date in industry.snapshot_dates
        if snapshot_date <= trading_date
        and (snapshot_date, instrument) in industry.by_snapshot_and_code
    )
    if not candidates:
        return None
    _, industry_name = industry.by_snapshot_and_code[(candidates[-1], instrument)]
    return industry_name


def _canonical_row(row: object) -> bytes:
    if isinstance(row, Mapping):
        payload: object = {str(key): row[key] for key in sorted(row)}
    elif isinstance(row, Sequence) and not isinstance(row, (str, bytes, bytearray)):
        payload = [str(value) for value in row]
    else:
        payload = str(row)
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _read_csv_date_window(
    path: Path,
    start_date: date,
    end_date: date,
    *,
    chunk_size: int = 64 * 1024,
) -> tuple[tuple[str, ...], tuple[dict[str, str], ...]]:
    """Read a sorted daily CSV backwards until the requested window is covered."""

    with path.open("rb") as handle:
        raw_header = handle.readline()
        fieldnames = tuple(
            next(csv.reader([raw_header.decode("utf-8-sig").strip()]))
        )
        data_start = handle.tell()
        handle.seek(0, 2)
        position = handle.tell()
        carry = b""
        selected_lines: list[bytes] = []
        reached_before_window = False
        while position > data_start and not reached_before_window:
            read_start = max(data_start, position - chunk_size)
            handle.seek(read_start)
            block = handle.read(position - read_start) + carry
            lines = block.splitlines()
            if read_start > data_start and lines:
                carry = lines[0]
                complete_lines = lines[1:]
            else:
                carry = b""
                complete_lines = lines
            for raw_line in reversed(complete_lines):
                if not raw_line:
                    continue
                row_date = _parse_date(raw_line[:10].decode("ascii", errors="ignore"))
                if row_date is None or row_date > end_date:
                    continue
                if row_date < start_date:
                    reached_before_window = True
                    break
                selected_lines.append(raw_line)
            position = read_start
        selected_lines.reverse()
    rows = tuple(
        dict(zip(fieldnames, next(csv.reader([line.decode("utf-8")])), strict=False))
        for line in selected_lines
    )
    return fieldnames, rows


def _artifact_from_payload(name: str, payload: object, row_count: int) -> SourceArtifact:
    digest = hashlib.sha256(_canonical_row(payload)).hexdigest()
    return SourceArtifact(name=name, content_hash=digest, row_count=row_count)


def _artifact_from_file(name: str, path: Path, row_count: int) -> SourceArtifact:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return SourceArtifact(name=name, content_hash=digest.hexdigest(), row_count=row_count)


def _string_set(value: object) -> set[str]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return set()
    return {str(item) for item in value}


def _valid_ohlcv(values: Sequence[object]) -> bool:
    try:
        open_price, high, low, close, volume, amount = (
            float(str(value)) for value in values
        )
    except (TypeError, ValueError):
        return False
    return (
        open_price > 0
        and high >= max(open_price, close, low)
        and low <= min(open_price, close, high)
        and low > 0
        and close > 0
        and volume >= 0
        and amount >= 0
    )


def _invalid_daily_value_count(rows: Iterable[Mapping[str, str]]) -> int:
    return sum(
        row.get("tradestatus", "").strip() != "0"
        and not _valid_ohlcv(
            (
                row.get("open"),
                row.get("high"),
                row.get("low"),
                row.get("close"),
                row.get("volume"),
                row.get("amount"),
            )
        )
        for row in rows
    )


def _economic_adjustment_issue_count(
    raw_rows: Mapping[tuple[str, date], Mapping[str, str]],
    front_rows: Mapping[tuple[str, date], Mapping[str, str]],
    minute_aggregates: Mapping[tuple[str, date], tuple[float, ...]],
    trading_pairs: set[tuple[str, date]],
) -> int:
    issue_count = 0
    for pair in trading_pairs:
        raw = raw_rows.get(pair)
        front = front_rows.get(pair)
        minute = minute_aggregates.get(pair)
        if raw is None or front is None or minute is None:
            continue
        try:
            raw_values = tuple(
                float(str(raw[field]))
                for field in ("open", "high", "low", "close", "volume", "amount")
            )
            front_values = tuple(
                float(str(front[field]))
                for field in ("open", "high", "low", "close", "volume", "amount")
            )
        except (KeyError, TypeError, ValueError):
            issue_count += 1
            continue
        front_matches_intraday = all(
            math.isclose(daily, intraday, rel_tol=5e-4, abs_tol=1e-6)
            for daily, intraday in zip(front_values, minute, strict=True)
        )
        price_ratios = tuple(
            raw_value / front_value
            for raw_value, front_value in zip(raw_values[:4], front_values[:4], strict=True)
            if front_value > 0
        )
        ratio_is_consistent = len(price_ratios) == 4 and all(
            math.isclose(price_ratios[0], ratio, rel_tol=5e-4, abs_tol=1e-6)
            for ratio in price_ratios[1:]
        )
        volume_and_amount_match = all(
            math.isclose(raw_value, front_value, rel_tol=5e-4, abs_tol=1e-6)
            for raw_value, front_value in zip(raw_values[4:], front_values[4:], strict=True)
        )
        if not (
            front_matches_intraday
            and ratio_is_consistent
            and volume_and_amount_match
        ):
            issue_count += 1
    return issue_count


def _valid_five_minute_timestamp(value: str) -> bool:
    digits = "".join(character for character in value if character.isdigit())
    if len(digits) >= 17:
        hhmmss = digits[-9:-3]
    elif len(digits) >= 6:
        hhmmss = digits[-6:]
    else:
        return False
    try:
        parsed = time.fromisoformat(
            f"{hhmmss[0:2]}:{hhmmss[2:4]}:{hhmmss[4:6]}"
        )
    except ValueError:
        return False
    minute_of_day = parsed.hour * 60 + parsed.minute
    morning = 9 * 60 + 35 <= minute_of_day <= 11 * 60 + 30
    afternoon = 13 * 60 + 5 <= minute_of_day <= 15 * 60
    return (
        parsed.second == 0
        and parsed.microsecond == 0
        and minute_of_day % 5 == 0
        and (morning or afternoon)
    )


def _industry_quality(
    industry: _IndustrySnapshot | None,
    active_pairs: set[tuple[str, date]],
) -> tuple[set[tuple[str, date]], set[tuple[str, date]]]:
    if industry is None:
        return set(active_pairs), set()
    missing: set[tuple[str, date]] = set()
    future: set[tuple[str, date]] = set()
    for code, trading_date in active_pairs:
        candidates = tuple(
            snapshot_date
            for snapshot_date in industry.snapshot_dates
            if snapshot_date <= trading_date
            and (snapshot_date, code) in industry.by_snapshot_and_code
        )
        if not candidates:
            missing.add((code, trading_date))
            continue
        snapshot_date = candidates[-1]
        update_date, _ = industry.by_snapshot_and_code[(snapshot_date, code)]
        if update_date > snapshot_date or snapshot_date > trading_date:
            future.add((code, trading_date))
    return missing, future


def _count_reason(count: int, finding: str, action: str) -> str:
    return f"{count} {finding}; {action}."


__all__ = ["BaoStockHistoricalSource", "BaoStockSourceLayout"]
