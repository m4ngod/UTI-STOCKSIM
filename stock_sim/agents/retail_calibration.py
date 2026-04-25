from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CalibrationBand:
    low: float
    target: float
    high: float


@dataclass(frozen=True)
class FamilyCalibrationProfile:
    family: str
    share: CalibrationBand
    median_holding_bars: CalibrationBand
    expected_price_capture: CalibrationBand
    execution_patience: CalibrationBand
    finite_patience_seconds: CalibrationBand
    loss_aversion_raw: CalibrationBand
    courage_raw: CalibrationBand


@dataclass(frozen=True)
class MarketMetricTarget:
    name: str
    low: float
    target: float
    high: float
    note: str


FAMILY_CALIBRATION_PROFILES: dict[str, FamilyCalibrationProfile] = {
    "trend_follow": FamilyCalibrationProfile(
        family="trend_follow",
        share=CalibrationBand(0.16, 0.20, 0.24),
        median_holding_bars=CalibrationBand(5.0, 9.0, 16.0),
        expected_price_capture=CalibrationBand(0.42, 0.58, 0.78),
        execution_patience=CalibrationBand(0.12, 0.32, 0.58),
        finite_patience_seconds=CalibrationBand(4.0, 18.0, 34.0),
        loss_aversion_raw=CalibrationBand(0.12, 0.32, 0.56),
        courage_raw=CalibrationBand(0.42, 0.65, 0.90),
    ),
    "mean_revert": FamilyCalibrationProfile(
        family="mean_revert",
        share=CalibrationBand(0.18, 0.22, 0.26),
        median_holding_bars=CalibrationBand(6.0, 10.0, 18.0),
        expected_price_capture=CalibrationBand(0.25, 0.42, 0.62),
        execution_patience=CalibrationBand(0.30, 0.52, 0.80),
        finite_patience_seconds=CalibrationBand(14.0, 48.0, 95.0),
        loss_aversion_raw=CalibrationBand(0.28, 0.52, 0.82),
        courage_raw=CalibrationBand(0.28, 0.48, 0.72),
    ),
    "buy_the_dip": FamilyCalibrationProfile(
        family="buy_the_dip",
        share=CalibrationBand(0.10, 0.12, 0.15),
        median_holding_bars=CalibrationBand(5.0, 8.0, 14.0),
        expected_price_capture=CalibrationBand(0.18, 0.34, 0.52),
        execution_patience=CalibrationBand(0.18, 0.38, 0.64),
        finite_patience_seconds=CalibrationBand(6.0, 22.0, 48.0),
        loss_aversion_raw=CalibrationBand(0.20, 0.40, 0.68),
        courage_raw=CalibrationBand(0.36, 0.58, 0.84),
    ),
    "profit_taking": FamilyCalibrationProfile(
        family="profit_taking",
        share=CalibrationBand(0.08, 0.12, 0.15),
        median_holding_bars=CalibrationBand(4.0, 7.0, 12.0),
        expected_price_capture=CalibrationBand(0.08, 0.20, 0.36),
        execution_patience=CalibrationBand(0.24, 0.44, 0.72),
        finite_patience_seconds=CalibrationBand(5.0, 18.0, 36.0),
        loss_aversion_raw=CalibrationBand(0.38, 0.62, 0.88),
        courage_raw=CalibrationBand(0.18, 0.36, 0.58),
    ),
    "slow_fundamental_allocator": FamilyCalibrationProfile(
        family="slow_fundamental_allocator",
        share=CalibrationBand(0.10, 0.14, 0.18),
        median_holding_bars=CalibrationBand(12.0, 20.0, 36.0),
        expected_price_capture=CalibrationBand(0.16, 0.28, 0.42),
        execution_patience=CalibrationBand(0.52, 0.72, 0.92),
        finite_patience_seconds=CalibrationBand(60.0, 150.0, 240.0),
        loss_aversion_raw=CalibrationBand(0.18, 0.38, 0.62),
        courage_raw=CalibrationBand(0.36, 0.56, 0.78),
    ),
    "liquidity_noise": FamilyCalibrationProfile(
        family="liquidity_noise",
        share=CalibrationBand(0.10, 0.14, 0.18),
        median_holding_bars=CalibrationBand(2.0, 4.0, 8.0),
        expected_price_capture=CalibrationBand(0.05, 0.14, 0.24),
        execution_patience=CalibrationBand(0.10, 0.30, 0.62),
        finite_patience_seconds=CalibrationBand(2.5, 10.0, 24.0),
        loss_aversion_raw=CalibrationBand(0.14, 0.32, 0.58),
        courage_raw=CalibrationBand(0.26, 0.46, 0.74),
    ),
    "noise": FamilyCalibrationProfile(
        family="noise",
        share=CalibrationBand(0.04, 0.06, 0.10),
        median_holding_bars=CalibrationBand(1.0, 3.0, 6.0),
        expected_price_capture=CalibrationBand(0.04, 0.10, 0.18),
        execution_patience=CalibrationBand(0.08, 0.24, 0.56),
        finite_patience_seconds=CalibrationBand(2.5, 8.0, 24.0),
        loss_aversion_raw=CalibrationBand(0.12, 0.28, 0.54),
        courage_raw=CalibrationBand(0.24, 0.42, 0.70),
    ),
}


MARKET_METRIC_TARGETS: tuple[MarketMetricTarget, ...] = (
    MarketMetricTarget(
        name="buy_sell_order_ratio",
        low=0.75,
        target=1.00,
        high=1.35,
        note="Use total submitted buy orders / total submitted sell orders over one episode.",
    ),
    MarketMetricTarget(
        name="post_open_two_sided_book_coverage",
        low=0.85,
        target=0.95,
        high=1.00,
        note="Fraction of symbols that show both bids and asks within the first calibration window.",
    ),
    MarketMetricTarget(
        name="post_open_trade_presence",
        low=0.70,
        target=0.88,
        high=1.00,
        note="Fraction of symbols that produce at least one real trade in the first calibration window.",
    ),
    MarketMetricTarget(
        name="order_flow_herding_index",
        low=0.30,
        target=0.48,
        high=0.68,
        note="Share of bars where one side exceeds 70% of submissions. Lower is more balanced.",
    ),
    MarketMetricTarget(
        name="median_passive_submission_share",
        low=0.30,
        target=0.45,
        high=0.62,
        note="Share of orders priced inside the passive quote path rather than immediate cross.",
    ),
    MarketMetricTarget(
        name="median_trade_interarrival_seconds",
        low=0.20,
        target=0.75,
        high=2.40,
        note="Use active market phases only; target a continuous but not hyperactive tape.",
    ),
)


CALIBRATION_SEQUENCE: tuple[str, ...] = (
    "market-level acceptance metrics",
    "family share mix",
    "family parameter distributions",
    "dynamic persona state response",
    "cold-start and open-window stress tests",
)


def family_share_targets() -> dict[str, CalibrationBand]:
    return {family: profile.share for family, profile in FAMILY_CALIBRATION_PROFILES.items()}


def metric_targets_by_name() -> dict[str, MarketMetricTarget]:
    return {metric.name: metric for metric in MARKET_METRIC_TARGETS}


__all__ = [
    "CalibrationBand",
    "FamilyCalibrationProfile",
    "MarketMetricTarget",
    "FAMILY_CALIBRATION_PROFILES",
    "MARKET_METRIC_TARGETS",
    "CALIBRATION_SEQUENCE",
    "family_share_targets",
    "metric_targets_by_name",
]
