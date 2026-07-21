from __future__ import annotations

import csv
from datetime import date
import json
from pathlib import Path

import pytest

from strategy_diagnostics import (
    BaoStockHistoricalSource,
    BaoStockSourceLayout,
    HistoricalSegmentSelection,
    create_diagnostics_application,
)


def _write_csv(path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _five_minute_times() -> list[str]:
    result = []
    for start_hour, start_minute, end_hour, end_minute in (
        (9, 35, 11, 30),
        (13, 5, 15, 0),
    ):
        cursor = start_hour * 60 + start_minute
        end = end_hour * 60 + end_minute
        while cursor <= end:
            result.append(f"20240102{cursor // 60:02d}{cursor % 60:02d}00000")
            cursor += 5
    return result


def _build_local_source(
    root: Path,
    *,
    future_industry: bool = False,
) -> BaoStockHistoricalSource:
    duckdb = pytest.importorskip("duckdb")
    raw_meta = root / "metadata" / "a_stock_daily_unadjusted"
    front_meta = root / "metadata" / "a_stock_daily_front_adjusted"
    minute_meta = root / "metadata" / "a_stock_5min_front_adjusted"
    daily_fields = (
        "date",
        "code",
        "open",
        "high",
        "low",
        "close",
        "preclose",
        "volume",
        "amount",
        "adjustflag",
        "turn",
        "tradestatus",
        "pctChg",
        "isST",
    )
    minute_fields = (
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
    )
    for metadata, fields, frequency, adjustflag in (
        (raw_meta, daily_fields, "d", "3"),
        (front_meta, daily_fields, "d", "2"),
        (minute_meta, minute_fields, "5", "2"),
    ):
        metadata.mkdir(parents=True, exist_ok=True)
        (metadata / "manifest.json").write_text(
            json.dumps(
                {
                    "generated_at": "2026-07-21T23:00:00+08:00",
                    "frequency": frequency,
                    "adjustflag": adjustflag,
                    "fields": list(fields),
                }
            ),
            encoding="utf-8",
        )

    codes = ("sh.600000", "sz.000001")
    _write_csv(
        raw_meta / "a_stock_daily_catalog.csv",
        ("code", "code_name", "ipoDate", "outDate", "type", "status"),
        [
            {
                "code": code,
                "code_name": code,
                "ipoDate": "2000-01-01",
                "outDate": "",
                "type": "1",
                "status": "1",
            }
            for code in codes
        ],
    )
    for metadata, flag in ((raw_meta, "3"), (front_meta, "2")):
        summaries = []
        dataset_name = (
            "daily_unadjusted"
            if metadata == raw_meta
            else "daily_front_adjusted"
        )
        for index, code in enumerate(codes):
            file_path = (
                root
                / "a_stock_k_data"
                / dataset_name
                / "by_code"
                / "fixture"
                / f"{index}.csv"
            )
            _write_csv(
                file_path,
                daily_fields,
                [
                    {
                        "date": "2024-01-02",
                        "code": code,
                        "open": "10",
                        "high": "11",
                        "low": "9",
                        "close": "10.5",
                        "preclose": "10",
                        "volume": "1000",
                        "amount": "10500",
                        "adjustflag": flag,
                        "turn": "1",
                        "tradestatus": "1",
                        "pctChg": "5",
                        "isST": "0",
                    }
                ],
            )
            summaries.append({"code": code, "file": str(file_path)})
        _write_csv(
            metadata / "a_stock_daily_download_summary.csv",
            ("code", "file"),
            summaries,
        )

    database = minute_meta / "market_data.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            "CREATE TABLE minute_5_bars ("
            "code VARCHAR, date VARCHAR, time VARCHAR, open DOUBLE, high DOUBLE, "
            "low DOUBLE, close DOUBLE, volume BIGINT, amount DOUBLE, adjustflag VARCHAR)"
        )
        connection.executemany(
            "INSERT INTO minute_5_bars VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (code, "2024-01-02", timestamp, 10, 11, 9, 10.5, 100, 1050, "2")
                for code in codes
                for timestamp in _five_minute_times()
            ],
        )

    industry_path = root / "industry_snapshots.csv"
    _write_csv(
        industry_path,
        (
            "snapshot_date",
            "update_date",
            "code",
            "code_name",
            "industry",
            "industry_classification",
        ),
        [
            {
                "snapshot_date": "2023-12-31",
                "update_date": "2024-01-03" if future_industry else "2023-12-20",
                "code": code,
                "code_name": code,
                "industry": "fixture-industry",
                "industry_classification": "fixture",
            }
            for code in codes
        ],
    )
    return BaoStockHistoricalSource(
        BaoStockSourceLayout(
            root=root,
            industry_snapshot_paths=(industry_path,),
        )
    )


def test_local_baostock_interval_passes_real_point_in_time_checks(tmp_path: Path) -> None:
    source = _build_local_source(tmp_path / "baostock")
    application = create_diagnostics_application(historical_source=source)
    application.start()

    report = application.admit_historical_segment(
        HistoricalSegmentSelection(
            market="mainland-a-share",
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 2),
        )
    )

    assert report.status == "admitted"
    assert report.eligible_instrument_count == 2
    assert report.trading_day_count == 1
    assert report.bar_count == 96
    assert report.segment is not None
    assert report.source_snapshot is not None
    assert "baostock" not in report.segment.to_dict()
    assert "storage" not in repr(report.to_dict()).lower()


def test_future_dated_industry_snapshot_fails_closed(tmp_path: Path) -> None:
    source = _build_local_source(tmp_path / "baostock", future_industry=True)
    application = create_diagnostics_application(historical_source=source)
    application.start()

    report = application.admit_historical_segment(
        HistoricalSegmentSelection(
            market="mainland-a-share",
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 2),
        )
    )

    assert report.status == "rejected"
    assert any(
        reason.startswith("causal_availability:")
        for reason in report.failure_reasons
    )
    assert report.segment is None


@pytest.mark.parametrize(
    ("mutation", "failed_check"),
    (
        (
            "DELETE FROM minute_5_bars WHERE code = 'sh.600000' "
            "AND time = (SELECT min(time) FROM minute_5_bars WHERE code = 'sh.600000')",
            "bar_continuity",
        ),
        (
            "INSERT INTO minute_5_bars SELECT * FROM minute_5_bars LIMIT 1",
            "duplicates",
        ),
        (
            "UPDATE minute_5_bars SET time = '20240102120000000' "
            "WHERE code = 'sh.600000' AND time = "
            "(SELECT min(time) FROM minute_5_bars WHERE code = 'sh.600000')",
            "timestamps",
        ),
        (
            "UPDATE minute_5_bars SET adjustflag = '3' "
            "WHERE code = 'sh.600000'",
            "adjustment_consistency",
        ),
    ),
)
def test_local_source_detects_intraday_quality_failures(
    tmp_path: Path,
    mutation: str,
    failed_check: str,
) -> None:
    duckdb = pytest.importorskip("duckdb")
    root = tmp_path / "baostock"
    source = _build_local_source(root)
    database = root / "metadata" / "a_stock_5min_front_adjusted" / "market_data.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute(mutation)
    application = create_diagnostics_application(historical_source=source)
    application.start()

    report = application.admit_historical_segment(
        HistoricalSegmentSelection(
            market="mainland-a-share",
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 2),
        )
    )

    checks = {check.code: check for check in report.checks}
    assert report.status == "rejected"
    assert checks[failed_check].passed is False
    assert any(
        action in checks[failed_check].summary
        for action in ("repair", "reconcile", "retry")
    )
