from app.services.evidence_core import (
    MarketMetricsExtractor,
    build_random_seed_ledger,
    build_world_split_registry,
    build_world_spec_from_arena_identity,
    build_world_spec_v1,
    compute_calibration_scorecard,
    compare_to_calibration_target_bands,
    derive_seed,
    engineering_default_target_bands_v0,
    hidden_world_specs,
    normalize_calibration_observed_metrics,
    random_seed_ledger_hash,
    world_split_registry_hash,
    world_spec_hash,
)


class _EnumLike:
    def __init__(self, name, value):
        self.name = name
        self.value = value


def test_world_spec_hash_is_canonical_and_excludes_self_hash():
    first = build_world_spec_v1(
        world_name="visible",
        split="train",
        symbols=["001", "002"],
        clock={"run_clock": True, "clock_speed": 240.0},
    )
    second = {
        **first,
        "universe": {"selection_rule": "explicit_symbols", "symbols": ["001", "002"]},
        "world_spec_hash": "wrong-self-hash",
    }

    assert world_spec_hash(first) == first["world_spec_hash"]
    assert world_spec_hash(second) == first["world_spec_hash"]
    assert first["market_rules"]["status"] == "not_available"

    changed = build_world_spec_v1(
        world_name="visible",
        split="hidden",
        symbols=["001", "002"],
        clock={"run_clock": True, "clock_speed": 240.0},
    )
    assert changed["world_spec_hash"] != first["world_spec_hash"]


def test_world_spec_from_arena_identity_maps_supported_fields():
    spec = build_world_spec_from_arena_identity(
        {
            "symbols": ["001"],
            "clock_start_day": "7",
            "clock_speed": 120.0,
            "run_clock": False,
            "seed_training_liquidity": True,
        },
        world_name="arena",
    )

    assert spec["schema"] == "world_spec_v1"
    assert spec["universe"]["symbols"] == ["001"]
    assert spec["clock"]["clock_start_day"] == "7"
    assert spec["liquidity_seed_ref"] == "arena_training_liquidity"
    assert len(spec["world_spec_hash"]) == 64


def test_random_seed_ledger_derives_and_hashes_stably():
    ledger = build_random_seed_ledger(20260504)

    assert ledger["schema"] == "random_seed_ledger_v1"
    assert ledger["seeds"]["retail_population"] == derive_seed(20260504, "retail_population")
    assert ledger["seeds"]["hidden_world_selection"] != ledger["seeds"]["retail_population"]
    assert random_seed_ledger_hash({**ledger, "random_seed_ledger_hash": "bad"}) == ledger["random_seed_ledger_hash"]


def test_world_split_registry_tracks_visible_validation_hidden_and_exploit():
    specs = [
        build_world_spec_v1(world_name="visible-a", split="visible", symbols=["001"], clock={"run_clock": True}),
        build_world_spec_v1(world_name="validation-a", split="validation", symbols=["002"], clock={"run_clock": True}),
        build_world_spec_v1(world_name="hidden-a", split="hidden", symbols=["003"], clock={"run_clock": True}),
        build_world_spec_v1(world_name="exploit-a", split="exploit", symbols=["004"], clock={"run_clock": True}),
    ]

    registry = build_world_split_registry(specs)

    assert registry["schema"] == "hidden_world_registry_v1"
    assert registry["pass_fail"] is True
    assert registry["split_counts"] == {"visible": 1, "validation": 1, "hidden": 1, "exploit": 1}
    assert registry["hidden_world_hashes"] == [specs[2]["world_spec_hash"]]
    assert hidden_world_specs(registry)[0]["world_name"] == "hidden-a"
    assert world_split_registry_hash({**registry, "registry_hash": "bad"}) == registry["registry_hash"]


def test_world_split_registry_blocks_missing_hidden_split():
    registry = build_world_split_registry(
        [
            build_world_spec_v1(world_name="visible-a", split="visible", symbols=["001"]),
            build_world_spec_v1(world_name="validation-a", split="validation", symbols=["002"]),
        ]
    )

    assert registry["pass_fail"] is False
    assert registry["failure_reasons"] == ["missing_required_world_split:hidden"]


def test_market_metrics_extractor_reports_metrics_and_coverage():
    result = MarketMetricsExtractor().extract(
        orders=[
            {"agent_id": "A", "side": "buy", "order_type": "limit"},
            {"agent_id": "B", "side": "sell", "order_type": "market"},
            {"agent_id": "A", "side": "buy", "order_type": "limit"},
        ],
        trades=[
            {"price": 10.0, "qty": 100},
            {"price": 10.1, "qty": 50},
            {"price": 10.2, "qty": 50},
        ],
        snapshots=[
            {"best_bid": 9.99, "best_ask": 10.01, "bid_depth": 1000, "ask_depth": 900},
            {"best_bid": None, "best_ask": 10.03, "bid_depth": 0, "ask_depth": 800},
        ],
        bars=[
            {"close": 10.0},
            {"close": 10.1},
            {"close": 10.05},
            {"close": 10.2},
        ],
        accounts=[{"account_id": "A"}],
        account_equity_snapshots=[{"equity": 100000}, {"equity": 100100}, {"equity": 100050}],
        holdings=[{"holding_bars": 4}, {"holding_bars": 6}],
    )

    metrics = result["metrics"]
    coverage = result["metric_coverage"]

    assert metrics["volume"] == 200
    assert metrics["turnover"] == 2015.0
    assert metrics["active_agent_count"] == 2
    assert metrics["buy_sell_ratio"] == 2.0
    assert metrics["empty_book_ratio"] == 0.5
    assert coverage["return_volatility"] == "present"
    assert coverage["fee_ledger_consistency"] == "not_available"
    assert metrics["fill_rate"] is None
    assert metrics["cancel_rate"] is None


