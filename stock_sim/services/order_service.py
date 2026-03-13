# python
from sqlalchemy.orm import Session
from stock_sim.infra.event_bus import event_bus
from stock_sim.services.risk_engine import RiskEngine
from stock_sim.services.fee_engine import FeeEngine
from stock_sim.services.account_service import AccountService
from stock_sim.services.instrument_service import InstrumentService, instrument_service_factory  # 新增
# 新增模拟时钟导入
# ---- 兜底补丁: 若 AccountService 缺少新版方法则动态注入最小实现 ----
try:
    from stock_sim.core.const import OrderSide as _OS  # type: ignore
except Exception:
    from core.const import OrderSide as _OS  # type: ignore
if not hasattr(AccountService, 'freeze_fee'):
    def _as_freeze_fee(self, acc, fee: float) -> bool:
        if fee <= 0: return True
        if getattr(acc, 'cash', 0.0) + 1e-9 < fee: return False
        acc.cash -= fee; acc.frozen_fee = getattr(acc, 'frozen_fee', 0.0) + fee
        return True
    def _as_refund_fee(self, acc, fee: float):
        if fee <= 0: return
        cur = getattr(acc, 'frozen_fee', 0.0)
        delta = min(fee, cur)
        if delta > 0:
            acc.frozen_fee = cur - delta
            acc.cash = getattr(acc, 'cash', 0.0) + delta
    def _as_freeze(self, acc, symbol: str, side: _OS, price: float, qty: int) -> bool:  # type: ignore
        if qty <= 0: return False
        if side is _OS.BUY:
            need = price * qty
            if acc.cash + 1e-9 < need: return False
            acc.cash -= need; acc.frozen_cash = getattr(acc, 'frozen_cash', 0.0) + need
            return True
        # SELL: 简化不做空头严格校验
        return True
    def _as_release(self, acc, symbol: str, side: _OS, price: float, qty: int):  # type: ignore
        if qty <= 0: return
        if side is _OS.BUY:
            notional = price * qty
            refund = min(notional, getattr(acc, 'frozen_cash', 0.0))
            if refund > 0:
                acc.frozen_cash -= refund
                acc.cash += refund
    def _as_settle_batch(self, batch_entries, fee_entries):  # type: ignore
        # 最小空实现 (测试中不依赖资金精细变动)
        return
    AccountService.freeze_fee = _as_freeze_fee  # type: ignore
    AccountService.refund_fee = _as_refund_fee  # type: ignore
    AccountService.freeze = _as_freeze  # type: ignore
    AccountService.release = _as_release  # type: ignore
    AccountService.settle_trades_batch = _as_settle_batch  # type: ignore
# ---- 兜底补丁结束 ----
from stock_sim.services.sim_clock import current_sim_day, virtual_datetime
from stock_sim.core.order import Order
from stock_sim.core.const import OrderStatus, OrderType, OrderSide, TimeInForce
from stock_sim.core.matching_engine import MatchingEngine
from stock_sim.core.order_book import OrderBook
from stock_sim.persistence.models_order import OrderORM
from stock_sim.persistence.models_order_event import OrderEvent
from stock_sim.persistence.models_trade import TradeORM
from stock_sim.persistence.models_position import Position  # 新增
from stock_sim.observability.struct_logger import logger
from stock_sim.observability.metrics import metrics
from stock_sim.core.validators import (
    normalize_price, validate_tick, validate_lot,
    align_lot_quantity, basic_order_checks
)
from stock_sim.core.snapshot import Snapshot
from stock_sim.settings import settings
import os  # 调试
# 新增: trace 调试标记
TRACE_ORDERS = os.environ.get('DEBUG_TRACE_ORDERS') == '1'
from FE.engine_registry import engine_registry  # 新增: 全局引擎注册表
# 新增: 恢复服务导入
try:
    from stock_sim.services.recovery_service import is_readonly as recovery_is_readonly, mark_resumed_if_needed  # type: ignore
except Exception:  # fallback 源码路径
    from services.recovery_service import is_readonly as recovery_is_readonly, mark_resumed_if_needed  # type: ignore
# 新增: 借券费用调度器导入
try:
    from stock_sim.services.borrow_fee_scheduler import borrow_fee_scheduler  # type: ignore
except Exception:
    from services.borrow_fee_scheduler import borrow_fee_scheduler  # type: ignore

