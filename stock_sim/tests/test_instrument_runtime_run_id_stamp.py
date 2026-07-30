from stock_sim.persistence.models_instrument import Instrument
from stock_sim.services.engine_registry import engine_registry
from stock_sim.services.instrument_runtime_service import ensure_runtime_engine_for_instrument
from stock_sim.services.sim_clock import ensure_sim_clock_started


def test_ensure_runtime_engine_for_instrument_stamps_active_run_id():
    symbol = "RUNSTMP1"
    engine_registry.remove(symbol)

    clk = ensure_sim_clock_started()
    if hasattr(clk, "configure"):
        clk.configure(run_id="RUN-ENGINE-STAMP-001")

    inst = Instrument(
        symbol=symbol,
        name="Run Stamp Instrument",
        tick_size=0.01,
        lot_size=1,
        min_qty=1,
        settlement_cycle=1,
        initial_price=10.0,
        ipo_opened=True,
        is_active=True,
    )

    eng = ensure_runtime_engine_for_instrument(inst)
    book = eng.get_book(symbol)

    assert book.instrument_meta.get("run_id") == "RUN-ENGINE-STAMP-001"
    assert getattr(book.snapshot, "run_id", None) == "RUN-ENGINE-STAMP-001"

    if hasattr(clk, "configure"):
        clk.configure(run_id="")

