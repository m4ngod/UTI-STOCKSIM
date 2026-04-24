from __future__ import annotations

from datetime import datetime
import json
from typing import Any, Dict
from uuid import uuid4

try:
    from stock_sim.persistence import models_init  # type: ignore
    from stock_sim.persistence.models_imports import SessionLocal  # type: ignore
    from stock_sim.services.account_service import AccountService as RuntimeAccountService  # type: ignore
    from stock_sim.services.agent_binding_service import AgentBindingService as RuntimeAgentBindingService  # type: ignore
    from stock_sim.services.instrument_service import InstrumentService  # type: ignore
    from stock_sim.services.order_service import OrderService  # type: ignore
    from stock_sim.services.run_context import RunContext  # type: ignore
    from stock_sim.services.simulation_run_service import SimulationRunService  # type: ignore
    from stock_sim.services.engine_registry import engine_registry  # type: ignore
    from stock_sim.core.matching_engine import MatchingEngine  # type: ignore
    from stock_sim.core.instruments import create_instrument  # type: ignore
    from stock_sim.core.order import Order  # type: ignore
    from stock_sim.core.const import OrderSide  # type: ignore
    from stock_sim.services.sim_clock import ensure_sim_clock_started, virtual_datetime  # type: ignore
    from stock_sim.services.ipo_retail_distribution import allocate_pending_ipo_distributions  # type: ignore
except Exception:  # pragma: no cover
    try:
        from persistence import models_init  # type: ignore
        from persistence.models_imports import SessionLocal  # type: ignore
        from services.account_service import AccountService as RuntimeAccountService  # type: ignore
        from services.agent_binding_service import AgentBindingService as RuntimeAgentBindingService  # type: ignore
        from services.instrument_service import InstrumentService  # type: ignore
        from services.order_service import OrderService  # type: ignore
        from services.run_context import RunContext  # type: ignore
        from services.simulation_run_service import SimulationRunService  # type: ignore
        from services.engine_registry import engine_registry  # type: ignore
        from core.matching_engine import MatchingEngine  # type: ignore
        from core.instruments import create_instrument  # type: ignore
        from core.order import Order  # type: ignore
        from core.const import OrderSide  # type: ignore
        from services.sim_clock import ensure_sim_clock_started, virtual_datetime  # type: ignore
        from services.ipo_retail_distribution import allocate_pending_ipo_distributions  # type: ignore
    except Exception:  # pragma: no cover
        models_init = None  # type: ignore
        SessionLocal = None  # type: ignore
        RuntimeAccountService = None  # type: ignore
        RuntimeAgentBindingService = None  # type: ignore
        InstrumentService = None  # type: ignore
        OrderService = None  # type: ignore
        RunContext = None  # type: ignore
        SimulationRunService = None  # type: ignore
        engine_registry = None  # type: ignore
        MatchingEngine = None  # type: ignore
        create_instrument = None  # type: ignore
        Order = None  # type: ignore
        OrderSide = None  # type: ignore
        ensure_sim_clock_started = None  # type: ignore
        virtual_datetime = None  # type: ignore
        allocate_pending_ipo_distributions = None  # type: ignore


