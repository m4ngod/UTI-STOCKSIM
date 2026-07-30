from sqlalchemy.orm import Session
from stock_sim.infra.event_bus import event_bus
from stock_sim.services.risk_engine import RiskEngine
from stock_sim.services.fee_engine import FeeEngine
from stock_sim.services.account_service import AccountService
from stock_sim.services.order_auction_reconciliation_service import OrderAuctionReconciliationService
from stock_sim.services.instrument_service import InstrumentService
from stock_sim.services.order_cancel_service import OrderCancelService
from stock_sim.services.order_engine_router import OrderEngineRouter
from stock_sim.services.order_instrument_resolver import OrderInstrumentResolver
from stock_sim.services.order_maintenance_service import OrderMaintenanceService
from stock_sim.services.order_persistence_service import OrderPersistenceService
from stock_sim.services.order_pretrade_service import OrderPreTradeService
from stock_sim.services.order_runtime_sync_service import OrderRuntimeSyncService
from stock_sim.services.order_trade_settlement_service import OrderTradeSettlementService
from stock_sim.services.trade_persistence_service import TradePersistenceService
from stock_sim.services.run_context import RunContext
from stock_sim.services.simulation_run_service import SimulationRunService
from stock_sim.services.sim_clock import current_sim_day, virtual_datetime
from stock_sim.core.order import Order
from stock_sim.core.const import OrderStatus, OrderSide, TimeInForce
from stock_sim.core.matching_engine import MatchingEngine
from stock_sim.persistence.models_order import OrderORM
from stock_sim.observability.metrics import metrics
import os  # 调试
# 新增: trace 调试标记
TRACE_ORDERS = os.environ.get('DEBUG_TRACE_ORDERS') == '1'
# 新增: 恢复服务导入
try:
    from stock_sim.services.recovery_service import is_readonly as recovery_is_readonly, mark_resumed_if_needed  # type: ignore
except Exception:  # fallback 源码路径
    from services.recovery_service import is_readonly as recovery_is_readonly, mark_resumed_if_needed  # type: ignore

