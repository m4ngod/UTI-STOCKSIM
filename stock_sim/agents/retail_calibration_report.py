from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from statistics import median
from typing import Iterable, Literal

from agents.retail_calibration import metric_targets_by_name


Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class CalibrationOrderSample:
    ts_ms: int
    symbol: str
    agent_id: str
    family: str
    side: Side
    price: float
    current_price: float | None = None
    expected_price: float | None = None
    passive: bool | None = None
    aggressive: bool | None = None
    bar_index: int | None = None
    post_open: bool = False


@dataclass(frozen=True)
class CalibrationTradeSample:
    ts_ms: int
    symbol: str
    price: float
    post_open: bool = False


@dataclass(frozen=True)
class CalibrationBookSample:
    ts_ms: int
    symbol: str
    best_bid: float | None
    best_ask: float | None
    post_open: bool = False


@dataclass(frozen=True)
class CalibrationHoldingSample:
    agent_id: str
    family: str
    symbol: str
    holding_bars: float


@dataclass(frozen=True)
class MetricEvaluation:
    name: str
    value: float | None
    low: float
    target: float
    high: float
    status: str
    distance_to_target: float | None


@dataclass(frozen=True)
class FamilyCalibrationReport:
    family: str
    order_count: int
    buy_count: int
    sell_count: int
    buy_sell_imbalance: float | None
    passive_submission_share: float | None
    median_holding_bars: float | None
    median_expected_price_capture: float | None


@dataclass(frozen=True)
class RetailCalibrationReport:
    market_metrics: dict[str, float | None]
    metric_evaluations: dict[str, MetricEvaluation]
    family_reports: dict[str, FamilyCalibrationReport]
    symbol_count: int
    order_count: int
    trade_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "market_metrics": dict(self.market_metrics),
            "metric_evaluations": {
                key: asdict(value) for key, value in self.metric_evaluations.items()
            },
            "family_reports": {
                key: asdict(value) for key, value in self.family_reports.items()
            },
            "symbol_count": self.symbol_count,
            "order_count": self.order_count,
            "trade_count": self.trade_count,
        }


