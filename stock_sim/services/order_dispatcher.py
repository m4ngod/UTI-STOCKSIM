# python
"""
订单派发器：多生产线程 -> 队列 -> 单线程撮合 + 事务批量提交。
精简版：
  - 无尾部加速/心跳/强制停止高级功能
  - 提交后使用独立会话做简单手续费多余冻结返还（基于 FROZEN_FEE_CLEAN_INTERVAL_SEC）
  - 按 settings.ORDER_DISPATCH_COMMIT_N / TXN_MAX_SECONDS 控制提交频率
"""
from __future__ import annotations
import time, threading, queue
from typing import Optional
from stock_sim.core.order import Order
from stock_sim.core.matching_engine import MatchingEngine
from stock_sim.services.order_service import OrderService
from sqlalchemy.exc import OperationalError
from stock_sim.persistence.models_imports import SessionLocal as _SessionFactory
from stock_sim.infra.unit_of_work import UnitOfWork
from stock_sim.settings import settings
from stock_sim.observability.metrics import metrics
from stock_sim.observability.struct_logger import logger

class OrderDispatcher:
    def __init__(self, engine: MatchingEngine, *, qsize: int = 100_000, clean_symbol: bool = False):
        self.engine = engine
        self._q: queue.Queue[Order] = queue.Queue(maxsize=qsize)
        self._stop_flag = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_fee_clean = 0.0
        self._clean_symbol = clean_symbol
        self._thread_exc: Exception | None = None

    # ---------------- Lifecycle ----------------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        if self._clean_symbol:
            self._cleanup_symbol_data()
        self._thread = threading.Thread(target=self._run_wrapper, name="OrderDispatcher", daemon=True)
        self._thread.start()

    def _run_wrapper(self):
        try:
            self._run()
        except Exception as e:  # 捕获顶层异常记录
            self._thread_exc = e
            logger.log("order_dispatcher_crashed", err=str(e))

    def submit(self, order: Order):
        self._q.put(order)
        metrics.inc("orders_queue_in")

    def stop(self, wait: bool = True):
        self._stop_flag.set()
        if wait and self._thread:
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                logger.log("dispatcher_join_timeout")

    def is_alive(self) -> bool:
        return self._thread.is_alive() if self._thread else False

    def last_error(self):
        return self._thread_exc

    # ---------------- Core Loop ----------------
    def _run(self):
        commit_batch = max(1, settings.ORDER_DISPATCH_COMMIT_N)
        processed_in_tx = 0
        uow = UnitOfWork(_SessionFactory)
        uow.__enter__()
        order_service = OrderService(uow.session, self.engine)
        first_err_logged = False
        txn_start = time.perf_counter()
        try:
            while True:
                # 提前提交：时间窗口
                if processed_in_tx >= settings.TXN_EARLY_MIN_ORDERS and (time.perf_counter() - txn_start) > settings.TXN_MAX_SECONDS:
                    self._commit_cycle(uow, order_service, processed_in_tx, early=True)
                    processed_in_tx = 0
                    txn_start = time.perf_counter()
                # 取单
                try:
                    timeout = 0.2 if not self._stop_flag.is_set() else 1.0
                    order = self._q.get(timeout=timeout)
                except queue.Empty:
                    if self._stop_flag.is_set():
                        self._flush_batch_if_needed(order_service, force=True)
                        if processed_in_tx > 0:
                            self._commit_cycle(uow, order_service, processed_in_tx, early=False)
                        break
                    continue
                # 处理
                t0 = time.perf_counter()
                success = True
                try:
                    order_service.place_order(order)
                except OperationalError as e:
                    success = False
                    metrics.inc("orders_failed_exception")
                    code = getattr(getattr(e, 'orig', None), 'args', [None])[0]
                    if code in settings.TXN_LOCK_TIMEOUT_CODES:
                        metrics.inc("lock_timeouts")
                    try:
                        uow.session.rollback()
                    except Exception:
                        pass
                    if not first_err_logged:
                        logger.log("order_dispatch_error_first", err=str(e))
                        first_err_logged = True
                    logger.log("order_dispatch_error", err=str(e))
                except Exception as e:
                    success = False
                    metrics.inc("orders_failed_exception")
                    try:
                        uow.session.rollback()
                    except Exception:
                        pass
                    if not first_err_logged:
                        logger.log("order_dispatch_error_first", err=str(e))
                        first_err_logged = True
                    logger.log("order_dispatch_error", err=str(e))
                dt_ms = (time.perf_counter() - t0) * 1000
                metrics.add_timing("order_process_ms", dt_ms)
                metrics.inc("orders_queue_processed")
                if success:
                    metrics.inc("orders_queue_success")
                processed_in_tx += 1
                self._flush_batch_if_needed(order_service)
                if processed_in_tx >= commit_batch:
                    self._commit_cycle(uow, order_service, processed_in_tx, early=False)
                    processed_in_tx = 0
                    txn_start = time.perf_counter()
        finally:
            try:
                if processed_in_tx > 0:
                    self._commit_cycle(uow, order_service, processed_in_tx, early=False)
            except Exception:
                pass
            try:
                uow.__exit__(None, None, None)
            except Exception:
                pass
            metrics.gauge("queue_remaining", self._q.qsize())
            logger.log("order_dispatcher_stop", remaining=self._q.qsize())

    # ---------------- Commit Cycle ----------------
    def _commit_cycle(self, uow: UnitOfWork, order_service: OrderService, batch_size: int, *, early: bool):
        self._flush_batch_if_needed(order_service, force=True)
        start = time.perf_counter()
        try:
            uow.commit()
            metrics.inc("dispatcher_commits")
            if early:
                metrics.inc("dispatcher_early_commits")
        except OperationalError as e:
            code = getattr(getattr(e, 'orig', None), 'args', [None])[0]
            if code in settings.TXN_LOCK_TIMEOUT_CODES:
                metrics.inc("lock_timeouts")
            metrics.inc("dispatcher_commit_errors")
            logger.log("dispatcher_commit_error", err=str(e))
            uow.rollback()
        except Exception as e:
            metrics.inc("dispatcher_commit_errors")
            logger.log("dispatcher_commit_error", err=str(e))
            uow.rollback()
        flush_ms = (time.perf_counter() - start) * 1000
        metrics.add_timing("txn_flush_ms", flush_ms)
        metrics.inc("txn_objects_orders", batch_size)
        # 结束旧事务 -> 独立手续费清理 -> 新事务
        uow.__exit__(None, None, None)
        self._fee_cleanup_detached(order_service)
        uow.__enter__()
        order_service.s = uow.session
        if hasattr(order_service, 'accounts'):
            try:
                order_service.accounts.s = uow.session
            except Exception:
                pass

    # ---------------- Fee Cleanup (simple) ----------------
    def _fee_cleanup_detached(self, order_service: OrderService):
        now = time.time()
        if now - self._last_fee_clean < settings.FROZEN_FEE_CLEAN_INTERVAL_SEC:
            return
        self._last_fee_clean = now
        req_map = order_service.calc_required_frozen_fee()
        if not req_map:
            return
        sess = _SessionFactory()
        try:
            from stock_sim.persistence.models_account import Account as _Acc
            with sess.no_autoflush:
                for acc_id, need in req_map.items():
                    acc = sess.get(_Acc, acc_id)
                    if not acc:
                        continue
                    excess = acc.frozen_fee - need
                    if excess > 1e-6:
                        acc.frozen_fee -= excess
                        acc.cash += excess
            try:
                sess.commit()
            except Exception:
                sess.rollback()
        finally:
            sess.close()

    # ---------------- Batch Settlement Support ----------------
    def _flush_batch_if_needed(self, order_service: OrderService, force: bool = False):
        if settings.BATCH_SETTLEMENT_SIZE <= 0:
            return
        try:
            pending = len(getattr(order_service, '_batch_trades', []))
            if not force and pending < settings.BATCH_SETTLEMENT_SIZE:
                return
            if pending == 0:
                return
            order_service.flush_batch()
            metrics.inc("batch_flush_count")
        except Exception as e:
            logger.log("batch_flush_error", err=str(e))

    # ---------------- Symbol Cleanup (test helper) ----------------
    def _cleanup_symbol_data(self):
        sym = getattr(self.engine, 'symbol', None)
        if not sym:
            return
        sess = _SessionFactory()
        try:
            from stock_sim.persistence.models_order import OrderORM
            from stock_sim.persistence.models_trade import TradeORM
            from stock_sim.persistence.models_ledger import Ledger
            from stock_sim.persistence.models_order_event import OrderEvent
            ids = [r[0] for r in sess.query(OrderORM.id).filter_by(symbol=sym).all()]
            if ids:
                sess.query(OrderEvent).filter(OrderEvent.order_id.in_(ids)).delete(synchronize_session=False)
            sess.query(TradeORM).filter_by(symbol=sym).delete(synchronize_session=False)
            sess.query(Ledger).filter_by(symbol=sym).delete(synchronize_session=False)
            sess.query(OrderORM).filter_by(symbol=sym).delete(synchronize_session=False)
            sess.commit()
            logger.log("dispatcher_symbol_clean", symbol=sym, orders=len(ids))
        except Exception as e:
            sess.rollback()
            logger.log("dispatcher_symbol_clean_err", symbol=sym, err=str(e))
        finally:
            sess.close()