class RuntimeCommandService:
    def __init__(self) -> None:
        try:
            if models_init is not None:
                ensure = getattr(models_init, "ensure_models", None)
                if callable(ensure):
                    ensure()
                else:
                    models_init.init_models()
        except Exception:
            pass

    def _ensure_models(self) -> None:
        if models_init is None:
            return
        ensure = getattr(models_init, "ensure_models", None)
        if callable(ensure):
            ensure()
            return
        models_init.init_models()

    def _normalize_run_id(self, value: object) -> str | None:
        text = str(value or "").strip()
        return text or None

    @staticmethod
    def _coerce_binding_meta(value: object) -> Dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, str) and value.strip():
            try:
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    return dict(parsed)
            except Exception:
                return {}
        return {}

    def _current_clock_snapshot(self) -> Dict[str, Any]:
        if ensure_sim_clock_started is None:
            return {}
        try:
            clk = ensure_sim_clock_started()
            if hasattr(clk, "snapshot"):
                snap = dict(clk.snapshot() or {})
                snap["run_id"] = self._normalize_run_id(snap.get("run_id"))
                return snap
        except Exception:
            pass
        return {}

    def _generate_run_id(self) -> str:
        stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        return f"RUN-DESKTOP-{stamp}-{uuid4().hex[:8].upper()}"

    def _build_run_context(self, run_id: str, *, sim_day: int | None, speed: float | None = None) -> RunContext | None:
        if RunContext is None:
            return None
        normalized_day = None if sim_day is None else max(0, int(sim_day))
        sim_dt = None
        if normalized_day is not None and virtual_datetime is not None:
            try:
                sim_dt = virtual_datetime(normalized_day)
            except Exception:
                sim_dt = None
        speed_profile = None
        if speed is not None:
            try:
                speed_profile = f"{float(speed):g}x"
            except Exception:
                speed_profile = None
        return RunContext(
            run_id=run_id,
            run_type="simulation",
            scenario_name="desktop-session",
            sim_day=normalized_day,
            sim_dt=sim_dt,
            speed_profile=speed_profile,
        )

    def _mark_run_running(self, run_id: str, *, sim_day: int | None, speed: float | None = None) -> None:
        if SessionLocal is None or SimulationRunService is None or models_init is None:
            return
        ctx = self._build_run_context(run_id, sim_day=sim_day, speed=speed)
        if ctx is None:
            return
        try:
            self._ensure_models()
            session = SessionLocal()
        except Exception:
            return
        try:
            svc = SimulationRunService(session)
            svc.create_run(ctx)
            svc.mark_running(run_id, sim_day=ctx.sim_day, sim_dt=ctx.sim_dt)
            session.commit()
        except Exception:
            try:
                session.rollback()
            except Exception:
                pass
        finally:
            session.close()

    def _mark_run_completed(self, run_id: str, *, sim_day: int | None) -> None:
        if SessionLocal is None or SimulationRunService is None or models_init is None:
            return
        sim_dt = None
        if sim_day is not None and virtual_datetime is not None:
            try:
                sim_dt = virtual_datetime(sim_day)
            except Exception:
                sim_dt = None
        try:
            self._ensure_models()
            session = SessionLocal()
        except Exception:
            return
        try:
            svc = SimulationRunService(session)
            if svc.get(run_id) is None:
                session.rollback()
                return
            svc.mark_completed(run_id, sim_day=sim_day, sim_dt=sim_dt)
            session.commit()
        except Exception:
            try:
                session.rollback()
            except Exception:
                pass
        finally:
            session.close()

    def _stamp_engine_run_id(self, symbol: str, run_id: str) -> None:
        if engine_registry is None:
            return
        engine = engine_registry.get(symbol)
        if engine is None:
            return
        try:
            book = engine.get_book(symbol) if hasattr(engine, "get_book") else None
        except Exception:
            book = None
        if book is not None:
            try:
                meta = getattr(book, "instrument_meta", None)
                if not isinstance(meta, dict):
                    meta = {}
                    setattr(book, "instrument_meta", meta)
                meta["run_id"] = run_id
            except Exception:
                pass
            try:
                setattr(book.snapshot, "run_id", run_id)
            except Exception:
                pass

    def _stamp_registered_engine_run_id(self, run_id: str) -> None:
        if engine_registry is None:
            return
        for symbol in engine_registry.symbols():
            self._stamp_engine_run_id(symbol, run_id)

    def _ensure_active_run_id(self, *, sim_day: int | None, speed: float | None = None) -> str | None:
        snap = self._current_clock_snapshot()
        run_id = self._normalize_run_id(snap.get("run_id"))
        if run_id is None:
            run_id = self._generate_run_id()
            if ensure_sim_clock_started is not None:
                try:
                    ensure_sim_clock_started().configure(run_id=run_id)
                except Exception:
                    pass
        self._mark_run_running(run_id, sim_day=sim_day, speed=speed)
        self._stamp_registered_engine_run_id(run_id)
        return run_id

    def ensure_desktop_run(self) -> str | None:
        snap = self._current_clock_snapshot()
        sim_day_raw = snap.get("sim_day")
        try:
            sim_day = None if sim_day_raw is None else max(0, int(sim_day_raw))
        except Exception:
            sim_day = None
        speed_raw = snap.get("speed")
        try:
            speed = None if speed_raw is None else float(speed_raw)
        except Exception:
            speed = None
        return self._ensure_active_run_id(sim_day=sim_day, speed=speed)

    def _resolve_active_run_context(self) -> RunContext | None:
        snap = self._current_clock_snapshot()
        run_id = self._normalize_run_id(snap.get("run_id"))
        if run_id is None:
            return None
        sim_day_raw = snap.get("sim_day")
        try:
            sim_day = None if sim_day_raw is None else max(0, int(sim_day_raw))
        except Exception:
            sim_day = None
        return self._build_run_context(run_id, sim_day=sim_day)

    def bootstrap_agent_account(
        self,
        *,
        account_id: str,
        initial_cash: float,
        agent_type: str | None = None,
        strategy: str | None = None,
    ) -> None:
        if models_init is None or SessionLocal is None or RuntimeAccountService is None:
            return
        self._ensure_models()
        run_id = self.ensure_desktop_run()
        try:
            sess = SessionLocal()
        except Exception:
            return
        try:
            runtime_account = RuntimeAccountService(sess)
            runtime_account.get_or_create(account_id, cash=initial_cash)
            if RuntimeAgentBindingService is not None:
                binding_meta = {
                    "name": account_id,
                    "initial_cash": float(initial_cash),
                    "strategy": strategy,
                    "type": agent_type,
                    "status": "STOPPED",
                    "params_version": 0,
                    "start_time": None,
                    "last_heartbeat": None,
                    "run_id": run_id,
                }
                RuntimeAgentBindingService(sess).bind(
                    account_id,
                    str(agent_type or "GENERIC"),
                    account_id,
                    overwrite=True,
                    meta=binding_meta,
                    run_id=run_id,
                )
            sess.commit()
        except Exception:
            try:
                sess.rollback()
            except Exception:
                pass
        finally:
            sess.close()

    def update_agent_binding_meta(self, agent_id: str, **updates: Any) -> None:
        if SessionLocal is None or RuntimeAgentBindingService is None:
            return
        normalized_agent_id = str(agent_id or "").strip()
        if not normalized_agent_id:
            return
        try:
            self._ensure_models()
            sess = SessionLocal()
        except Exception:
            return
        try:
            bindings = RuntimeAgentBindingService(sess)
            row = bindings.get(normalized_agent_id)
            if row is None:
                return
            merged = self._coerce_binding_meta(getattr(row, "meta", None))
            for key, value in updates.items():
                if value is None and key not in {"start_time", "last_heartbeat"}:
                    continue
                merged[key] = value
            bindings.set_meta(normalized_agent_id, merged)
            try:
                sess.commit()
            except Exception:
                pass
        except Exception:
            try:
                sess.rollback()
            except Exception:
                pass
        finally:
            sess.close()

    def create_instrument(
        self,
        *,
        symbol: str,
        name: str,
        price_step: float,
        initial_price: float,
        float_shares: int,
        market_cap: float,
        total_shares: int,
    ) -> bool:
        if SessionLocal is None or InstrumentService is None or models_init is None:
            return False
        try:
            self._ensure_models()
            session = SessionLocal()
        except Exception:
            return False
        try:
            svc = InstrumentService(session)
            normalized_symbol = str(symbol or "").strip().upper()
            svc.create(
                symbol=normalized_symbol,
                name=name,
                tick_size=float(price_step),
                lot_size=1,
                min_qty=1,
                settlement_cycle=1,
                market_cap=float(market_cap),
                total_shares=int(total_shares),
                free_float_shares=int(float_shares),
                initial_price=float(initial_price),
                ipo_opened=True,
                overwrite=True,
            )
            session.commit()
            try:
                svc.finalize_create(normalized_symbol)
            except Exception:
                pass
            run_ctx = self._resolve_active_run_context()
            if run_ctx is not None:
                self._stamp_engine_run_id(normalized_symbol, run_ctx.run_id)
        except Exception:
            try:
                session.rollback()
            except Exception:
                pass
            try:
                session.close()
            except Exception:
                pass
            return False
        finally:
            try:
                session.close()
            except Exception:
                pass
        return True

    def submit_order(
        self,
        *,
        symbol: str,
        side: str,
        price: float,
        qty: int,
        account_id: str,
    ) -> Dict[str, Any]:
        if (
            SessionLocal is None
            or InstrumentService is None
            or OrderService is None
            or RuntimeAccountService is None
            or engine_registry is None
            or MatchingEngine is None
            or create_instrument is None
            or Order is None
            or OrderSide is None
        ):
            raise RuntimeError("runtime trading services unavailable")
        session = SessionLocal()
        try:
            normalized_symbol = str(symbol or "").strip().upper()
            normalized_account_id = str(account_id or "").strip()
            side_s = str(side or "").strip().lower()
            if not normalized_symbol:
                raise ValueError("symbol 涓嶈兘涓虹┖")
            if not normalized_account_id:
                raise ValueError("account_id 涓嶈兘涓虹┖")
            if side_s not in {"buy", "sell"}:
                raise ValueError("side 蹇呴』鏄?buy/sell")
            if int(qty) <= 0:
                raise ValueError("qty 蹇呴』 > 0")
            if float(price) <= 0:
                raise ValueError("price 蹇呴』 > 0")

            inst_srv = InstrumentService(session)
            dto = inst_srv.get(normalized_symbol)
            if dto is None:
                reg = engine_registry.get(normalized_symbol)
                reg_inst = getattr(reg, "instrument", None) if reg is not None else None
                if reg_inst is None:
                    raise ValueError(f"instrument not found: {normalized_symbol}")

                class _Dto:
                    pass

                dto = _Dto()
                dto.tick_size = float(getattr(reg_inst, "tick_size", 0.01) or 0.01)
                dto.lot_size = int(getattr(reg_inst, "lot_size", 100) or 100)
                dto.min_qty = int(getattr(reg_inst, "min_qty", dto.lot_size) or dto.lot_size)
                dto.initial_price = float(getattr(reg_inst, "initial_price", price) or price)

            engine = engine_registry.get(normalized_symbol)
            if engine is None:
                engine = MatchingEngine(
                    normalized_symbol,
                    create_instrument(
                        normalized_symbol,
                        tick_size=dto.tick_size,
                        lot_size=dto.lot_size,
                        min_qty=dto.min_qty,
                        initial_price=dto.initial_price,
                    ),
                )
                engine_registry.register(normalized_symbol, engine, overwrite=True)

            RuntimeAccountService(session).get_or_create(normalized_account_id)

            order = Order(
                symbol=normalized_symbol,
                side=OrderSide.BUY if side_s == "buy" else OrderSide.SELL,
                price=float(price),
                quantity=int(qty),
                account_id=normalized_account_id,
            )
            run_context = self._resolve_active_run_context()
            if run_context is not None:
                self._stamp_engine_run_id(normalized_symbol, run_context.run_id)
            trades = OrderService(
                session,
                engine=engine,
                instrument_service=inst_srv,
                run_context=run_context,
            ).place_order(order)
            session.commit()
            return {
                "ok": order.status.name != "REJECTED",
                "order_id": order.order_id,
                "symbol": normalized_symbol,
                "account_id": normalized_account_id,
                "side": side_s,
                "price": float(order.price),
                "qty": int(order.quantity),
                "filled": int(order.filled),
                "status": order.status.name,
                "trade_count": len(trades),
                "trades": [
                    trade.to_dict() if hasattr(trade, "to_dict") else dict(trade)
                    for trade in trades
                ],
            }
        finally:
            session.close()

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        if SessionLocal is None or OrderService is None or models_init is None:
            raise RuntimeError("runtime trading services unavailable")
        session = SessionLocal()
        try:
            self._ensure_models()
            ok = bool(OrderService(session, run_context=self._resolve_active_run_context()).cancel(order_id))
            session.commit()
            return {"ok": ok, "order_id": order_id}
        finally:
            session.close()

    def clock_snapshot(self) -> Dict[str, Any]:
        return self._current_clock_snapshot()

    def start_clock(self, *, sim_day: int | None, day_seconds: float, speed: float, allocate_pending_ipo: bool = False) -> Dict[str, Any]:
        if ensure_sim_clock_started is None:
            return {}
        try:
            clk = ensure_sim_clock_started()
            if sim_day is not None and hasattr(clk, "set_day"):
                clk.set_day(int(sim_day))
            run_id = self._ensure_active_run_id(sim_day=sim_day, speed=speed)
            if allocate_pending_ipo and callable(allocate_pending_ipo_distributions):
                allocate_pending_ipo_distributions(sim_day=int(sim_day or 0))
            if hasattr(clk, "start_loop"):
                clk.start_loop(day_seconds=day_seconds, speed=speed, run_id=run_id)
        except Exception:
            return {}
        return self.clock_snapshot()

    def pause_clock(self) -> Dict[str, Any]:
        if ensure_sim_clock_started is None:
            return {}
        try:
            clk = ensure_sim_clock_started()
            if hasattr(clk, "pause_loop"):
                clk.pause_loop()
        except Exception:
            return {}
        return self.clock_snapshot()

    def resume_clock(self, *, day_seconds: float, speed: float) -> Dict[str, Any]:
        if ensure_sim_clock_started is None:
            return {}
        try:
            clk = ensure_sim_clock_started()
            snap = self._current_clock_snapshot()
            sim_day_raw = snap.get("sim_day")
            try:
                sim_day = None if sim_day_raw is None else max(0, int(sim_day_raw))
            except Exception:
                sim_day = None
            run_id = self._ensure_active_run_id(sim_day=sim_day, speed=speed)
            if hasattr(clk, "start_loop"):
                clk.start_loop(day_seconds=day_seconds, speed=speed, run_id=run_id)
        except Exception:
            return {}
        return self.clock_snapshot()

    def stop_clock(self) -> Dict[str, Any]:
        if ensure_sim_clock_started is None:
            return {}
        try:
            clk = ensure_sim_clock_started()
            snap = self._current_clock_snapshot()
            run_id = self._normalize_run_id((snap or {}).get("run_id"))
            sim_day_raw = (snap or {}).get("sim_day")
            try:
                sim_day = None if sim_day_raw is None else max(0, int(sim_day_raw))
            except Exception:
                sim_day = None
            if hasattr(clk, "stop_loop"):
                clk.stop_loop()
            if run_id is not None:
                self._mark_run_completed(run_id, sim_day=sim_day)
            if hasattr(clk, "configure"):
                clk.configure(run_id="")
        except Exception:
            return {}
        return self.clock_snapshot()

    def set_clock_speed(self, speed: float) -> Dict[str, Any]:
        if ensure_sim_clock_started is None:
            return {}
        try:
            clk = ensure_sim_clock_started()
            if hasattr(clk, "set_speed"):
                clk.set_speed(speed)
        except Exception:
            return {}
        return self.clock_snapshot()

    def allocate_pending_ipo_distributions(self, *, sim_day: int) -> None:
        if not callable(allocate_pending_ipo_distributions):
            return
        try:
            allocate_pending_ipo_distributions(sim_day=int(sim_day))
        except Exception:
            pass

    def allocate_pending_ipo_distributions_if_running(self) -> None:
        snap = self.clock_snapshot()
        if not bool((snap or {}).get("running", False)):
            return
        self.allocate_pending_ipo_distributions(sim_day=int((snap or {}).get("sim_day", 0) or 0))


__all__ = ["RuntimeCommandService"]