class RetailCalibrationReportCollector:
    def __init__(self, *, bar_ms: int = 1_000):
        self._bar_ms = max(1, int(bar_ms))
        self._orders: list[CalibrationOrderSample] = []
        self._trades: list[CalibrationTradeSample] = []
        self._books: list[CalibrationBookSample] = []
        self._holdings: list[CalibrationHoldingSample] = []

    def record_order(self, sample: CalibrationOrderSample) -> None:
        self._orders.append(sample)

    def record_trade(self, sample: CalibrationTradeSample) -> None:
        self._trades.append(sample)

    def record_book(self, sample: CalibrationBookSample) -> None:
        self._books.append(sample)

    def record_holding(self, sample: CalibrationHoldingSample) -> None:
        self._holdings.append(sample)

    def extend_orders(self, samples: Iterable[CalibrationOrderSample]) -> None:
        self._orders.extend(samples)

    def extend_trades(self, samples: Iterable[CalibrationTradeSample]) -> None:
        self._trades.extend(samples)

    def extend_books(self, samples: Iterable[CalibrationBookSample]) -> None:
        self._books.extend(samples)

    def extend_holdings(self, samples: Iterable[CalibrationHoldingSample]) -> None:
        self._holdings.extend(samples)

    def build(self) -> RetailCalibrationReport:
        market_metrics = self._market_metrics()
        return RetailCalibrationReport(
            market_metrics=market_metrics,
            metric_evaluations=_evaluate_market_metrics(market_metrics),
            family_reports=self._family_reports(),
            symbol_count=len(self._episode_symbols()),
            order_count=len(self._orders),
            trade_count=len(self._trades),
        )

    def _market_metrics(self) -> dict[str, float | None]:
        buy_count = sum(1 for order in self._orders if order.side == "buy")
        sell_count = sum(1 for order in self._orders if order.side == "sell")
        post_open_symbols = self._post_open_symbols()
        return {
            "buy_sell_order_ratio": _ratio(buy_count, sell_count),
            "post_open_two_sided_book_coverage": self._post_open_two_sided_book_coverage(post_open_symbols),
            "post_open_trade_presence": self._post_open_trade_presence(post_open_symbols),
            "order_flow_herding_index": self._order_flow_herding_index(),
            "median_passive_submission_share": self._median_passive_submission_share(),
            "median_trade_interarrival_seconds": self._median_trade_interarrival_seconds(),
        }

    def _family_reports(self) -> dict[str, FamilyCalibrationReport]:
        by_family: dict[str, list[CalibrationOrderSample]] = defaultdict(list)
        holding_by_family: dict[str, list[float]] = defaultdict(list)
        for order in self._orders:
            by_family[_clean_family(order.family)].append(order)
        for sample in self._holdings:
            holding_by_family[_clean_family(sample.family)].append(float(sample.holding_bars))

        families = sorted(set(by_family) | set(holding_by_family))
        reports: dict[str, FamilyCalibrationReport] = {}
        for family in families:
            orders = by_family.get(family, [])
            buy_count = sum(1 for order in orders if order.side == "buy")
            sell_count = sum(1 for order in orders if order.side == "sell")
            passive_values = [_is_passive(order) for order in orders]
            passive_known = [value for value in passive_values if value is not None]
            capture_values = [
                value
                for value in (_expected_price_capture(order) for order in orders)
                if value is not None
            ]
            reports[family] = FamilyCalibrationReport(
                family=family,
                order_count=len(orders),
                buy_count=buy_count,
                sell_count=sell_count,
                buy_sell_imbalance=_imbalance(buy_count, sell_count),
                passive_submission_share=_mean_bool(passive_known),
                median_holding_bars=_median_or_none(holding_by_family.get(family, [])),
                median_expected_price_capture=_median_or_none(capture_values),
            )
        return reports

    def _post_open_two_sided_book_coverage(self, symbols: set[str]) -> float | None:
        if not symbols:
            return None
        two_sided = {
            _clean_symbol(sample.symbol)
            for sample in self._books
            if sample.post_open and sample.best_bid is not None and sample.best_ask is not None
        }
        return len(two_sided & symbols) / len(symbols)

    def _post_open_trade_presence(self, symbols: set[str]) -> float | None:
        if not symbols:
            return None
        traded = {
            _clean_symbol(sample.symbol)
            for sample in self._trades
            if sample.post_open
        }
        return len(traded & symbols) / len(symbols)

    def _order_flow_herding_index(self) -> float | None:
        buckets: dict[tuple[str, int], Counter[str]] = defaultdict(Counter)
        for order in self._orders:
            bucket_id = order.bar_index if order.bar_index is not None else order.ts_ms // self._bar_ms
            buckets[(_clean_symbol(order.symbol), int(bucket_id))][order.side] += 1
        if not buckets:
            return None
        herded = 0
        for counts in buckets.values():
            total = sum(counts.values())
            if total and (max(counts.values()) / total) > 0.70:
                herded += 1
        return herded / len(buckets)

    def _median_passive_submission_share(self) -> float | None:
        by_symbol: dict[str, list[bool]] = defaultdict(list)
        for order in self._orders:
            passive = _is_passive(order)
            if passive is not None:
                by_symbol[_clean_symbol(order.symbol)].append(passive)
        shares = [_mean_bool(values) for values in by_symbol.values() if values]
        return _median_or_none([value for value in shares if value is not None])

    def _median_trade_interarrival_seconds(self) -> float | None:
        by_symbol: dict[str, list[int]] = defaultdict(list)
        for trade in self._trades:
            by_symbol[_clean_symbol(trade.symbol)].append(int(trade.ts_ms))
        diffs: list[float] = []
        for times in by_symbol.values():
            ordered = sorted(times)
            diffs.extend((right - left) / 1000.0 for left, right in zip(ordered, ordered[1:]))
        return _median_or_none(diffs)

    def _post_open_symbols(self) -> set[str]:
        symbols = {
            _clean_symbol(sample.symbol)
            for sample in self._books
            if sample.post_open
        }
        symbols.update(
            _clean_symbol(sample.symbol)
            for sample in self._orders
            if sample.post_open
        )
        symbols.update(
            _clean_symbol(sample.symbol)
            for sample in self._trades
            if sample.post_open
        )
        return {symbol for symbol in symbols if symbol}

    def _episode_symbols(self) -> set[str]:
        symbols = {_clean_symbol(sample.symbol) for sample in self._books}
        symbols.update(_clean_symbol(sample.symbol) for sample in self._orders)
        symbols.update(_clean_symbol(sample.symbol) for sample in self._trades)
        symbols.update(_clean_symbol(sample.symbol) for sample in self._holdings)
        return {symbol for symbol in symbols if symbol}