def test_market_metrics_extractor_accepts_live_postgresql_fact_shapes():
    result = MarketMetricsExtractor().extract(
        orders=[
            {
                "account_id": "buy_the_dip206",
                "symbol": "001",
                "side": _EnumLike("BUY", 1),
                "type": "OrderType.LIMIT",
                "status": "OrderStatus.FILLED",
                "filled": 10,
                "sim_day": 1,
            },
            {
                "account_id": "mean_revert381",
                "symbol": "001",
                "side": _EnumLike("SELL", 2),
                "type": "OrderType.LIMIT",
                "status": "OrderStatus.CANCELLED",
                "filled": 0,
                "sim_day": 2,
            },
            {
                "account_id": "buy_the_dip206",
                "symbol": "001",
                "side": _EnumLike("SELL", 2),
                "type": "OrderType.LIMIT",
                "status": "OrderStatus.FILLED",
                "filled": 10,
                "sim_day": 3,
            },
        ],
        snapshots=[
            {"bid1": 10.0, "ask1": 10.02, "bid1_qty": 1000, "ask1_qty": 900},
            {"bid1": 10.01, "ask1": None, "bid1_qty": 800, "ask1_qty": None},
        ],
        bars=[{"close": 10.0}, {"close": 10.1}, {"close": 10.05}, {"close": 10.2}],
        agent_bindings=[
            {
                "account_id": "buy_the_dip206",
                "agent_type": "RETAIL",
                "meta": '{"strategy": "buy_the_dip"}',
            },
            {
                "account_id": "mean_revert381",
                "agent_type": "RETAIL",
                "meta": '{"strategy": "mean_revert"}',
            },
        ],
    )

    metrics = result["metrics"]
    assert round(metrics["spread_mean"], 6) == 0.02
    assert metrics["depth_mean"] == 1350.0
    assert metrics["buy_sell_ratio"] == 0.5
    assert metrics["holding_period_mean"] == 2.0
    assert metrics["retail_family_mix"] == 0.2
    assert result["metric_coverage"]["spread_mean"] == "present"
    assert result["source_counts"]["agent_bindings"] == 2


def test_calibration_target_bands_require_all_p0_metrics():
    observed = normalize_calibration_observed_metrics(
        {
            "spread_mean": 0.02,
            "depth_mean": 1000,
            "turnover": 10000,
            "return_volatility": 0.02,
            "return_autocorr_lag1": 0.1,
            "fill_rate": 0.5,
            "cancel_rate": 0.2,
            "buy_sell_ratio": 1.0,
            "holding_period_mean": 5.0,
            "retail_family_mix": 0.3,
            "order_lifespan_mean": 2.0,
        }
    )
    passed = compare_to_calibration_target_bands(
        observed_metrics=observed,
        target_bands=engineering_default_target_bands_v0(),
    )
    missing = compare_to_calibration_target_bands(
        observed_metrics={**observed, "spread": None},
        target_bands=engineering_default_target_bands_v0(),
    )

    assert passed["engineering_pass"] is True
    assert passed["research_pass"] is False
    assert passed["metric_results"]["spread"]["status"] == "pass"
    assert missing["engineering_pass"] is False
    assert missing["missing_metrics"] == ["spread"]
    assert "missing_metric:spread" in missing["failure_reasons"]


def test_calibration_scorecard_passes_and_blocks_missing_required_metrics():
    target = {
        "target_profile_id": "test_profile",
        "required_metrics": ["return_volatility", "spread_mean"],
        "pass_threshold": 1.0,
        "metrics": {
            "return_volatility": {"mean": 0.02, "scale": 0.01, "critical_max_distance": 3.0},
            "spread_mean": {"mean": 0.02, "scale": 0.01, "critical_max_distance": 3.0},
        },
        "weights": {"return_volatility": 1.0, "spread_mean": 1.0},
    }

    passed = compute_calibration_scorecard(
        sim_metrics={"return_volatility": 0.021, "spread_mean": 0.019},
        metric_coverage={"return_volatility": "present", "spread_mean": "present"},
        target_profile=target,
    )
    failed = compute_calibration_scorecard(
        sim_metrics={"return_volatility": 0.021, "spread_mean": None},
        metric_coverage={"return_volatility": "present", "spread_mean": "missing"},
        target_profile=target,
    )

    assert passed["pass"] is True
    assert passed["score"] < 1.0
    assert failed["pass"] is False
    assert failed["coverage_failures"] == ["spread_mean"]
    assert failed["failure_reasons"] == ["required_metric_not_present:spread_mean"]
