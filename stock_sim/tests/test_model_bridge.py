from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.services.instrument_service import InstrumentService
from stock_sim.services.order_service import OrderService
from stock_sim.services.account_service import AccountService
from stock_sim.services.engine_registry import engine_registry
from stock_sim.core.matching_engine import MatchingEngine
from stock_sim.core.instruments import create_instrument
from stock_sim.core.order import Order
from stock_sim.core.const import OrderSide
from stock_sim.rl.model_bridge import ModelBridge



def _prepare_runtime(symbol: str, *, initial_price: float = 10.0):
    engine_registry.remove(symbol)
    models_init.init_models()
    s = SessionLocal()
    inst_srv = InstrumentService(s)
    inst_srv.create(
        symbol=symbol,
        name=symbol,
        tick_size=0.01,
        lot_size=100,
        min_qty=100,
        settlement_cycle=1,
        total_shares=1_000_000,
        free_float_shares=500_000,
        initial_price=initial_price,
        ipo_opened=True,
    )
    engine = MatchingEngine(
        symbol,
        create_instrument(symbol, tick_size=0.01, lot_size=100, min_qty=100, initial_price=initial_price, settlement_cycle=1),
    )
    osrv = OrderService(s, engine, instrument_service=inst_srv)
    acc_svc = AccountService(s)
    bridge = ModelBridge(osrv)
    return s, osrv, acc_svc, bridge



def test_observation_builder_emits_obs_v1_shape():
    s, _osrv, acc_svc, bridge = _prepare_runtime("MBO1")
    try:
        acc = acc_svc.get_or_create("ACC_MBO1", cash=100000.0)
        pos = acc_svc.get_position(acc, "MBO1")
        pos.quantity = 100
        pos.avg_price = 10.0
        s.flush()

        obs = bridge.build_observation(account_id="ACC_MBO1", symbol="MBO1", run_id="run1", episode_id="ep1", step_index=3)
        assert obs["contract_version"] == "obs.v1"
        assert set(obs.keys()) == {"contract_version", "market", "account", "context", "features"}
        assert obs["market"]["symbol"] == "MBO1"
        assert obs["account"]["account_id"] == "ACC_MBO1"
        assert obs["context"]["run_id"] == "run1"
        assert isinstance(obs["account"]["positions"], list)
    finally:
        s.close()



def test_model_bridge_hold_action_returns_noop():
    s, _osrv, _acc_svc, bridge = _prepare_runtime("MBH1")
    try:
        result = bridge.step(action={
            "contract_version": "act.v1",
            "action_type": "hold",
            "target": {"account_id": "ACC_MBH1"},
            "payload": {},
            "constraints": {},
            "meta": {},
        })
        assert result["accepted"] is True
        assert result["status"] == "NOOP"
        assert result["trades"] == []
    finally:
        s.close()



def test_model_bridge_order_action_dispatches_into_runtime():
    s, osrv, acc_svc, bridge = _prepare_runtime("MBD1")
    try:
        seller = acc_svc.get_or_create("ACC_MBD_SELL", cash=100000.0)
        seller_pos = acc_svc.get_position(seller, "MBD1")
        seller_pos.quantity = 100
        seller_pos.avg_price = 10.0
        s.flush()

        resting_sell = Order(
            symbol="MBD1",
            side=OrderSide.SELL,
            price=10.0,
            quantity=100,
            account_id="ACC_MBD_SELL",
        )
        osrv.place_order(resting_sell)

        result = bridge.step(action={
            "contract_version": "act.v1",
            "action_type": "order",
            "target": {"account_id": "ACC_MBD_BUY", "symbol": "MBD1"},
            "payload": {
                "side": "BUY",
                "order_type": "LIMIT",
                "price": 10.0,
                "quantity": 100,
                "tif": "GFD",
            },
            "constraints": {},
            "meta": {},
        })
        assert result["accepted"] is True
        assert result["action_type"] == "order"
        assert result["status"] in {"FILLED", "PARTIAL", "NEW", "CANCELED"}
        assert result["order_id"] is not None
        assert isinstance(result["trades"], list)
    finally:
        s.close()