class OrderService:
    """
    Runtime order-path facade coordinating specialized backend collaborators.
    """
    def __init__(self, session: Session, engine: MatchingEngine | None = None, instrument_service: InstrumentService | None = None, run_context: RunContext | None = None):
        # engine 现在可选: 仅作为向后兼容的默认引擎 (symbol 未注册时可用)
        self.s = session
        self.engine = engine  # deprecated: 动态路由后仅兜底
        self.risk = RiskEngine()
        self.fees = FeeEngine()
        self.run_context = run_context
        self.run_service = SimulationRunService(session) if run_context is not None else None
        self.accounts = AccountService(session, run_context=run_context)
        self.instrument_service = instrument_service or InstrumentService(session)
        self.instrument_resolver = OrderInstrumentResolver(self.instrument_service)
        self.engine_router = OrderEngineRouter(
            injected_engine=self.engine,
            instrument_resolver=self.instrument_resolver,
        )
        self.persistence = OrderPersistenceService(session)
        self.trade_persistence = TradePersistenceService(session)
        self._mem_orders: dict[str, Order] = {}
        self._batch_trades: list = []  # 批量模式缓冲
        self.runtime_sync = OrderRuntimeSyncService(mem_orders=self._mem_orders)
        self.trade_settlement = OrderTradeSettlementService(
            session=session,
            accounts=self.accounts,
            fees=self.fees,
            risk=self.risk,
            trade_persistence=self.trade_persistence,
            mem_orders=self._mem_orders,
            engine_lookup=self._get_engine,
            order_book_locator=self.runtime_sync.locate_order_book,
            run_id_provider=self._get_run_id,
            mem_order_updater=self.runtime_sync.sync_order_state,
            persist_order=self._persist_order,
            persist_event=self._persist_event,
        )
        self.pretrade = OrderPreTradeService(
            accounts=self.accounts,
            fees=self.fees,
            risk=self.risk,
            run_id_provider=self._get_run_id,
            persist_order=self._persist_order,
            trace_orders=TRACE_ORDERS,
        )
        self.cancellations = OrderCancelService(
            session=session,
            accounts=self.accounts,
            pretrade=self.pretrade,
            mem_orders=self._mem_orders,
            engine_lookup=self._get_engine,
            run_id_provider=self._get_run_id,
            persist_state=self._persist_state,
            persist_event=self._persist_event,
            mem_order_updater=self.runtime_sync.sync_order_state,
        )
        self.auction_reconciliation = OrderAuctionReconciliationService(
            session=session,
            default_engine=self.engine,
            cancellation_service=self.cancellations,
            mem_order_updater=self.runtime_sync.sync_order_state,
        )
        self.maintenance = OrderMaintenanceService(
            session=session,
            risk=self.risk,
        )

    def _get_engine(self, symbol: str) -> MatchingEngine:
        return self.engine_router.resolve_engine(symbol)

    # ---- 内部: 取标的参数 ----
    def _get_symbol_params(self, symbol: str):
        return self.engine_router.get_symbol_params(symbol)

    def _ensure_run_registered(self):
        if self.run_context is None or self.run_service is None:
            return
        try:
            self.run_service.create_run(self.run_context)
            self.run_service.mark_running(
                self.run_context.run_id,
                sim_day=current_sim_day(),
                sim_dt=virtual_datetime(current_sim_day()) if current_sim_day() is not None else None,
            )
        except Exception:
            pass

    # ---------------------- PUBLIC API ----------------------
    def place_order(self, order: Order):
        # ---- 恢复与只读保护 ----
        # 首笔订单尝试发送恢复完成事件（若此前成功恢复且未发送）。
        try:
            mark_resumed_if_needed()
        except Exception:
            pass
        if recovery_is_readonly():
            self.pretrade.reject_order(order, reason="READONLY_RECOVERY")
            return []
        dbg = os.environ.get('DEBUG_FRONT') == '1'
        if TRACE_ORDERS:
            print(f"[TRACE OrderService.place_order.begin] oid={order.order_id} sym={order.symbol} side={order.side.name} px={order.price} qty={order.quantity} acct={order.account_id}")
        # 处理（一次性）集合竞价未成交残余的释放与取消事件 (跨所有引擎)
        self.auction_reconciliation.reconcile_unmatched_auction_cancels()

        self._ensure_run_registered()
        self._mem_orders[order.order_id] = order
        metrics.inc("orders_submitted")
        params = self._get_symbol_params(order.symbol)
        engine = self._get_engine(order.symbol)
        if TRACE_ORDERS:
            print(f"[TRACE OrderService.place_order.params] oid={order.order_id} params_exist={params is not None} tick={getattr(params,'tick_size',None)} lot={getattr(params,'lot_size',None)} min_qty={getattr(params,'min_qty',None)} settle={getattr(params,'settlement_cycle',None)}")
        # (1) 预交易校验 + 冻结
        pretrade_ok, acc = self.pretrade.prepare_order(
            order,
            params=params,
            engine=engine,
            debug_mode=dbg,
        )
        if not pretrade_ok:
            return []
        if TRACE_ORDERS:
            print(f"[TRACE OrderService.persist.initial] oid={order.order_id} status={order.status.name}")
        # (2) 初始持久化
        self._persist_order(order, "NEW", "")

        # (3) 投递撮合
        if TRACE_ORDERS:
            print(f"[TRACE OrderService.pre_engine] oid={order.order_id} pre_status={order.status.name} pre_filled={order.filled}")
        trades = engine.submit_order(order, skip_freeze=True)
        if TRACE_ORDERS:
            print(f"[TRACE OrderService.after_engine] oid={order.order_id} post_status={order.status.name} post_filled={order.filled} remaining={order.remaining} trades={len(trades)}")
        if trades:
            metrics.inc("orders_with_trades")
            metrics.inc("trades_count", len(trades))

        # (4) 成交后处理
        self._after_trades(trades)

        # (5) TIF 收尾
        if self._finalize_tif_after_match(order, acc):
            return trades

        if order.status in (OrderStatus.NEW, OrderStatus.PARTIAL):
            self._persist_state(order, "REST", "")
        elif order.status == OrderStatus.FILLED and order.side is OrderSide.BUY and 'est_fee' in order._meta:
            pass

        if order.status == OrderStatus.NEW:
            metrics.inc("orders_new")
        elif order.status == OrderStatus.PARTIAL:
            metrics.inc("orders_partial")
        elif order.status == OrderStatus.FILLED:
            metrics.inc("orders_filled")
        return trades

    def cancel(self, order_id: str):
        return self.cancellations.cancel_user_order(order_id)

    def daily_reset(self):
        return self.maintenance.daily_reset()

    # ---------------------- INTERNAL ----------------------

    def settle_external_trades(self, trades):
        """Settle already-produced trades from external paths such as IPO open.

        Unlike the normal matching path, these trades may be produced outside
        ``submit_order()`` but still need full ORM/account/ledger settlement.
        """
        self.trade_settlement.settle_external_trades(trades)

    def _after_trades(self, trades):
        self.trade_settlement.process_trades(
            trades,
            publish_trade_events=True,
            persist_missing_orders=True,
        )

    def flush_batch(self):
        """批量模式下：处理缓冲的 trades，执行账��/持仓结算与费用多退少补。"""
        if not self._batch_trades:
            return
        trades = self._batch_trades
        self._batch_trades = []
        self.trade_settlement.process_trades(
            trades,
            publish_trade_events=False,
            persist_missing_orders=False,
        )

    def calc_required_frozen_fee(self) -> dict[str, float]:
        return self.runtime_sync.calc_required_frozen_fee()

    def _get_run_id(self) -> str | None:
        return None if self.run_context is None else self.run_context.run_id

    def _finalize_tif_after_match(self, order: Order, acc) -> bool:
        if order.tif is TimeInForce.FOK and order.status != OrderStatus.FILLED:
            if TRACE_ORDERS:
                print(f"[TRACE OrderService.fok_cancel] oid={order.order_id} filled={order.filled} qty={order.quantity}")
            detail = "FOK_UNFILLABLE"
            self.cancellations.cancel_runtime_order(order, acc, reason=detail)
            return True

        if order.tif is TimeInForce.IOC and order.remaining > 0:
            if TRACE_ORDERS:
                print(f"[TRACE OrderService.ioc_cancel] oid={order.order_id} filled={order.filled} remaining={order.remaining}")
            detail = 'IOC_REMAIN_CANCEL' if order.filled > 0 else 'IOC_UNFILLABLE'
            self.cancellations.cancel_runtime_order(order, acc, reason=detail)
            return True

        return False

    def _persist_order(self, order: Order, event: str, detail: str):
        """初次持久化订单并写事件。"""
        sim_day = current_sim_day(); sim_dt = virtual_datetime(sim_day)
        self.persistence.create_order_record(
            order,
            sim_day=sim_day,
            sim_dt=sim_dt,
            run_id=self._get_run_id(),
        )
        self._persist_event(order.order_id, event, detail)

    def _persist_state(self, order: Order, event: str, detail: str):
        """更新已存在订单状态并写事件。"""
        sd = current_sim_day()
        self.persistence.update_order_state(
            order,
            sim_day=sd,
            sim_dt=virtual_datetime(sd),
        )
        self._persist_event(order.order_id, event, detail)

    def _persist_event(self, order_id: str, event: str, detail: str):
        # OrderEvent 不含 sim_day 字段，仅补写其关联订单的 sim_day (若订单已存在且未写)
        try:
            existing = self.persistence.get_order_record(order_id)
            if existing and not getattr(existing, 'sim_day', None):
                sd = current_sim_day(); existing.sim_day = sd; existing.sim_dt = virtual_datetime(sd)
        except Exception:
            pass
        self.persistence.create_order_event(
            order_id=order_id,
            event=event,
            detail=detail,
            run_id=self._get_run_id(),
        )
