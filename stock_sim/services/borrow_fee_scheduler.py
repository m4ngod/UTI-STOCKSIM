# python
"""BorrowFeeScheduler (platform-hardening Task6)

职责:
  - 每个模拟日对仍存在净空头( borrowed_qty>0 或 quantity<0 )的持仓计提借券费用。
  - 费用公式: fee = borrowed_qty * ref_price * BORROW_RATE_DAILY
  - ref_price 优先使用最近快照 last_price, 否则使用 position.avg_price, 再否则 0 跳过。
  - 避免重复: Position.borrow_fee_last_day == sim_day 则跳过。
  - 记录 Ledger (side='BORROW_FEE', cash_delta=-fee, extra_json JSON 标记 kind='BORROW_FEE').
  - 扣减账户现金 acc.cash -= fee (允许为负)。
  - 发布事件 EventType.BORROW_FEE_ACCRUED。

配置:
  settings.BORROW_FEE_ENABLED: 全局开关
  settings.BORROW_RATE_DAILY: 日费率 (浮点)
  settings.BORROW_FEE_MIN_NOTIONAL: 名义金额低于阈值忽略

返回: run() -> (count, total_fee)
"""
from __future__ import annotations
import json
from typing import Tuple

try:
    from stock_sim.settings import settings  # type: ignore
    from stock_sim.services.sim_clock import current_sim_day  # type: ignore
    from stock_sim.persistence.models_position import Position  # type: ignore
    from stock_sim.persistence.models_snapshot import Snapshot1s  # type: ignore
    from stock_sim.persistence.models_imports import SessionLocal  # type: ignore
    from stock_sim.services.account_service import AccountService  # type: ignore
    from stock_sim.infra.event_bus import event_bus  # type: ignore
    from stock_sim.core.const import EventType  # type: ignore
    from stock_sim.observability.metrics import metrics  # type: ignore
except Exception:  # noqa
    from settings import settings  # type: ignore
    from services.sim_clock import current_sim_day  # type: ignore
    from persistence.models_position import Position  # type: ignore
    from persistence.models_snapshot import Snapshot1s  # type: ignore
    from persistence.models_imports import SessionLocal  # type: ignore
    from services.account_service import AccountService  # type: ignore
    from infra.event_bus import event_bus  # type: ignore
    from core.const import EventType  # type: ignore
    from observability.metrics import metrics  # type: ignore

class BorrowFeeScheduler:
    def run(self, session=None) -> Tuple[int, float]:
        if not settings.BORROW_FEE_ENABLED:
            return 0, 0.0
        sim_day = current_sim_day()
        if sim_day is None:
            return 0, 0.0
        own_session = False
        if session is None:
            session = SessionLocal()
            own_session = True
        count = 0
        total_fee = 0.0
        acc_service = AccountService(session)
        try:
            # 仅查询存在潜在空头的行, 利用 borrowed_qty 或 quantity <0
            positions = (session.query(Position)
                         .filter((Position.borrowed_qty > 0) | (Position.quantity < 0))
                         .all())
            # 预取最近快照: 简化为逐 symbol 查询
            price_cache: dict[str,float] = {}
            for pos in positions:
                borrowed = pos.borrowed_qty if pos.borrowed_qty and pos.borrowed_qty > 0 else max(0, -pos.quantity)
                if borrowed <= 0:
                    continue
                if pos.borrow_fee_last_day == sim_day:
                    continue  # 已计提
                sym = pos.symbol
                if sym not in price_cache:
                    snap = (session.query(Snapshot1s)
                            .filter(Snapshot1s.symbol == sym)
                            .order_by(Snapshot1s.ts.desc())
                            .limit(1).first())
                    if snap and getattr(snap, 'last_price', None) is not None:
                        price_cache[sym] = float(snap.last_price or 0.0)
                    else:
                        price_cache[sym] = float(pos.avg_price or 0.0)
                ref_price = price_cache.get(sym, 0.0)
                if ref_price <= 0:
                    continue
                notional = borrowed * ref_price
                if notional < settings.BORROW_FEE_MIN_NOTIONAL:
                    continue
                fee = notional * settings.BORROW_RATE_DAILY
                # 账户扣减
                acc = pos.account
                if acc is None:
                    # 关系未加载, 重新获取
                    acc = acc_service.get_or_create(pos.account_id)
                acc.cash -= fee
                # 记录 ledger
                extra = json.dumps({
                    "kind": "BORROW_FEE",
                    "borrowed_qty": borrowed,
                    "ref_price": ref_price,
                    "notional": notional,
                    "rate_daily": settings.BORROW_RATE_DAILY,
                    "sim_day": sim_day,
                })
                acc_service._write_ledger(acc.id, sym, "BORROW_FEE", ref_price, borrowed,
                                           -fee, 0.0, 0.0, 0.0, None, extra_json=extra)
                # 标记避免重复
                pos.borrow_fee_last_day = sim_day
                try:
                    event_bus.publish(EventType.BORROW_FEE_ACCRUED, {
                        "account_id": acc.id,
                        "symbol": sym,
                        "borrowed_qty": borrowed,
                        "ref_price": ref_price,
                        "fee": fee,
                        "sim_day": sim_day,
                    })
                except Exception:
                    pass
                count += 1
                total_fee += fee
            if count:
                try:
                    metrics.inc("borrow_fee_positions", count)
                    metrics.inc("borrow_fee_total_events")
                except Exception:
                    pass
            session.flush()
            if own_session:
                session.commit()
            return count, total_fee
        except Exception:
            if own_session:
                session.rollback()
            metrics.inc("borrow_fee_errors")
            return count, total_fee
        finally:
            if own_session:
                session.close()

borrow_fee_scheduler = BorrowFeeScheduler()

__all__ = ["borrow_fee_scheduler", "BorrowFeeScheduler"]

