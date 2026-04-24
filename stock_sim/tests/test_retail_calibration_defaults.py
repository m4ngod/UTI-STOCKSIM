from __future__ import annotations

from agents.retail_calibration import (
    CALIBRATION_SEQUENCE,
    FAMILY_CALIBRATION_PROFILES,
    MARKET_METRIC_TARGETS,
    family_share_targets,
    metric_targets_by_name,
)


def test_retail_calibration_family_share_targets_sum_to_one():
    shares = family_share_targets()
    total = sum(band.target for band in shares.values())

    assert abs(total - 1.0) < 1e-9
    assert set(shares) >= {
        "trend_follow",
        "mean_revert",
        "buy_the_dip",
        "profit_taking",
        "slow_fundamental_allocator",
        "liquidity_noise",
        "noise",
    }


def test_retail_calibration_profiles_have_ordered_bands():
    for profile in FAMILY_CALIBRATION_PROFILES.values():
        for band in (
            profile.share,
            profile.median_holding_bars,
            profile.expected_price_capture,
            profile.execution_patience,
            profile.loss_aversion_raw,
            profile.courage_raw,
        ):
            assert band.low <= band.target <= band.high


def test_retail_calibration_metric_targets_are_addressable():
    metrics = metric_targets_by_name()
    assert metrics["buy_sell_order_ratio"].target == 1.0
    assert metrics["post_open_two_sided_book_coverage"].target >= 0.9
    assert len(MARKET_METRIC_TARGETS) >= 5
    assert CALIBRATION_SEQUENCE[0] == "market-level acceptance metrics"
