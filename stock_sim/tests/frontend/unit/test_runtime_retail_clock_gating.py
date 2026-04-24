from app.services.runtime_retail_agent import RuntimeRetailAgent
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

    def submit_order(self, req):
        self.calls.append(req)
        return {"ok": True}


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
