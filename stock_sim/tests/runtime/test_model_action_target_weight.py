from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.services.instrument_service import InstrumentService
from stock_sim.services.order_service import OrderService
from stock_sim.services.account_service import AccountService
from stock_sim.services.engine_registry import engine_registry
from stock_sim.core.matching_engine import MatchingEngine
from stock_sim.core.instruments import create_instrument
from stock_sim.rl.action_parser import ActionParser
from stock_sim.rl.model_bridge import ModelBridge


def _runtime(symbol: str, *, initial_price: float = 10.0):
    engine_registry.remove(symbol)
    models_init.init_models()
    session = SessionLocal()
    inst = InstrumentService(session)
    inst.create(
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
    return session, OrderService(session, engine, instrument_service=inst), AccountService(session)


def test_action_parser_accepts_and_clips_target_weight():
    parsed = ActionParser().parse(
        {
            "contract_version": "act.v1",
            "action_type": "target_weight",
            "target": {"account_id": "MODEL_1", "symbols": ["TW1", "TW2"]},
            "payload": {"weights": {"TW1": 0.8, "TW2": 0.8}},
            "constraints": {"max_gross_leverage": 1.0, "clip_to_limits": True},
            "meta": {},
        }
    )

    assert parsed["action_type"] == "target_weight"
    assert round(sum(abs(v) for v in parsed["payload"]["weights"].values()), 6) == 1.0


def test_model_bridge_target_weight_creates_rebalance_order():
    session, osrv, acc_svc = _runtime("TWGT1", initial_price=10.0)
    try:
        acc_svc.get_or_create("MODEL_TW", cash=100_000.0)
        bridge = ModelBridge(osrv)

        result = bridge.step(
            action={
                "contract_version": "act.v1",
                "action_type": "target_weight",
                "target": {"account_id": "MODEL_TW", "symbols": ["TWGT1"]},
                "payload": {"weights": {"TWGT1": 0.5}, "cash_buffer_ratio": 0.0},
                "constraints": {"allow_short": False, "max_gross_leverage": 1.0, "clip_to_limits": True},
                "meta": {"model_id": "random_weight_v1"},
            }
        )

        assert result["accepted"] is True
        assert result["action_type"] == "target_weight"
        assert result["status"] == "EXECUTED"
        assert result["orders"][0]["symbol"] == "TWGT1"
        assert result["orders"][0]["side"] == "BUY"
        assert result["orders"][0]["quantity"] == 5000
    finally:
        session.close()


def test_model_bridge_rejects_target_position_until_translator_exists():
    session, osrv, _acc_svc = _runtime("TPOS1", initial_price=10.0)
    try:
        bridge = ModelBridge(osrv)
        result = bridge.step(
            action={
                "contract_version": "act.v1",
                "action_type": "target_position",
                "target": {"account_id": "MODEL_TP"},
                "payload": {"positions": {"TPOS1": 100}},
                "constraints": {},
                "meta": {},
            }
        )

        assert result["accepted"] is False
        assert result["reject_reason"] == "TARGET_POSITION_NOT_IMPLEMENTED"
    finally:
        session.close()
