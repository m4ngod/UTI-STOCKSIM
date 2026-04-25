from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.persistence.models_instrument import Instrument
from stock_sim.services.engine_registry import engine_registry
from stock_sim.services.instrument_service import InstrumentService


def test_restore_active_runtime_engines_registers_persisted_instruments():
    symbol = "RSTENG1"
    models_init.ensure_models()
    engine_registry.remove(symbol)

    session = SessionLocal()
    try:
        svc = InstrumentService(session)
        svc.create(
            symbol=symbol,
            name="Restore Engine",
            tick_size=0.01,
            lot_size=1,
            min_qty=1,
            settlement_cycle=1,
            initial_price=10.0,
            ipo_opened=True,
            overwrite=True,
        )
        session.commit()
    finally:
        session.close()

    engine_registry.remove(symbol)

    session = SessionLocal()
    try:
        restored = InstrumentService(session).restore_active_runtime_engines()
        assert symbol in {dto.symbol for dto in restored}
        assert engine_registry.get(symbol) is not None
    finally:
        row = session.get(Instrument, symbol)
        if row is not None:
            session.delete(row)
            session.commit()
        session.close()
        engine_registry.remove(symbol)