def build_retail_calibration_report(
    *,
    orders: Iterable[CalibrationOrderSample] = (),
    trades: Iterable[CalibrationTradeSample] = (),
    books: Iterable[CalibrationBookSample] = (),
    holdings: Iterable[CalibrationHoldingSample] = (),
    bar_ms: int = 1_000,
) -> RetailCalibrationReport:
    collector = RetailCalibrationReportCollector(bar_ms=bar_ms)
    collector.extend_orders(orders)
    collector.extend_trades(trades)
    collector.extend_books(books)
    collector.extend_holdings(holdings)
    return collector.build()


def _evaluate_market_metrics(metrics: dict[str, float | None]) -> dict[str, MetricEvaluation]:
    targets = metric_targets_by_name()
    out: dict[str, MetricEvaluation] = {}
    for name, target in targets.items():
        value = metrics.get(name)
        if value is None:
            status = "missing"
            distance = None
        elif value < target.low:
            status = "low"
            distance = value - target.target
        elif value > target.high:
            status = "high"
            distance = value - target.target
        else:
            status = "inside"
            distance = value - target.target
        out[name] = MetricEvaluation(
            name=name,
            value=value,
            low=target.low,
            target=target.target,
            high=target.high,
            status=status,
            distance_to_target=distance,
        )
    return out


def _expected_price_capture(order: CalibrationOrderSample) -> float | None:
    if order.current_price is None or order.expected_price is None:
        return None
    current = float(order.current_price)
    expected = float(order.expected_price)
    submitted = float(order.price)
    if order.side == "buy":
        denominator = expected - current
        if denominator <= 1e-12:
            return None
        capture = (expected - submitted) / denominator
    else:
        denominator = current - expected
        if denominator <= 1e-12:
            return None
        capture = (submitted - expected) / denominator
    return max(0.0, min(1.0, capture))


def _is_passive(order: CalibrationOrderSample) -> bool | None:
    if order.passive is not None:
        return bool(order.passive)
    if order.aggressive is not None:
        return not bool(order.aggressive)
    return None


def _ratio(numerator: int, denominator: int) -> float | None:
    if numerator == 0 and denominator == 0:
        return None
    if denominator == 0:
        return float("inf")
    return numerator / denominator


def _imbalance(buy_count: int, sell_count: int) -> float | None:
    total = buy_count + sell_count
    if total <= 0:
        return None
    return (buy_count - sell_count) / total


def _mean_bool(values: list[bool]) -> float | None:
    if not values:
        return None
    return sum(1 for value in values if value) / len(values)


def _median_or_none(values: Iterable[float]) -> float | None:
    clean = [float(value) for value in values]
    if not clean:
        return None
    return float(median(clean))


def _clean_symbol(value: str) -> str:
    return str(value or "").strip().upper()


def _clean_family(value: str) -> str:
    return str(value or "unknown").strip().lower() or "unknown"


__all__ = [
    "CalibrationBookSample",
    "CalibrationHoldingSample",
    "CalibrationOrderSample",
    "CalibrationTradeSample",
    "FamilyCalibrationReport",
    "MetricEvaluation",
    "RetailCalibrationReport",
    "RetailCalibrationReportCollector",
    "build_retail_calibration_report",
]
