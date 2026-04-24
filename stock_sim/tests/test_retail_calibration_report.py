from __future__ import annotations

from agents.retail_calibration_report import (
    CalibrationBookSample,
    CalibrationHoldingSample,
    CalibrationOrderSample,
    CalibrationTradeSample,
    RetailCalibrationReportCollector,
    build_retail_calibration_report,
)


def test_retail_calibration_report_computes_market_metrics():
    report = build_retail_calibration_report(
        orders=[
            CalibrationOrderSample(0, "AAA", "a1", "mean_revert", "buy", 99.0, current_price=100.0, expected_price=104.0, passive=True, bar_index=0, post_open=True),
            CalibrationOrderSample(100, "AAA", "a2", "trend_follow", "sell", 101.0, current_price=100.0, expected_price=96.0, passive=True, bar_index=0, post_open=True),
            CalibrationOrderSample(1_000, "BBB", "a3", "mean_revert", "buy", 50.5, current_price=50.0, expected_price=52.0, aggressive=True, bar_index=1, post_open=True),
            CalibrationOrderSample(1_100, "BBB", "a4", "trend_follow", "buy", 50.4, current_price=50.0, expected_price=52.0, aggressive=False, bar_index=1, post_open=True),
        ],
        books=[
            CalibrationBookSample(0, "AAA", 99.0, 101.0, post_open=True),
            CalibrationBookSample(0, "BBB", 50.0, None, post_open=True),
        ],
        trades=[
            CalibrationTradeSample(200, "AAA", 100.5, post_open=True),
            CalibrationTradeSample(900, "AAA", 100.8, post_open=True),
            CalibrationTradeSample(1_500, "BBB", 50.6, post_open=False),
        ],
        holdings=[
            CalibrationHoldingSample("a1", "mean_revert", "AAA", 8),
            CalibrationHoldingSample("a3", "mean_revert", "BBB", 12),
        ],
    )

    assert report.order_count == 4
    assert report.trade_count == 3
    assert report.market_metrics["buy_sell_order_ratio"] == 3.0
    assert report.market_metrics["post_open_two_sided_book_coverage"] == 0.5
    assert report.market_metrics["post_open_trade_presence"] == 0.5
    assert report.market_metrics["order_flow_herding_index"] == 0.5
    assert report.market_metrics["median_passive_submission_share"] == 0.75
    assert report.market_metrics["median_trade_interarrival_seconds"] == 0.7
    assert report.metric_evaluations["buy_sell_order_ratio"].status == "high"


def test_retail_calibration_report_groups_family_diagnostics():
    collector = RetailCalibrationReportCollector()
    collector.record_order(
        CalibrationOrderSample(0, "AAA", "mr1", "mean_revert", "buy", 99.0, current_price=100.0, expected_price=104.0, passive=True)
    )
    collector.record_order(
        CalibrationOrderSample(100, "AAA", "mr2", "mean_revert", "sell", 101.0, current_price=100.0, expected_price=96.0, passive=False)
    )
    collector.record_holding(CalibrationHoldingSample("mr1", "mean_revert", "AAA", 5))
    collector.record_holding(CalibrationHoldingSample("mr2", "mean_revert", "AAA", 9))

    report = collector.build()
    family = report.family_reports["mean_revert"]

    assert family.order_count == 2
    assert family.buy_count == 1
    assert family.sell_count == 1
    assert family.buy_sell_imbalance == 0.0
    assert family.passive_submission_share == 0.5
    assert family.median_holding_bars == 7.0
    assert family.median_expected_price_capture == 1.0


def test_retail_calibration_report_marks_missing_metrics():
    report = build_retail_calibration_report()

    assert report.market_metrics["buy_sell_order_ratio"] is None
    assert report.metric_evaluations["buy_sell_order_ratio"].status == "missing"
    assert report.to_dict()["order_count"] == 0
