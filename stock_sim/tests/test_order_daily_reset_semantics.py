from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.services.instrument_service import InstrumentService
from stock_sim.services.order_service import OrderService
from stock_sim.services.engine_registry import engine_registry
from stock_sim.core.matching_engine import MatchingEngine
from stock_sim.core.instruments import create_instrument
from stock_sim.core.const import OrderSide


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
        create_instrument(
            symbol,
            tick_size=0.01,
            lot_size=100,
            min_qty=100,
            initial_price=initial_price,
            settlement_cycle=1,
        ),
    )
    osrv = OrderService(s, engine, instrument_service=inst_srv)
    return s, osrv


def test_daily_reset_clears_tplus_runtime_counters():
    s, osrv = _prepare_runtime("DRS1")
    try:
        osrv.risk.update_tplus("ACC_DRS", "DRS1", OrderSide.BUY, 300)
        assert osrv.risk.get_tplus("ACC_DRS", "DRS1", OrderSide.BUY) == 300

        ok = osrv.daily_reset()

        assert ok is True
        assert osrv.risk.get_tplus("ACC_DRS", "DRS1", OrderSide.BUY) == 0
    finally:
        s.close()
