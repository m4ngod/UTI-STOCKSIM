import time

from app.services.runtime_retail_agent import ManagedOrder, MarketContext, RuntimeRetailAgent
from services.sim_clock import ensure_sim_clock_started


class _FakeSnapshot:
    def __init__(self):
        self.best_bid_price = 9.9
        self.best_ask_price = 10.1
        self.last_price = 10.0
        self.mid_price = 10.0


class _FakeInstrument:
    tick_size = 0.01
    lot_size = 1
    settlement_cycle = 0
    initial_price = 10.0


class _FakeEngine:
    def __init__(self):
        self.instrument = _FakeInstrument()
        self.trades = []

    def get_snapshot(self, _depth):
        return _FakeSnapshot()

    def get_book(self, _symbol):
        class _Book:
            phase = "CONTINUOUS"

        return _Book()


class _FakeTradingService:
    def __init__(self):
        self.calls = []
        self.cancel_calls = []

    def submit_order(self, req):
        self.calls.append(req)
        return {"ok": True}

    def cancel_order(self, order_id):
        self.cancel_calls.append(order_id)
        return {"ok": True, "order_id": order_id}


def test_runtime_retail_waits_for_clock_start(monkeypatch):
    clk = ensure_sim_clock_started()
    if hasattr(clk, "stop_loop"):
        clk.stop_loop()
    fake_engine = _FakeEngine()
    fake_trading = _FakeTradingService()
    monkeypatch.setattr("app.services.runtime_retail_agent.engine_registry.symbols", lambda: ["AAA"])
    monkeypatch.setattr("app.services.runtime_retail_agent.engine_registry.get", lambda _symbol: fake_engine)

    agent = RuntimeRetailAgent(agent_id="retail-001", strategy="liquidity_noise", trading_service=fake_trading, seed=1)
    monkeypatch.setattr(agent, "_cold_start_parity", lambda _symbol: True)
    agent._step()
    assert fake_trading.calls == []

    clk.start_loop(day_seconds=999, speed=1.0)
    try:
        agent._step()
        assert len(fake_trading.calls) == 1
    finally:
        clk.stop_loop()


def test_runtime_retail_cold_start_noise_agent_without_inventory_can_abstain(monkeypatch):
    clk = ensure_sim_clock_started()
    if hasattr(clk, "stop_loop"):
        clk.stop_loop()
    fake_engine = _FakeEngine()
    fake_trading = _FakeTradingService()
    monkeypatch.setattr("app.services.runtime_retail_agent.engine_registry.symbols", lambda: ["AAA"])
    monkeypatch.setattr("app.services.runtime_retail_agent.engine_registry.get", lambda _symbol: fake_engine)

    agent = RuntimeRetailAgent(agent_id="retail-noise-001", strategy="liquidity_noise", trading_service=fake_trading, seed=1)
    monkeypatch.setattr(agent, "_available_sell_qty", lambda _symbol: 0)
    monkeypatch.setattr(agent, "_cold_start_parity", lambda _symbol: False)

    clk.start_loop(day_seconds=999, speed=1.0)
    try:
        agent._step()
        assert fake_trading.calls == []
    finally:
        clk.stop_loop()


def test_runtime_retail_cold_start_holding_agent_can_still_post_buy_interest(monkeypatch):
    clk = ensure_sim_clock_started()
    if hasattr(clk, "stop_loop"):
        clk.stop_loop()
    fake_engine = _FakeEngine()
    fake_trading = _FakeTradingService()
    monkeypatch.setattr("app.services.runtime_retail_agent.engine_registry.symbols", lambda: ["AAA"])
    monkeypatch.setattr("app.services.runtime_retail_agent.engine_registry.get", lambda _symbol: fake_engine)

    agent = RuntimeRetailAgent(agent_id="retail-buy-the-dip-001", strategy="buy_the_dip", trading_service=fake_trading, seed=1)
    monkeypatch.setattr(agent, "_available_sell_qty", lambda _symbol: 100)

    clk.start_loop(day_seconds=999, speed=1.0)
    try:
        agent._step()
        assert len(fake_trading.calls) == 1
        assert fake_trading.calls[0].side == "buy"
    finally:
        clk.stop_loop()


def test_runtime_retail_passive_quotes_seed_empty_book_on_both_sides():
    agent = RuntimeRetailAgent(
        agent_id="retail-price-001",
        strategy="liquidity_noise",
        trading_service=_FakeTradingService(),
        seed=1,
    )
    ctx = MarketContext(
        symbol="AAA",
        reference_price=10.0,
        initial_price=10.0,
        tick_size=0.01,
        lot_size=1,
        settlement_cycle=0,
        best_bid=None,
        best_ask=None,
        phase="CONTINUOUS",
        trade_count=0,
        cold_start=True,
    )

    assert agent._price_for_side(ctx, "buy", aggressive=False) == 9.99
    assert agent._price_for_side(ctx, "sell", aggressive=False) == 10.01


def test_runtime_retail_cold_start_buy_quote_is_capped_when_no_ask():
    agent = RuntimeRetailAgent(
        agent_id="retail-price-cap-001",
        strategy="liquidity_noise",
        trading_service=_FakeTradingService(),
        seed=1,
    )
    ctx = MarketContext(
        symbol="AAA",
        reference_price=10.15,
        initial_price=10.0,
        tick_size=0.01,
        lot_size=1,
        settlement_cycle=0,
        best_bid=10.15,
        best_ask=None,
        phase="CONTINUOUS",
        trade_count=0,
        cold_start=True,
    )

    assert agent._price_for_side(ctx, "buy", aggressive=False) == 10.02


def test_runtime_retail_patience_cancels_stale_live_orders():
    fake_trading = _FakeTradingService()
    agent = RuntimeRetailAgent(
        agent_id="retail-impatient-001",
        strategy="liquidity_noise",
        trading_service=fake_trading,
        seed=1,
    )
    agent._persona = agent._persona.__class__(
        **{
            **agent._persona.__dict__,
            "patience_seconds": 2.0,
        }
    )
    agent._managed_orders["O-STALE"] = ManagedOrder(
        order_id="O-STALE",
        symbol="AAA",
        side="buy",
        submitted_at=time.monotonic() - 5.0,
    )

    agent._enforce_order_patience()

    assert fake_trading.cancel_calls == ["O-STALE"]
    assert agent._managed_orders == {}