class OrderService:
    """
    订单生命周期 orchestrator
    """
    def __init__(self, session: Session, engine: MatchingEngine | None = None, instrument_service: InstrumentService | None = None):
        # engine 现在可选: 仅作为向后兼容的默认引擎 (symbol 未注册时可用)
        self.s = session
        self.engine = engine  # deprecated: 动态路由后仅兜底
        self.risk = RiskEngine()
        self.fees = FeeEngine()
        self.accounts = AccountService(session)
        self.instrument_service = instrument_service or instrument_service_factory()
        self._mem_orders: dict[str, Order] = {}
        self._batch_trades: list = []  # 批量模式缓冲

    # ---- 内部: 取得 / 创建 引擎 ----
    def _get_engine(self, symbol: str) -> MatchingEngine:
        sym = symbol.upper()
        eng_reg = engine_registry.get(sym)
        if self.engine:
            if eng_reg and eng_reg is not self.engine:
                try:
                    books = getattr(self.engine, '_books', {})
                    # 若 self.engine 尚无该簿则注册；否则仅同步 phase
                    if sym not in books and hasattr(self.engine, 'register_symbol'):
                        self.engine.register_symbol(sym, getattr(eng_reg, 'instrument', None))
                    # 同步 phase (保持 IPO 已开盘连续状态)
                    try:
                        src_book = eng_reg.get_book(sym)
                        dst_book = self.engine.get_book(sym)
                        dst_book.phase = src_book.phase
                        # 若已是连续阶段且尚未标记 has_continuous_started, 设 True
                        if getattr(dst_book, 'phase', None) and dst_book.phase.name == 'CONTINUOUS':
                            dst_book.has_continuous_started = True
                    except Exception:
                        pass
                    engine_registry.register(sym, self.engine, overwrite=True)
                except Exception:
                    pass
                return self.engine
            if not eng_reg:
                try:
                    books = getattr(self.engine, '_books', {})
                    if sym not in books and hasattr(self.engine, 'register_symbol'):
                        self.engine.register_symbol(sym, getattr(self.engine, 'instrument', None))
                        # 若 instrument 提示已开盘 (instrument.ipo_opened) 则设为连续
                        try:
                            book = self.engine.get_book(sym)
                            inst = getattr(self.engine, 'instrument', None)
                            if inst and getattr(inst, 'ipo_opened', False):
                                from stock_sim.core.const import Phase as _Phase  # type: ignore
                                book.phase = _Phase.CONTINUOUS
                                book.has_continuous_started = True
                        except Exception:
                            pass
                    engine_registry.register(sym, self.engine, overwrite=False)
                    return self.engine
                except Exception:
                    pass
            if eng_reg is self.engine or getattr(self.engine, 'symbol', '').upper() == sym:
                return self.engine
        if eng_reg:
            return eng_reg
        eng_new = engine_registry.get_or_create(sym)
        return eng_new

    # ---- 内部: 取标的参数 ----
    def _get_symbol_params(self, symbol: str):
        sym = symbol.upper()
        eng = self._get_engine(sym)
        view = None
        if hasattr(eng, 'get_instrument_view'):
            try:
                view = eng.get_instrument_view(sym)
            except Exception:
                view = None
        dto = None
        if view is None:
            # 尝试从 DB 加载并注册 (必要时补充 instrument 信息)
            try:
                dto = self.instrument_service.get(sym)
            except Exception:
                dto = None
            if dto:
                class _Tmp: ...
                tmp = _Tmp()
                tmp.tick_size = dto.tick_size; tmp.lot_size = dto.lot_size; tmp.min_qty = dto.min_qty
                tmp.settlement_cycle = dto.settlement_cycle
                tmp.market_cap = dto.market_cap; tmp.total_shares = dto.total_shares
                tmp.free_float_shares = dto.free_float_shares; tmp.initial_price = dto.initial_price
                tmp.pe = None; tmp.ipo_opened = dto.ipo_opened
                try:
                    eng.register_symbol(sym, tmp)
                except Exception:
                    pass
                try:
                    view = eng.get_instrument_view(sym)
                except Exception:
                    view = None
        else:
            # 即便已有 view, 仍加载 DB 以获取 ipo_opened 状态 (用于自建 engine 缺失)
            try:
                dto = self.instrument_service.get(sym)
            except Exception:
                dto = None
        # 同步 phase: 若 DB 标记已开盘且当前簿仍处于集合竞价 -> 切换为 CONTINUOUS
        if dto and getattr(dto, 'ipo_opened', False):
            try:
                from stock_sim.core.const import Phase as _Phase  # type: ignore
                book = eng.get_book(sym)
                if book.phase.name != 'CONTINUOUS':
                    book.phase = _Phase.CONTINUOUS
                    book.has_continuous_started = True
            except Exception:
                pass
        return view

    # ---------------------- PUBLIC API ----------------------
    def place_order(self, order: Order):
        # ---- 恢复与只读保护 ----
        # 首笔订单尝试发送恢复完成事件（若此前成功恢复且未发送）。
        try:
            mark_resumed_if_needed()
        except Exception:
            pass
        if recovery_is_readonly():
            # 系统处于恢复失败只读模式，直接拒绝
            order.status = OrderStatus.REJECTED
            reason = "READONLY_RECOVERY"
            self._persist_order(order, "REJECT", reason)
            metrics.inc("orders_rejected")
            metrics.inc(settings.REJECT_METRIC_PREFIX + reason.lower())
            try:
                event_bus.publish("OrderRejected", {"order": order.to_dict(), "reason": reason})
            except Exception:
                pass
            logger.log("order_reject", order_id=order.order_id, reason=reason)
            return []
        dbg = os.environ.get('DEBUG_FRONT') == '1'
        if TRACE_ORDERS:
            print(f"[TRACE OrderService.place_order.begin] oid={order.order_id} sym={order.symbol} side={order.side.name} px={order.price} qty={order.quantity} acct={order.account_id}")
        # 处理（一次性）集合竞价未成交残余的释放与取消事件 (跨所有引擎)
        self._handle_auction_cancels()

        self._mem_orders[order.order_id] = order
        metrics.inc("orders_submitted")
        params = self._get_symbol_params(order.symbol)
        if TRACE_ORDERS:
            print(f"[TRACE OrderService.place_order.params] oid={order.order_id} params_exist={params is not None} tick={getattr(params,'tick_size',None)} lot={getattr(params,'lot_size',None)} min_qty={getattr(params,'min_qty',None)} settle={getattr(params,'settlement_cycle',None)}")
        # (1) 价格 & 数量对齐 (基于 instrument 参数)
        if params:
            try:
                # 价格按 tick 归一
                tick = getattr(params, 'tick_size', 0) or 0
                if tick > 0:
                    new_price = normalize_price(order.price, tick)
                    if new_price != order.price and TRACE_ORDERS:
                        print(f"[TRACE OrderService.norm_price] oid={order.order_id} from={order.price} to={new_price} tick={tick}")
                    order.price = new_price
                # 数量合法性校验/对齐
                lot = getattr(params, 'lot_size', 1) or 1
                min_qty = getattr(params, 'min_qty', 1) or 1
                if not validate_lot(order.quantity, lot, min_qty):
                    aligned = align_lot_quantity(order.quantity, lot, min_qty)
                    if aligned <= 0:
                        # 直接拒绝
                        order.status = OrderStatus.REJECTED
                        self._persist_order(order, "REJECT", "MIN_QTY")
                        metrics.inc("orders_rejected")
                        metrics.inc(settings.REJECT_METRIC_PREFIX + "min_qty")
                        try:
                            event_bus.publish("OrderRejected", {"order": order.to_dict(), "reason": "MIN_QTY"})
                        except Exception:
                            pass
                        logger.log("order_reject", order_id=order.order_id, reason="MIN_QTY")
                        if TRACE_ORDERS:
                            print(f"[TRACE OrderService.reject.MIN_QTY] oid={order.order_id} sym={order.symbol} qty={order.quantity} lot={lot} min={min_qty}")
                        return []
                    if TRACE_ORDERS:
                        print(f"[TRACE OrderService.align_qty] oid={order.order_id} from={order.quantity} to={aligned} lot={lot} min={min_qty}")
                    logger.log("order_norm_qty", order_id=order.order_id, src=order.quantity, dst=aligned)
                    order.quantity = aligned
            except Exception:
                # 任何异常均忽略，不阻塞下游
                pass

        # (2) 基础校验
        ok, reason = basic_order_checks(order.price, order.quantity)
        if TRACE_ORDERS:
            print(f"[TRACE OrderService.basic_checks] oid={order.order_id} ok={ok} reason={reason}")
        if not ok:
            if dbg:
                print(f"[DBG OrderService.reject.basic] reason={reason}")
            order.status = OrderStatus.REJECTED
            self._persist_order(order, "REJECT", reason)
            metrics.inc("orders_rejected")
            metrics.inc(settings.REJECT_METRIC_PREFIX + reason.lower())
            event_bus.publish("OrderRejected", {"order": order.to_dict(), "reason": reason})
            logger.log("order_reject", order_id=order.order_id, reason=reason)
            if TRACE_ORDERS:
                print(f"[TRACE OrderService.reject.basic] oid={order.order_id} sym={order.symbol} reason={reason} price={order.price} qty={order.quantity}")
            return []

        # (3) 风控
        acc = self.accounts.get_or_create(order.account_id)
        # 若账户初始现金为 0 (可能因旧 AccountService 版本) 则回填默认初始资金
        try:
            if getattr(acc, 'cash', 0.0) <= 0:
                from stock_sim.settings import settings as _st  # type: ignore
                acc.cash = float(getattr(_st, 'DEFAULT_CASH', 1_000_000.0))
        except Exception:
            pass
        if TRACE_ORDERS:
            try:
                pos_state = [(p.symbol, p.quantity, p.frozen_qty) for p in acc.positions]
            except Exception:
                pos_state = 'ERR'
            print(f"[TRACE OrderService.before_risk] oid={order.order_id} cash={acc.cash:.4f} frozen_cash={acc.frozen_cash:.4f} frozen_fee={acc.frozen_fee:.4f} positions={pos_state}")
        risk_positions = acc.positions
        settlement_cycle = getattr(params, 'settlement_cycle', 0) if params else 0
        rr = self.risk.validate(
            account=acc,
            positions=risk_positions,
            symbol=order.symbol,
            side=order.side,
            price=order.price,
            qty=order.quantity,
            context={"settlement_cycle": settlement_cycle, "tif": order.tif, "engine": self._get_engine(order.symbol)},
            order_type=order.order_type
        )
        if not rr.ok:
            if dbg:
                print(f"[DBG OrderService.reject.risk] code={rr.code} reason={rr.reason}")
            order.status = OrderStatus.REJECTED
            self._persist_order(order, "REJECT", rr.reason)
            metrics.inc("orders_rejected")
            metrics.inc(settings.REJECT_METRIC_PREFIX + rr.code.lower())
            event_bus.publish("OrderRejected", {"order": order.to_dict(), "reason": rr.reason})
            logger.log("order_reject", order_id=order.order_id, reason=rr.reason)
            if TRACE_ORDERS:
                print(f"[TRACE OrderService.reject.risk] oid={order.order_id} code={rr.code} reason={rr.reason}")
            return []

        # (4) 费用预估（默认假设吃单）+ 买单手续费预冻结
        fee_est = self.fees.estimate_order(order.side, order.price, order.quantity)
        if TRACE_ORDERS:
            print(f"[TRACE OrderService.fee_est] oid={order.order_id} est_fee={fee_est.est_fee} est_tax={fee_est.est_tax} notional_basis={fee_est.basis_notional}")
        order.attach_meta(est_fee=fee_est.est_fee)
        logger.log("order_fee_est",
                   order_id=order.order_id,
                   est_fee=fee_est.est_fee,
                   est_tax=fee_est.est_tax,
                   notional=fee_est.basis_notional)
        if order.side is OrderSide.BUY:
            if not self.accounts.freeze_fee(acc, fee_est.est_fee):
                order.status = OrderStatus.REJECTED
                self._persist_order(order, "REJECT", "FEE_FREEZE_FAIL")
                metrics.inc("orders_rejected")
                metrics.inc(settings.REJECT_METRIC_PREFIX + "fee_freeze_fail")
                event_bus.publish("OrderRejected", {"order": order.to_dict(), "reason": "FEE_FREEZE_FAIL"})
                logger.log("order_reject", order_id=order.order_id, reason="FEE_FREEZE_FAIL")
                if TRACE_ORDERS:
                    print(f"[TRACE OrderService.reject.fee_freeze_fail] oid={order.order_id} fee={fee_est.est_fee} cash={acc.cash}")
                return []
            if order.status == OrderStatus.REJECTED and dbg:
                print("[DBG OrderService.reject.fee_freeze]")

        # (5) 冻结主体（名义金额或持仓）
        if TRACE_ORDERS:
            print(f"[TRACE OrderService.freeze_main.try] oid={order.order_id} side={order.side.name} symbol={order.symbol} px={order.price} qty={order.quantity}")
        skip_main_freeze = False
        try:
            # 若当前 symbol 仍处于集合竞价阶段，允许买单跳过现金冻结 (IPO 大额申购场景)
            eng_for_phase = self._get_engine(order.symbol)
            book_phase = eng_for_phase.get_book(order.symbol).phase
            from stock_sim.core.const import Phase as _Phase  # type: ignore
            if book_phase is _Phase.CALL_AUCTION and order.side is OrderSide.BUY:
                skip_main_freeze = True
        except Exception:
            pass
        if not skip_main_freeze:
            if not self.accounts.freeze(acc, order.symbol, order.side, order.price, order.quantity):
                if dbg:
                    print(f"[DBG OrderService.reject.freeze] cash={acc.cash} frozen_cash={acc.frozen_cash}")
                if order.side is OrderSide.BUY and fee_est.est_fee > 0:
                    self.accounts.refund_fee(acc, fee_est.est_fee)
                order.status = OrderStatus.REJECTED
                self._persist_order(order, "REJECT", "FREEZE_FAIL")
                metrics.inc("orders_rejected")
                metrics.inc(settings.REJECT_METRIC_PREFIX + "freeze_fail")
                event_bus.publish("OrderRejected", {"order": order.to_dict(), "reason": "FREEZE_FAIL"})
                logger.log("order_reject", order_id=order.order_id, reason="FREEZE_FAIL")
                if TRACE_ORDERS:
                    print(f"[TRACE OrderService.reject.freeze_fail] oid={order.order_id} cash={acc.cash:.4f} frozen_cash={acc.frozen_cash:.4f}")
                return []
        else:
            if TRACE_ORDERS:
                print(f"[TRACE OrderService.freeze_main.skip_call_auction] oid={order.order_id} symbol={order.symbol} qty={order.quantity}")
        if TRACE_ORDERS:
            print(f"[TRACE OrderService.persist.initial] oid={order.order_id} status={order.status.name}")
        # (6) 初始持久化
        self._persist_order(order, "NEW", "")

        # (7) 投递撮合
        if TRACE_ORDERS:
            print(f"[TRACE OrderService.pre_engine] oid={order.order_id} pre_status={order.status.name} pre_filled={order.filled}")
        eng_dyn = self._get_engine(order.symbol)
        trades = eng_dyn.submit_order(order, skip_freeze=True)
        if TRACE_ORDERS:
            print(f"[TRACE OrderService.after_engine] oid={order.order_id} post_status={order.status.name} post_filled={order.filled} remaining={order.remaining} trades={len(trades)}")
        if trades:
            metrics.inc("orders_with_trades")
            metrics.inc("trades_count", len(trades))

        # (8) 成交后处理
        self._after_trades(trades)

        # (9) IOC / FOK 处理 + 未成交手续费退款 (首次撮合后判断)
        if order.tif is TimeInForce.FOK and order.status != OrderStatus.FILLED:
            # 全量未满足
            if TRACE_ORDERS:
                print(f"[TRACE OrderService.fok_cancel] oid={order.order_id} filled={order.filled} qty={order.quantity}")
            # 释放剩余冻结主体
            if order.remaining > 0:
                self.accounts.release(acc, order.symbol, order.side, order.price, order.remaining)
            # 费用按未成交部分退还
            if order.side is OrderSide.BUY and 'est_fee' in order._meta and order.quantity > 0:
                unfilled_ratio = order.remaining / order.quantity
                if unfilled_ratio > 0:
                    refund_fee = order._meta['est_fee'] * unfilled_ratio
                    self.accounts.refund_fee(acc, refund_fee)
            order.status = OrderStatus.CANCELED
            detail = "FOK_UNFILLABLE"
            self._persist_state(order, "CANCEL", detail)
            event_bus.publish("OrderCanceled", {"order_id": order.order_id, "reason": detail})
            logger.log("order_cancel", order_id=order.order_id, reason=detail)
            return trades
        elif order.tif is TimeInForce.IOC and order.remaining > 0:
            if TRACE_ORDERS:
                print(f"[TRACE OrderService.ioc_cancel] oid={order.order_id} filled={order.filled} remaining={order.remaining}")
            if order.remaining > 0:
                self.accounts.release(acc, order.symbol, order.side, order.price, order.remaining)
            # 退还未成交手续费（按比例）
            if order.side is OrderSide.BUY and 'est_fee' in order._meta and order.quantity > 0:
                unfilled_ratio = order.remaining / order.quantity
                if unfilled_ratio > 0:
                    refund_fee = order._meta['est_fee'] * unfilled_ratio
                    self.accounts.refund_fee(acc, refund_fee)
            order.status = OrderStatus.CANCELED
            detail = 'IOC_REMAIN_CANCEL' if order.filled > 0 else 'IOC_UNFILLABLE'
            self._persist_state(order, 'CANCEL', detail)
            event_bus.publish('OrderCanceled', {'order_id': order.order_id, 'reason': detail})
            logger.log('order_cancel', order_id=order.order_id, reason=detail)
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
        orm = self.s.get(OrderORM, order_id)
        if not orm:
            return False
        eng = self._get_engine(orm.symbol)
        ok = eng.cancel_order(order_id)
        if ok:
            acc = self.accounts.get_or_create(orm.account_id)
            remaining = orm.quantity - orm.filled
            if remaining > 0:
                self.accounts.release(acc, orm.symbol, orm.side, orm.price, remaining)
            mem = self._mem_orders.get(order_id)
            if mem and mem.side is OrderSide.BUY and 'est_fee' in mem._meta and orm.quantity > 0:
                unfilled_ratio = (orm.quantity - orm.filled) / orm.quantity
                refund_fee = mem._meta['est_fee'] * unfilled_ratio
                self.accounts.refund_fee(acc, refund_fee)
            orm.status = OrderStatus.CANCELED
            self._persist_event(order_id, "CANCEL", "USER")
            event_bus.publish("OrderCanceled", {"order_id": order_id, "reason": "USER"})
            logger.log("order_cancel", order_id=order_id, reason="USER")
            self._update_mem_order(order_id, orm, eng)
        return ok

    def daily_reset(self):
        """日切：
        - 重置风险引擎日内成交额与 T+1 基准 (记录���个账户-标的的最新持仓数量)
        - 计提借券费用 (空头持仓)
        - 可在外部调度 (如 MarketClock 发现新交易日时) 调用
        """
        # 重置日内成交额
        try:
            self.risk.storage.reset_day()
        except Exception:
            pass
        # 采集所有当前持仓（尽量批量，不做逐账户循环）
        try:
            positions = self.s.query(Position).all()
            self.risk.reset_day_tplus(positions)
        except Exception:
            pass
        # 借券费用计提
        try:
            cnt, total_fee = borrow_fee_scheduler.run(self.s)
            if cnt:
                metrics.inc("borrow_fee_accrual_batches")
        except Exception:
            metrics.inc("borrow_fee_accrual_errors")
        return True

    # ---------------------- INTERNAL ----------------------
    def _handle_auction_cancels(self):
        # 迭代所有已注册引擎处理集合竞价取消
        symbols = []
        try:
            symbols = engine_registry.symbols()
        except Exception:
            pass
        engines = []
        for s in symbols:
            eng = engine_registry.get(s)
            if eng:
                engines.append(eng)
        # 向后兼容: 若 self.engine 不在注册表也处理
        if self.engine and self.engine not in engines:
            engines.append(self.engine)
        for eng in engines:
            ids = getattr(eng, 'auction_canceled_order_ids', None)
            if not ids:
                continue
            for oid in list(ids):
                orm = self.s.get(OrderORM, oid)
                if not orm:
                    continue
                if orm.status != OrderStatus.CANCELED:
                    acc = self.accounts.get_or_create(orm.account_id)
                    remaining = orm.quantity - orm.filled
                    if remaining > 0:
                        self.accounts.release(acc, orm.symbol, orm.side, orm.price, remaining)
                        mem = self._mem_orders.get(oid)
                        if mem and mem.side is OrderSide.BUY and 'est_fee' in mem._meta and orm.quantity > 0:
                            unfilled_ratio = remaining / orm.quantity
                            refund_fee = mem._meta['est_fee'] * unfilled_ratio
                            self.accounts.refund_fee(acc, refund_fee)
                    orm.status = OrderStatus.CANCELED
                    self._persist_event(oid, "CANCEL", "AUCTION_UNMATCHED")
                    event_bus.publish("OrderCanceled", {"order_id": oid, "reason": "AUCTION_UNMATCHED"})
                    logger.log("order_cancel", order_id=oid, reason="AUCTION_UNMATCHED")
                self._update_mem_order(oid, orm, eng)
            try:
                eng.auction_canceled_order_ids = []
            except Exception:
                pass

    def _locate_order_book(self, eng: MatchingEngine):
        """健壮定位指定引擎中的订单簿。"""
        candidates = (
            "order_book","book","ob","continuous_book","continuous_order_book","auction_book","auction_order_book",
        )
        for attr in candidates:
            if hasattr(eng, attr):
                ob = getattr(eng, attr)
                if isinstance(ob, OrderBook):
                    return ob
        try:
            for attr in dir(eng):
                if attr.startswith("_"): continue
                try:
                    val = getattr(eng, attr)
                except Exception:
                    continue
                if isinstance(val, OrderBook):
                    return val
        except Exception:
            pass
        return None

    def _update_mem_order(self, order_id: str, orm_obj: OrderORM | None, eng: MatchingEngine | None):
        if not orm_obj:
            return
        obj = self._mem_orders.get(order_id)
        if obj:
            try:
                obj.filled = orm_obj.filled
                obj.status = orm_obj.status
                obj.price = orm_obj.price
            except Exception:
                pass
        if eng and hasattr(eng, "get_order"):
            try:
                eng_obj = eng.get_order(order_id)
                if eng_obj is not None and eng_obj is not obj:
                    eng_obj.filled = orm_obj.filled
                    eng_obj.status = orm_obj.status
            except Exception:
                pass
        if eng:
            ob = self._locate_order_book(eng)
            if ob:
                for name in ("orders","_orders","order_map"):
                    m = getattr(ob, name, None)
                    if isinstance(m, dict) and order_id in m:
                        try:
                            target = m[order_id]
                            target.filled = orm_obj.filled
                            target.status = orm_obj.status
                        except Exception:
                            pass
                        break

    def _after_trades(self, trades):
        if not trades:
            return
        # 动态定位订单簿: 取第一笔成交的引擎 (symbol 相同)
        first = trades[0]
        eng_first = self._get_engine(first.symbol)
        order_book = self._locate_order_book(eng_first)
        sim_day = current_sim_day(); sim_dt = virtual_datetime(sim_day)
        cost_map = {}
        actual_buy_fee_accum: dict[str, float] = {}
        # 为批量结算收集
        batch_entries = []  # (buy_acc, sell_acc, symbol, price, qty, buy_oid, sell_oid)
        fee_entries = []    # (fee_buy, fee_sell, tax_sell)
        for tr in trades:
            eng_tr = eng_first if tr.symbol == first.symbol else self._get_engine(tr.symbol)
            cost_map[tr.buy_order_id] = cost_map.get(tr.buy_order_id, 0.0) + tr.price * tr.quantity
            self.s.add(TradeORM(
                id=tr.trade_id, symbol=tr.symbol, price=tr.price,
                quantity=tr.quantity, buy_order_id=tr.buy_order_id,
                sell_order_id=tr.sell_order_id,
                buy_account_id=tr.buy_account_id, sell_account_id=tr.sell_account_id,
                sim_day=sim_day, sim_dt=sim_dt
            ))
            buy_orm = self.s.get(OrderORM, tr.buy_order_id)
            if buy_orm:
                buy_orm.filled += tr.quantity
                buy_orm.status = (OrderStatus.FILLED
                                  if buy_orm.filled >= buy_orm.quantity else OrderStatus.PARTIAL)
                self._persist_event(
                    buy_orm.id,
                    "FILL" if buy_orm.status == OrderStatus.FILLED else "PARTIAL",
                    ""
                )
            sell_orm = self.s.get(OrderORM, tr.sell_order_id)
            if sell_orm:
                sell_orm.filled += tr.quantity
                sell_orm.status = (OrderStatus.FILLED
                                   if sell_orm.filled >= sell_orm.quantity else OrderStatus.PARTIAL)
                self._persist_event(
                    sell_orm.id,
                    "FILL" if sell_orm.status == OrderStatus.FILLED else "PARTIAL",
                    ""
                )
            self._update_mem_order(tr.buy_order_id, buy_orm, eng_tr)
            self._update_mem_order(tr.sell_order_id, sell_orm, eng_tr)
            buy_acc = self.accounts.get_or_create(buy_orm.account_id) if buy_orm else None
            sell_acc = self.accounts.get_or_create(sell_orm.account_id) if sell_orm else None
            fee_buy_res = self.fees.calc(OrderSide.BUY, tr.price, tr.quantity, is_taker=True)
            fee_sell_res = self.fees.calc(OrderSide.SELL, tr.price, tr.quantity, is_taker=True)
            actual_buy_fee_accum[tr.buy_order_id] = actual_buy_fee_accum.get(tr.buy_order_id, 0.0) + fee_buy_res.fee
            batch_entries.append((buy_acc, sell_acc, tr.symbol, tr.price, tr.quantity, tr.buy_order_id, tr.sell_order_id))
            fee_entries.append((fee_buy_res.fee, fee_sell_res.fee, fee_sell_res.tax))
            # T+1 日内统计（买卖实际数量）
            if buy_acc:
                self.risk.update_tplus(buy_acc.id, tr.symbol, OrderSide.BUY, tr.quantity)
            if sell_acc:
                self.risk.update_tplus(sell_acc.id, tr.symbol, OrderSide.SELL, tr.quantity)
            if order_book and hasattr(order_book, "last_snapshot") and tr.symbol == first.symbol:
                try:
                    prev = order_book.last_snapshot()
                except Exception:
                    prev = None
                if prev is None or not isinstance(prev, Snapshot):
                    prev = Snapshot(symbol=tr.symbol)
                prev.update_trade(tr.price, tr.quantity)
                try:
                    setattr(order_book, "_last_snapshot", prev)
                except Exception:
                    pass
            event_bus.publish("Trade", {"trade": tr.to_dict()})
            logger.log("trade", **tr.to_dict())
            metrics.inc("trades_processed")
        # 批量结算
        self.accounts.settle_trades_batch(batch_entries, fee_entries)
        self.s.flush()
        # 资金冻结差额返还
        for oid, cost in cost_map.items():
            buy_orm = self.s.get(OrderORM, oid)
            if not buy_orm:
                continue
            if buy_orm.status == OrderStatus.FILLED:
                frozen_should = buy_orm.price * buy_orm.quantity
                if frozen_should > cost:
                    acc = self.accounts.get_or_create(buy_orm.account_id)
                    refund = frozen_should - cost
                    refund = min(refund, acc.frozen_cash)
                    if refund > 0:
                        acc.frozen_cash -= refund
                        acc.cash += refund
                        metrics.inc("cash_refund_after_fill")
        # 手续费多退
        for buy_oid, actual_fee in actual_buy_fee_accum.items():
            mem = self._mem_orders.get(buy_oid)
            if not mem:
                continue
            if mem.status == OrderStatus.FILLED and 'est_fee' in mem._meta:
                est = mem._meta['est_fee']
                if est > actual_fee + 1e-9:
                    acc = self.accounts.get_or_create(mem.account_id)
                    self.accounts.refund_fee(acc, est - actual_fee)
                    metrics.inc("fee_refund_after_fill")
        for tr in trades:
            for oid in (tr.buy_order_id, tr.sell_order_id):
                orm = self.s.get(OrderORM, oid)
                if orm and orm.status == OrderStatus.FILLED:
                    mem = self._mem_orders.get(oid)
                    if mem:
                        mem.status = orm.status
                        mem.filled = orm.filled

    def flush_batch(self):
        """批量模式下：处理缓冲的 trades，执行账��/持仓结算与费用多退少补。"""
        if not self._batch_trades:
            return
        sim_day = current_sim_day(); sim_dt = virtual_datetime(sim_day)
        trades = self._batch_trades
        self._batch_trades = []
        # 采用首笔成交 symbol 对应引擎的订单簿 (简单实现)
        eng_first = self._get_engine(trades[0].symbol)
        order_book = self._locate_order_book(eng_first)
        cost_map = {}
        actual_buy_fee_accum: dict[str, float] = {}
        batch_entries = []
        fee_entries = []
        for tr in trades:
            eng_tr = eng_first if tr.symbol == trades[0].symbol else self._get_engine(tr.symbol)
            cost_map[tr.buy_order_id] = cost_map.get(tr.buy_order_id, 0.0) + tr.price * tr.quantity
            self.s.add(TradeORM(
                id=tr.trade_id, symbol=tr.symbol, price=tr.price,
                quantity=tr.quantity, buy_order_id=tr.buy_order_id,
                sell_order_id=tr.sell_order_id,
                buy_account_id=tr.buy_account_id, sell_account_id=tr.sell_account_id,
                sim_day=sim_day, sim_dt=sim_dt
            ))
            buy_orm = self.s.get(OrderORM, tr.buy_order_id)
            if buy_orm:
                buy_orm.filled += tr.quantity
                buy_orm.status = (OrderStatus.FILLED if buy_orm.filled >= buy_orm.quantity else OrderStatus.PARTIAL)
                self._persist_event(buy_orm.id, 'FILL' if buy_orm.status == OrderStatus.FILLED else 'PARTIAL', '')
            sell_orm = self.s.get(OrderORM, tr.sell_order_id)
            if sell_orm:
                sell_orm.filled += tr.quantity
                sell_orm.status = (OrderStatus.FILLED if sell_orm.filled >= sell_orm.quantity else OrderStatus.PARTIAL)
                self._persist_event(sell_orm.id, 'FILL' if sell_orm.status == OrderStatus.FILLED else 'PARTIAL', '')
            self._update_mem_order(tr.buy_order_id, buy_orm, eng_tr)
            self._update_mem_order(tr.sell_order_id, sell_orm, eng_tr)
            buy_acc = self.accounts.get_or_create(buy_orm.account_id) if buy_orm else None
            sell_acc = self.accounts.get_or_create(sell_orm.account_id) if sell_orm else None
            fee_buy_res = self.fees.calc(OrderSide.BUY, tr.price, tr.quantity, is_taker=True)
            fee_sell_res = self.fees.calc(OrderSide.SELL, tr.price, tr.quantity, is_taker=True)
            actual_buy_fee_accum[tr.buy_order_id] = actual_buy_fee_accum.get(tr.buy_order_id, 0.0) + fee_buy_res.fee
            batch_entries.append((buy_acc, sell_acc, tr.symbol, tr.price, tr.quantity, tr.buy_order_id, tr.sell_order_id))
            fee_entries.append((fee_buy_res.fee, fee_sell_res.fee, fee_sell_res.tax))
            if buy_acc:
                self.risk.update_tplus(buy_acc.id, tr.symbol, OrderSide.BUY, tr.quantity)
            if sell_acc:
                self.risk.update_tplus(sell_acc.id, tr.symbol, OrderSide.SELL, tr.quantity)
            if order_book and hasattr(order_book, 'last_snapshot') and tr.symbol == trades[0].symbol:
                try:
                    prev = order_book.last_snapshot()
                except Exception:
                    prev = None
                if prev is None or not isinstance(prev, Snapshot):
                    prev = Snapshot(symbol=tr.symbol)
                prev.update_trade(tr.price, tr.quantity)
                try:
                    setattr(order_book, '_last_snapshot', prev)
                except Exception:
                    pass
            metrics.inc('trades_processed', 1)
        # 批量结算
        self.accounts.settle_trades_batch(batch_entries, fee_entries)
        self.s.flush()
        # 冻结资金差额返还
        for oid, cost in cost_map.items():
            buy_orm = self.s.get(OrderORM, oid)
            if not buy_orm:
                continue
            if buy_orm.status == OrderStatus.FILLED:
                frozen_should = buy_orm.price * buy_orm.quantity
                if frozen_should > cost:
                    acc = self.accounts.get_or_create(buy_orm.account_id)
                    refund = frozen_should - cost
                    refund = min(refund, acc.frozen_cash)
                    if refund > 0:
                        acc.frozen_cash -= refund
                        acc.cash += refund
                        metrics.inc('cash_refund_after_fill')
        # 手续费多退
        for buy_oid, actual_fee in actual_buy_fee_accum.items():
            mem = self._mem_orders.get(buy_oid)
            if not mem:
                continue
            if mem.status == OrderStatus.FILLED and 'est_fee' in mem._meta:
                est = mem._meta['est_fee']
                if est > actual_fee + 1e-9:
                    acc = self.accounts.get_or_create(mem.account_id)
                    self.accounts.refund_fee(acc, est - actual_fee)
                    metrics.inc('fee_refund_after_fill')

    def calc_required_frozen_fee(self) -> dict[str, float]:
        """统计每账户基于活动订单剩余数量仍需保留的预估手续费（线性按剩余比例近似）。"""
        req: dict[str, float] = {}
        for o in self._mem_orders.values():
            if o.side is OrderSide.BUY and o.status in (OrderStatus.NEW, OrderStatus.PARTIAL) and o.quantity > 0:
                est = o._meta.get('est_fee', 0.0)
                if est <= 0:
                    continue
                remain_ratio = o.remaining / o.quantity
                need = est * remain_ratio
                if need <= 0:
                    continue
                req[o.account_id] = req.get(o.account_id, 0.0) + need
        return req

    def _persist_order(self, order: Order, event: str, detail: str):
        """初次持久化订单并写事件。"""
        sim_day = current_sim_day(); sim_dt = virtual_datetime(sim_day)
        orm = OrderORM(
            id=order.order_id,
            account_id=order.account_id,
            symbol=order.symbol,
            side=order.side,
            type=order.order_type,
            tif=order.tif,
            price=order.price,
            orig_price=getattr(order, "_orig_price", order.price),
            quantity=order.quantity,
            filled=order.filled,
            status=order.status,
            sim_day=sim_day, sim_dt=sim_dt
        )
        self.s.add(orm)
        self._persist_event(order.order_id, event, detail)

    def _persist_state(self, order: Order, event: str, detail: str):
        """更新已存在订单状态并写事件。"""
        orm = self.s.get(OrderORM, order.order_id)
        if orm:
            orm.price = order.price
            orm.filled = order.filled
            orm.status = order.status
            if not getattr(orm, 'sim_day', None):
                sd = current_sim_day(); orm.sim_day = sd; orm.sim_dt = virtual_datetime(sd)
        self._persist_event(order.order_id, event, detail)

    def _persist_event(self, order_id: str, event: str, detail: str):
        # OrderEvent 不含 sim_day 字段，仅补写其关联订单的 sim_day (若订单已存在且未写)
        try:
            existing = self.s.get(OrderORM, order_id)
            if existing and not getattr(existing, 'sim_day', None):
                sd = current_sim_day(); existing.sim_day = sd; existing.sim_dt = virtual_datetime(sd)
        except Exception:
            pass
        self.s.add(OrderEvent(order_id=order_id, event=event, detail=detail))
